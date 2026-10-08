import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

import xiaozhi.event as event_module
from xiaozhi.event import Step
from xiaozhi.services.audio.aec import SubbandEchoCanceller
from xiaozhi.services.audio.kws import _KWS
from xiaozhi.services.audio.stream import GlobalStream, MyStream
from xiaozhi.services.protocols.typing import DeviceState


def speech_like(n, seed):
    """Noise shaped a bit like speech: louder, band-limited bursts."""
    rng = np.random.default_rng(seed)
    x = np.convolve(rng.standard_normal(n), np.hanning(9), mode="same")
    envelope = 0.5 + 0.5 * np.sin(np.arange(n) * 2 * np.pi * 3 / 16000)
    return x * envelope


def power_db(x):
    return 10 * np.log10(np.mean(np.asarray(x) ** 2) + 1e-20)


class EchoCancellerTests(unittest.TestCase):
    def run_canceller(self, mic, ref, chunk=1440):
        canceller = SubbandEchoCanceller()
        out = np.concatenate([canceller.process(mic[i : i + chunk], ref[i : i + chunk])
                              for i in range(0, len(mic), chunk)])
        return canceller, out

    def test_output_is_the_input_delayed_when_nothing_plays(self):
        mic = speech_like(16000, 1) * 1000
        canceller, out = self.run_canceller(mic, np.zeros_like(mic), chunk=777)
        self.assertEqual(len(out), len(mic))
        d = canceller.delay
        np.testing.assert_allclose(out[d:], mic[:-d], atol=1e-6)
        self.assertFalse(canceller.ref_active)

    def test_removes_the_echo_and_keeps_the_talker(self):
        n = 16000 * 12
        ref = speech_like(n, 2) * 3000
        # Echo: a short delay plus a decaying tail, like the enclosure and room.
        path = np.zeros(400)
        path[20] = 0.8
        path[60:400] = 0.05 * np.exp(-np.arange(340) / 80) * np.random.default_rng(3).standard_normal(340)
        echo = np.convolve(ref, path)[:n]
        talker = np.zeros(n)
        talker[16000 * 10 : 16000 * 11] = speech_like(16000, 4) * 300
        canceller, out = self.run_canceller(echo + talker, ref)
        d = canceller.delay
        before = slice(16000 * 8, 16000 * 10)  # echo only, filter converged
        reduction = power_db(echo[before]) - power_db(out[before.start + d : before.stop + d])
        self.assertGreater(reduction, 30)
        during = slice(16000 * 10, 16000 * 11)
        kept = power_db(out[during.start + d : during.stop + d]) - power_db(talker[during])
        self.assertLess(abs(kept), 1.0)  # the talker comes through at full level
        self.assertTrue(canceller.ref_active)
        self.assertGreater(canceller.reduction_db(), 20)

    def test_chunk_size_does_not_change_the_result(self):
        n = 16000 * 3
        ref = speech_like(n, 5) * 2000
        mic = np.convolve(ref, [0, 0.5, 0.2])[:n] + speech_like(n, 6) * 50
        _, a = self.run_canceller(mic, ref, chunk=1440)
        _, b = self.run_canceller(mic, ref, chunk=100)
        np.testing.assert_allclose(a, b, atol=1e-6)

    def test_near_end_ratio_tells_a_talker_from_leaking_echo(self):
        n = 16000 * 10
        ref = speech_like(n, 7) * 3000
        echo = np.convolve(ref, [0, 0, 0.9, 0.3])[:n]
        # Nonlinear leak the linear filter cannot remove: ~ -25 dB.
        leak = 0.05 * np.tanh(ref / 3000) * 3000
        quiet, _ = self.run_canceller(echo + leak, ref)
        talker = np.zeros(n)
        talker[-16000:] = speech_like(16000, 8) * 1000
        loud, _ = self.run_canceller(echo + leak + talker, ref)
        self.assertLess(quiet.near_end_ratio_db(), -10)
        self.assertGreater(loud.near_end_ratio_db(), quiet.near_end_ratio_db() + 10)


