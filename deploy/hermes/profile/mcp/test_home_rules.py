"""Unit tests for home_rules (no Home Assistant needed).

    cd deploy/hermes/profile/mcp && python3 -m unittest test_home_rules
"""

import unittest

import os
import tempfile

from home_rules import announce, rules, scene_index


def state(entity_id, value="off", **attrs):
    return {"entity_id": entity_id, "state": value, "attributes": attrs}


STATES = [
    state("binary_sensor.washer_running", "on", friendly_name="滚筒洗衣机 程序是否已运行"),
    state("binary_sensor.leak", "off", friendly_name="USP国际电工水浸传感器 水浸传感器 浸没状态"),
    state("binary_sensor.fridge_door", "off", friendly_name="冰箱 冷藏室门开关状态"),
    state("event.bedroom_switch_double", "unknown", friendly_name="主卧灯控制开关 BLE专用开关传感器 双击"),
    state("light.study", "off", friendly_name="书房灯 灯"),
    state("light.living", "on", friendly_name="客厅灯"),
    state("switch.fish_tank", "on", friendly_name="鱼缸智能插座 开关"),
    state("climate.bedroom_ac", "off", friendly_name="主卧空调"),
    state("lock.front_door", "locked", friendly_name="入户门锁"),
    state("switch.heater", "off", friendly_name="小太阳 取暖器"),
    state("sensor.living_temperature", "27.5", friendly_name="客厅温度"),
    state("select.washer_mode", "标准", friendly_name="洗衣机 模式", options=["标准", "快洗"]),
    state("notify.xiaomi_cn_1_oh2p_play_text_a_7_3", "unknown", friendly_name="Xiaomi 智能音箱 Pro 播放文本"),
    state("switch.xiaomi_cn_1_oh2p_no_disturb_p_9_1", "on", friendly_name="勿扰"),
    state("text.xiaomi_cn_1_oh2p_enable_time_period_p_9_2", "21:35:00-06:35:00"),
    state("script.xiaoqi_scene_abc123", "off", friendly_name="小七场景：我回来了"),
    state("automation.xiao_qi_lian_dong", "on", friendly_name="小七联动：洗衣提醒", id="xiaoqi_rule_def456",
          last_triggered=None),
    state("automation.users_own", "on", friendly_name="My own automation", id="1690000000000"),
    state("script.users_script", "off", friendly_name="My script"),
]
SERVICES = {
    "light": {"turn_on": {}, "turn_off": {}, "toggle": {}},
    "switch": {"turn_on": {}, "turn_off": {}, "toggle": {}},
    "climate": {"set_temperature": {}, "turn_on": {}, "turn_off": {}, "set_hvac_mode": {}},
    "lock": {"lock": {}, "unlock": {}},
}


def build(kind, actions, **kw):
    return rules.build(kind, kw.pop("name", "测试"), actions, STATES, SERVICES, **kw)


