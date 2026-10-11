"""Unit tests for home_rules.scene_run and the save read-back (no Home Assistant needed).

    cd deploy/hermes/profile/mcp && python3 -m unittest test_scene_run
"""

import json
import unittest

from home_rules import rules, scene_run

LIVING, DINING = "light.living", "light.dining"


def state(entity_id, value, name):
    return {"entity_id": entity_id, "state": value, "attributes": {"friendly_name": name}}


class FakeHA:
    """Scripts switch their devices after `lag` state reads; `dead` devices never change."""

    def __init__(self, configs, states, lag=2, dead=(), fail_call=False):
        self.configs, self.states, self.lag, self.dead = configs, states, lag, set(dead)
        self.fail_call = fail_call
        self.calls, self.reads, self.pending = [], 0, {}

    def request(self, method, path, body=None, text=False):
        assert path == "/api/template" and "xiaoqi_scene_" in body["template"]
        scripts = [[s["entity_id"], s["attributes"]["friendly_name"]] for s in self.states.values()
                   if s["entity_id"].startswith("script.xiaoqi_scene_")]
        return json.dumps(scripts, ensure_ascii=False)

    def get_config(self, kind, object_id):
        if object_id not in self.configs:
            raise RuntimeError("HTTP 404")
        return self.configs[object_id]

    def call(self, domain, service, data=None):
        if self.fail_call:
            raise OSError("connection refused")
        self.calls.append((domain, service, data))
        object_id = data["entity_id"].split(".", 1)[1]
        for step in self.configs[object_id]["sequence"]:
            if "delay" in step:
                break
            new = {"turn_on": "on", "turn_off": "off"}.get(step.get("action", "").split(".")[-1])
            if new and step["target"]["entity_id"] not in self.dead:
                self.pending[step["target"]["entity_id"]] = new

    def state(self, entity_id):
        self.reads += 1
        if self.reads > self.lag and entity_id in self.pending:
            self.states[entity_id]["state"] = self.pending.pop(entity_id)
        return dict(self.states[entity_id])


def home_ha(**kw):
    configs = {
        "xiaoqi_scene_home": {"sequence": [
            {"action": "light.turn_on", "target": {"entity_id": LIVING}},
            {"action": "light.turn_on", "target": {"entity_id": DINING}},
        ]},
    }
    states = {
        LIVING: state(LIVING, "off", "客厅灯  灯"),
        DINING: state(DINING, "off", "餐厅灯"),
        "script.xiaoqi_scene_home": state("script.xiaoqi_scene_home", "off", "小七场景：我回来了"),
    }
    return FakeHA(configs, states, **kw)


def run(ha, entity_id="script.xiaoqi_scene_home", verify_s=5.0):
    clock = {"now": 0.0}

    def sleep(seconds):
        clock["now"] += seconds

    return scene_run.run(ha, entity_id, verify_s=verify_s, clock=lambda: clock["now"], sleep=sleep)


class MatchTests(unittest.TestCase):
    PHRASES = {"我回来了": "script.a", "晚安": "script.b", "好了": "script.c", "我回来了开空调": "script.d"}

    def match(self, text):
        return scene_run.match(text, self.PHRASES)

    def test_the_phrase_as_speech_recognition_writes_it(self):
        for text in ("我回来了", "我回来了。", "我回来啦。", "小琪，我回来了。", "小七我回来了", "你好小七，我回来了！",
                     "嗯，我回来了", "我回来了，小七。", "我回来"):
            self.assertEqual(self.match(text), ("我回来了", ""), text)

    def test_a_request_after_the_phrase_is_the_rest(self):
        self.assertEqual(self.match("我回来了，把空调开到二十六度。"), ("我回来了", "把空调开到二十六度。"))
        self.assertEqual(self.match("晚安，明天早上七点叫我"), ("晚安", "明天早上七点叫我"))

    def test_talking_about_a_scene_is_left_to_the_model(self):
        for text in ("以后我说我回来了，就打开客厅灯", "把我回来了这个场景删掉", "我回来了，这个场景开哪几盏灯？",
                     "我回来了，以后也把空调打开", "我回来了吗", "他说我回来了", "我出门了"):
            self.assertIsNone(self.match(text), text)

    def test_short_phrases_do_not_swallow_agreement(self):
        self.assertIsNone(self.match("好"))
        self.assertIsNone(self.match("好的"))
        self.assertEqual(self.match("好了。"), ("好了", ""))

    def test_the_longest_phrase_wins(self):
        self.assertEqual(self.match("我回来了开空调"), ("我回来了开空调", ""))

    def test_scene_list_from_the_template(self):
        self.assertEqual(scene_run.list_scenes(home_ha()), {"我回来了": "script.xiaoqi_scene_home"})

    def test_names_match_home_rules(self):
        self.assertEqual("script." + scene_run.SCENE_OBJECT_PREFIX, "script." + rules.SCENE_PREFIX)
        self.assertEqual(scene_run.SCENE_ALIAS, rules.SCENE_ALIAS)