class PrerollStreamTests(unittest.TestCase):
    def setUp(self):
        self.saved = (dict(GlobalStream.readers), GlobalStream.samples, bytes(GlobalStream._history))
        GlobalStream.readers.clear()
        GlobalStream.samples = 0
        GlobalStream._history = bytearray()

    def tearDown(self):
        readers, samples, history = self.saved
        GlobalStream.readers.clear()
        GlobalStream.readers.update(readers)
        GlobalStream.samples = samples
        GlobalStream._history = bytearray(history)

    def test_late_reader_gets_what_was_said_since_a_position(self):
        kws = MyStream(16000, 1, 8, input=True, start=True)
        GlobalStream.input(np.arange(100, dtype="<i2").tobytes())
        kws.read(40)
        position = kws.position()  # the keyword ended here
        self.assertEqual(position, 40)
        GlobalStream.input(np.arange(100, 150, dtype="<i2").tobytes())

        vad = MyStream(16000, 1, 8, input=True, start=False)
        vad.start_stream(since=position)
        GlobalStream.input(np.arange(150, 160, dtype="<i2").tobytes())

        got = np.frombuffer(vad.read(), dtype="<i2")
        np.testing.assert_array_equal(got, np.arange(40, 160))
        self.assertEqual(vad.position(), 160)

    def test_too_old_position_starts_at_the_oldest_kept_sample(self):
        from xiaozhi.services.audio import stream as stream_module

        with patch.object(stream_module, "HISTORY_SAMPLES", 50):
            GlobalStream.input(np.arange(120, dtype="<i2").tobytes())
            reader = MyStream(16000, 1, 8, input=True, start=False)
            reader.start_stream(since=0)
        np.testing.assert_array_equal(np.frombuffer(reader.read(), dtype="<i2"), np.arange(70, 120))


def make_event_manager():
    return getattr(event_module, "__EventManager")()


class BargeInSessionTests(unittest.IsolatedAsyncioTestCase):
    async def run_barge_in(self, near_end_db=None, min_db=None):
        manager = make_event_manager()
        loop = asyncio.get_running_loop()
        listening = asyncio.Event()
        calls = []

        class FakeVAD:
            def resume(self, target, since=None):
                calls.append(("vad", target, since))
                listening.set()

        class FakeProtocol:
            async def send_abort_speaking(self, reason):
                calls.append(("server_abort",))

        class FakeXiaoZhi:
            def __init__(self):
                self.loop = loop
                self.protocol = FakeProtocol()

            def set_device_state(self, state):
                calls.append(("state", state))

            def ignore_tts_until_stt(self):
                calls.append(("gate",))

            async def abort_tts_output(self):
                calls.append(("stop_playback",))

        speaker = SimpleNamespace(run_shell=AsyncMock())
        canceller = SimpleNamespace(near_end_ratio_db=lambda: near_end_db)
        settings = {"prompt_tone": "/tone.opus", "keyword_tail_ms": 100, "near_end_min_db": min_db}
        with (
            patch.dict(event_module.APP_CONFIG, {"barge_in": settings}),
            patch("xiaozhi.event.get_env", return_value="1"),
            patch("xiaozhi.event.get_xiaozhi", return_value=FakeXiaoZhi()),
            patch("xiaozhi.event.get_xiaoai", return_value=SimpleNamespace(echo=canceller)),
            patch("xiaozhi.event.get_vad", return_value=FakeVAD()),
            patch("xiaozhi.event.get_audio_codec", return_value=None),
            patch("xiaozhi.event.get_speaker", return_value=speaker),
            patch("xiaozhi.event.HEALTH") as health,
        ):
            manager.barge_in("你好小七", position=48000)
            try:
                await asyncio.wait_for(listening.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0)
        return manager, calls, speaker, health

    async def test_stops_playback_plays_a_tone_and_listens_from_the_keyword(self):
        manager, calls, speaker, health = await self.run_barge_in()
        self.assertEqual(
            calls,
            [("state", DeviceState.IDLE), ("gate",), ("stop_playback",), ("server_abort",),
             ("vad", "speech", 48000 - 100 * 16)],
        )
        speaker.run_shell.assert_awaited_once()
        self.assertIn("miplayer -f /tone.opus", speaker.run_shell.await_args.args[0])
        self.assertEqual(manager.current_step, Step.on_barge_in)
        self.assertIsNone(manager.listen_from)
        health.emit.assert_any_call("barge_in", keyword="你好小七", near_end_db=None, rejected=False)

    async def test_a_hit_that_sounds_like_echo_can_be_ignored(self):
        manager, calls, speaker, health = await self.run_barge_in(near_end_db=-22.0, min_db=-17)
        self.assertEqual(calls, [])
        speaker.run_shell.assert_not_awaited()
        health.emit.assert_any_call("barge_in", keyword="你好小七", near_end_db=-22.0, rejected=True)

    async def test_late_tts_end_does_not_restart_the_barge_in_turn(self):
        manager = make_event_manager()
        manager.current_step = Step.on_barge_in
        with patch("xiaozhi.event.get_env", return_value="1"), patch.object(manager, "start_session") as start:
            manager.on_tts_end("session")
        start.assert_not_called()


class KWSDuringPlaybackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("xiaozhi.services.audio.kws.set_kws"):
            self.kws = _KWS()
        self.state = SimpleNamespace(device_state=DeviceState.SPEAKING)
        patcher = patch("xiaozhi.services.audio.kws.get_xiaozhi", return_value=self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ready(self, enabled, live):
        return (
            patch.dict("xiaozhi.services.audio.kws.APP_CONFIG", {"barge_in": {"enabled": enabled}}),
            patch("xiaozhi.services.audio.kws.get_xiaoai",
                  return_value=SimpleNamespace(echo_reference_live=lambda: live)),
        )

    def test_listens_while_speaking_only_with_a_live_echo_reference(self):
        for enabled, live, expected in [(True, True, "active"), (True, False, DeviceState.SPEAKING),
                                        (False, True, DeviceState.SPEAKING)]:
            config, xiaoai = self.ready(enabled, live)
            with config, xiaoai:
                self.assertEqual(self.kws._mode(), expected)

    async def test_hit_while_speaking_interrupts_instead_of_greeting(self):
        config, xiaoai = self.ready(True, True)
        with (
            config, xiaoai,
            patch("xiaozhi.services.audio.kws.EventManager.barge_in") as barge_in,
            patch("xiaozhi.services.audio.kws.EventManager.wakeup", new=AsyncMock()) as wakeup,
        ):
            await self.kws._dispatch_wakeup("你好小七", self.kws._revision, 1234)
            barge_in.assert_called_once_with("你好小七", 1234)
            wakeup.assert_not_awaited()
            self.state.device_state = DeviceState.IDLE
            await self.kws._dispatch_wakeup("你好小七", self.kws._revision, 1234)
            wakeup.assert_awaited_once_with("你好小七", "kws")


class EchoAwareVADTests(unittest.TestCase):
    def test_frames_that_may_hold_echo_need_the_higher_threshold(self):
        from xiaozhi.services.audio.vad import _VAD

        with patch.dict(event_module.APP_CONFIG, {"barge_in": {"echo_vad_threshold": 0.7}}), \
                patch("xiaozhi.services.audio.vad.set_vad"):
            vad = _VAD()
        with patch("xiaozhi.services.audio.vad.get_xiaoai", return_value=SimpleNamespace(echo_until=5000)):
            self.assertEqual(vad.frame_threshold(4999), 0.7)
            self.assertEqual(vad.frame_threshold(5000), vad.threshold)
            self.assertEqual(vad.frame_threshold(None), vad.threshold)
        with patch("xiaozhi.services.audio.vad.get_xiaoai", return_value=None):
            self.assertEqual(vad.frame_threshold(0), vad.threshold)


class InterruptedReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_tts_is_dropped_until_the_next_utterance_is_recognized(self):
        from xiaozhi.xiaozhi import XiaoZhi

        xiaozhi = XiaoZhi.__new__(XiaoZhi)
        xiaozhi._tts_gate = False
        xiaozhi.tts_output_mode = "native_xiaomi"
        xiaozhi.native_tts = SimpleNamespace(start=AsyncMock(), add_text=AsyncMock())
        xiaozhi.config = SimpleNamespace(update_config_file=Mock())
        xiaozhi.schedule = Mock()
        xiaozhi.ignore_tts_until_stt()
        with patch("xiaozhi.xiaozhi.EventManager") as events:
            await xiaozhi._handle_tts_message({"state": "start"})
            await xiaozhi._handle_tts_message({"state": "sentence_start", "text": "旧回答"})
            await xiaozhi._handle_tts_message({"state": "stop"})
            xiaozhi.native_tts.start.assert_not_awaited()
            xiaozhi.native_tts.add_text.assert_not_awaited()
            events.on_tts_end.assert_not_called()

            xiaozhi._handle_stt_message({"text": "明天天气怎么样"})
            await xiaozhi._handle_tts_message({"state": "start", "session_id": "s"})
            await xiaozhi._handle_tts_message({"state": "sentence_start", "text": "明天晴"})
        xiaozhi.native_tts.start.assert_awaited_once()
        xiaozhi.native_tts.add_text.assert_awaited_once_with("明天晴")


class EchoPacketTests(unittest.TestCase):
    def test_stereo_packets_become_mono_and_mark_the_reference_live(self):
        from xiaozhi.xiaoai import XiaoAI

        XiaoAI.echo, XiaoAI._echo_seen = None, None
        self.addCleanup(setattr, XiaoAI, "echo", None)
        self.addCleanup(setattr, XiaoAI, "_echo_seen", None)
        self.assertFalse(XiaoAI.echo_reference_live())
        frames = np.zeros((1440, 2), dtype="<i2")
        frames[:, 0] = 100
        meta = {"capture_id": "c", "seq": 1, "sample_start": 0, "samples": 1440, "layout": "mic_ref"}
        with patch("xiaozhi.xiaoai.GlobalStream") as stream, patch("xiaozhi.xiaoai.HEALTH"):
            XiaoAI.on_input_packet((frames.tobytes(), json.dumps(meta)))
        fed = stream.input.call_args.args[0]
        self.assertEqual(len(fed), 1440 * 2)
        self.assertTrue(XiaoAI.echo_reference_live())
        # Once the canceller's delay has passed, the mic comes through at the configured gain.
        with patch("xiaozhi.xiaoai.GlobalStream") as stream, patch("xiaozhi.xiaoai.HEALTH"):
            XiaoAI.on_input_packet((frames.tobytes(), json.dumps({**meta, "seq": 2})))
        out = np.frombuffer(stream.input.call_args.args[0], dtype="<i2")
        self.assertEqual(int(out[-1]), int(round(100 * XiaoAI.echo_gain)))

    def test_playback_in_a_packet_opens_the_echo_window(self):
        from xiaozhi.xiaoai import XiaoAI

        XiaoAI.echo, XiaoAI.echo_until = None, -1
        self.addCleanup(setattr, XiaoAI, "echo", None)
        self.addCleanup(setattr, XiaoAI, "echo_until", -1)
        frames = np.zeros((1440, 2), dtype="<i2")
        meta = {"capture_id": "c", "seq": 1, "layout": "mic_ref"}
        stream = SimpleNamespace(samples=16000, input=Mock())
        with patch("xiaozhi.xiaoai.GlobalStream", stream), patch("xiaozhi.xiaoai.HEALTH"):
            XiaoAI.on_input_packet((frames.tobytes(), json.dumps(meta)))
            self.assertEqual(XiaoAI.echo_until, -1)  # nothing played
            frames[100, 1] = 5
            XiaoAI.on_input_packet((frames.tobytes(), json.dumps({**meta, "seq": 2})))
        self.assertEqual(XiaoAI.echo_until, 16000 + 1440 + XiaoAI.echo.delay + 300 * 16)

    def test_mono_packets_pass_through(self):
        from xiaozhi.xiaoai import XiaoAI

        data = np.arange(10, dtype="<i2").tobytes()
        with patch("xiaozhi.xiaoai.GlobalStream") as stream, patch("xiaozhi.xiaoai.HEALTH"):
            XiaoAI.on_input_packet((data, json.dumps({"capture_id": "c", "seq": 1})))
        self.assertEqual(stream.input.call_args.args[0], data)


if __name__ == "__main__":
    unittest.main()