class SceneTests(unittest.TestCase):
    def test_scene_becomes_a_script(self):
        config, problems = build("scene", [
            {"type": "device", "entity_id": "light.living", "service": "turn_on"},
            {"type": "device", "entity_id": "climate.bedroom_ac", "service": "set_temperature",
             "data": {"temperature": 26}},
        ], name="我回来了", summary="开客厅灯，主卧空调调到二十六度")
        self.assertEqual(problems, [])
        self.assertEqual(config["alias"], "小七场景：我回来了")
        self.assertEqual(config["description"], "由小七根据语音创建：开客厅灯，主卧空调调到二十六度")
        self.assertEqual(config["sequence"][1], {"action": "climate.set_temperature",
                                                 "target": {"entity_id": "climate.bedroom_ac"},
                                                 "data": {"temperature": 26}})

    def test_scene_takes_no_trigger(self):
        _, problems = build("scene", [{"type": "device", "entity_id": "light.living", "service": "turn_on"}],
                            trigger={"type": "time", "at": "07:00"})
        self.assertTrue(any("不需要触发条件" in p for p in problems))

    def test_unknown_entity_and_service_are_reported(self):
        _, problems = build("scene", [
            {"type": "device", "entity_id": "light.kitchen", "service": "turn_on"},
            {"type": "device", "entity_id": "light.living", "service": "blink"},
        ])
        self.assertTrue(any("light.kitchen 不存在" in p for p in problems))
        self.assertTrue(any("没有 blink 这个操作" in p for p in problems))

    def test_high_risk_devices_are_refused(self):
        for entity_id, service in (("lock.front_door", "unlock"), ("switch.heater", "turn_on")):
            _, problems = build("scene", [{"type": "device", "entity_id": entity_id, "service": service}])
            self.assertTrue(any("高风险设备" in p for p in problems), entity_id)

    def test_fish_tank_plug_is_low_risk(self):
        self.assertEqual(rules.risk_of(STATES[6]), "low")

    def test_announcements_and_other_scenes_cannot_be_commands(self):
        _, problems = build("scene", [{"type": "device", "entity_id": "notify.xiaomi_cn_1_oh2p_play_text_a_7_3",
                                       "service": "send_message"}])
        self.assertTrue(any("不是可以控制的设备" in p for p in problems))

    def test_scene_can_run_another_scene_but_not_itself(self):
        config, problems = build("scene", [{"type": "scene", "scene": "我回来了"}], name="周末",
                                 scenes={"我回来了": "xiaoqi_scene_abc123"})
        self.assertEqual((problems, config["sequence"]), ([], [{"action": "script.xiaoqi_scene_abc123"}]))
        _, problems = build("scene", [{"type": "scene", "scene": "我回来了"}], name="我回来了",
                            scenes={"我回来了": "xiaoqi_scene_abc123"})
        self.assertTrue(any("不能调用它自己" in p for p in problems))


