"""Unit tests for home_history (no Home Assistant needed).

    cd deploy/hermes/profile/mcp && python3 -m unittest test_home_history

The fish-tank rows are the real recorder history of 2026-10-05..09.
"""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from home_history import history

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 9, 22, 40, tzinfo=TZ)
FISH = "switch.cuco_cn_731278484_v3_on_p_2_1"
USER = {"context_user_id": "5475ba69", "context_domain": "switch", "context_service": "turn_on",
        "context_event_type": "call_service"}


def row(state, when):
    return {"state": state, "last_changed": when}


FISH_ROWS = [row(s, t) for s, t in [
    ("on", "2026-10-07T23:44:27.749692+00:00"),
    ("off", "2026-10-08T02:30:44.714604+00:00"),
    ("on", "2026-10-08T11:52:59.897356+00:00"),
    ("off", "2026-10-08T13:49:06.383110+00:00"),
    ("on", "2026-10-09T00:33:03.778561+00:00"),
    ("off", "2026-10-09T03:00:51.255399+00:00"),
    ("unavailable", "2026-10-09T12:57:26.653774+00:00"),
    ("off", "2026-10-09T12:57:52.987332+00:00"),
]]
FISH_LOGBOOK = [
    {"state": "on", "when": "2026-10-08T11:52:59.897356+00:00", **USER},
    {"state": "off", "when": "2026-10-08T13:49:06.383110+00:00"},
    {"state": "on", "when": "2026-10-09T00:33:03.778561+00:00", **USER},
    {"state": "off", "when": "2026-10-09T03:00:51.255399+00:00", **USER, "context_service": "turn_off"},
]
CURRENT = {"state": "off", "attributes": {"friendly_name": "鱼缸智能插座 开关"}}


def summarize(entity_id, rows, period="today", logbook=(), current=None, now=NOW, **kw):
    lo, hi = history.window(now, period, **kw)
    # HA returns the state at the window start first; the tests pass raw rows instead.
    return history.summarize(entity_id, current or CURRENT, rows, list(logbook), lo, hi, now, TZ)


class WindowTests(unittest.TestCase):
    def test_periods(self):
        lo, hi = history.window(NOW, "today")
        self.assertEqual((lo, hi), (datetime(2026, 10, 9, tzinfo=TZ), NOW))
        lo, hi = history.window(NOW, "yesterday")
        self.assertEqual((lo, hi), (datetime(2026, 10, 8, tzinfo=TZ), datetime(2026, 10, 9, tzinfo=TZ)))
        self.assertEqual(history.window(NOW, "this_week")[0], datetime(2026, 10, 5, tzinfo=TZ))  # a Monday
        self.assertEqual(history.window(NOW, "last_7_days")[0], datetime(2026, 10, 3, tzinfo=TZ))
        self.assertEqual(history.window(NOW, "this_month")[0], datetime(2026, 10, 1, tzinfo=TZ))

    def test_last_night_by_start_and_end(self):
        lo, hi = history.window(NOW, "today", start="yesterday 18:00", end="today 08:00")
        self.assertEqual((lo, hi), (datetime(2026, 10, 8, 18, tzinfo=TZ), datetime(2026, 10, 9, 8, tzinfo=TZ)))
        lo, _ = history.window(NOW, start="2026-10-08 06:30")
        self.assertEqual(lo, datetime(2026, 10, 8, 6, 30, tzinfo=TZ))
        lo, _ = history.window(NOW, start="2026-10-08T00:00:00+00:00")
        self.assertEqual(lo, datetime(2026, 10, 8, 8, tzinfo=TZ))

    def test_end_never_passes_now_and_bad_input_is_explained(self):
        self.assertEqual(history.window(NOW, "today", end="23:30")[1], NOW)
        for kw in ({"period": "forever"}, {"start": "21:00", "end": "20:00"}, {"start": "昨晚"}):
            with self.assertRaises(ValueError):
                history.window(NOW, **kw)


