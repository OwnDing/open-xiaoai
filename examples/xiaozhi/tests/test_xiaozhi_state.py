import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xiaozhi.xiaozhi import XiaoZhi


class XiaoZhiStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_finish_reference_is_cleared_before_repeated_followups(self):
        native_tts = SimpleNamespace(error=None)

        async def finish():
            return True

        native_tts.finish = finish
        fake = SimpleNamespace(
            native_tts=native_tts,
            _native_finish_task=asyncio.current_task(),
            schedule=Mock(),
            _handle_tts_stop=Mock(),
        )
        finish_task_states = []

        with patch(
            "xiaozhi.xiaozhi.EventManager.on_tts_end",
            side_effect=lambda _: finish_task_states.append(fake._native_finish_task),
        ):
            for index in range(12):
                fake._native_finish_task = asyncio.current_task()
                await XiaoZhi._finish_native_tts(fake, f"session-{index}")

        self.assertEqual(finish_task_states, [None] * 12)
        self.assertIsNone(fake._native_finish_task)
        self.assertEqual(fake.schedule.call_count, 12)


if __name__ == "__main__":
    unittest.main()
