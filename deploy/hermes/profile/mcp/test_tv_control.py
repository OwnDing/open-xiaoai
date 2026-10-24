"""Unit tests for the tv_control MCP server (a simulated TV and Home Assistant, no network).

    cd deploy/hermes/profile/mcp && python3 -m unittest test_tv_control
"""

import json
import sys
import types
import unittest
from unittest.mock import patch


class _Server:
    def __init__(self, name, instructions=""):
        self.name = name

    def tool(self):
        return lambda fn: fn


sys.modules.setdefault("mcp", types.ModuleType("mcp"))
sys.modules.setdefault("mcp.server", types.ModuleType("mcp.server"))
sys.modules.setdefault("mcp.server.mcpserver", types.SimpleNamespace(MCPServer=_Server))

from tv_control import server  # noqa: E402
from tv_control import tv as tvmod  # noqa: E402
from tv_control.tv import IR_POWER, QIYI, QIYI_ACTION, TV, TVError  # noqa: E402

APPS = [{"label": "银河奇异果", "package": QIYI}, {"label": "网易云音乐", "package": "com.netease.cloudmusic.tv"},
        {"label": "YT TV", "package": "com.google.android.apps.youtube.unplugged"}]


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeHA:
    def __init__(self, home):
        self.home = home
        self.calls = []

    def call(self, domain, service, data=None):
        self.calls.append((domain, service, data))
        if (domain, service) == ("button", "press") and data["entity_id"] == IR_POWER:
            self.home.ir_toggle()
        if (domain, service) == ("androidtv", "adb_command") and "xiaoqi-tv-helper.sh start" in data["command"]:
            self.home.helper_running = self.home.on


class Home:
    """A TV: power, whether the helper runs, what is in front and playing."""

    def __init__(self, on=True, helper_running=True):
        self.on = on
        self.helper_running = helper_running
        self.package = "com.tcl.cyberui"
        self.sessions = []
        self.items = []
        self.requests = []
        self.search_results = {}
        self.episode = 3
        self.ime_submits = True  # a native field; a web page ignores the IME action
        self.submitted_page = []
        self.between = []  # what screen reads show after a submit before the new page (blank, bits of the old)
        self.showing = []

    def ir_toggle(self):
        self.on = not self.on
        # A cold boot would also stop the helper; standby keeps it.

    def helper(self, method, path, body=None, timeout=8):
        self.requests.append((method, path, body))
        if not (self.on and self.helper_running):
            return None
        if path == "/status":
            return {"ok": True, "package": self.package, "screen_on": True}
        if path == "/apps":
            return {"ok": True, "apps": APPS}
        if path == "/launch":
            self.package = body["package"]
            return {"ok": True}
        if path == "/key":
            if body.get("key") == "SLEEP":
                self.on = False
            return {"ok": True, "pressed": len(body.get("keys", [])) or body.get("repeat", 1)}
        if path == "/intent":
            keyword = json.loads(body["extras"]["playInfo"])["keyword"]
            self.package = QIYI
            self.items = self.search_results.get(keyword, [])
            return {"ok": True}
        if path == "/type":
            fields = [i for i in self.items if i.get("editable")]
            if not fields:
                return {"ok": False, "error": "屏幕上没有输入框"}
            field = next((i for i in fields if i.get("focused")), fields[0])
            field["text"] = body["text"]
            if body.get("submit") and self.ime_submits:
                self.items = self.submitted_page
            return {"ok": True, "submitted": bool(body.get("submit") and self.ime_submits)} if body.get("submit") else {"ok": True}
        if path.startswith("/screen"):
            if self.showing:
                return {"ok": True, "package": self.package, "items": self.showing.pop(0)}
            items = list(self.items)
            if self.sessions and self.sessions[0]["state"] == "playing":
                items.append({"text": f"狂飙 第{self.episode}集", "bounds": [0, 0, 10, 10]})
            return {"ok": True, "package": self.package, "items": items}
        if path == "/click" and body["text"] in ("搜索", "搜索网页") and self.submitted_page:
            matching = [i for i in self.items if i["text"] == body["text"]]
            if matching[body.get("index", 0)].get("submits"):
                self.items = self.submitted_page
                self.showing = list(self.between)
            return {"ok": True, "clicked": body["text"]}
        if path == "/click":
            if body["text"] == "播放" and any(i["text"] == "播放" for i in self.items):
                self.sessions = [{"package": QIYI, "state": "playing", "title": "狂飙", "position_ms": 95000,
                                  "duration_ms": 2734000}]
                self.items = []
                return {"ok": True, "clicked": "播放"}
            return {"ok": False, "error": "没有找到", "on_screen": [i["text"] for i in self.items]}
        if path == "/media":
            if method == "GET":
                return {"ok": True, "sessions": self.sessions}
            if body.get("name") == QIYI_ACTION + "SELECT_EPISODE" and "index" in body["extras"]:
                self.episode = body["extras"]["index"]
            return {"ok": True, "package": body.get("package"), "action": body["action"]}
        if path == "/volume":
            return {"ok": True, "level": (body or {}).get("level", 8), "max": 100, "muted": bool((body or {}).get("mute"))}
        return {"ok": False, "error": "unexpected " + path}