class OnOffTests(unittest.TestCase):
    def test_how_long_the_fish_tank_light_was_on_today(self):
        out = summarize(FISH, FISH_ROWS, "today", FISH_LOGBOOK)
        self.assertEqual(out["on_total"], "2小时28分")
        self.assertEqual(out["times_switched_on"], 1)
        self.assertEqual(out["on_periods"], [
            {"on": "08:33", "on_by": "小七", "off": "11:00", "off_by": "小七", "duration": "2小时28分"}])
        self.assertEqual(out["now"], "off")
        self.assertNotIn("offline", out)  # a 26-second blip is not worth mentioning
        self.assertNotIn("per_day", out)

    def test_yesterday_two_periods_and_who_switched_them(self):
        out = summarize(FISH, FISH_ROWS, "yesterday", FISH_LOGBOOK)
        self.assertEqual(out["on_total"], "4小时42分")
        self.assertEqual(out["times_switched_on"], 2)
        first, second = out["on_periods"]
        self.assertEqual((first["on"], first["off"]), ("07:44", "10:30"))
        self.assertNotIn("on_by", first)  # nothing logged for it
        self.assertEqual((second["on"], second["on_by"], second["off"], second["off_by"]),
                         ("19:52", "小七", "21:49", "米家App、小爱同学或手动"))

    def test_still_on_counts_until_now(self):
        rows = [row("off", "2026-10-08T16:00:00+00:00"), row("on", "2026-10-09T12:10:00+00:00")]
        out = summarize(FISH, rows, "today")
        self.assertEqual(out["on_total"], "2小时30分")
        self.assertEqual(out["on_periods"][0]["off"], "现在还开着")

    def test_on_across_midnight_is_cut_at_the_edge(self):
        rows = [row("on", "2026-10-08T14:00:00+00:00"), row("off", "2026-10-08T17:30:00+00:00")]
        out = summarize(FISH, rows, "today")
        self.assertEqual(out["on_total"], "1小时30分")
        self.assertEqual(out["times_switched_on"], 0)
        self.assertEqual(out["on_periods"][0]["on"], "开始前就开着")
        out = summarize(FISH, rows, "yesterday")
        self.assertEqual(out["on_periods"][0]["off"], "这段时间结束时还开着")

    def test_offline_time_is_left_out_but_does_not_split_a_period(self):
        rows = [row("on", "2026-10-09T01:00:00+00:00"), row("unavailable", "2026-10-09T02:00:00+00:00"),
                row("on", "2026-10-09T02:30:00+00:00"), row("off", "2026-10-09T03:00:00+00:00")]
        out = summarize(FISH, rows, "today")
        self.assertEqual((out["on_total"], out["times_switched_on"]), ("1小时30分", 1))
        self.assertEqual(out["offline"], "30分钟（离线，没算在内）")

    def test_several_days_have_a_per_day_breakdown_and_average(self):
        out = summarize(FISH, FISH_ROWS, "last_7_days")
        days = {d["date"]: d["on"] for d in out["per_day"]}
        self.assertEqual((days["10月7日"], days["10月8日"], days["10月9日"]), ("没有记录", "4小时42分", "2小时28分"))
        self.assertEqual(out["records_from"], "10月8日 07:44")
        self.assertEqual(out["on_periods"][0]["on"], "10月8日 07:44")
        # 10-08 is recorded only from 07:44 and today is not over: no whole day to average.
        self.assertNotIn("average_per_full_day", out)

        rows = [row("off", "2026-10-06T12:00:00+00:00")] + FISH_ROWS
        out = summarize(FISH, rows, "last_7_days")
        days = {d["date"]: d["on"] for d in out["per_day"]}
        self.assertEqual((days["10月6日"], days["10月7日"]), ("0分钟", "0分钟"))
        self.assertEqual((out["full_days"], out["average_per_full_day"]), (2, "2小时21分"))  # (0 + 4h42m) / 2

    def test_nothing_recorded(self):
        out = summarize(FISH, [], "today")
        self.assertEqual(out["no_records"], "这段时间没有记录")

    def test_tv_and_ac_states_count_as_on(self):
        rows = [row("playing", "2026-10-09T11:00:00+00:00"), row("paused", "2026-10-09T11:30:00+00:00"),
                row("off", "2026-10-09T12:00:00+00:00")]
        self.assertEqual(summarize("media_player.tv", rows)["on_total"], "1小时")
        rows = [row("cool", "2026-10-09T05:00:00+00:00"), row("off", "2026-10-09T06:15:00+00:00")]
        self.assertEqual(summarize("climate.ac", rows)["on_total"], "1小时15分")

    def test_actor_names_linkages_and_scenes(self):
        self.assertEqual(history.actor({"context_event_type": "automation_triggered",
                                        "context_name": "小七联动：洗衣提醒"}), "联动：洗衣提醒")
        self.assertEqual(history.actor({"context_event_type": "script_started",
                                        "context_name": "小七场景：我回来了"}), "场景：我回来了")
        self.assertEqual(history.actor({"context_event_type": "automation_triggered",
                                        "context_name": "Night"}), "自动化：Night")
        self.assertIsNone(history.actor(None))