class RuleTests(unittest.TestCase):
    def test_washer_finished_announcement(self):
        config, problems = build("rule", [{"type": "announce", "message": "衣服洗好了，记得晾。"}],
                                 name="洗衣提醒",
                                 trigger={"type": "state", "entity_id": "binary_sensor.washer_running",
                                          "from": "on", "to": "off"})
        self.assertEqual(problems, [])
        self.assertEqual(config["triggers"], [{"trigger": "state", "entity_id": "binary_sensor.washer_running",
                                               "to": "off", "from": "on"}])
        self.assertEqual(config["actions"], [{"action": "script.xiaoqi_announce",
                                              "data": {"message": "衣服洗好了，记得晾。", "urgent": False}}])

    def test_fridge_door_open_for_two_minutes(self):
        config, _ = build("rule", [{"type": "announce", "message": "冰箱门没关好。"}],
                          trigger={"type": "state", "entity_id": "binary_sensor.fridge_door", "to": "on",
                                   "for_seconds": 120})
        self.assertEqual(config["triggers"][0]["for"], {"seconds": 120})

    def test_binary_sensor_states_are_on_off(self):
        _, problems = build("rule", [{"type": "announce", "message": "门开了"}],
                            trigger={"type": "state", "entity_id": "binary_sensor.fridge_door", "to": "open"})
        self.assertTrue(any("只有 on 和 off" in p for p in problems))

    def test_select_states_follow_options(self):
        _, problems = build("rule", [{"type": "announce", "message": "x"}],
                            trigger={"type": "state", "entity_id": "select.washer_mode", "to": "超快"})
        self.assertTrue(any("标准、快洗" in p for p in problems))

    def test_only_safety_alarms_may_be_urgent(self):
        config, problems = build("rule", [{"type": "announce", "message": "阳台漏水了！", "urgent": True}],
                                 trigger={"type": "state", "entity_id": "binary_sensor.leak", "to": "on"})
        self.assertEqual(problems, [])
        self.assertTrue(config["actions"][0]["data"]["urgent"])
        _, problems = build("rule", [{"type": "announce", "message": "衣服洗好了", "urgent": True}],
                            trigger={"type": "state", "entity_id": "binary_sensor.washer_running", "to": "off"})
        self.assertTrue(any("安全报警" in p for p in problems))

    def test_switch_click_event(self):
        config, problems = build("rule", [{"type": "device", "entity_id": "light.living", "service": "turn_off"}],
                                 trigger={"type": "event", "entity_id": "event.bedroom_switch_double"})
        self.assertEqual(problems, [])
        self.assertEqual(config["triggers"][0], {"trigger": "state", "entity_id": "event.bedroom_switch_double",
                                                 "not_from": ["unavailable"], "not_to": ["unavailable", "unknown"]})
        _, problems = build("rule", [{"type": "device", "entity_id": "light.living", "service": "turn_off"}],
                            trigger={"type": "event", "entity_id": "binary_sensor.fridge_door"})
        self.assertTrue(any("event. 开头" in p for p in problems))

    def test_time_trigger_with_weekdays_and_conditions(self):
        config, problems = build("rule", [{"type": "device", "entity_id": "light.study", "service": "turn_off"}],
                                 trigger={"type": "time", "at": "23:00", "weekdays": ["mon", "fri"]},
                                 conditions=[{"type": "state", "entity_id": "light.study", "state": "on"}])
        self.assertEqual(problems, [])
        self.assertEqual(config["triggers"], [{"trigger": "time", "at": "23:00:00"}])
        self.assertEqual(config["conditions"], [{"condition": "time", "weekday": ["mon", "fri"]},
                                                {"condition": "state", "entity_id": "light.study", "state": "on"}])

    def test_temperature_threshold(self):
        config, problems = build("rule", [{"type": "announce", "message": "客厅有点热了"}],
                                 trigger={"type": "numeric", "entity_id": "sensor.living_temperature", "above": 30})
        self.assertEqual((problems, config["triggers"][0]["above"]), ([], 30.0))
        _, problems = build("rule", [{"type": "announce", "message": "x"}],
                            trigger={"type": "numeric", "entity_id": "binary_sensor.fridge_door", "above": 1})
        self.assertTrue(any("不是数值" in p for p in problems))

    def test_medium_risk_linkage_must_announce(self):
        ac_off = {"type": "device", "entity_id": "climate.bedroom_ac", "service": "turn_off"}
        trigger = {"type": "time", "at": "02:00"}
        _, problems = build("rule", [ac_off], trigger=trigger)
        self.assertTrue(any("中风险设备" in p for p in problems))
        _, problems = build("rule", [ac_off, {"type": "announce", "message": "空调关了"}], trigger=trigger)
        self.assertEqual(problems, [])

    def test_one_shot_linkage_switches_itself_off(self):
        config, problems = build("rule", [{"type": "announce", "message": "衣服洗好了"}], once=True,
                                 trigger={"type": "state", "entity_id": "binary_sensor.washer_running", "to": "off"},
                                 summary="这次洗完时播报")
        self.assertEqual(problems, [])
        self.assertEqual(config["description"], "由小七根据语音创建：（一次性）这次洗完时播报")
        self.assertEqual(config["actions"][-1], {"action": "automation.turn_off",
                                                 "target": {"entity_id": "{{ this.entity_id }}"}})
        item = {"kind": "rule", "enabled": False, "last_triggered": "2026-10-06T22:00:00"}
        self.assertTrue(rules.is_spent(item, config["description"]))
        self.assertFalse(rules.is_spent(dict(item, enabled=True), config["description"]))
        self.assertFalse(rules.is_spent(item, "由小七根据语音创建：每次洗完时播报"))

    def test_same_behaviour_ignores_names(self):
        trigger = {"type": "state", "entity_id": "binary_sensor.leak", "to": "on"}
        a, _ = build("rule", [{"type": "announce", "message": "阳台漏水了", "urgent": True}], name="漏水提醒",
                     trigger=trigger, summary="一")
        b, _ = build("rule", [{"type": "announce", "message": "阳台漏水了", "urgent": True}], name="漏水报警",
                     trigger=trigger, summary="二")
        c, _ = build("rule", [{"type": "announce", "message": "漏水啦", "urgent": True}], trigger=trigger)
        self.assertTrue(rules.same_behaviour("rule", a, b))
        self.assertFalse(rules.same_behaviour("rule", a, c))

    def test_bad_time_and_delay(self):
        _, problems = build("rule", [{"type": "delay", "seconds": 7200}], trigger={"type": "time", "at": "25:00"})
        self.assertTrue(any("HH:MM" in p for p in problems))
        self.assertTrue(any("1 到 3600" in p for p in problems))


