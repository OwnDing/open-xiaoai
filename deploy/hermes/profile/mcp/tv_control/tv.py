"""The living-room TCL TV, reached two ways.

- 小七电视助手 (deploy/tv-helper): a program the TV runs as the adb shell user, with an HTTP API
  (TV_HELPER_URL, TV_HELPER_TOKEN) for screen text, clicks, keys, media sessions and apps.
- Home Assistant (HASS_URL, HASS_TOKEN): the 小爱 speaker's IR power button, since the TV turns
  its WiFi off in standby, and the TV's adb (androidtv integration), to start the helper again
  after the TV really rebooted (standby keeps it running).

The IR code toggles power, so it is only sent when the TV does not answer on the network.
"""

import json
import math
import os
import re
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from home_rules.ha import HAError, HomeAssistant

IR_POWER = "button.miir_cn_ir_2102915700556705793_ir01_turn_on_a_2_5"
TV_ENTITY = "media_player.living_room_tv"
HELPER_START = "sh /data/local/tmp/xiaoqi-tv-helper.sh start"
QIYI = "com.tcl.qiyiguo"
QIYI_ACTION = "com.gala.video.mediasession.custom.action."
# iQiyi seeks 6-9 s per LEFT/RIGHT press, more when pressed in a row.
SEEK_STEP_S = 8
IR_WAKE_S = 45
# Buttons that send what was typed (browser address bar, Bing, app search boxes), as _norm gives them.
SUBMIT_LABELS = {"搜索", "搜索网页", "search", "前往", "go", "确定", "完成", "进入"}

# Spoken names that are not part of the launcher label.
APP_ALIASES = {
    "爱奇艺": "银河奇异果", "奇异果": "银河奇异果", "iqiyi": "银河奇异果",
    "网易云": "网易云音乐", "youtube": "YT TV", "油管": "YT TV", "苹果音乐": "Apple Music",
    "浏览器": "BrowseHere浏览器", "相册": "智能相册", "少儿": "雷咚咚少儿", "天气": "天气预报",
    "直播": "有线频道", "电视直播": "有线频道", "应用市场": "应用商店",
}


def _spoken(hms):
    """'00:03:05' -> '3分05秒', '01:02:03' -> '1小时2分03秒'."""
    hours, minutes, seconds = (int(part) for part in hms.split(":"))
    return (f"{hours}小时" if hours else "") + (f"{minutes}分" if hours or minutes else "") + f"{seconds:02d}秒"


class TVError(Exception):
    """Something the user should hear about, in Chinese."""


def _norm(text):
    return re.sub(r"[\s\W_]+", "", str(text)).lower()