class RunTests(unittest.TestCase):
    def test_waits_until_the_lights_are_on(self):
        ha = home_ha(lag=3)
        result = run(ha)
        self.assertEqual(ha.calls, [("script", "turn_on", {"entity_id": "script.xiaoqi_scene_home"})])
        self.assertEqual(result["done"], [("客厅灯", "开了"), ("餐厅灯", "开了")])
        self.assertEqual((result["failed"], result["error"]), ([], None))
        self.assertEqual(scene_run.reply("我回来了", result), "好，客厅灯和餐厅灯开了。")

    def test_a_device_that_does_not_switch_is_reported(self):
        result = run(home_ha(dead=[DINING]), verify_s=2.0)
        self.assertEqual(result["done"], [("客厅灯", "开了")])
        self.assertEqual(result["failed"], ["餐厅灯"])
        self.assertEqual(scene_run.reply("我回来了", result), "客厅灯开了，但餐厅灯没有反应。")
        result = run(home_ha(dead=[LIVING, DINING]), verify_s=2.0)
        self.assertEqual(scene_run.reply("我回来了", result), "客厅灯和餐厅灯没有反应，“我回来了”没有执行成功。")

    def test_an_unavailable_device_does_not_hold_up_the_reply(self):
        ha = home_ha(lag=0, dead=[DINING])
        ha.states[DINING]["state"] = "unavailable"
        result = run(ha)
        self.assertEqual(result["failed"], ["餐厅灯"])
        self.assertLess(ha.reads, 6)

    def test_home_assistant_down(self):
        result = run(home_ha(fail_call=True))
        self.assertIn("connection refused", result["error"])
        self.assertEqual(scene_run.reply("我回来了", result), "现在连不上家里的设备，“我回来了”没有执行。")

    def test_unreadable_config_still_runs(self):
        ha = home_ha()
        ha.get_config = lambda kind, object_id: (_ for _ in ()).throw(RuntimeError("HTTP 500"))
        result = run(ha)
        self.assertEqual(len(ha.calls), 1)
        self.assertEqual((result["error"], result["unchecked"]), (None, 1))
        self.assertEqual(scene_run.reply("我回来了", result), "好，“我回来了”执行了。")

    def test_plan_covers_nested_scenes_waits_and_unchecked_steps(self):
        ha = home_ha()
        ha.configs["xiaoqi_scene_film"] = {"sequence": [
            {"action": "script.xiaoqi_scene_home"},
            {"action": "climate.set_temperature", "target": {"entity_id": "climate.ac"}, "data": {"temperature": 26}},
            {"action": "script.xiaoqi_announce", "data": {"message": "开始了"}},
            {"action": "light.turn_off", "target": {"entity_id": DINING}},
            {"delay": {"seconds": 60}},
            {"action": "light.turn_off", "target": {"entity_id": LIVING}},
        ]}
        checks, unchecked, later = scene_run.plan(ha, "script.xiaoqi_scene_film")
        self.assertEqual(checks[LIVING][1], "开了")
        self.assertEqual(checks[DINING], ({"off"}, "关了"))  # the later step on the same device wins
        self.assertEqual((unchecked, later), (1, True))

    def test_expectations(self):
        self.assertEqual(scene_run.expectation("light", "turn_on", None), ({"on"}, "开了"))
        self.assertEqual(scene_run.expectation("climate", "turn_on", None)[0], scene_run.NOT_OFF)
        self.assertTrue(scene_run.satisfied(scene_run.NOT_OFF, "cool"))
        self.assertFalse(scene_run.satisfied(scene_run.NOT_OFF, "unavailable"))
        self.assertEqual(scene_run.expectation("cover", "close_cover", {})[1], "关上了")
        self.assertEqual(scene_run.expectation("light", "toggle", {}), (None, None))


class ReplyTests(unittest.TestCase):
    def result(self, **kw):
        return dict({"done": [], "failed": [], "unchecked": 0, "later": False, "error": None}, **kw)

    def test_groups_by_what_happened(self):
        result = self.result(done=[("客厅灯", "开了"), ("餐厅灯", "开了"), ("走廊灯", "开了"), ("电视", "关了")])
        self.assertEqual(scene_run.reply("我回来了", result), "好，客厅灯、餐厅灯和走廊灯开了，电视关了。")

    def test_nothing_checkable_and_later_steps(self):
        self.assertEqual(scene_run.reply("看电影", self.result(unchecked=2)), "好，“看电影”执行了。")
        self.assertEqual(scene_run.reply("晚安", self.result(done=[("主卧灯", "关了")], later=True)),
                         "好，主卧灯关了。后面的动作会按设定的时间接着执行。")

    def test_templates_are_configurable(self):
        templates = {"done": "{done}，欢迎回家。", "later": ""}
        result = self.result(done=[("客厅灯", "开了")], later=True)
        self.assertEqual(scene_run.reply("我回来了", result, templates), "客厅灯开了，欢迎回家。")
        self.assertEqual(scene_run.reply("我回来了", result, {"done": "{oops}"}),
                         "好，客厅灯开了。后面的动作会按设定的时间接着执行。")


class ReadbackTests(unittest.TestCase):
    def test_devices_are_named_as_home_assistant_names_them(self):
        states = [state(LIVING, "off", "客厅灯  灯"), state("light.bedroom_ambient", "off", "主卧灯 氛围灯"),
                  state("event.double", "unknown", "主卧开关 双击"), state("climate.ac", "off", "主卧空调")]
        lines = rules.readback([
            {"type": "device", "entity_id": LIVING, "service": "turn_on"},
            {"type": "device", "entity_id": "light.bedroom_ambient", "service": "turn_off"},
            {"type": "device", "entity_id": "climate.ac", "service": "set_temperature", "data": {"temperature": 26}},
            {"type": "announce", "message": "灯开好了"},
            {"type": "delay", "seconds": 30},
        ], states, trigger={"type": "event", "entity_id": "event.double"})
        self.assertEqual(lines, ["触发：主卧开关双击", "打开客厅灯", "关闭主卧灯氛围灯",
                                 "调温度主卧空调（{\"temperature\": 26}）", "播报“灯开好了”", "等30秒"])


if __name__ == "__main__":
    unittest.main()
