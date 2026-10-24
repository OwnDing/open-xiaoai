"""MCP server "tv_control": the living-room TCL TV (Android) for 小七.

    python -m tv_control.server    # stdio, started by Hermes (mcp_servers)

Power, apps, iQiyi (银河奇异果) search and playback, volume, and the screen itself for anything
else. See tv.py for how the TV is reached; needs TV_HELPER_URL, TV_HELPER_TOKEN, HASS_URL and
HASS_TOKEN.
"""

import sys
from typing import Any, Literal, Optional

from mcp.server.mcpserver import MCPServer

from home_rules.ha import HAError

from .tv import TV, TVError

INSTRUCTIONS = (
    "The living-room TV (TCL, Android): turn it on/off, open apps, play shows and films in "
    "iQiyi (银河奇异果), control playback and volume, read and click what is on screen."
)
server = MCPServer("tv_control", instructions=INSTRUCTIONS)
_tv = None


def _run(action, *args, **kwargs) -> dict[str, Any]:
    global _tv
    if _tv is None:
        _tv = TV()
    try:
        return action(_tv, *args, **kwargs)
    except TVError as e:
        return {"ok": False, "error": str(e), "say": f"{e}。"}
    except HAError as e:
        return {"ok": False, "error": f"Home Assistant: {e}", "say": "电视控制出错了。"}


@server.tool()
def tv_status() -> dict[str, Any]:
    """Whether the TV is on, which app is in front, what is playing (title, playing/paused,
    position) and the volume (0-100)."""
    return _run(TV.describe)


@server.tool()
def tv_power(on: bool) -> dict[str, Any]:
    """Turn the TV on (打开电视) or off (关电视). Safe to call when it already is: the speaker's
    IR is only used when the TV is really off. Other tv_ tools turn it on themselves."""
    return _run(TV.power, on)


@server.tool()
def tv_open_app(app: str) -> dict[str, Any]:
    """Open an app on the TV: 奇异果/爱奇艺, 网易云音乐, Apple Music, YouTube, 浏览器, 相册, 设置,
    应用商店, 有线频道 ... Turns the TV on first if needed."""
    return _run(TV.open_app, app)


@server.tool()
def tv_play(title: str, episode: int = 0) -> dict[str, Any]:
    """Play a show or film in iQiyi (银河奇异果): searches title and plays the exact match;
    episode (第几集, from 1) picks an episode of a series, 0 keeps where it was.
    ok=false with `found` lists what iQiyi has instead: read a few and ask which one;
    then tv_click the chosen title on the result page."""
    return _run(TV.play, title, episode)


@server.tool()
def tv_playback(action: Literal["pause", "resume", "stop", "next", "previous", "episode", "forward", "rewind"],
                value: int = 0) -> dict[str, Any]:
    """Control what the TV is playing: pause 暂停, resume 继续, stop 停止, next/previous 下一集/上一集,
    episode (value = episode number, iQiyi only), forward/rewind 快进/快退 (value = seconds, roughly)."""
    return _run(TV.media, action, value)


@server.tool()
def tv_volume(level: Optional[int] = None, change: Optional[int] = None,
              mute: Optional[bool] = None) -> dict[str, Any]:
    """TV volume, 0-100: level sets it (音量调到20), change raises or lowers it (大点声 +5,
    小点声 -5), mute true/false (静音/取消静音). No arguments: read it."""
    return _run(TV.volume, level, change, mute)


@server.tool()
def tv_screen() -> dict[str, Any]:
    """The texts on the TV screen in reading order, the focused one, and the app. Use it to
    answer what is on screen and before tv_click or tv_keys in an unfamiliar page."""
    return _run(lambda tv: tv.screen(60))


@server.tool()
def tv_click(text: str, index: int = 0) -> dict[str, Any]:
    """Click the item on screen labelled text (a button, menu entry or title; index picks the
    n-th match). ok=false lists what is on screen."""
    return _run(TV.click, text, index)


@server.tool()
def tv_type(text: str, submit: bool = True) -> dict[str, Any]:
    """Type text into the input field on the TV screen (browser address bar: a site such as
    bing.com; a search box: the words), replacing what is in it. Open the field first: tv_click
    "搜索或输入 URL" in BrowseHere, or the app's search box. submit=true then sends it (go/search)
    and returns the texts of the page it lands on as `page`: no tv_screen needed after it.
    submitted=false means the page did not change: look at the screen before saying it searched."""
    return _run(TV.type, text, submit)


@server.tool()
def tv_keys(keys: list[str]) -> dict[str, Any]:
    """Press remote keys in order: UP DOWN LEFT RIGHT OK BACK HOME MENU, VOLUME_UP VOLUME_DOWN,
    MEDIA_PLAY_PAUSE, digits 0-9. For moving around pages; prefer tv_click when the item has text.
    Never for typing: while an on-screen keyboard is up, OK and ENTER type its highlighted key
    (a stray "k"); use tv_type."""
    return _run(TV.keys, keys)


def main():
    print("tv_control: ready", file=sys.stderr)
    server.run("stdio")


if __name__ == "__main__":
    main()
