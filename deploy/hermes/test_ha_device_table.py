"""python -m unittest test_ha_device_table (no Home Assistant needed)."""

import sys
import types
import unittest

sys.modules.setdefault("websockets", types.ModuleType("websockets"))
import ha_device_table  # noqa: E402

AREAS = [{"area_id": "living", "name": "客厅"}, {"area_id": "study", "name": "书房"}]
DEVICES = [{"id": "plug", "area_id": "living"}, {"id": "lamp", "area_id": "study"}]
ENTITIES = [
    # Smart plug: its switch is the device; the indicator LED is a config "light".
    {"entity_id": "switch.plug_on", "device_id": "plug", "original_name": " 开关 开关"},
    {"entity_id": "switch.plug_dnd", "device_id": "plug", "original_name": "* 指示灯勿扰模式 勿扰模式"},
    {"entity_id": "sensor.plug_temp", "device_id": "plug", "original_name": "* 开关次数 设备温度",
     "options": {"conversation": {"should_expose": True}}},
    {"entity_id": "light.plug_led", "device_id": "plug", "original_name": " 指示灯", "entity_category": "config"},
    # Lamp: its light is the device; its switches are features.
    {"entity_id": "light.lamp", "device_id": "lamp", "original_name": "书房灯"},
    {"entity_id": "switch.lamp_night", "device_id": "lamp", "original_name": "夜灯模式"},
]
STATES = [
    {"entity_id": "switch.plug_on", "attributes": {"friendly_name": "鱼缸智能插座  开关 开关"}},
    {"entity_id": "switch.plug_dnd", "attributes": {"friendly_name": "鱼缸智能插座 * 指示灯勿扰模式 勿扰模式"}},
    {"entity_id": "sensor.plug_temp", "attributes": {"friendly_name": "鱼缸智能插座 * 开关次数 设备温度", "device_class": "temperature"}},
    {"entity_id": "light.plug_led", "attributes": {"friendly_name": "鱼缸智能插座  指示灯"}},
    {"entity_id": "light.lamp", "attributes": {"friendly_name": "书房灯"}},
    {"entity_id": "switch.lamp_night", "attributes": {"friendly_name": "书房灯 夜灯模式"}},
]


class DeviceTableTest(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(ha_device_table.build_lines(AREAS, DEVICES, ENTITIES, STATES))

    def test_plug_switch_listed_despite_its_indicator_light(self):
        self.assertIn("switch.plug_on", self.text)
        self.assertNotIn("light.plug_led", self.text)

    def test_xiaomi_non_standard_entities_left_out(self):
        self.assertNotIn("switch.plug_dnd", self.text)
        self.assertNotIn("sensor.plug_temp", self.text)

    def test_feature_switch_of_a_lamp_left_out(self):
        self.assertIn("light.lamp", self.text)
        self.assertNotIn("switch.lamp_night", self.text)


if __name__ == "__main__":
    unittest.main()
