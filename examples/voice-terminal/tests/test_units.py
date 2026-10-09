import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from voice_terminal import control
from voice_terminal.codec import UPLINK_FRAME, OpusDecoder, OpusEncoder
from voice_terminal.audio import Microphone
from voice_terminal.config import VadConfig, WakeConfig, load_config
from voice_terminal.exit_words import DEFAULT_EXIT_WORDS, match_exit_words
from voice_terminal.frontend import Frontend
from voice_terminal.kws import WakeWordDetector
from voice_terminal.terminal import FrameRouter, Mode
from voice_terminal.vad import WINDOW, SpeechDetector

ROOT = Path(__file__).resolve().parents[1]


class ScriptedModel:
    """Speech probability per 512-sample window from a list."""

    def __init__(self, probs):
        self.probs = list(probs)

    def __call__(self, window):
        return self.probs.pop(0) if self.probs else 0.0


def windows(count):
    return np.zeros(WINDOW * count, dtype=np.float32)


def test_vad_start_and_end():
    config = VadConfig(threshold=0.5, min_speech_ms=250, min_silence_ms=500, short_utterance_ms=0)
    # 250 ms = 7.8 windows of speech -> start on the 8th; 500 ms silence = 16 windows -> end.
    detector = SpeechDetector(config, model=ScriptedModel([0.9] * 30 + [0.1] * 16))
    assert detector.accept(windows(7)) == []
    assert detector.accept(windows(1)) == ["start"]
    assert detector.accept(windows(22)) == []
    assert detector.accept(windows(15)) == []
    assert detector.accept(windows(1)) == ["end"]


def test_vad_short_utterance_waits_longer():
    config = VadConfig(min_speech_ms=250, min_silence_ms=500, short_utterance_ms=800, short_utterance_silence_ms=1000)
    detector = SpeechDetector(config, model=ScriptedModel([0.9] * 8 + [0.1] * 40))
    assert detector.accept(windows(8)) == ["start"]
    assert detector.accept(windows(16)) == []  # 500 ms is not enough after a short "嗯"
    assert detector.accept(windows(16)) == ["end"]  # 1000 ms is


def test_vad_max_utterance():
    config = VadConfig(min_speech_ms=250, max_utterance_s=1.0)
    detector = SpeechDetector(config, model=ScriptedModel([0.9] * 100))
    assert detector.accept(windows(8)) == ["start"]
    # 1 s = 31.25 windows, so the forced end lands on window 32; four more
    # speech windows are not yet enough for the next start.
    assert detector.accept(windows(36)) == ["end"]


def test_opus_roundtrip():
    encoder, decoder = OpusEncoder(), OpusDecoder()
    t = np.arange(16000) / 16000
    packets = encoder.encode((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32))
    assert len(packets) == 16000 // UPLINK_FRAME
    pcm = np.concatenate([decoder.decode(p) for p in packets])
    assert abs(len(pcm) - len(packets) * 2880) <= 2880  # 60 ms at 48 kHz per packet
    assert 0.15 < float(np.sqrt(np.mean(pcm[4800:] ** 2))) < 0.3


class FakeSpeech:
    def __init__(self):
        self.script = []
        self.resets = []

    def reset(self, in_utterance):
        self.resets.append(in_utterance)

    def accept(self, frame):
        return [self.script.pop(0)] if self.script else []


class FakeWake:
    def __init__(self):
        self.hit = None
        self.resets = 0

    def reset(self):
        self.resets += 1

    def accept(self, frame):
        hit, self.hit = self.hit, None
        return hit


