import asyncio
import json
import sys

import numpy as np
from conftest import FakeConnection, FakeMic, FakeSpeaker, wait_for

from voice_terminal import terminal as terminal_module
from voice_terminal.codec import OpusEncoder
from voice_terminal.terminal import Event, Mode, State, Terminal


class NoSpeech:
    def reset(self, in_utterance):
        pass

    def accept(self, samples):
        return []


def make_terminal(config):
    FakeConnection.instances.clear()
    speaker = FakeSpeaker()
    terminal = Terminal(config, lambda on_frame: FakeMic(), speaker, None, NoSpeech(), connection_factory=FakeConnection)
    return terminal, speaker


def opus_packet():
    encoder = OpusEncoder()
    t = np.arange(960 * 3) / 16000
    return encoder.encode((0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32))[0]


async def start(terminal):
    task = asyncio.create_task(terminal.run())
    await wait_for(lambda: terminal.state == State.STANDBY)
    return task, FakeConnection.instances[-1]


async def stop(terminal, task):
    terminal.shutdown()
    await asyncio.wait_for(task, 2)


def answer(terminal, text="一加一等于二。"):
    terminal._on_json({"type": "tts", "state": "start"})
    terminal._on_audio(opus_packet())
    terminal._on_json({"type": "tts", "state": "sentence_start", "text": text})
    terminal._on_json({"type": "tts", "state": "stop"})


def test_voice_turn_then_idle_timeout(config):
    async def scenario():
        terminal, speaker = make_terminal(config)
        task, conn = await start(terminal)
        assert terminal.router.mode == Mode.WAKE

        terminal._uplink.put_nowait(Event("wake", "你好小七"))
        await wait_for(lambda: terminal.state == State.AWAKE)
        assert len(speaker.played) == 1  # wake prompt
        assert terminal.router.mode == Mode.WAIT_SPEECH

        terminal._uplink.put_nowait(Event("speech_start", [b"p1"]))
        terminal._uplink.put_nowait(Event("audio", [b"p2"]))
        terminal._uplink.put_nowait(Event("speech_end"))
        await wait_for(lambda: terminal.state == State.THINKING)
        assert conn.sent == [("listen", "start", "manual"), b"p1", b"p2", ("listen", "stop")]

        terminal._on_json({"type": "stt", "text": "一加一等于几"})
        answer(terminal)
        await wait_for(lambda: terminal.stats["turns"] == 1)
        assert speaker.fed > 0 and speaker.ended == 1
        assert terminal.stats["last_stt"] == "一加一等于几"
        assert terminal.stats["last_reply"] == "一加一等于二。"

        # Continuous conversation, then the idle timeout plays goodbye.
        await wait_for(lambda: terminal.state == State.AWAKE)
        await wait_for(lambda: terminal.state == State.STANDBY)
        assert len(speaker.played) == 2
        assert terminal.router.mode == Mode.WAKE
        await stop(terminal, task)

    asyncio.run(scenario())


def test_no_recognition_asks_again(config):
    async def scenario():
        terminal, speaker = make_terminal(config)
        task, conn = await start(terminal)
        terminal.start_dialog("manual")
        await wait_for(lambda: terminal.state == State.AWAKE)
        terminal._uplink.put_nowait(Event("speech_start", []))
        terminal._uplink.put_nowait(Event("speech_end"))
        await wait_for(lambda: len(speaker.played) == 2)  # wake + "没听清"
        await wait_for(lambda: terminal.state == State.AWAKE)
        await stop(terminal, task)

    asyncio.run(scenario())


def test_text_question_plays_reply(config):
    async def scenario():
        terminal, speaker = make_terminal(config)
        task, conn = await start(terminal)
        terminal.start_dialog("text", "现在几点了")
        await wait_for(lambda: ("listen", "detect", "现在几点了") in conn.sent)
        assert terminal.state == State.THINKING
        terminal._on_json({"type": "stt", "text": "现在几点了"})
        answer(terminal, "现在是晚上十点。")
        await wait_for(lambda: terminal.stats["turns"] == 1)
        assert speaker.fed > 0
        assert speaker.played == []  # no wake prompt for text
        await stop(terminal, task)

    asyncio.run(scenario())


def test_stop_during_reply(config):
    async def scenario():
        terminal, speaker = make_terminal(config)
        task, conn = await start(terminal)
        terminal.start_dialog("text", "讲个长故事")
        await wait_for(lambda: terminal.state == State.THINKING)
        terminal._on_json({"type": "tts", "state": "start"})
        await wait_for(lambda: terminal.state == State.SPEAKING)
        await terminal.stop_dialog()
        assert ("abort",) in conn.sent
        assert terminal.state == State.STANDBY and terminal.router.mode == Mode.WAKE
        terminal._on_audio(opus_packet())
        assert speaker.fed == 0  # audio after stop is dropped
        await stop(terminal, task)

    asyncio.run(scenario())


def test_unsolicited_reply_is_played(config):
    async def scenario():
        terminal, speaker = make_terminal(config)
        task, conn = await start(terminal)
        answer(terminal, "提醒：该出门了。")
        await wait_for(lambda: terminal.stats["turns"] == 1)
        assert speaker.fed > 0
        await stop(terminal, task)

    asyncio.run(scenario())


def test_reconnects_and_drops_conversation(config):
    async def scenario():
        terminal, speaker = make_terminal(config)
        task, first = await start(terminal)
        terminal.start_dialog("manual")
        await wait_for(lambda: terminal.state == State.AWAKE)
        await first.close()
        await wait_for(lambda: len(FakeConnection.instances) == 2 and terminal.state == State.STANDBY)
        assert terminal._dialog is None
        assert terminal.stats["reconnects"] == 1
        await stop(terminal, task)

    asyncio.run(scenario())


class SilentMic(FakeMic):
    def __init__(self, silent_s, heard_sound):
        self.silent_s, self.heard_sound = silent_s, heard_sound


def test_silent_mic_reopens_then_runs_recover_command(config, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_module, "AUDIO_CHECK_SECONDS", 0.01)
    monkeypatch.setattr(terminal_module, "SILENT_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(terminal_module, "refresh_devices", lambda: None)
    (tmp_path / "mark.py").write_text("open('recovered.txt', 'a').write('x')\n", encoding="utf-8")
    config.audio.silent_reopen_s = 5
    config.audio.silent_recover_command = f'"{sys.executable}" mark.py'
    # Went silent; still silent after the plain reopen; has sound after the command.
    mics = iter([SilentMic(10, True), SilentMic(10, False), SilentMic(0, True)])
    made = []

    def make_mic(on_frame):
        made.append(next(mics))
        return made[-1]

    async def scenario():
        FakeConnection.instances.clear()
        terminal = Terminal(config, make_mic, FakeSpeaker(), None, NoSpeech(), connection_factory=FakeConnection)
        task = asyncio.create_task(terminal.run())
        await wait_for(lambda: len(made) == 3 and terminal._silent_attempts == 0, timeout=10)
        assert (tmp_path / "recovered.txt").read_text() == "x"  # only after the reopen did not help
        assert terminal.status()["mic_silent_s"] == 0.0
        await asyncio.sleep(0.05)
        assert len(made) == 3
        await stop(terminal, task)
        lines = (tmp_path / "logs" / "audio-health.jsonl").read_text(encoding="utf-8").splitlines()
        kinds = [json.loads(line)["event"] for line in lines]
        assert kinds.count("capture_silent") == 2 and "silent_recover" in kinds and "capture_sound_back" in kinds

    asyncio.run(scenario())