class SensorTests(unittest.TestCase):
    TEMP = {"state": "22.5", "attributes": {"friendly_name": "卧室温度", "unit_of_measurement": "°C",
                                            "state_class": "measurement"}}

    def test_min_max_average_last_night(self):
        rows = [row("24.0", "2026-10-08T10:00:00+00:00"), row("22.0", "2026-10-08T19:00:00+00:00"),
                row("unavailable", "2026-10-08T20:00:00+00:00"), row("23.0", "2026-10-08T22:00:00+00:00")]
        out = summarize("sensor.bedroom_t", rows, current=self.TEMP, start="yesterday 18:00", end="today 08:00")
        self.assertEqual(out["min"], {"value": 22.0, "at": "10月9日 03:00"})
        self.assertEqual(out["max"], {"value": 24.0, "at": "10月8日 18:00"})
        self.assertEqual(out["unit"], "°C")
        self.assertEqual(out["latest"], 23.0)
        self.assertEqual(out["average"], 23.7)  # 9 h at 24, 1 h at 22, 2 h at 23 (offline 2 h left out)

    def test_power_sensor_gives_an_energy_estimate(self):
        power = {"state": "0", "attributes": {"friendly_name": "鱼缸智能插座 电功率", "unit_of_measurement": "W",
                                              "state_class": "measurement"}}
        rows = [row("0", "2026-10-08T15:00:00+00:00"), row("12", "2026-10-09T00:30:00+00:00"),
                row("0", "2026-10-09T03:00:00+00:00")]
        out = summarize("sensor.fish_power", rows, current=power)
        self.assertEqual(out["estimated_energy_kwh"], 0.03)  # 12 W for 2.5 h
        self.assertEqual(out["max"], {"value": 12.0, "at": "08:30"})

    def test_power_of_keeps_what_a_switch_needs(self):
        power = {"state": "0", "attributes": {"friendly_name": "鱼缸智能插座 电功率", "unit_of_measurement": "W"}}
        rows = [row("0", "2026-10-08T15:00:00+00:00"), row("12", "2026-10-09T00:30:00+00:00"),
                row("0", "2026-10-09T03:00:00+00:00")]
        self.assertEqual(history.power_of(summarize("sensor.fish_power", rows, current=power)),
                         {"name": "鱼缸智能插座 电功率", "unit": "W",
                          "max": {"value": 12.0, "at": "08:30"}, "estimated_energy_kwh": 0.03})
        self.assertIsNone(history.power_of(summarize("sensor.bedroom_t", rows, current=self.TEMP)))

    def test_energy_used_today_survives_a_meter_reset(self):
        meter = {"state": "1.4", "attributes": {"friendly_name": "鱼缸智能插座 用电量", "unit_of_measurement": "kWh",
                                                "state_class": "total_increasing"}}
        rows = [row("10.0", "2026-10-08T15:00:00+00:00"), row("10.3", "2026-10-09T02:00:00+00:00"),
                row("0.2", "2026-10-09T05:00:00+00:00"), row("0.5", "2026-10-09T09:00:00+00:00")]
        out = summarize("sensor.fish_energy", rows, current=meter)
        self.assertEqual((out["used"], out["unit"]), (0.8, "kWh"))


class OtherStateTests(unittest.TestCase):
    def test_washer_phases(self):
        rows = [row("待机", "2026-10-08T15:00:00+00:00"), row("洗涤", "2026-10-09T01:00:00+00:00"),
                row("漂洗", "2026-10-09T01:40:00+00:00"), row("完成", "2026-10-09T02:10:00+00:00")]
        out = summarize("sensor.washer_phase", rows)
        self.assertEqual(out["changes"], [{"at": "09:00", "state": "洗涤"}, {"at": "09:40", "state": "漂洗"},
                                          {"at": "10:10", "state": "完成"}])
        self.assertEqual(out["time_in_state"]["洗涤"], "40分钟")

    def test_button_events_are_counted(self):
        rows = [row("2026-10-08T15:00:00.000+00:00", "2026-10-08T15:00:00+00:00"),
                row("2026-10-09T01:00:00.000+00:00", "2026-10-09T01:00:00+00:00"),
                row("2026-10-09T03:00:00.000+00:00", "2026-10-09T03:00:00+00:00")]
        out = summarize("event.bedroom_double", rows)
        self.assertEqual((out["times_happened"], out["at"]), (2, ["09:00", "11:00"]))


class FormatTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual([history.fmt_duration(s) for s in (0, 20, 61, 3600, 8868, 7260)],
                         ["0分钟", "不到1分钟", "1分钟", "1小时", "2小时28分", "2小时1分"])

    def test_entity_ids_are_checked_before_reaching_a_url(self):
        self.assertTrue(history.ENTITY_ID.match(FISH))
        for bad in ("../../api/config", "switch.a/b", "switch"):
            self.assertFalse(history.ENTITY_ID.match(bad), bad)


if __name__ == "__main__":
    unittest.main()