def test_router_pre_roll_and_modes():
    posted = []
    wake, speech = FakeWake(), FakeSpeech()
    router = FrameRouter(wake, speech, OpusEncoder(), pre_roll_ms=600, post=lambda k, d: posted.append((k, d)))
    frame = np.full(160, 0.1, dtype=np.float32)

    router.set_mode(Mode.WAKE)
    wake.hit = "你好小七"
    router.on_frame(frame)
    assert posted == [("wake", "你好小七")] and router.mode == Mode.OFF

    router.set_mode(Mode.WAIT_SPEECH)
    for _ in range(100):  # 1 s of frames, pre-roll keeps ~600 ms
        router.on_frame(frame)
    speech.script = ["start"]
    router.on_frame(frame)
    kind, packets = posted[-1]
    assert kind == "speech_start" and router.mode == Mode.STREAM
    assert len(packets) == 10  # ~600 ms of pre-roll -> ten 60 ms packets

    for _ in range(6):
        router.on_frame(frame)
    speech.script = ["end"]
    router.on_frame(frame)
    assert posted[-1] == ("speech_end", None) and router.mode == Mode.OFF
    assert any(k == "audio" for k, _ in posted)


def test_example_config_loads():
    config = load_config(ROOT / "terminal.example.toml")
    assert config.device_id == "02:76:74:00:00:01"
    assert config.audio.frontend == ["hpf", "ns", "agc"]
    assert config.wake.stream_offsets_ms == [0, 80, 160, 240]
    assert config.audio.silent_reopen_s == 10
    assert "restart-audio-device.ps1" in config.audio.silent_recover_command
    assert config.client_id
    assert config.path(config.vad.model) == ROOT / "models" / "silero_vad.onnx"