class OwnershipTests(unittest.TestCase):
    def test_only_own_scenes_and_rules_are_listed(self):
        items = rules.owned(STATES)
        self.assertEqual([(i["kind"], i["id"], i["name"]) for i in items],
                         [("scene", "xiaoqi_scene_abc123", "我回来了"), ("rule", "xiaoqi_rule_def456", "洗衣提醒")])

    def test_find_prefers_exact_names(self):
        items = rules.owned(STATES)
        self.assertEqual([i["id"] for i in rules.find(items, "洗衣")], ["xiaoqi_rule_def456"])
        self.assertEqual([i["id"] for i in rules.find(items, "我回来了", "scene")], ["xiaoqi_scene_abc123"])
        self.assertEqual(rules.find(items, "我回来了", "rule"), [])

    def test_new_ids_carry_the_prefix(self):
        self.assertTrue(rules.new_id("scene").startswith(rules.SCENE_PREFIX))
        self.assertTrue(rules.new_id("rule").startswith(rules.RULE_PREFIX))


class AnnounceTests(unittest.TestCase):
    def test_speaker_entities_are_found(self):
        self.assertEqual(announce.find_speaker(STATES), {
            "play_text": "notify.xiaomi_cn_1_oh2p_play_text_a_7_3",
            "name": "Xiaomi 智能音箱 Pro 播放文本",
            "no_disturb": "switch.xiaomi_cn_1_oh2p_no_disturb_p_9_1",
            "quiet_period": "text.xiaomi_cn_1_oh2p_enable_time_period_p_9_2",
        })
        self.assertIsNone(announce.find_speaker(STATES[:5]))

    def test_script_skips_quiet_hours_unless_urgent(self):
        config = announce.script_config(announce.find_speaker(STATES))
        self.assertEqual(config["mode"], "queued")
        self.assertEqual(set(config["fields"]), {"message", "urgent"})
        sequence = config["sequence"]
        self.assertEqual(sequence[2]["then"], [{"stop": "勿扰时段，非紧急播报不出声"}])
        self.assertEqual(sequence[3]["target"], {"entity_id": "notify.xiaomi_cn_1_oh2p_play_text_a_7_3"})
        # Do-not-disturb does not block play-text, so it is never switched.
        self.assertEqual([step.get("action") for step in sequence if "action" in step], ["notify.send_message"])

    def test_script_without_do_not_disturb_just_speaks(self):
        speaker = {"play_text": "notify.x_play_text", "name": "x", "no_disturb": None, "quiet_period": None}
        sequence = announce.script_config(speaker)["sequence"]
        self.assertEqual(sequence[-1]["action"], "notify.send_message")


class SceneIndexTests(unittest.TestCase):
    SOUL = "人设\r\n<!-- devices:end -->\r\n\r\n已保存的场景：\r\n<!-- scenes:start -->\r\n（还没有）\r\n<!-- scenes:end -->\r\n"

    def test_render_and_update(self):
        self.assertEqual(scene_index.render([]), "（还没有）")
        self.assertEqual(scene_index.render([("我出门了", "关书房灯"), ("晚安", "")]), "- “我出门了”：关书房灯\n- “晚安”")
        self.assertIsNone(scene_index.update("no markers", []))

    def test_sync_rewrites_only_the_block_and_keeps_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "SOUL.md")
            with open(path, "wb") as f:
                f.write(self.SOUL.encode("utf-8"))
            self.assertEqual(scene_index.sync(path, [("我出门了", "关书房灯")]), "1 scene(s)")
            text = open(path, "rb").read().decode("utf-8")
            self.assertIn("<!-- scenes:start -->\r\n- “我出门了”：关书房灯\r\n<!-- scenes:end -->", text)
            self.assertTrue(text.startswith("人设\r\n<!-- devices:end -->"))
            self.assertEqual(scene_index.sync(path, [("我出门了", "关书房灯")]), "unchanged")
            self.assertEqual(scene_index.sync(path, []), "0 scene(s)")
            self.assertIn("（还没有）", open(path, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