def make(home):
    tv = TV(helper_url="http://tv.test:8765", helper_token="t", ha=FakeHA(home), clock=Clock())
    tv.helper = home.helper
    tv.reachable = lambda tries=3: home.on
    return tv


RESULT_PAGE = [{"text": "狂飙", "bounds": [324, 53, 420, 118]}, {"text": "的全部结果", "bounds": [420, 53, 660, 118]},
               {"text": "播放", "bounds": [364, 482, 534, 572], "focused": True}]
NO_MATCH_PAGE = [{"text": "繁花", "bounds": [324, 53, 420, 118]}, {"text": "的全部结果", "bounds": [420, 53, 660, 118]},
                 {"text": "全部", "bounds": [321, 147, 387, 192], "focused": True},
                 {"text": "一路繁花第2季", "bounds": [324, 219, 796, 489]},
                 {"text": "海上繁花", "bounds": [324, 537, 796, 807]},
                 {"text": "一路繁花第2季", "bounds": [844, 855, 1316, 1080]}]


class PowerTests(unittest.TestCase):
    def test_on_when_already_on_never_sends_ir(self):
        home = Home(on=True)
        tv = make(home)
        self.assertEqual(tv.power(True)["say"], "电视已经开着。")
        self.assertEqual(tv.ha.calls, [])
        self.assertTrue(home.on)

    def test_on_from_standby_presses_ir_once(self):
        home = Home(on=False)
        tv = make(home)
        self.assertEqual(tv.power(True)["say"], "电视打开了。")
        self.assertEqual([c for c in tv.ha.calls if c[0] == "button"], [("button", "press", {"entity_id": IR_POWER})])
        self.assertTrue(home.on)

    def test_on_after_reboot_restarts_helper_without_ir(self):
        home = Home(on=True, helper_running=False)
        tv = make(home)
        self.assertEqual(tv.power(True)["say"], "电视已经开着。")
        self.assertEqual([c[:2] for c in tv.ha.calls], [("androidtv", "adb_command")])
        self.assertTrue(home.helper_running)

    def test_on_waits_for_a_slow_wake(self):
        # 2026-10-23 19:46: back on the network about 30 s after the IR press.
        home = Home(on=False)
        tv = make(home)
        tv.reachable = lambda tries=3: home.on and tv.clock.now >= 30
        self.assertEqual(tv.power(True)["say"], "电视打开了。")
        self.assertEqual(len([c for c in tv.ha.calls if c[0] == "button"]), 1)

    def test_on_fails_when_ir_does_not_wake_it(self):
        home = Home(on=False)
        home.ir_toggle = lambda: None
        tv = make(home)
        with self.assertRaises(TVError):
            tv.power(True)

    def test_off(self):
        home = Home(on=True)
        tv = make(home)
        self.assertEqual(tv.power(False)["say"], "电视关了。")
        self.assertFalse(home.on)
        self.assertEqual(tv.power(False)["say"], "电视已经关着。")
        self.assertEqual(tv.ha.calls, [])

    def test_status_of_a_tv_in_standby_skips_the_helper(self):
        home = Home(on=False)
        tv = make(home)
        self.assertIsNone(tv.status())
        self.assertEqual(tv.describe(), {"ok": True, "power": "off"})
        self.assertEqual(home.requests, [])

    def test_reachable_retries_before_calling_the_tv_off(self):
        tv = TV(helper_url="http://tv.test:8765", helper_token="t", ha=FakeHA(Home()), clock=Clock())
        attempts = []

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def connect(address, timeout):
            attempts.append(address)
            if len(attempts) < 3:
                raise OSError("lost packet")
            return Connection()

        with patch.object(tvmod.socket, "create_connection", side_effect=connect):
            self.assertTrue(tv.reachable())
        self.assertEqual(attempts, [("tv.test", 5555)] * 3)
        with patch.object(tvmod.socket, "create_connection", side_effect=OSError()):
            self.assertFalse(tv.reachable())