def test_config_rejects_unknown_options(tmp_path):
    path = tmp_path / "t.toml"
    path.write_text('[terminal]\ndevice_id = "x"\n[audio]\nbogus = 1\n', encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        load_config(path)
    path.write_text("[terminal]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="device_id"):
        load_config(path)
    for offsets in ("[]", "[0, -80]", "[0, 80.5]"):
        path.write_text(f'[terminal]\ndevice_id = "x"\n[wake]\nstream_offsets_ms = {offsets}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="stream_offsets_ms"):
            load_config(path)
    path.write_text('[terminal]\ndevice_id = "x"\n[wake]\nstream_offsets_ms = [160, 0, 160]\n', encoding="utf-8")
    assert load_config(path).wake.stream_offsets_ms == [0, 160]


class ControlTarget:
    def __init__(self):
        self.conn = object()
        self.calls = []

    def status(self):
        return {"state": "standby"}

    def start_dialog(self, trigger, text=""):
        self.calls.append((trigger, text))

    async def stop_dialog(self):
        self.calls.append(("stop", ""))


async def http(port, method, path, body=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else b""
    writer.write(f"{method} {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(payload)


def test_control_api():
    async def scenario():
        target = ControlTarget()
        server = await control.serve(target, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        assert await http(port, "GET", "/status") == (200, {"state": "standby"})
        assert (await http(port, "POST", "/ask", {"text": "现在几点了"}))[0] == 200
        assert (await http(port, "POST", "/ask", {}))[0] == 400
        assert (await http(port, "POST", "/wake"))[0] == 200
        assert (await http(port, "POST", "/stop"))[0] == 200
        target.conn = None
        assert (await http(port, "POST", "/wake"))[0] == 409
        server.close()
        assert target.calls == [("text", "现在几点了"), ("manual", ""), ("stop", "")]

    asyncio.run(scenario())


def test_playback_buffer_waits_for_threshold_and_refills():
    from voice_terminal.audio import _PlaybackBuffer

    buf = _PlaybackBuffer(threshold=100)
    ones = np.ones(60, dtype=np.float32)
    buf.push(ones)
    assert not buf.pull(10).any()  # 60 < 100 queued: still filling
    buf.push(ones)
    assert buf.pull(120).all() and buf.buffered == 0  # 120 >= 100: plays all of it
    assert buf.underruns == 1  # ran dry mid-answer
    buf.push(ones)
    assert not buf.pull(10).any()  # refilling again after running dry
    buf.push(ones, complete=True)
    out = buf.pull(200)
    assert out[:120].all() and not out[120:].any()
    assert buf.underruns == 1  # the end of a complete clip is not an underrun


def test_playback_buffer_plays_short_complete_clips_and_clears():
    from voice_terminal.audio import _PlaybackBuffer

    buf = _PlaybackBuffer(threshold=1000)
    buf.push(np.ones(50, dtype=np.float32), complete=True)  # a short prompt
    assert buf.pull(50).all()
    buf.push(np.ones(50, dtype=np.float32))
    buf.clear()
    assert buf.buffered == 0 and not buf.pull(10).any()


def test_trim_silence_keeps_speech_and_short_margins():
    from voice_terminal.audio import trim_silence

    rate = 24000
    tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(rate // 2) / rate)).astype(np.float32)
    padded = np.concatenate([np.zeros(rate // 5, np.float32), tone, np.zeros(rate * 6 // 10, np.float32)])
    trimmed = trim_silence(padded, rate)
    assert abs(len(trimmed) - (len(tone) + rate * 150 // 1000)) <= rate // 100  # 30 ms + 120 ms margins
    assert np.allclose(trim_silence(np.zeros(1000, np.float32), rate), 0)  # all silence: unchanged


def test_read_audio_wav_and_mp3(tmp_path):
    import av

    from voice_terminal.audio import read_audio, write_wav

    rate = 24000
    tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)).astype(np.float32)
    write_wav(tmp_path / "t.wav", tone, rate)
    samples, got_rate = read_audio(tmp_path / "t.wav")
    assert got_rate == rate and len(samples) == rate

    try:
        av.codec.Codec("libmp3lame", "w")
    except Exception:
        pytest.skip("PyAV build has no MP3 encoder")
    with av.open(str(tmp_path / "t.mp3"), "w") as out:
        stream = out.add_stream("libmp3lame", rate=rate, layout="mono")
        frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    samples, got_rate = read_audio(tmp_path / "t.mp3")
    assert got_rate == rate and abs(len(samples) - rate) < rate // 10
    assert 0.15 < float(np.sqrt(np.mean(samples[2400:-2400] ** 2))) < 0.3


def test_router_guard_keeps_early_speech_as_pre_roll():
    posted = []
    speech = FakeSpeech()
    router = FrameRouter(FakeWake(), speech, OpusEncoder(), pre_roll_ms=600, post=lambda k, d: posted.append((k, d)))
    frame = np.full(160, 0.1, dtype=np.float32)

    router.set_mode(Mode.GUARD)
    for _ in range(30):  # 300 ms heard during the echo guard: kept, but no VAD
        router.on_frame(frame)
    assert speech.resets == [] and posted == []
    router.set_mode(Mode.WAIT_SPEECH)  # keeps the guard audio
    speech.script = ["start"]
    router.on_frame(frame)
    kind, packets = posted[-1]
    assert kind == "speech_start" and len(packets) == 5  # 310 ms -> five 60 ms packets

    router.set_mode(Mode.OFF)
    router.on_frame(frame)
    router.set_mode(Mode.WAIT_SPEECH)  # not after a guard: starts empty
    speech.script = ["start"]
    router.on_frame(frame)
    assert posted[-1] == ("speech_start", [])  # 10 ms is less than one packet


class FakeKwsStream:
    def __init__(self):
        self.samples = self.decoded = self.resets = 0

    def accept_waveform(self, rate, samples):
        assert rate == 16000
        self.samples += len(samples)


class FakeSpotter:
    """Ready after every 320 ms per stream, like the encoder's chunks; wake(stream index, decode count)."""

    CHUNK = 5120

    def __init__(self, wake=lambda index, decoded: False):
        self.streams = []
        self.wake = wake

    def create_stream(self):
        self.streams.append(FakeKwsStream())
        return self.streams[-1]

    def is_ready(self, stream):
        return stream.samples - stream.decoded * self.CHUNK >= self.CHUNK

    def decode_stream(self, stream):
        stream.decoded += 1

    def decode_streams(self, streams):
        raise AssertionError("this model only takes one stream per call")

    def get_result(self, stream):
        return "你好小七" if self.wake(self.streams.index(stream) % 4, stream.decoded) else ""

    def reset_stream(self, stream):
        stream.resets += 1


def feed(detector, seconds):
    hits = []
    for _ in range(int(seconds * 100)):
        hit = detector.accept(np.zeros(160, dtype=np.float32))
        if hit:
            hits.append(hit)
    return hits


def test_wake_streams_are_offset_and_decoded_one_at_a_time():
    spotter = FakeSpotter()
    config = WakeConfig(max_active_paths=16, stream_offsets_ms=[0, 80, 160, 240])
    detector = WakeWordDetector(config, Path("."), spotter=spotter)
    assert feed(detector, 1.0) == []
    assert [s.samples for s in spotter.streams] == [16000, 14720, 13440, 12160]
    assert [s.decoded for s in spotter.streams] == [3, 2, 2, 2]

    detector.reset()  # fresh streams, offset again
    feed(detector, 0.5)
    assert len(spotter.streams) == 8
    assert [s.samples for s in spotter.streams[4:]] == [8000, 6720, 5440, 4160]


def test_any_wake_stream_wakes_once_and_resets_all():
    spotter = FakeSpotter(wake=lambda index, decoded: index == 2 and decoded == 1)
    detector = WakeWordDetector(WakeConfig(stream_offsets_ms=[0, 80, 160, 240]), Path("."), spotter=spotter)
    assert feed(detector, 1.0) == ["你好小七"]
    assert [s.resets for s in spotter.streams] == [1, 1, 1, 1]


def test_microphone_measures_exact_silence():
    mic = Microphone("mic", "", Frontend([]), lambda frame: None)
    status = SimpleNamespace(input_overflow=False)
    mic._running = True
    mic.last_callback = mic.last_sound = time.monotonic() - 20
    mic._callback(np.zeros((80, 1), dtype=np.float32), 80, None, status)
    assert 19 < mic.silent_s < 21 and not mic.heard_sound
    assert mic.health()["mic_silent_ms"] > 19000
    mic._callback(np.full((80, 1), 1e-4, dtype=np.float32), 80, None, status)
    assert mic.silent_s < 1 and mic.heard_sound
    mic.last_callback -= 10  # stalled: no callbacks is not silence
    assert mic.stalled and mic.silent_s == 0.0


def exits(text):
    return match_exit_words(text, DEFAULT_EXIT_WORDS, ["你好小七"])


@pytest.mark.parametrize("text", ["拜拜", "再见！", "退下吧", "没事了", "不用了，谢谢", "好的，谢谢，再见",
                                  "嗯，拜拜啦", "Bye bye.", "没事了，拜拜", "你好小七，拜拜", "小七再见",
                                  "你好小青，拜拜", "亲拜拜"])
def test_exit_words_end_the_conversation(text):
    assert exits(text)


@pytest.mark.parametrize("text", ["关灯，拜拜", "用英语怎么说再见", "跟奶奶说拜拜", "晚安", "我要出门了拜拜",
                                  "你好小七", "谢谢", "", "不用了，帮我把灯关掉"])
def test_requests_are_not_exit_words(text):
    assert exits(text) is None


def test_exit_words_come_from_the_config(tmp_path):
    assert match_exit_words("拜拜", []) is None
    assert match_exit_words("先这样吧", ["先这样"]) == "先这样"
    path = tmp_path / "t.toml"
    path.write_text('[terminal]\ndevice_id = "x"\n', encoding="utf-8")
    assert load_config(path).session.exit_words == DEFAULT_EXIT_WORDS
    path.write_text('[terminal]\ndevice_id = "x"\n[session]\nexit_words = []\n', encoding="utf-8")
    assert load_config(path).session.exit_words == []