def _clock(ms):
    seconds = int(ms // 1000)
    hours, rest = divmod(seconds, 3600)
    return (f"{hours}:" if hours else "") + f"{rest // 60:02d}:{rest % 60:02d}"


class TV:
    def __init__(self, helper_url=None, helper_token=None, ha=None, clock=time):
        self.url = (helper_url or os.environ.get("TV_HELPER_URL", "http://192.168.5.9:8765")).rstrip("/")
        self.token = helper_token if helper_token is not None else os.environ.get("TV_HELPER_TOKEN", "")
        self.host = urlsplit(self.url).hostname
        self._ha = ha
        self.clock = clock
        self._apps = None

    @property
    def ha(self):
        if self._ha is None:
            self._ha = HomeAssistant()
        return self._ha

    # -- transport -------------------------------------------------------------------------

    def helper(self, method, path, body=None, timeout=8):
        """One helper call; None when the helper does not answer (TV off, or helper not running)."""
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read() or b"{}")
            except ValueError:
                return {"ok": False, "error": f"HTTP {e.code}"}
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def call(self, method, path, body=None, timeout=8):
        """A helper call that must succeed."""
        result = self.helper(method, path, body, timeout)
        if result is None:
            raise TVError("电视助手没有响应")
        return result

    def reachable(self, tries=3):
        """Whether the TV is on the network (adb port), asked a few times so one lost packet
        never makes a running TV look off: that would make power_on toggle it off by IR."""
        for attempt in range(tries):
            try:
                # On the LAN a TV that is on answers in milliseconds.
                with socket.create_connection((self.host, 5555), timeout=1.0):
                    return True
            except OSError:
                if attempt + 1 < tries:
                    self.clock.sleep(0.5)
        return False

    def wait(self, check, timeout, step=0.5):
        """Polls check() until it returns something truthy or timeout seconds pass."""
        deadline = self.clock.monotonic() + timeout
        while True:
            value = check()
            if value or self.clock.monotonic() >= deadline:
                return value
            self.clock.sleep(step)

    # -- power ---------------------------------------------------------------------------------

    def status(self):
        """The helper's status; None when the TV is off or the helper does not run. One quick
        probe first: a TV in standby is off the network and would hold the whole HTTP timeout."""
        if not self.reachable(tries=1):
            return None
        return self.helper("GET", "/status", timeout=4)

    def start_helper(self):
        """Starts the helper through Home Assistant's adb (after a reboot); its status, or None."""
        try:
            self.ha.call("androidtv", "adb_command", {"entity_id": TV_ENTITY, "command": HELPER_START})
        except HAError:
            return None
        return self.wait(self.status, 10)

    def ensure_on(self):
        """Turns the TV on if needed; returns (status, was_off)."""
        status = self.status()
        if status and status.get("ok"):
            if not status.get("screen_on"):
                self.call("POST", "/key", {"key": "WAKEUP"})
            return status, False
        if self.reachable():
            status = self.start_helper()
            if not status:
                raise TVError("电视开着，但电视助手启动不了")
            return status, False
        self.ha.call("button", "press", {"entity_id": IR_POWER})
        # The TV is back on WiFi in 4 s, but after a recent standby the mini PC (Windows) found it
        # only 15-75 s later (2026-10-23): it backs off its ARP retries for an unreachable host.
        # Giving up early invites a second power press, which turns the starting TV off again.
        if not self.wait(lambda: self.reachable(tries=1), IR_WAKE_S, step=1):
            raise TVError(f"已经发了红外开机，但电视过了{IR_WAKE_S}秒还没连上网络")
        status = self.wait(self.status, 8) or self.start_helper()
        if not status:
            raise TVError("电视开了，但电视助手启动不了")
        return status, True

    def power(self, on):
        if on:
            _, was_off = self.ensure_on()
            return {"ok": True, "say": "电视打开了。" if was_off else "电视已经开着。"}
        status = self.status()
        if status and status.get("ok"):
            self.call("POST", "/key", {"key": "SLEEP"})
        elif self.reachable():
            self.ha.call("androidtv", "adb_command", {"entity_id": TV_ENTITY, "command": "input keyevent SLEEP"})
        else:
            return {"ok": True, "say": "电视已经关着。"}
        return {"ok": True, "say": "电视关了。"}

    # -- apps ----------------------------------------------------------------------------------

    def apps(self):
        if self._apps is None:
            self._apps = self.call("GET", "/apps").get("apps", [])
        return self._apps

    def app_label(self, package):
        # TCL's launcher and its art-frame screensaver ("艺术画框" in the app list).
        special = {"com.tcl.cyberui": "主页", "com.tcl.appreciate.art": "屏保"}
        if package in special:
            return special[package]
        for app in self.apps():
            if app["package"] == package:
                return app["label"]
        return package

    def find_app(self, name):
        want = _norm(APP_ALIASES.get(_norm(name), name))
        apps = self.apps()
        for test in (lambda label: label == want, lambda label: want in label, lambda label: label and label in want):
            for app in apps:
                if test(_norm(app["label"])):
                    return app
        return None

    def open_app(self, name):
        # The app list comes from the TV, so it has to be on first.
        self.ensure_on()
        app = self.find_app(name)
        if app is None:
            raise TVError(f"电视上没有“{name}”这个应用")
        result = self.call("POST", "/launch", {"package": app["package"]})
        if not result.get("ok"):
            raise TVError(f"{app['label']}打不开：{result.get('error')}")
        self.wait(lambda: (self.status() or {}).get("package") == app["package"], 10)
        return {"ok": True, "app": app["label"], "say": f"打开{app['label']}了。"}

    # -- what is on --------------------------------------------------------------------------

    def screen(self, limit=60):
        return self.call("GET", f"/screen?limit={limit}")

    def sessions(self):
        return self.call("GET", "/media").get("sessions", [])

    def playing(self):
        """The media session that is playing (else the first one), or None."""
        sessions = self.sessions()
        for session in sessions:
            if session.get("state") == "playing":
                return session
        return sessions[0] if sessions else None

    def episode_on_screen(self):
        """'第3集' from iQiyi's title bar while it shows, else ''."""
        for item in self.screen(40).get("items", []):
            found = re.search(r"第\d+集", item["text"])
            if found:
                return found.group(0)
        return ""

    def position_on_screen(self):
        """'00:03:05' from iQiyi's progress bar while it shows, else ''."""
        for item in self.screen(40).get("items", []):
            if re.fullmatch(r"\d\d:\d\d:\d\d", item["text"]):
                return item["text"]
        return ""

    def describe(self):
        status = self.status()
        if not status or not status.get("ok"):
            return {"ok": True, "power": "on" if self.reachable() else "off"}
        result = {"ok": True, "power": "on", "app": self.app_label(status.get("package", ""))}
        session = self.playing()
        if session and session.get("state") in ("playing", "paused"):
            result["media"] = {
                "app": self.app_label(session["package"]), "state": session["state"],
                "title": session.get("title", ""), "position": _clock(session.get("position_ms", 0)),
                "duration": _clock(session.get("duration_ms", 0)),
            }
        volume = self.helper("GET", "/volume", timeout=4)
        if volume and volume.get("ok"):
            result["volume"] = 0 if volume.get("muted") else volume.get("level")
        return result

    # -- iQiyi ---------------------------------------------------------------------------------

    def _search_page(self):
        screen = self.screen(80)
        labels = [item["text"] for item in screen.get("items", [])]
        return screen if any("全部结果" in label for label in labels) else None

    def play(self, title, episode=0):
        """Searches iQiyi for title and plays the exact match; without one, returns the results."""
        self.ensure_on()
        playinfo = json.dumps({"version": "1.0", "keyword": title}, ensure_ascii=False)
        result = self.call("POST", "/intent", {
            "action": "com.gitvdemo.video.action.ACTION_SEARCHRESULT", "package": QIYI,
            "extras": {"playInfo": playinfo}})
        if not result.get("ok"):
            raise TVError("奇异果搜索打不开")
        page = self.wait(self._search_page, 12)
        if not page:
            raise TVError("奇异果没有打开搜索结果")
        items = page.get("items", [])
        if not any(item["text"] == "播放" for item in items):
            # No exact match: list the result cards (right of the menu, below the tabs).
            found = list(dict.fromkeys(item["text"] for item in items
                                       if item["bounds"][0] >= 300 and item["bounds"][1] >= 200 and len(item["text"]) >= 2))
            return {"ok": False, "found": found[:8],
                    "say": f"奇异果里没有找到《{title}》" + (f"，有{'、'.join(found[:4])}。" if found else "。")}
        click = self.call("POST", "/click", {"text": "播放"})
        if not click.get("ok"):
            raise TVError("点不了播放")
        session = self.wait(lambda: next((s for s in self.sessions()
                                          if s["package"] == QIYI and s.get("state") == "playing"), None), 20)
        if not session:
            raise TVError(f"《{title}》没有播起来")
        name = session.get("title") or title
        if not episode:
            return {"ok": True, "title": name, "say": f"开始播放《{name}》。"}
        # iQiyi resumes the last episode watched and ignores requests while its player starts.
        want = f"第{episode}集"
        self.clock.sleep(2)
        for _ in range(2):
            self.media("episode", episode)
            if self.wait(lambda: self.episode_on_screen() == want, 8):
                return {"ok": True, "title": name, "episode": want, "say": f"开始播放《{name}》{want}。"}
        return {"ok": True, "title": name, "episode": self.episode_on_screen() or "",
                "say": f"开始播放《{name}》了，但没能确认切到{want}。"}

    # -- playback ------------------------------------------------------------------------------

    def media(self, action, value=0):
        session = self.playing()
        if session is None:
            raise TVError("电视上没有在播放的节目")
        package = session["package"]
        if action == "episode" and (package != QIYI or value < 1):
            raise TVError("要说第几集" if package == QIYI else "这个应用不能直接选集")
        if package == QIYI and action in ("next", "previous", "episode"):
            extras = {"index": int(value)} if action == "episode" else {"action": "next" if action == "next" else "prev"}
            body = {"action": "custom", "package": package, "name": QIYI_ACTION + "SELECT_EPISODE", "extras": extras}
        elif action in ("forward", "rewind"):
            # iQiyi ignores seek requests from other apps; the remote's LEFT/RIGHT work.
            presses = max(1, min(30, math.ceil((value or 30) / SEEK_STEP_S)))
            self.call("POST", "/key", {"key": "RIGHT" if action == "forward" else "LEFT", "repeat": presses,
                                       "interval_ms": 300})
            word = "快进" if action == "forward" else "快退"
            at = self.position_on_screen() if package == QIYI else ""
            return {"ok": True, "position": at, "say": f"{word}到{_spoken(at)}了。" if at else f"{word}了。"}
        else:
            body = {"action": {"resume": "play"}.get(action, action), "package": package}
        result = self.call("POST", "/media", body)
        if not result.get("ok"):
            raise TVError(result.get("error") or "操作没有成功")
        say = {"pause": "暂停了。", "resume": "继续播放。", "toggle": "好的。", "stop": "停止播放了。",
               "next": "下一集。", "previous": "上一集。", "episode": f"切到第{value}集。"}.get(action, "好的。")
        return {"ok": True, "say": say}

    def volume(self, level=None, change=None, mute=None):
        body = {}
        if mute is not None:
            body["mute"] = bool(mute)
        if level is not None:
            body["level"] = int(level)
        elif change:
            body["delta"] = int(change)
        if not body:
            result = self.call("GET", "/volume")
        else:
            result = self.call("POST", "/volume", body)
        if not result.get("ok"):
            raise TVError(result.get("error") or "音量没有调成")
        if result.get("muted"):
            return {"ok": True, "volume": 0, "muted": True, "say": "电视静音了。"}
        return {"ok": True, "volume": result.get("level"), "say": f"电视音量{result.get('level')}。"}

    # -- generic -------------------------------------------------------------------------------

    def click(self, text, index=0):
        result = self.call("POST", "/click", {"text": text, "index": index})
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "on_screen": result.get("on_screen", [])}
        return {"ok": True, "clicked": result.get("clicked")}

    def type(self, text, submit=True):
        """Puts text into the input field on screen (the focused one, else the first), replacing
        what is there. submit runs the field's own search/go action; web pages ignore that (Bing's
        search box, BrowseHere's address bar), so then the search button beside the field is
        clicked. Sent means the page changed; the texts of the new one come back as `page`."""
        before = self._page() if submit else None
        result = self.call("POST", "/type", {"text": text, "submit": submit})
        if not result.get("ok"):
            raise TVError(result.get("error") or "输入没有成功")
        if not submit:
            return {"ok": True, "typed": text, "say": f"输入了“{text}”。"}
        page = self.wait(lambda: self._moved_on(before), 2)
        say = f"输入了“{text}”并确认了。"
        if not page:
            button = self._submit_button(text)
            if not button or not self.call("POST", "/click", {"text": button[0], "index": button[1]}).get("ok"):
                return {"ok": True, "typed": text, "submitted": False,
                        "say": f"输入了“{text}”，但没找到能确认的按钮，看一下屏幕再点。"}
            page = self.wait(lambda: self._moved_on(before), 4)
            if not page:
                return {"ok": True, "typed": text, "submitted": False,
                        "say": f"输入了“{text}”，点了“{button[0]}”，但页面没有变化。"}
            say = f"输入了“{text}”，点了“{button[0]}”。"
        # A web page is blank while it loads.
        labels = page[1] or self.wait(lambda: self._page()[1], 6)
        return {"ok": True, "typed": text, "submitted": True, "page": [label[:40] for label in labels[:30]],
                "say": say if labels else say + "页面还在加载。"}

    def _page(self):
        """(app, the texts on screen other than input fields)."""
        screen = self.screen(150)
        return screen.get("package"), [i["text"] for i in screen.get("items", []) if i["text"] and not i.get("editable")]

    def _moved_on(self, before):
        """The page on screen once it is no longer before (another app, or most of its texts gone,
        as while a web page loads), else None. Suggestions under a field only add texts."""
        app, labels = self._page()
        old = set(before[1])
        if app != before[0] or len(old & set(labels)) * 2 < len(old):
            return app, labels
        return None

    def _submit_button(self, text):
        """(label, index for /click) of the search/go button on the row of the field holding text
        (else the focused field, else the first), nearest first."""
        items = self.screen(150).get("items", [])
        field = min((i for i in items if i.get("editable")),
                    key=lambda i: (i["text"] != text, not i.get("focused")), default=None)
        if field is None:
            return None
        left, top, right, bottom = field["bounds"]
        found = []
        for item in items:
            label = item["text"].strip()
            if _norm(label) not in SUBMIT_LABELS:
                continue
            x0, y0, x1, y1 = item["bounds"]
            if x0 >= left and top - 40 <= (y0 + y1) / 2 <= bottom + 40:
                index = sum(_norm(other["text"]) == _norm(label) for other in items[:items.index(item)])
                found.append((abs(x0 - right), label, index))
        return min(found)[1:] if found else None

    def keys(self, keys):
        result = self.call("POST", "/key", {"keys": list(keys), "interval_ms": 250})
        if not result.get("ok"):
            raise TVError(result.get("error") or "按键没有成功")
        return {"ok": True, "pressed": result.get("pressed")}
