"""Tests for profile/plugins/qq_guard (run: python3 -m unittest test_qq_guard)."""

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.modules.setdefault("httpx", types.SimpleNamespace(Client=lambda **_: None, Timeout=lambda **_: None))

_spec = importlib.util.spec_from_file_location("qq_guard", HERE / "profile" / "plugins" / "qq_guard" / "__init__.py")
qq_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qq_guard)


def event(text="客厅灯开着吗", platform="qqbot", chat_type="dm", media=(), message_type="text"):
    source = types.SimpleNamespace(platform=types.SimpleNamespace(value=platform), chat_type=chat_type,
                                   chat_id="OPENID", user_id="OPENID")
    return types.SimpleNamespace(text=text, source=source, media_urls=list(media), message_id="MSG",
                                 message_type=types.SimpleNamespace(value=message_type))


class Adapter:
    def __init__(self):
        self.sent, self.typing = [], 0

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content, reply_to))
        return types.SimpleNamespace(success=True)

    async def send_typing(self, chat_id, metadata=None):
        self.typing += 1


class Gateway:
    def __init__(self, authorized=True):
        self.authorized, self.adapter = authorized, Adapter()

    def _is_user_authorized(self, source):
        return self.authorized

    def _delivery_adapter_for(self, source):
        return self.adapter


class Provider:
    def __init__(self, reply="客厅灯开着。", error=None):
        self.reply, self.error, self.dialogues = reply, error, []

    def response(self, session_id, dialogue):
        self.dialogues.append(dialogue)
        if self.error:
            raise self.error
        yield from self.reply


def guard(provider, history_dir):
    g = qq_guard.Guard.__new__(qq_guard.Guard)
    g._provider, g._failed_at, g.locks = provider, 0.0, {}
    g.history = qq_guard.History(Path(history_dir) / "history.json")
    return g


class HandlesTest(unittest.TestCase):
    def test_plain_text_dm_on_qq(self):
        self.assertTrue(qq_guard.handles(event()))

    def test_left_to_hermes(self):
        for e in (event(platform="telegram"), event(chat_type="group"), event(text="/new"), event(text="  "),
                  event(media=["/tmp/a.jpg"]), event(message_type="voice")):
            self.assertFalse(qq_guard.handles(e))


class HistoryTest(unittest.TestCase):
    def test_keeps_last_turns_and_resets_when_idle(self):
        with tempfile.TemporaryDirectory() as d:
            h = qq_guard.History(Path(d) / "h.json")
            for i in range(10):
                h.add("c", f"q{i}", f"a{i}", now=1000 + i)
            messages = h.get("c", now=1100)
            self.assertEqual(len(messages), qq_guard.KEEP_MESSAGES)
            self.assertEqual(messages[-1], {"role": "assistant", "content": "a9"})
            self.assertEqual(h.get("c", now=1009 + qq_guard.IDLE_RESET_S + 1), [])
            # Survives a restart.
            self.assertEqual(qq_guard.History(Path(d) / "h.json").get("c", now=1100), messages)

    def test_context_has_the_facts_the_provider_keeps(self):
        content = qq_guard.context_message(datetime(2026, 11, 4, 9, 5))["content"]
        self.assertIn("- Current time: 09:05", content)
        self.assertIn("- Today's date: 2026-11-04 星期三", content)
        self.assertIn("- Device room:", content)


class DispatchTest(unittest.TestCase):
    def run_dispatch(self, g, e, gateway):
        return asyncio.run(g.on_dispatch(event=e, gateway=gateway))

    def test_answers_and_skips_hermes(self):
        with tempfile.TemporaryDirectory() as d:
            provider, gw = Provider(), Gateway()
            g = guard(provider, d)
            result = self.run_dispatch(g, event(), gw)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(gw.adapter.sent, [("OPENID", "客厅灯开着。", "MSG")])
            self.assertEqual(gw.adapter.typing, 1)
            dialogue = provider.dialogues[0]
            self.assertEqual(dialogue[0]["role"], "system")
            self.assertEqual(dialogue[-1], {"role": "user", "content": "客厅灯开着吗"})
            # The next turn carries this one.
            self.run_dispatch(g, event("那书房呢"), gw)
            self.assertEqual([m["content"] for m in provider.dialogues[1][1:]],
                             ["客厅灯开着吗", "客厅灯开着。", "那书房呢"])

    def test_unpaired_user_goes_to_hermes(self):
        with tempfile.TemporaryDirectory() as d:
            provider, gw = Provider(), Gateway(authorized=False)
            self.assertIsNone(self.run_dispatch(guard(provider, d), event(), gw))
            self.assertEqual(provider.dialogues, [])
            self.assertEqual(gw.adapter.sent, [])

    def test_provider_failure_falls_back_to_hermes(self):
        with tempfile.TemporaryDirectory() as d:
            gw = Gateway()
            self.assertIsNone(self.run_dispatch(guard(Provider(error=RuntimeError("down")), d), event(), gw))
            self.assertEqual(gw.adapter.sent, [])

    def test_empty_reply_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            gw = Gateway()
            self.run_dispatch(guard(Provider(reply=""), d), event(), gw)
            self.assertEqual(gw.adapter.sent[0][1], qq_guard.EMPTY_REPLY)


class ProviderLoadTest(unittest.TestCase):
    def test_loads_the_speaker_provider_with_qq_replies(self):
        module = qq_guard.load_provider_module(HERE / "xiaozhi-provider" / "hermes.py",
                                               HERE / "profile" / "mcp" / "home_rules")
        self.assertTrue(hasattr(module, "LLMProvider"))
        self.assertIsNotNone(module.scene_run)
        # The stubs do not leak into the gateway process.
        self.assertNotIn("core.providers.llm.base", sys.modules)
        provider = module.LLMProvider(dict(qq_guard.PROVIDER_CONFIG, api_key="k"))
        self.assertEqual(provider.search_filler, "")
        self.assertIn("发一遍", provider.claim_failed_reply)
        self.assertTrue(provider.tool_guard)


if __name__ == "__main__":
    unittest.main()
