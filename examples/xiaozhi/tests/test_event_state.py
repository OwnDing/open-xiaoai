import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import xiaozhi.event as event_module
from xiaozhi.event import Step


def make_event_manager():
    return getattr(event_module, "__EventManager")()


class EventStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_step_from_another_thread_resolves_on_owner_loop(self):
        manager = make_event_manager()

        with patch("xiaozhi.event.get_env", return_value="1"):
            waiter = asyncio.create_task(
                manager.wait_next_step(manager.session_id, timeout=1)
            )
            await asyncio.sleep(0)

            thread = threading.Thread(
                target=manager.update_step,
                args=(Step.on_speech, b"speech"),
            )
            thread.start()
            thread.join()

            self.assertEqual(
                await waiter,
                (Step.on_speech, b"speech"),
            )

    async def test_timeout_cleans_pending_waiter(self):
        manager = make_event_manager()

        result = await manager.wait_next_step(manager.session_id, timeout=0.01)

        self.assertEqual(result, ("timeout", None))
        self.assertIsNone(manager.next_step_future)
        self.assertIsNone(manager.next_step_loop)

    async def test_new_session_interrupts_previous_waiter(self):
        manager = make_event_manager()
        waiter = asyncio.create_task(
            manager.wait_next_step(manager.session_id, timeout=1)
        )
        await asyncio.sleep(0)

        manager._set_step(Step.on_wakeup, new_session=True)

        self.assertEqual(await waiter, ("interrupted", None))

    async def test_stale_session_cannot_replace_current_waiter(self):
        manager = make_event_manager()
        manager._set_step(Step.on_wakeup, new_session=True)
        current_waiter = asyncio.create_task(
            manager.wait_next_step(manager.session_id, timeout=1)
        )
        await asyncio.sleep(0)

        stale_result = await manager.wait_next_step(manager.session_id - 1)
        manager.update_step(Step.on_speech, b"speech")

        self.assertEqual(stale_result, ("interrupted", None))
        self.assertEqual(await current_waiter, (Step.on_speech, b"speech"))

    async def test_session_runs_on_xiaozhi_loop(self):
        manager = make_event_manager()
        running_loop = asyncio.get_running_loop()
        called = asyncio.Event()
        observed_loop = None

        async def fake_start_session(session_id, trigger_step):
            nonlocal observed_loop
            observed_loop = asyncio.get_running_loop()
            called.set()

        manager._EventManager__start_session = fake_start_session
        with patch(
            "xiaozhi.event.get_xiaozhi",
            return_value=SimpleNamespace(loop=running_loop),
        ):
            manager.start_session(1, Step.on_wakeup)
            await asyncio.wait_for(called.wait(), timeout=1)

        self.assertIs(observed_loop, running_loop)

    async def test_tts_end_rearms_a_complete_listening_cycle(self):
        manager = make_event_manager()
        running_loop = asyncio.get_running_loop()
        completed = asyncio.Event()

        class FakeInputStream:
            def __init__(self):
                self.start_count = 0

            def start_stream(self):
                self.start_count += 1

        class FakeProtocol:
            def __init__(self):
                self.calls = []

            async def send_abort_speaking(self, reason):
                self.calls.append("abort")

            async def send_start_listening(self, mode):
                self.calls.append("start")

            async def send_stop_listening(self):
                self.calls.append("stop")
                completed.set()

        class FakeXiaoZhi:
            def __init__(self):
                self.loop = running_loop
                self.protocol = FakeProtocol()
                self.states = []
                self.abort_count = 0

            def set_device_state(self, state):
                self.states.append(state)

            async def abort_tts_output(self):
                self.abort_count += 1

        class FakeVAD:
            def __init__(self):
                self.targets = []

            def resume(self, target):
                self.targets.append(target)
                if self.targets == ["speech"]:
                    running_loop.call_soon(manager.on_speech, b"speech")
                elif self.targets == ["speech", "silence"]:
                    running_loop.call_soon(manager.on_silence)

        xiaozhi = FakeXiaoZhi()
        vad = FakeVAD()
        codec = SimpleNamespace(input_stream=FakeInputStream())
        manager.current_step = Step.on_tts_start

        with (
            patch("xiaozhi.event.get_env", return_value="1"),
            patch("xiaozhi.event.get_xiaozhi", return_value=xiaozhi),
            patch("xiaozhi.event.get_vad", return_value=vad),
            patch("xiaozhi.event.get_audio_codec", return_value=codec),
            patch("xiaozhi.event.get_speaker", return_value=object()),
            patch("xiaozhi.event.set_speech_frames") as set_speech_frames,
        ):
            manager.on_tts_end("session-1")
            await asyncio.wait_for(completed.wait(), timeout=1)

        self.assertEqual(xiaozhi.abort_count, 0)
        # Listens right after the short echo guard; no silence wait first.
        self.assertEqual(vad.targets, ["speech", "silence"])
        self.assertEqual(xiaozhi.protocol.calls, ["abort", "start", "stop"])
        self.assertEqual(codec.input_stream.start_count, 1)
        set_speech_frames.assert_called_once_with(b"speech")


    async def run_turn_without_reply(self, stt_arrives):
        """One listening turn; the server either recognizes speech or stays silent."""
        manager = make_event_manager()
        running_loop = asyncio.get_running_loop()
        relisten = asyncio.Event()
        stopped = asyncio.Event()
        prompts = []
        manager.current_step = Step.on_tts_start

        class FakeProtocol:
            async def send_abort_speaking(self, reason):
                pass

            async def send_start_listening(self, mode):
                pass

            async def send_stop_listening(self):
                stopped.set()
                if stt_arrives:
                    running_loop.call_later(0.01, manager.on_stt)

        class FakeVAD:
            def __init__(self):
                self.targets = []

            def resume(self, target):
                self.targets.append(target)
                if len(self.targets) == 3:
                    relisten.set()  # second turn started listening again
                elif target == "speech":
                    running_loop.call_soon(manager.on_speech, b"speech")
                else:
                    running_loop.call_soon(manager.on_silence)

        class FakeSpeaker:
            async def play(self, text=None, **kwargs):
                prompts.append(text)

        xiaozhi = SimpleNamespace(
            loop=running_loop,
            protocol=FakeProtocol(),
            set_device_state=lambda state: None,
            abort_tts_output=lambda: asyncio.sleep(0),
        )
        vad = FakeVAD()
        codec = SimpleNamespace(input_stream=SimpleNamespace(start_stream=lambda: None))
        settings = {"no_reply_timeout": 0.05, "tts_end_guard_ms": 0}
        with (
            patch.dict(event_module.APP_CONFIG["vad"], settings),
            patch("xiaozhi.event.get_env", return_value="1"),
            patch("xiaozhi.event.get_xiaozhi", return_value=xiaozhi),
            patch("xiaozhi.event.get_vad", return_value=vad),
            patch("xiaozhi.event.get_audio_codec", return_value=codec),
            patch("xiaozhi.event.get_speaker", return_value=FakeSpeaker()),
            patch("xiaozhi.event.set_speech_frames"),
        ):
            manager.on_tts_end("session-1")
            await asyncio.wait_for(stopped.wait(), timeout=1)
            try:
                await asyncio.wait_for(relisten.wait(), timeout=0.3)
            except asyncio.TimeoutError:
                pass
        return prompts, vad.targets

    async def test_unrecognized_speech_prompts_and_listens_again(self):
        prompts, targets = await self.run_turn_without_reply(stt_arrives=False)

        self.assertEqual(prompts, ["我没听清，再说一遍？"])
        self.assertEqual(targets, ["speech", "silence", "speech"])

    async def test_recognized_speech_does_not_prompt(self):
        prompts, targets = await self.run_turn_without_reply(stt_arrives=True)

        self.assertEqual(prompts, [])
        self.assertEqual(targets, ["speech", "silence"])


if __name__ == "__main__":
    unittest.main()
