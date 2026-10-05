import threading
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from xiaozhi.services.audio.kws import _KWS
from xiaozhi.services.audio.kws.sherpa import _SherpaOnnx
from xiaozhi.services.audio.stream import MyStream
from xiaozhi.services.protocols.typing import DeviceState


class KWSLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("xiaozhi.services.audio.kws.set_kws"):
            self.kws = _KWS()
        self.kws.stream = MyStream(16000, 1, 8, input=True, start=False)
        self.kws.on_message = Mock()
        self.state = SimpleNamespace(device_state=DeviceState.IDLE)
        self.model = Mock()
        self.model.kws.return_value = None
        self.health = Mock()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("xiaozhi.services.audio.kws.get_xiaozhi", return_value=self.state))
        self.stack.enter_context(patch("xiaozhi.services.audio.kws.SherpaOnnx", self.model))
        self.stack.enter_context(patch("xiaozhi.services.audio.kws.HEALTH", self.health))
        self.frame = bytes(960 * 2)

    def test_reset_runs_on_detection_worker_and_discards_old_buffer(self):
        self.kws.pause()
        self.kws._process_frames(self.frame)
        self.kws.resume(reason="session_exit")
        self.model.reset.assert_not_called()
        self.kws.stream.input_bytes.extend(bytes(320 * 2))
        threads = []
        self.model.reset.side_effect = lambda: threads.append(threading.current_thread())
        worker = threading.Thread(target=self.kws._process_frames, args=(self.frame,))
        worker.start(); worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(threads, [worker])
        self.assertEqual(self.kws.stream.input_bytes, [])
        self.model.kws.assert_not_called()
        self.health.kws.assert_any_call(1280, "reset")
        self.kws._process_frames(self.frame)
        self.model.reset.assert_called_once()
        self.model.kws.assert_called_once_with(self.frame)

    def test_nested_pause_waits_for_both_owners(self):
        self.kws.pause(); self.kws.pause()
        self.kws.resume(reason="session_exit")
        self.assertTrue(self.kws.paused)
        self.kws._process_frames(self.frame)
        self.model.kws.assert_not_called()
        self.model.reset.assert_not_called()
        self.kws.resume()
        self.kws._process_frames(self.frame)
        self.assertFalse(self.kws.paused)
        self.model.reset.assert_called_once()

    def test_rearm_before_reading_accepts_the_first_fresh_frame(self):
        self.kws.pause(); self.kws.resume(reason="session_exit")
        self.kws.stream.input_bytes.extend(bytes(640))
        self.kws._process_frames(b"")
        self.model.kws.return_value = "你好小七"
        self.kws._process_frames(self.frame)
        self.model.kws.assert_called_once_with(self.frame)
        self.kws.on_message.assert_called_once_with("你好小七", self.kws._revision)

    def test_reset_failure_is_logged(self):
        self.kws.pause(); self.kws.resume()
        self.model.reset.side_effect = RuntimeError("reset failed")
        with self.assertRaises(RuntimeError):
            self.kws._process_frames(self.frame)
        self.health.kws.assert_called_once_with(960, "reset", error=True)
        self.assertTrue(any(c.args[0] == "kws_reset_error" for c in self.health.emit.call_args_list))

    def test_listening_and_speaking_discontinuities_reset_on_return(self):
        for index, mode in enumerate([DeviceState.LISTENING, DeviceState.SPEAKING], 1):
            self.state.device_state = mode
            self.kws._process_frames(self.frame)
            self.state.device_state = DeviceState.IDLE
            self.kws._process_frames(self.frame)
            self.assertEqual(self.model.reset.call_count, index)
        self.model.kws.assert_not_called()

    def test_pause_during_decode_suppresses_stale_hit(self):
        def decode(frames):
            self.kws.pause()
            return "你好小七"
        self.model.kws.side_effect = decode
        self.kws._process_frames(self.frame)
        self.kws.on_message.assert_not_called()
        self.assertFalse(self.health.kws.call_args.kwargs["hit"])
        self.assertTrue(any(c.args[0] == "kws_stale_hit" for c in self.health.emit.call_args_list))

    async def test_queued_hit_is_rechecked_on_owner_loop(self):
        revision = self.kws._revision
        self.kws.pause(); self.kws.resume()
        with patch("xiaozhi.services.audio.kws.EventManager.wakeup", new=AsyncMock()) as wake:
            await self.kws._dispatch_wakeup("你好小七", revision)
            wake.assert_not_awaited()
            self.kws._process_frames(b"")
            await self.kws._dispatch_wakeup("你好小七", self.kws._revision)
            wake.assert_awaited_once_with("你好小七", "kws")

    def test_reset_request_during_reset_is_not_lost(self):
        self.kws.pause(); self.kws.resume(reason="session_exit")
        self.model.reset.side_effect = lambda: self.kws.resume(reason="new_request")
        self.kws._process_frames(self.frame)
        self.assertEqual(self.kws._reset_reason, "new_request")
        self.model.reset.side_effect = None
        self.kws._process_frames(self.frame)
        self.assertEqual(self.model.reset.call_count, 2)
        self.assertIsNone(self.kws._reset_reason)

    def test_real_microphone_buffer_is_discarded_too(self):
        self.kws.stream = Mock(spec=["get_read_available", "read"])
        self.kws.stream.get_read_available.return_value = 320
        self.kws.stream.read.return_value = bytes(640)
        self.kws.pause(); self.kws.resume()
        self.kws._process_frames(self.frame)
        self.kws.stream.read.assert_called_once_with(320, exception_on_overflow=False)
        self.health.kws.assert_called_once_with(1280, "reset")

    def test_model_reset_drops_features_without_reloading_weights(self):
        model = _SherpaOnnx()
        old_stream = object()
        new_stream = object()
        model.stream = old_stream
        model.keyword_spotter = Mock()
        model.keyword_spotter.create_stream.return_value = new_stream
        model.reset()
        self.assertIs(model.stream, new_stream)
        model.keyword_spotter.create_stream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