class AppTests(unittest.TestCase):
    def test_aliases_and_partial_names(self):
        tv = make(Home())
        self.assertEqual(tv.find_app("爱奇艺")["package"], QIYI)
        self.assertEqual(tv.find_app("网易云")["label"], "网易云音乐")
        self.assertEqual(tv.find_app("YouTube")["label"], "YT TV")
        self.assertIsNone(tv.find_app("抖音"))

    def test_open_app_turns_the_tv_on(self):
        home = Home(on=False)
        tv = make(home)
        result = tv.open_app("网易云")
        self.assertEqual(result["say"], "打开网易云音乐了。")
        self.assertTrue(home.on)
        self.assertEqual(home.package, "com.netease.cloudmusic.tv")

    def test_unknown_app(self):
        with self.assertRaises(TVError):
            make(Home()).open_app("抖音")


class PlayTests(unittest.TestCase):
    def test_plays_exact_match_and_switches_episode(self):
        home = Home()
        home.search_results["狂飙"] = RESULT_PAGE
        tv = make(home)
        result = tv.play("狂飙", episode=2)
        self.assertEqual(result["say"], "开始播放《狂飙》第2集。")
        self.assertEqual(home.episode, 2)

    def test_plays_without_episode(self):
        home = Home()
        home.search_results["狂飙"] = RESULT_PAGE
        result = make(home).play("狂飙")
        self.assertEqual(result, {"ok": True, "title": "狂飙", "say": "开始播放《狂飙》。"})

    def test_no_exact_match_lists_results_once(self):
        home = Home()
        home.search_results["繁花"] = NO_MATCH_PAGE
        result = make(home).play("繁花")
        self.assertFalse(result["ok"])
        self.assertEqual(result["found"], ["一路繁花第2季", "海上繁花"])
        self.assertIn("没有找到《繁花》", result["say"])


class PlaybackTests(unittest.TestCase):
    def playing(self, package=QIYI):
        home = Home()
        home.sessions = [{"package": package, "state": "playing", "title": "狂飙", "position_ms": 1000}]
        return home, make(home)

    def test_next_uses_iqiyi_episode_action(self):
        home, tv = self.playing()
        tv.media("next")
        body = home.requests[-1][2]
        self.assertEqual(body["name"], QIYI_ACTION + "SELECT_EPISODE")
        self.assertEqual(body["extras"], {"action": "next"})

    def test_pause_on_another_app_uses_transport_controls(self):
        home, tv = self.playing("com.netease.cloudmusic.tv")
        self.assertEqual(tv.media("pause")["say"], "暂停了。")
        self.assertEqual(home.requests[-1][2], {"action": "pause", "package": "com.netease.cloudmusic.tv"})
        with self.assertRaises(TVError):
            tv.media("episode", 3)

    def test_forward_presses_right(self):
        home, tv = self.playing()
        tv.media("forward", 60)
        key = [r for r in home.requests if r[1] == "/key"][-1][2]
        self.assertEqual((key["key"], key["repeat"]), ("RIGHT", 8))

    def test_nothing_playing(self):
        with self.assertRaises(TVError):
            make(Home()).media("pause")


# Bing in BrowseHere, 2026-10-23: a "搜索" link elsewhere, the field's own button on its row.
BING = [{"text": "搜索", "bounds": [100, 40, 160, 80]},
        {"text": "", "bounds": [239, 221, 1583, 286], "focused": True, "editable": True},
        {"text": "搜索网页", "bounds": [1586, 236, 1660, 271], "submits": True},
        {"text": "Search", "bounds": [1664, 254, 1680, 293]}]


