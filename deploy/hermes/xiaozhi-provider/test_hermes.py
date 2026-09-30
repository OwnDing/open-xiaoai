"""Unit tests for the xiaozhi Hermes provider (no server or network needed).

    cd deploy/hermes/xiaozhi-provider && python3 -m unittest test_hermes
"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

# Stub the xiaozhi-server modules the provider imports.
_logger = types.SimpleNamespace(bind=lambda **_: _logger, warning=lambda message: None)
sys.modules.setdefault("httpx", types.SimpleNamespace(Client=lambda **_: None, Timeout=lambda **_: None))
sys.modules.setdefault("config", types.ModuleType("config"))
sys.modules.setdefault("config.logger", types.SimpleNamespace(setup_logging=lambda: _logger))
for name in ("core", "core.providers", "core.providers.llm"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules.setdefault("core.providers.llm.base", types.SimpleNamespace(LLMProviderBase=object))

_spec = importlib.util.spec_from_file_location("hermes_provider", Path(__file__).with_name("hermes.py"))
hermes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hermes)


def user(text):
    return {"role": "user", "content": json.dumps({"content": text, "language": "zh"}, ensure_ascii=False)}


class ProviderTests(unittest.TestCase):
    def run_turn(self, text, *streams):
        """Replays scripted Hermes streams; returns (spoken text, requests sent)."""
        provider = hermes.LLMProvider({"api_key": "x"})
        scripts = list(streams)
        requests = []

        def fake_events(dialogue):
            requests.append(dialogue[-1]["content"])
            yield from scripts.pop(0)

        provider._events = fake_events
        return "".join(provider.response("s", [user(text)])), requests

    def test_plain_answer_is_unchanged(self):
        spoken, requests = self.run_turn(
            "为什么天空是蓝色的", [("text", "因为"), ("text", "阳光被散射。")]
        )
        self.assertEqual(spoken, "因为阳光被散射。")
        self.assertEqual(len(requests), 1)

    def test_search_speaks_our_filler_instead_of_the_models(self):
        spoken, _ = self.run_turn(
            "你搜索一下今天的新闻",
            [("text", "我查一下。"), ("tool", "web_search"), ("tool", "web_search"),
             ("text", "\n\n🙂 今天几条要紧的。")],
        )
        # xiaozhi strips the emoji/whitespace before TTS.
        self.assertEqual(spoken, "我查一下。\n\n🙂 今天几条要紧的。")

    def test_search_without_model_filler_still_announces_it(self):
        spoken, _ = self.run_turn(
            "今天有什么新闻", [("tool", "web_search"), ("text", "今天最热的是星舰。")]
        )
        self.assertEqual(spoken, "我查一下。今天最热的是星舰。")

    def test_filler_only_reply_is_retried(self):
        spoken, requests = self.run_turn(
            "你能搜索新闻吗？",
            [("text", "我查一下。")],
            [("tool", "web_search"), ("text", "今天有三条新闻。")],
        )
        self.assertEqual(spoken, "我查一下。今天有三条新闻。")
        self.assertEqual(len(requests), 2)
        self.assertIn(hermes.FILLER_RETRY_NOTE, requests[1])

    def test_filler_only_twice_gives_an_honest_reply(self):
        spoken, _ = self.run_turn("你能搜索新闻吗？", [("text", "我查一下。")], [("text", "稍等。")])
        self.assertEqual(spoken, "这次没查到，你再问我一次吧。")

    def test_fake_search_filler_is_dropped(self):
        spoken, requests = self.run_turn(
            "临海有什么好吃的",
            [("text", "我查一下。"), ("text", "  🙂 临海最出名的是"), ("text", "蛋清羊尾。")],
        )
        self.assertEqual(spoken, "🙂 临海最出名的是蛋清羊尾。")
        self.assertEqual(len(requests), 1)

    def test_chained_fillers_are_all_dropped_before_a_search(self):
        spoken, _ = self.run_turn(
            "查下天气",
            [("text", "稍等，"), ("text", "我查一下。"), ("tool", "web_search"), ("text", "晴天。")],
        )
        self.assertEqual(spoken, "我查一下。晴天。")

    def test_advice_starting_with_cha_yi_xia_is_kept(self):
        spoken, _ = self.run_turn("我有点发烧", [("text", "查一下体温吧，"), ("text", "先别慌。")])
        self.assertEqual(spoken, "查一下体温吧，先别慌。")

    def test_answer_starting_with_wo_is_not_held(self):
        spoken, _ = self.run_turn("小七", [("text", "我在呢，"), ("text", "有事说吧。")])
        self.assertEqual(spoken, "我在呢，有事说吧。")

    def test_filler_before_home_assistant_tool_is_silent(self):
        spoken, _ = self.run_turn(
            "现在有几盏灯开着？",
            [("text", "我查一下。"), ("tool", "ha_get_state"), ("text", "三盏灯亮着。")],
        )
        self.assertEqual(spoken, "三盏灯亮着。")

    def test_device_command_without_tool_is_retried(self):
        spoken, requests = self.run_turn(
            "关闭次卧灯，打开书房灯",
            [("text", "好了，都弄好了。")],
            [("tool", "ha_call_service"), ("text", "好了，次卧灯关了。")],
        )
        self.assertEqual(spoken, "好了，次卧灯关了。")
        self.assertIn(hermes.RETRY_NOTE, requests[1])

    def test_questions_about_devices_are_not_commands(self):
        for text in ("我睡觉的时候，空调应该开多少度？", "客厅灯开着吗？", "我要关门了"):
            self.assertFalse(hermes.is_control_request(text), text)
        for text in ("关闭书房灯", "能把客厅灯关了吗？", "把空调调到26度", "开灯"):
            self.assertTrue(hermes.is_control_request(text), text)


if __name__ == "__main__":
    unittest.main()
