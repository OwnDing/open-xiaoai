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
_logger = types.SimpleNamespace(bind=lambda **_: _logger, warning=lambda message: None, info=lambda message: None)
sys.modules.setdefault("httpx", types.SimpleNamespace(Client=lambda **_: None, Timeout=lambda **_: None))
sys.modules.setdefault("config", types.ModuleType("config"))
sys.modules.setdefault("config.logger", types.SimpleNamespace(setup_logging=lambda: _logger))
for name in ("core", "core.providers", "core.providers.llm"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules.setdefault("core.providers.llm.base", types.SimpleNamespace(LLMProviderBase=object))

# scene_run.py and ha.py are mounted next to hermes.py in the server; here they
# come straight from home_rules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "mcp" / "home_rules"))
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

    def test_zai_filler_without_search_is_dropped(self):
        spoken, _ = self.run_turn(
            "今天宁波的天气怎么样？",
            [("text", "我再查一下。"), ("text", "抱歉，今天宁波中雨转小雨。")],
        )
        self.assertEqual(spoken, "抱歉，今天宁波中雨转小雨。")

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

    def test_state_question_answered_from_memory_is_retried(self):
        spoken, requests = self.run_turn(
            "现在有几盏灯开着？",
            [("text", "按我这边记录，客厅灯和餐厅灯是开着的。")],
            [("tool", "ha_list_entities"), ("text", "现在开着三盏灯。")],
        )
        self.assertEqual(spoken, "现在开着三盏灯。")
        self.assertIn(hermes.STATE_RETRY_NOTE, requests[1])

    def test_state_question_needs_a_home_assistant_tool(self):
        # A web search or memory lookup does not count as checking the device.
        spoken, requests = self.run_turn(
            "书房灯是不是开着",
            [("tool", "memory"), ("text", "开着呢。")],
            [("tool", "ha_get_state"), ("text", "书房灯关着。")],
        )
        self.assertEqual(spoken, "书房灯关着。")
        self.assertEqual(len(requests), 2)

    def test_english_narration_before_a_tool_is_dropped(self):
        spoken, _ = self.run_turn(
            "现在有几盏灯开着？",
            [("text", "I'll check the current "), ("text", "state of all the lights. "),
             ("tool", "ha_list_entities"), ("text", "现在开着四盏灯。")],
        )
        self.assertEqual(spoken, "现在开着四盏灯。")

    def test_english_lead_in_without_tool_is_dropped(self):
        spoken, _ = self.run_turn(
            "为什么猫喜欢纸箱", [("text", "Let me think. "), ("text", "猫喜欢纸箱是因为安全感。")]
        )
        self.assertEqual(spoken, "猫喜欢纸箱是因为安全感。")

    def test_english_lead_in_streamed_letter_by_letter_is_dropped(self):
        # The first chunk can be a lone "I", too short to look like English.
        spoken, _ = self.run_turn(
            "取消刚才关书房灯的定时任务",
            [("text", "I"), ("text", "'ll look up your scheduled tasks first."),
             ("tool", "cronjob_manage"), ("text", "好了，那个定时任务取消了。")],
        )
        self.assertEqual(spoken, "好了，那个定时任务取消了。")
        spoken, _ = self.run_turn(
            "现在有哪些定时任务",
            [("text", "I"), ("text", "'ll check."), ("text", "现在没有定时任务。")],
        )
        self.assertEqual(spoken, "现在没有定时任务。")

    def test_answer_starting_with_a_single_latin_letter_is_kept(self):
        spoken, _ = self.run_turn("今天股市怎么样", [("text", "A"), ("text", "股今天小幅上涨。")])
        self.assertEqual(spoken, "A股今天小幅上涨。")

    def test_mixed_chinese_with_english_names_is_kept(self):
        spoken, _ = self.run_turn(
            "今天科技新闻", [("tool", "web_search"), ("text", "OpenAI 发了新模型，"), ("text", "估值很高。")]
        )
        self.assertEqual(spoken, "我查一下。OpenAI 发了新模型，估值很高。")

    def test_answer_starting_with_english_name_is_kept(self):
        spoken, _ = self.run_turn(
            "我的手表有货吗", [("text", "Apple Watch "), ("text", "S11 这款最近常缺货。")]
        )
        self.assertEqual(spoken, "Apple Watch S11 这款最近常缺货。")

    XIAOZHI_PROMPT = (
        "You are a playful assistant.\n<identity>\n你是小七\n</identity>\n"
        "<tool_and_knowledge>\nAbout weather: The context already provides the local 7-day "
        "forecast — answer directly without a tool call.\n</tool_and_knowledge>\n"
        "<context>\n[Important: real time]\n- Current time: 23:31\n"
        "- Today's date: 2026-09-30 (星期三)\n- Today's lunar date: 八月二十\n"
        "- Device location: 浙江省宁波市\n- Local upcoming weather: 未找到城市\n\n</context>\n"
    )

    def test_xiaozhi_system_prompt_is_slimmed_to_real_time_facts(self):
        slim = hermes.slim_system_prompt(self.XIAOZHI_PROMPT)
        self.assertIn("- Current time: 23:31", slim)
        self.assertIn("- Device location: 浙江省宁波市", slim)
        self.assertIn("- Today's lunar date: 八月二十", slim)
        self.assertNotIn("weather", slim.lower())
        self.assertNotIn("tool", slim)
        self.assertIsNone(hermes.slim_system_prompt("你是家庭语音助手小七。"))

    def test_device_room_and_reply_style_survive_slimming(self):
        prompt = self.XIAOZHI_PROMPT.replace(
            "\n</context>",
            "- Device room: 书房（用户正在这个房间里对这台设备说话）\n"
            "- Reply style: 用完整的一句话回答。\n</context>",
        )
        slim = hermes.slim_system_prompt(prompt)
        self.assertIn("- Device room: 书房（用户正在这个房间里对这台设备说话）", slim)
        self.assertIn("- Reply style: 用完整的一句话回答。", slim)
        self.assertNotIn("Device room", hermes.slim_system_prompt(self.XIAOZHI_PROMPT))

    def test_hermes_receives_the_slim_system_prompt(self):
        provider = hermes.LLMProvider({"api_key": "x"})
        sent = []

        def fake_events(dialogue):
            sent.append(dialogue)
            yield ("text", "好的。")

        provider._events = fake_events
        dialogue = [{"role": "system", "content": self.XIAOZHI_PROMPT}, user("你好")]
        "".join(provider.response("s", dialogue))
        system = [m for m in sent[0] if m["role"] == "system"]
        self.assertEqual(len(system), 1)
        self.assertNotIn("7-day forecast", system[0]["content"])
        self.assertEqual(dialogue[0]["content"], self.XIAOZHI_PROMPT)  # caller's copy untouched

    def test_state_questions_and_preferences(self):
        for text in ("现在有几盏灯开着？", "书房灯是不是开着", "卧室现在温度多少",
                     "阳台漏水了吗"):
            self.assertTrue(hermes.is_state_question(text), text)
        for text in ("我睡觉的时候，空调应该开多少度？", "我一般睡觉开几度空调",
                     "关闭书房灯", "为什么天空是蓝色的"):
            self.assertFalse(hermes.is_state_question(text), text)

    def test_appliance_questions_and_commands(self):
        for text in ("冰箱冷藏室多少度", "洗衣机洗完了吗", "干衣机还要多久",
                     "净水机滤芯还剩多少"):
            self.assertTrue(hermes.is_state_question(text), text)
        for text in ("明天宁波温度多少度", "空调开几度睡觉舒服", "冷冻的饺子怎么煮"):
            self.assertFalse(hermes.is_state_question(text), text)
        for text in ("冰箱冷藏调到4度", "打开冰箱速冻", "洗衣机关机"):
            self.assertTrue(hermes.is_control_request(text), text)

    def test_history_questions(self):
        for text in ("今天鱼缸灯亮了多久", "一天那个鱼缸灯开了多久啊？", "客厅灯几点开的",
                     "鱼缸插座是不是三点关的", "鱼缸灯是不是三点关掉的", "客厅灯是八点二十分开的吗",
                     "空调昨天开了几次", "书房灯是谁关的", "电视今天看了多长时间", "鱼缸灯开着多久了",
                     "洗衣机洗了多久", "客厅灯什么时候打开的", "空调昨天用了多少电"):
            self.assertTrue(hermes.is_history_question(text), text)
        # No device, advice, what is left, the future, the present state, or a command.
        for text in ("去美国纽约要多久", "开车去纽约要多久", "开车到灯塔要多久", "空调开多久合适",
                     "洗衣机还要多久", "干衣机还要多久", "鱼缸灯几点关", "客厅灯开着吗",
                     "灯是开的还是关的", "书房灯是不是关的", "把灯和开关分开的", "鱼缸灯一天开多久比较好",
                     "鱼缸灯开了多久了，关掉吧", "现在几点了"):
            self.assertFalse(hermes.is_history_question(text), text)

    def test_history_follow_up_names_the_device_in_the_previous_question(self):
        reply = {"role": "assistant", "content": "鱼缸插座只有开关状态，查不了。"}
        for before, text, expected in (
            ("一天那个鱼缸灯开了多久啊？", "我问你今天开了多久？", True),
            ("鱼缸灯现在开着吗", "几点开的，几点钟关的。", True),
            ("宁波到上海多远", "开车要多久", False),
            ("鱼缸灯开着吗", "那去纽约要多久", False),
        ):
            dialogue = [user(before), reply, user(text)]
            self.assertEqual(hermes.is_history_follow_up(dialogue, text), expected, text)
        self.assertFalse(hermes.is_history_follow_up([user("我问你今天开了多久？")], "我问你今天开了多久？"))
        # Already answered with figures: repeating them needs no second lookup.
        for answered in ("今天开了两小时二十八分，早上八点三十三开到十一点。", "开了3次。", "亮了一个半小时。"):
            dialogue = [user("一天那个鱼缸灯开了多久啊？"), {"role": "assistant", "content": answered},
                        user("我问你今天开了多久？")]
            self.assertFalse(hermes.is_history_follow_up(dialogue, "我问你今天开了多久？"), answered)

    def test_history_question_answered_without_history_is_retried(self):
        spoken, requests = self.run_turn(
            "今天鱼缸灯亮了多久",
            [("tool", "ha_get_state"), ("text", "鱼缸插座只有开关状态，查不了开了多久。")],
            [("tool", "mcp__home_history__device_history"), ("text", "今天亮了两小时二十八分。")],
        )
        self.assertEqual(spoken, "今天亮了两小时二十八分。")
        self.assertIn(hermes.HISTORY_RETRY_NOTE, requests[1])

    def test_history_question_with_the_history_tool_is_not_retried(self):
        spoken, requests = self.run_turn(
            "鱼缸插座是不是三点关掉的",
            [("tool", "mcp__home_history__device_history"), ("text", "不是，是十一点关的。")],
        )
        self.assertEqual((spoken, len(requests)), ("不是，是十一点关的。", 1))

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

    def test_commands_for_later_are_scheduled(self):
        for text in ("好的，那你帮我两个小时以后关掉那个鱼缸插座的灯", "半小时后关闭客厅灯",
                     "一个半小时后关空调", "10分钟后打开风扇", "你三点钟的时候关掉它可以吗？把鱼缸插座关了",
                     "晚上9点半关闭书房灯", "15:30把空调关掉", "待会儿把客厅灯关了", "定时关闭电视"):
            self.assertTrue(hermes.is_scheduled_control(text), text)
        for text in ("关闭书房灯", "把空调调到26度", "客厅灯几点开的", "鱼缸插座是不是三点关的",
                     "两个小时后提醒我喝水"):
            self.assertFalse(hermes.is_scheduled_control(text), text)

    def test_scheduled_command_without_tool_asks_for_a_cron_job(self):
        spoken, requests = self.run_turn(
            "两个小时以后关掉鱼缸插座",
            [("text", "好，两小时后帮你关掉。")],
            [("tool", "cronjob_manage"), ("text", "好，下午三点零六分关鱼缸插座。")],
        )
        self.assertEqual(spoken, "好，下午三点零六分关鱼缸插座。")
        self.assertIn(hermes.SCHEDULE_RETRY_NOTE, requests[1])
        self.assertNotIn(hermes.RETRY_NOTE, requests[1])

    def test_scheduled_command_with_a_cron_job_is_not_retried(self):
        spoken, requests = self.run_turn(
            "半小时后关闭客厅灯",
            [("tool", "cronjob_manage"), ("text", "好，九点十分关客厅灯。")],
        )
        self.assertEqual(spoken, "好，九点十分关客厅灯。")
        self.assertEqual(len(requests), 1)

    def test_asking_back_about_an_unclear_command_is_kept(self):
        spoken, requests = self.run_turn(
            "鱼缸灯关了吧",
            [("text", "是现在就关鱼缸灯，还是等十一点再关？")],
        )
        self.assertEqual((spoken, len(requests)), ("是现在就关鱼缸灯，还是等十一点再关？", 1))

    def test_a_question_that_claims_success_is_still_retried(self):
        for claim in ("好了，鱼缸灯关了，还要别的吗？", "鱼缸灯已经关掉了，要不要把十一点那个也取消？"):
            spoken, requests = self.run_turn(
                "把鱼缸灯关了",
                [("text", claim)],
                [("tool", "ha_call_service"), ("text", "好了，鱼缸灯关了。")],
            )
            self.assertEqual(spoken, "好了，鱼缸灯关了。", claim)
            self.assertIn(hermes.RETRY_NOTE, requests[1])

    def test_teaching_scenes_and_linkages_is_not_forced_into_a_tool(self):
        for text in ("以后我说我回来了，就打开客厅灯和空调", "当洗衣机洗完的时候提醒我", "主卧开关一双击就关掉全屋的灯",
                     "阳台漏水了马上告诉我，如果是半夜也要说", "把我回来了这个场景删掉", "每天晚上十一点关掉书房灯",
                     "有哪些联动"):
            self.assertTrue(hermes.is_rule_request(text), text)
        for text in ("打开客厅灯", "两个小时后关掉鱼缸插座", "书房灯是不是开着", "我回来了",
                     "告诉我书房灯开着没"):
            self.assertFalse(hermes.is_rule_request(text), text)

    def test_rule_read_back_without_tool_is_spoken_once(self):
        spoken, requests = self.run_turn(
            "以后我说我回来了，就打开客厅灯",
            [("text", "以后你说“我回来了”，我就打开客厅灯，要我保存吗？")],
        )
        self.assertEqual(spoken, "以后你说“我回来了”，我就打开客厅灯，要我保存吗？")
        self.assertEqual(len(requests), 1)

    def run_dialogue(self, dialogue, *streams):
        provider = hermes.LLMProvider({"api_key": "x"})
        scripts, requests = list(streams), []

        def fake_events(sent):
            requests.append(sent[-1]["content"])
            yield from scripts.pop(0)

        provider._events = fake_events
        return "".join(provider.response("s", dialogue)), requests

    ASKED = {"role": "assistant", "content": "以后阳台一漏水，我就马上在音箱上告诉你，半夜也会说。要我保存吗？"}

    def test_agreeing_to_save_must_reach_the_rule_tool(self):
        spoken, requests = self.run_dialogue(
            [user("以后阳台漏水了马上告诉我"), self.ASKED, user("好")],
            [("text", "好了，阳台一漏水我就马上告诉你。")],
            [("tool", "mcp__home_rules__home_rule_save"), ("text", "保存好了。")],
        )
        self.assertEqual(spoken, "保存好了。")
        self.assertIn(hermes.SAVE_RETRY_NOTE, requests[1])

    def test_saving_on_the_first_try_is_not_retried(self):
        spoken, requests = self.run_dialogue(
            [user("以后阳台漏水了马上告诉我"), self.ASKED, user("可以。")],
            [("tool", "mcp__home_rules__home_rule_save"), ("text", "保存好了。")],
        )
        self.assertEqual((spoken, len(requests)), ("保存好了。", 1))

    SCHEDULED = [user("记得今天11点钟关闭鱼缸灯"), {"role": "assistant", "content": "好，今天上午十一点整关鱼缸插座，关好我会说一声。"}]

    def test_vague_words_right_after_a_schedule_only_ask(self):
        for overheard in ("会关，现在会关。", "关了吧", "开着吧"):
            spoken, requests = self.run_dialogue(
                self.SCHEDULED + [user(overheard)],
                [("text", "是现在就关鱼缸灯，还是等十一点？")],
            )
            self.assertEqual(spoken, "是现在就关鱼缸灯，还是等十一点？", overheard)
            self.assertIn(hermes.UNCLEAR_NOTE, requests[0], overheard)

    def test_clear_words_after_a_schedule_are_normal(self):
        asked = {"role": "assistant", "content": "是现在就关鱼缸灯，还是等十一点？"}
        stated = {"role": "assistant", "content": "现在是上午九点二十，鱼缸插座开着。"}
        for dialogue in (self.SCHEDULED + [user("现在就把鱼缸灯关了")],
                         self.SCHEDULED + [user("好的，谢谢")],
                         self.SCHEDULED + [user("改成十二点关")],
                         self.SCHEDULED + [asked, user("现在关")],
                         [user("鱼缸插座开着吗"), stated, user("关了吧")],
                         # A device is named: a state question, not an overheard half sentence.
                         self.SCHEDULED + [user("客厅灯现在开着吗")],
                         # The times came from a history answer, not a schedule.
                         [user("鱼缸灯今天是几点关的，谁关的"),
                          {"role": "assistant", "content": "今天鱼缸灯是上午十一点关的，是我关的。"},
                          user("客厅灯现在开着吗")],
                         [user("今天鱼缸灯亮了多久"),
                          {"role": "assistant", "content": "亮了两小时二十八分，早上八点三十三开，十一点关的。"},
                          user("关了吧")]):
            self.assertFalse(hermes.is_unclear_after_schedule(dialogue, hermes._message_text(dialogue[-1])),
                             dialogue[-1])

    def test_ok_without_a_save_question_is_a_normal_turn(self):
        spoken, requests = self.run_dialogue(
            [user("讲个笑话"), {"role": "assistant", "content": "从前有只猫。"}, user("好")],
            [("text", "再讲一个。")],
        )
        self.assertEqual((spoken, len(requests)), ("再讲一个。", 1))
        self.assertFalse(hermes.confirms_rule([user("x"), self.ASKED, user("不用了")], "不用了"))


class ClaimTests(unittest.TestCase):
    """A sentence that says a device was switched needs a tool that switched it."""

    run_turn = ProviderTests.run_turn
    run_dialogue = ProviderTests.run_dialogue

    def test_scene_phrase_answered_without_a_tool_is_retried(self):
        # 2026-10-11: "我回来了" answered five times from the chat, lights never switched.
        spoken, requests = self.run_turn(
            "小琪，我回来了。",
            [("text", "好，客厅灯和餐厅灯都开了。")],
            [("tool", "mcp__home_rules__home_rule_run"), ("text", "好，客厅灯和餐厅灯开了。")],
        )
        self.assertEqual(spoken, "好，客厅灯和餐厅灯开了。")
        self.assertIn(hermes.CLAIM_RETRY_NOTE, requests[1])

    def test_a_claim_without_a_tool_twice_is_never_spoken(self):
        spoken, requests = self.run_turn(
            "我回来了。",
            [("text", "好，客厅灯和餐厅灯都开了。")],
            [("text", "我再执行一次。"), ("text", "这次应该开了，客厅灯和餐厅灯，你看看。")],
        )
        self.assertEqual(spoken, hermes.LLMProvider({"api_key": "x"}).claim_failed_reply)
        self.assertEqual(len(requests), 2)

    def test_a_promise_before_the_tool_is_lead_in(self):
        spoken, requests = self.run_turn(
            "嗯",
            [("text", "我再打开一次。"), ("tool", "ha_call_service"), ("text", "好了，客厅灯开了。")],
        )
        self.assertEqual((spoken, len(requests)), ("好了，客厅灯开了。", 1))

    def test_made_up_state_needs_a_lookup(self):
        spoken, requests = self.run_turn(
            "嗯？",
            [("text", "我先老老实实查一下这两盏灯到底什么状态。"), ("text", "查到了，客厅灯现在显示是关着的。")],
            [("tool", "ha_get_state"), ("text", "客厅灯现在关着。")],
        )
        self.assertEqual(spoken, "客厅灯现在关着。")
        self.assertIn(hermes.STATE_RETRY_NOTE, requests[1])

    def test_a_lookup_backs_up_a_state_but_not_a_switch(self):
        spoken, _ = self.run_turn(
            "家里怎么样", [("tool", "ha_list_entities"), ("text", "灯都关着，门都关好了。")])
        self.assertEqual(spoken, "灯都关着，门都关好了。")
        spoken, requests = self.run_turn(
            "嗯",
            [("tool", "ha_get_state"), ("text", "确实关着，我再发一次开灯指令。"), ("text", "好了，开了。")],
            [("tool", "ha_call_service"), ("text", "好了，客厅灯开了。")],
        )
        self.assertEqual(spoken, "好了，客厅灯开了。")
        self.assertIn(hermes.CLAIM_RETRY_NOTE, requests[1])

    def test_earlier_sentences_are_spoken_before_a_late_claim(self):
        spoken, requests = self.run_turn(
            "今天怎么样",
            [("text", "今天天气不错，"), ("text", "适合出门。"), ("text", "客厅灯也给你开好了。")],
            [("text", "今天天气不错，适合出门。")],
        )
        self.assertEqual(spoken, "今天天气不错，适合出门。今天天气不错，适合出门。")
        self.assertEqual(len(requests), 2)

    def test_chat_about_devices_is_not_a_claim(self):
        for reply in ("空调开着睡觉容易着凉。", "鱼缸灯开太久了容易长藻，晚上记得把灯关了。",
                      "要不要我帮你把灯关了？", "就是以后你说“我回来了”，我就打开客厅灯和餐厅灯，要我保存吗？",
                      "刚才开了客厅灯和餐厅灯。", "灯光指令偶尔会没送到，重发一次就好。", "那说明灯是好的，是我这边指令没送到。",
                      "你是说刚才那次灯没开，还是说不用关了？", "空调还是开着比较好。", "冰箱只能看到门开着还是关着。"):
            spoken, requests = self.run_turn("嗯", [("text", reply)])
            self.assertEqual((spoken, len(requests)), (reply, 1), reply)

    def test_made_up_claims(self):
        for reply in ("好，客厅灯和餐厅灯都开了。", "我再执行一次。", "这次应该开了，客厅灯和餐厅灯，你看看。",
                      "这次两路都发出去了，你再看下客厅灯亮没亮。", "我单独再开一次餐厅灯。", "已经帮你把灯都关了。",
                      "好了，主卧灯开到最亮了。", "餐厅灯这次也开成功了。",
                      # 2026-10-11 test backend: the lights were off.
                      "好，客厅灯和餐厅灯亮了就好，有什么需要我帮忙的吗？"):
            self.assertEqual(hermes.claim_need(reply), "act", reply)
        for reply in ("我看看是灯离线了还是状态不对。", "客厅灯状态是开，餐厅灯状态是关。",
                      "两盏灯在系统里都显示是开。", "这次两盏灯的状态确实都是开。",
                      # 2026-10-11 test backend: the lights were off.
                      "好，客厅灯和餐厅灯开着呢。"):
            self.assertEqual(hermes.claim_need(reply), "look", reply)
            self.assertIsNone(hermes.claim_need(reply, looked=True), reply)
        self.assertIsNone(hermes.claim_need("好，客厅灯和餐厅灯都开了。", acted=True))

    def test_english_before_a_tool_is_still_dropped(self):
        spoken, _ = self.run_turn(
            "取消定时任务",
            [("text", "I'll look up your scheduled tasks first."), ("tool", "cronjob_manage"),
             ("text", "好了，那个定时任务取消了。")],
        )
        self.assertEqual(spoken, "好了，那个定时任务取消了。")

    def test_off_without_the_tool_guard(self):
        provider = hermes.LLMProvider({"api_key": "x", "tool_guard": False})
        provider._events = lambda dialogue: iter([("text", "好，客厅灯和餐厅灯都开了。")])
        self.assertEqual("".join(provider.response("s", [user("我回来了")])), "好，客厅灯和餐厅灯都开了。")

    DONE = {"role": "assistant", "content": "好，客厅灯和餐厅灯都开了。"}

    def test_it_did_not_work_needs_a_new_attempt(self):
        spoken, requests = self.run_dialogue(
            [user("我回来了"), self.DONE, user("没开呀。")],
            [("tool", "ha_get_state"), ("text", "两盏灯现在都关着，可能是灯离线了。")],
            [("tool", "ha_call_service"), ("text", "好了，这次两盏灯都开了。")],
        )
        self.assertEqual(spoken, "好了，这次两盏灯都开了。")
        self.assertIn(hermes.NOT_DONE_NOTE, requests[1])

    def test_complaints_only_count_after_a_done_claim(self):
        for text in ("没开呀。", "还是没有打开。", "两个都没开啊。", "没亮啊没有亮啊", "可是它现在还开着啊。"):
            self.assertTrue(hermes.is_not_done_complaint([user("我回来了"), self.DONE, user(text)], text), text)
        chat = {"role": "assistant", "content": "今天晴天。"}
        self.assertFalse(hermes.is_not_done_complaint([user("天气"), chat, user("没开呀")], "没开呀"))
        for text in ("我还没吃饭。", "没关系", "那现在客厅灯是开着还是关着？", "开个是没开过的呀"):
            self.assertFalse(hermes.is_not_done_complaint([user("我回来了"), self.DONE, user(text)], text), text)

    def test_a_little_brighter_is_not_one_oclock(self):
        for text in ("你把那个主卧灯的，你把主卧灯亮度调高一点不太暗。", "客厅灯调亮一点", "空调温度调低一点点",
                     "灯有一点暗，开灯"):
            self.assertFalse(hermes.is_scheduled_control(text), text)
        for text in ("下午一点关空调", "一点钟关灯", "1点关闭书房灯", "晚上十一点关闭鱼缸灯", "晚一点关闭客厅灯"):
            self.assertTrue(hermes.is_scheduled_control(text), text)


class FakeScenes:
    def __init__(self, phrases, reply="好，客厅灯和餐厅灯开了。"):
        self.phrases, self.reply, self.ran = phrases, reply, []

    def match(self, request):
        found = hermes.scene_run.match(request, self.phrases)
        return (found[0], self.phrases[found[0]], found[1]) if found else None

    def run(self, phrase, entity_id):
        self.ran.append(entity_id)
        return {"done": [], "failed": [], "unchecked": 0, "later": False, "error": None}, self.reply


class SceneShortcutTests(unittest.TestCase):
    def provider(self, *streams):
        provider = hermes.LLMProvider({"api_key": "x"})
        provider.scenes = FakeScenes({"我回来了": "script.xiaoqi_scene_home"})
        scripts, provider.requests = list(streams), []

        def fake_events(dialogue):
            provider.requests.append(dialogue[-1]["content"])
            yield from scripts.pop(0)

        provider._events = fake_events
        return provider

    def test_the_phrase_runs_without_the_model(self):
        provider = self.provider()
        spoken = "".join(provider.response("s", [user("小琪，我回来了。")]))
        self.assertEqual(spoken, "好，客厅灯和餐厅灯开了。")
        self.assertEqual((provider.scenes.ran, provider.requests), (["script.xiaoqi_scene_home"], []))

    def test_the_rest_goes_to_the_model(self):
        provider = self.provider([("tool", "ha_call_service"), ("text", "空调开到二十六度了。")])
        spoken = "".join(provider.response("s", [user("我回来了，把空调开到二十六度。")]))
        self.assertEqual(spoken, "好，客厅灯和餐厅灯开了。空调开到二十六度了。")
        self.assertTrue(provider.requests[0].startswith("把空调开到二十六度。\n（系统提示：用户这句话开头说的是已保存场景“我回来了”"))

    def test_the_rest_keeps_its_guard(self):
        provider = self.provider(
            [("text", "好，空调也开了。")],
            [("tool", "ha_call_service"), ("text", "空调开到二十六度了。")],
        )
        spoken = "".join(provider.response("s", [user("我回来了，把空调开到二十六度。")]))
        self.assertEqual(spoken, "好，客厅灯和餐厅灯开了。空调开到二十六度了。")
        self.assertIn("已保存场景“我回来了”", provider.requests[1])
        self.assertIn(hermes.RETRY_NOTE, provider.requests[1])

    def test_teaching_a_scene_is_not_running_it(self):
        provider = self.provider([("text", "以后你说“我回来了”，我就开客厅灯，要我保存吗？")])
        spoken = "".join(provider.response("s", [user("以后我说我回来了，就打开客厅灯")]))
        self.assertEqual(spoken, "以后你说“我回来了”，我就开客厅灯，要我保存吗？")
        self.assertEqual(provider.scenes.ran, [])

    def test_wired_to_home_assistant_from_the_config(self):
        provider = hermes.LLMProvider({"api_key": "x", "ha_url": "http://ha:8123", "ha_token": "t",
                                       "scene_replies": {"done": "{done}，欢迎回家。"}})
        self.assertEqual(provider.scenes.ha.url, "http://ha:8123")
        self.assertEqual(provider.scenes.replies, {"done": "{done}，欢迎回家。"})
        self.assertIsNone(hermes.LLMProvider({"api_key": "x", "ha_url": "http://ha:8123", "ha_token": "t",
                                              "scene_shortcut": False}).scenes)

    def test_scene_list_failures_back_off(self):
        calls = []

        class DownHA:
            def request(self, *args, **kwargs):
                calls.append(1)
                raise OSError("refused")

        shortcut = hermes.SceneShortcut(DownHA())
        self.assertIsNone(shortcut.match("我回来了"))
        self.assertIsNone(shortcut.match("我回来了"))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
