import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import xiaozhi.event as event_module
from xiaozhi.event import DEFAULT_EXIT_WORDS, Step, match_exit_intent, match_exit_words
from xiaozhi.services.audio.kws import _KWS
from xiaozhi.services.protocols.typing import DeviceState

KEYWORDS = ["天猫精灵", "小度小度", "豆包豆包", "你好小七", "你好小爱", "hi siri", "hey siri"]


def matches(text):
    return match_exit_words(text, DEFAULT_EXIT_WORDS, KEYWORDS)


def intent(text, keywords=("你好小七",)):
    return match_exit_intent(text, DEFAULT_EXIT_WORDS, keywords)[0]


class MatchExitWordsTests(unittest.TestCase):
    def test_a_goodbye_on_its_own_ends_the_conversation(self):
        for text in ["拜拜", "拜拜。", "再见！", "拜拜拜拜", "退下吧", "没事了", "不用了，谢谢",
                     "好的，谢谢，再见", "嗯，拜拜啦", "Bye bye.", "OK, goodbye", "退出"]:
            with self.subTest(text=text):
                self.assertIsNotNone(matches(text))

    def test_the_wake_word_may_come_along_even_misheard(self):
        # Follow-up window: the wake word reaches the recognizer. After a
        # barge-in the end of "七" can be in front.
        for text in ["你好小七，拜拜", "你好小七再见", "小七拜拜", "你好小琪拜拜", "你好小拜拜",
                     "亲拜拜", "七，再见", "你好小七，好的，拜拜"]:
            with self.subTest(text=text):
                self.assertIsNotNone(matches(text))

    def test_goodbye_as_the_recognizer_spells_it(self):
        # All heard live (2026-10-09..11).
        for text in ["拜 by", "拜e by", "拜e bye", "拜 bye", "拜 by拜 by", "Goode bye", "Bye bye",
                     "不用啊, goodbye", "没事，小七拜拜"]:
            with self.subTest(text=text):
                self.assertIsNotNone(matches(text))
        for text in ["baby", "nearby", "参拜", "没事", "不用"]:
            with self.subTest(text=text):
                self.assertIsNone(matches(text))

    def test_a_request_or_question_is_not_an_exit(self):
        for text in ["关灯，拜拜", "用英语怎么说再见", "再见用英语怎么说", "跟奶奶说拜拜", "晚安",
                     "我要出门了拜拜", "明天天气怎么样", "你好小七", "谢谢", "好的", "", "。",
                     "不用了，帮我把灯关掉"]:
            with self.subTest(text=text):
                self.assertIsNone(matches(text))

    def test_a_goodbye_opening_the_utterance_ends_it_at_once(self):
        # The rest was said to someone else in the room, or the TV.
        for text in ["拜拜，15加12已经27天没换水了", "拜拜，可有虫子我怕呀拜拜",
                     "小气拜拜，万事啊，你买粉给我们都", "你好小七，再见，我去做饭了", "拜拜"]:
            with self.subTest(text=text):
                self.assertEqual(intent(text), "now")

    def test_more_than_a_goodbye_is_answered_first(self):
        # A goodbye at the end, after a wake word misheard beyond repair, or
        # another exit word opening a request.
        for text in ["关灯，拜拜", "你好傻次，拜拜", "再师拜拜", "没什小心拜拜", "唔一下先拜拜",
                     "不用了，帮我把灯关掉", "不用了，我要拆快递的", "帮我查下明天天气，谢谢，拜拜"]:
            with self.subTest(text=text):
                self.assertEqual(intent(text), "after_answer")

    def test_a_goodbye_inside_a_sentence_is_not_an_exit(self):
        for text in ["用英语怎么说再见", "再见用英语怎么说", "再见面的时候怎么说", "明天天气怎么样",
                     "待会去吃鸡了，还没回来，拜拜，等他吃饭，我点外卖", "这个可以的，你好，小七",
                     "我在看电视呢，拜拜就是再见的意思吗", "晚安", "你好小七", "", "。"]:
            with self.subTest(text=text):
                self.assertIsNone(intent(text))

    def test_a_latin_wake_word_allows_no_misheard_prefix(self):
        self.assertIsNone(intent("用英语怎么说再见", KEYWORDS + ["hello there friend"]))
        self.assertEqual(intent("再师拜拜", ["hey siri"]), None)

    def test_words_come_from_the_config(self):
        self.assertIsNone(match_exit_words("拜拜", []))
        self.assertEqual(match_exit_words("先这样吧", ["先这样"]), "先这样")
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"exit_words": ["回见"]}):
            self.assertEqual(event_module.exit_word("回见"), "回见")
            self.assertIsNone(event_module.exit_word("拜拜"))
            self.assertEqual(event_module.exit_intent("关灯，回见"), ("after_answer", "回见"))


class ExitWordsSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = getattr(event_module, "__EventManager")()
        self.manager.current_step = Step.on_silence
        with patch("xiaozhi.services.audio.kws.set_kws"):
            self.kws = _KWS()
        self.vad = SimpleNamespace(resume=Mock(), pause=Mock())
        self.calls = []
        loop = asyncio.get_running_loop()

        async def send_abort(reason):
            self.calls.append("server_abort")

        self.xiaozhi = SimpleNamespace(
            loop=loop, device_state=DeviceState.IDLE,
            abort_tts_output=AsyncMock(),
            protocol=SimpleNamespace(send_abort_speaking=AsyncMock(side_effect=send_abort)),
            set_device_state=lambda state: setattr(self.xiaozhi, "device_state", state),
        )
        self.speaker = object()
        self.health = Mock()
        self.ended = asyncio.Event()

        async def goodbye(speaker):
            self.calls.append("goodbye" if self.kws.paused else "goodbye while listening")

        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in {"get_env": "1", "get_xiaozhi": self.xiaozhi,
                            "get_vad": self.vad, "get_kws": self.kws,
                            "get_audio_codec": object(), "get_speaker": self.speaker}.items():
            stack.enter_context(patch(f"xiaozhi.event.{name}", return_value=value))
        stack.enter_context(patch("xiaozhi.event.HEALTH", self.health))
        stack.enter_context(patch.dict(event_module.APP_CONFIG["wakeup"],
                                       {"after_wakeup": goodbye, "exit_guard_ms": 0}))
        self.health.emit.side_effect = lambda name, **_: name == "session_exit_end" and self.ended.set()

    async def test_says_goodbye_at_once_and_stops_listening(self):
        waiting = asyncio.create_task(self.manager.wait_next_step(self.manager.session_id, timeout=5))
        await asyncio.sleep(0)
        self.manager.on_exit_words("拜拜")
        self.assertEqual(await waiting, ("interrupted", None))
        await asyncio.wait_for(self.ended.wait(), 1)
        self.assertEqual(self.calls, ["server_abort", "goodbye"])
        self.vad.resume.assert_not_called()
        self.assertEqual(self.manager.current_step, Step.idle)
        self.assertFalse(self.kws.paused)
        self.health.emit.assert_any_call("session_exit_start", session_id=self.manager.session_id,
                                         reason="exit_words")
        # The answer the server still sends does not reopen the conversation.
        with patch.object(self.manager, "start_session") as start:
            self.manager.on_tts_end("reply-to-bye")
            start.assert_not_called()

    async def test_exits_even_when_the_server_has_closed_the_connection(self):
        self.xiaozhi.protocol.send_abort_speaking.side_effect = ConnectionError("closed")
        self.manager.on_exit_words("退出")
        await asyncio.wait_for(self.ended.wait(), 1)
        self.assertEqual(self.calls, ["goodbye"])
        self.assertEqual(self.manager.current_step, Step.idle)

    async def test_ends_after_the_answer_without_a_second_goodbye(self):
        self.manager.on_stt(exit_after_answer=True)
        self.manager.current_step = Step.on_tts_start
        self.manager.on_tts_end("reply")
        await asyncio.wait_for(self.ended.wait(), 1)
        self.assertEqual(self.calls, [])
        self.vad.resume.assert_not_called()
        self.assertEqual(self.manager.current_step, Step.idle)
        self.assertFalse(self.kws.paused)
        self.assertFalse(self.manager.exit_after_answer)
        self.health.emit.assert_any_call("session_exit_start", session_id=self.manager.session_id,
                                         reason="exit_after_answer")

    async def test_a_new_wake_forgets_the_pending_exit(self):
        self.manager.on_stt(exit_after_answer=True)
        with patch.dict(event_module.APP_CONFIG["wakeup"], {"timeout": 5}):
            self.manager.on_wakeup()
            for _ in range(20):
                if self.vad.resume.called:
                    break
                await asyncio.sleep(0.01)
        self.vad.resume.assert_called_with("speech")
        self.assertFalse(self.manager.exit_after_answer)
        self.assertNotEqual(self.manager.current_step, Step.idle)

    async def test_ignored_outside_a_conversation(self):
        self.manager.current_step = Step.idle
        with patch.object(self.manager, "start_session") as start:
            self.manager.on_exit_words("拜拜")
            start.assert_not_called()


class ExitWordsSttTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_answer_to_an_exit_word_is_not_played(self):
        from xiaozhi.xiaozhi import XiaoZhi

        xiaozhi = XiaoZhi.__new__(XiaoZhi)
        xiaozhi._tts_gate = False
        xiaozhi.tts_output_mode = "native_xiaomi"
        xiaozhi.native_tts = SimpleNamespace(start=AsyncMock(), add_text=AsyncMock())
        xiaozhi.config = SimpleNamespace(update_config_file=Mock())
        xiaozhi.schedule = Mock()
        with (
            patch.dict(event_module.APP_CONFIG["wakeup"], {"keywords": KEYWORDS}),
            patch("xiaozhi.xiaozhi.EventManager") as events,
        ):
            xiaozhi._handle_stt_message({"text": "你好小七拜拜"})
            events.on_exit_words.assert_called_once_with("你好小七拜拜")
            events.on_stt.assert_not_called()
            await xiaozhi._handle_tts_message({"state": "start"})
            await xiaozhi._handle_tts_message({"state": "sentence_start", "text": "再见啦"})
            await xiaozhi._handle_tts_message({"state": "stop"})
            xiaozhi.native_tts.start.assert_not_awaited()
            xiaozhi.native_tts.add_text.assert_not_awaited()
            events.on_tts_end.assert_not_called()

            xiaozhi._handle_stt_message({"text": "明天天气怎么样"})
            events.on_stt.assert_called_once_with(exit_after_answer=False)
            await xiaozhi._handle_tts_message({"state": "start", "session_id": "s"})
        xiaozhi.native_tts.start.assert_awaited_once()

    async def test_a_request_with_a_goodbye_is_answered(self):
        from xiaozhi.xiaozhi import XiaoZhi

        xiaozhi = XiaoZhi.__new__(XiaoZhi)
        xiaozhi._tts_gate = True
        xiaozhi.schedule = Mock()
        with (
            patch.dict(event_module.APP_CONFIG["wakeup"], {"keywords": ["你好小七"]}),
            patch("xiaozhi.xiaozhi.EventManager") as events,
        ):
            xiaozhi._handle_stt_message({"text": "关灯，拜拜"})
        events.on_exit_words.assert_not_called()
        events.on_stt.assert_called_once_with(exit_after_answer=True)
        self.assertFalse(xiaozhi._tts_gate)


if __name__ == "__main__":
    unittest.main()
