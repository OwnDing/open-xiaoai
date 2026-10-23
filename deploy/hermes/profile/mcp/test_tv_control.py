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
        if path.startswith("/screen"):
            items = list(self.items)
            if self.sessions and self.sessions[0]["state"] == "playing":
                items.append({"text": f"狂飙 第{self.episode}集", "bounds": [0, 0, 10, 10]})
            return {"ok": True, "package": self.package, "items": items}
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