class TypeTests(unittest.TestCase):
    def test_native_field_submits_itself(self):
        home = Home()
        home.items = [{"text": "搜索或输入 URL", "bounds": [216, 80, 1508, 176], "focused": True, "editable": True},
                      {"text": "搜索", "bounds": [1520, 80, 1616, 176]}]
        home.submitted_page = [{"text": "必应", "bounds": [0, 0, 10, 10]}]
        result = make(home).type("bing.com")
        self.assertEqual((result["submitted"], home.items), (True, home.submitted_page))
        self.assertEqual(result["page"], ["必应"])
        self.assertFalse(any(r[1] == "/click" for r in home.requests))

    def test_web_page_field_gets_the_button_on_its_row(self):
        home = Home()
        home.ime_submits = False
        home.items = [dict(item) for item in BING]
        home.submitted_page = [{"text": "今天天气 - 搜索", "bounds": [0, 0, 10, 10]}]
        result = make(home).type("今天天气")
        self.assertTrue(result["submitted"])
        self.assertEqual(home.items, home.submitted_page)
        self.assertIn(("POST", "/click", {"text": "搜索网页", "index": 0}), home.requests)

    def test_unfocused_field_is_not_taken_as_sent(self):
        # 2026-10-23: Bing's box had no focus, and 小七 heard "确认了" for a search never sent.
        home = Home()
        home.ime_submits = False
        home.items = [dict(item, focused=False) for item in BING]
        home.submitted_page = [{"text": "今天天气 - 搜索", "bounds": [0, 0, 10, 10]}]
        result = make(home).type("今天天气")
        self.assertEqual((result["submitted"], result["page"]), (True, ["今天天气 - 搜索"]))
        self.assertIn(("POST", "/click", {"text": "搜索网页", "index": 0}), home.requests)

    def test_waits_for_the_new_page_to_load(self):
        home = Home()
        home.ime_submits = False
        home.items = [dict(item) for item in BING]
        home.submitted_page = [{"text": "今天天气 - 搜索", "bounds": [0, 0, 10, 10]}]
        home.between = [[]] * 4
        self.assertEqual(make(home).type("今天天气")["page"], ["今天天气 - 搜索"])
        home.items = [dict(item) for item in BING]
        home.between = [[]] * 100
        result = make(home).type("今天天气")
        self.assertEqual((result["submitted"], result["page"]), (True, []))
        self.assertTrue(result["say"].endswith("页面还在加载。"))

    def test_bits_of_the_old_page_are_not_the_new_one(self):
        # 2026-10-24: right after the click Bing still showed parts of its home page.
        home = Home()
        home.ime_submits = False
        home.items = [dict(item) for item in BING] + [{"text": label, "bounds": [0, 300 + 40 * n, 100, 330 + 40 * n]}
                                                      for n, label in enumerate(("必应", "图片", "视频", "翻译"))]
        home.submitted_page = [{"text": "今天天气 - 搜索", "bounds": [0, 0, 10, 10]}, {"text": "跳至内容", "bounds": [0, 20, 10, 30]},
                               {"text": "图片", "bounds": [0, 50, 10, 60]}]
        home.between = [[{"text": "必应", "bounds": [0, 0, 10, 10]}, {"text": "图片", "bounds": [0, 50, 10, 60]}]] * 2
        result = make(home).type("今天天气")
        self.assertEqual((result["submitted"], result["page"]), (True, ["今天天气 - 搜索", "跳至内容", "图片"]))

    def test_button_that_changes_nothing(self):
        home = Home()
        home.ime_submits = False
        home.items = [{k: v for k, v in item.items() if k != "submits"} for item in BING]
        home.submitted_page = [{"text": "今天天气 - 搜索", "bounds": [0, 0, 10, 10]}]
        result = make(home).type("今天天气")
        self.assertFalse(result["submitted"])
        self.assertIn("页面没有变化", result["say"])

    def test_without_submit_only_types(self):
        home = Home()
        home.items = [dict(item) for item in BING]
        result = make(home).type("今天天气", submit=False)
        self.assertEqual(result["say"], "输入了“今天天气”。")
        self.assertEqual(home.items[1]["text"], "今天天气")

    def test_no_input_field(self):
        home = Home()
        home.items = [{"text": "主页", "bounds": [0, 0, 10, 10]}]
        with self.assertRaises(TVError):
            make(home).type("bing.com")


class ToolTests(unittest.TestCase):
    def test_errors_become_spoken_replies(self):
        home = Home(on=True)
        server._tv = make(home)
        try:
            result = server.tv_playback("pause")
        finally:
            server._tv = None
        self.assertEqual(result, {"ok": False, "error": "电视上没有在播放的节目", "say": "电视上没有在播放的节目。"})


if __name__ == "__main__":
    unittest.main()
