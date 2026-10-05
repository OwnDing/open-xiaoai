import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import xiaozhi.event as event_module
from xiaozhi.event import Step
from xiaozhi.services.audio.kws import _KWS
from xiaozhi.services.protocols.typing import DeviceState


class SessionExitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = getattr(event_module, "__EventManager")()
        self.manager.current_step = Step.on_tts_end
        with patch("xiaozhi.services.audio.kws.set_kws"):
            self.kws = _KWS()
        self.vad = SimpleNamespace(resume=Mock(), pause=Mock())
        self.xiaozhi = SimpleNamespace(
            loop=asyncio.get_running_loop(), device_state=DeviceState.IDLE,
            abort_tts_output=AsyncMock(),
            protocol=SimpleNamespace(send_abort_speaking=AsyncMock()),
        )
        def set_state(state):
            self.xiaozhi.device_state = state
            self.vad.pause()
        self.xiaozhi.set_device_state = set_state
        self.speaker = object()
        self.health = Mock()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"get_env": "1", "get_xiaozhi": self.xiaozhi,
                            "get_vad": self.vad, "get_kws": self.kws,
                            "get_audio_codec": object(), "get_speaker": self.speaker}.items():
            self.stack.enter_context(patch(f"xiaozhi.event.{name}", return_value=value))
        self.stack.enter_context(patch("xiaozhi.event.HEALTH", self.health))
        self.stack.enter_context(patch.dict(event_module.APP_CONFIG["vad"], {"tts_end_guard_ms": 0}))
        self.stack.enter_context(patch.dict(event_module.APP_CONFIG["wakeup"], {"timeout": 0.01, "exit_guard_ms": 0}))

    async def run_timeout(self):
        await self.manager._EventManager__start_session(self.manager.session_id, Step.on_tts_end)

    async def test_timeout_isolates_goodbye_and_requests_reset(self):
        async def goodbye(speaker):
            self.assertIs(speaker, self.speaker)
            self.assertTrue(self.kws.paused)
            self.assertEqual(self.manager.current_step, Step.idle)
            self.assertEqual(self.xiaozhi.device_state, DeviceState.IDLE)
            self.vad.pause.assert_called()
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"after_wakeup": goodbye}):
            await self.run_timeout()
        self.assertFalse(self.kws.paused)
        self.assertEqual(self.kws._reset_reason, "session_exit")
        self.assertIsNone(self.manager.next_step_future)
        self.assertIsNone(self.manager.next_step_loop)
        self.assertEqual(self.manager.current_step, Step.idle)
        phases = [c.args[0] for c in self.health.emit.call_args_list]
        self.assertEqual(phases, ["session_exit_start", "session_exit_prompt_start",
                                 "session_exit_prompt_end", "session_exit_guard_end", "session_exit_end"])

    async def test_guard_keeps_detection_paused_after_goodbye(self):
        played = asyncio.Event()
        async def goodbye(speaker):
            played.set()
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"after_wakeup": goodbye, "exit_guard_ms": 40}):
            task = asyncio.create_task(self.run_timeout())
            await asyncio.wait_for(played.wait(), 1)
            self.assertTrue(self.kws.paused)
            await task
        self.assertFalse(self.kws.paused)

    async def test_failed_goodbye_still_rearms(self):
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"after_wakeup": AsyncMock(side_effect=OSError("play failed"))}):
            await self.run_timeout()
        self.assertFalse(self.kws.paused)
        self.assertEqual(self.kws._reset_reason, "session_exit")
        self.assertTrue(any(c.args[0] == "session_exit_prompt_error" for c in self.health.emit.call_args_list))

    async def test_disabled_goodbye_still_rearms(self):
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"after_wakeup": ""}):
            await self.run_timeout()
        self.assertFalse(self.kws.paused)
        self.assertEqual(self.kws._reset_reason, "session_exit")

    async def test_cancelled_exit_does_not_release_new_wakeup_pause(self):
        playing = asyncio.Event()
        async def goodbye(speaker):
            playing.set()
            await asyncio.Event().wait()
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"after_wakeup": goodbye}):
            task = asyncio.create_task(self.run_timeout())
            await asyncio.wait_for(playing.wait(), 1)
            self.manager._set_step(Step.on_wakeup, new_session=True)
            self.kws.pause()  # the new wake's prompt owns a separate pause
            self.xiaozhi.device_state = DeviceState.LISTENING
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(self.kws.paused)
        self.assertEqual(self.xiaozhi.device_state, DeviceState.LISTENING)
        self.assertEqual(self.manager.current_step, Step.on_wakeup)
        self.kws.resume()
        self.assertFalse(self.kws.paused)

    async def test_late_tts_end_does_not_reopen_closed_session(self):
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"after_wakeup": ""}):
            await self.run_timeout()
        with patch.object(self.manager, "start_session") as start:
            self.manager.on_tts_end("old-response")
            start.assert_not_called()
            self.manager.on_wakeup()
            start.assert_called_once()
        self.assertEqual(self.manager.current_step, Step.on_wakeup)

    async def test_stale_exit_does_not_change_new_session(self):
        self.manager._set_step(Step.on_wakeup, new_session=True)
        self.xiaozhi.device_state = DeviceState.LISTENING
        await self.manager._end_session(self.manager.session_id - 1, self.xiaozhi, self.speaker)
        self.assertFalse(self.kws.paused)
        self.assertEqual(self.xiaozhi.device_state, DeviceState.LISTENING)
        self.health.emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
