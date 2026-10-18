"""MCP server "xiaoqi_music": songs from the local library, played on the living-room speaker.

    python -m xiaoqi_music.server    # stdio, started by Hermes (mcp_servers)

The open-xiaoai bridge plays them (MUSIC_URL, e.g. http://host.docker.internal:4400).
Plain requests ("播放梁静茹的勇气", "暂停", "下一首") never reach the model: the
xiaozhi provider hands them to the bridge itself. These tools are for the rest
("放点安静的歌", "来几首英文歌") and for scheduled music ("明早七点放音乐").
"""

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import quote
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = (
    "The household's own music library (Chinese pop and some English songs), played on the "
    "living-room Xiaomi speaker: list singers, search, play, stop, skip."
)
server = MCPServer("xiaoqi_music", instructions=INSTRUCTIONS)


def _url():
    return os.environ.get("MUSIC_URL", "http://host.docker.internal:4400").rstrip("/")


def _request(path, body=None, timeout=20):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(_url() + path, data=data,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "error": f"音乐服务不可用：{e}"}


@server.tool()
def music_artists() -> dict[str, Any]:
    """Every singer in the library with how many songs, most first.

    Use it to choose music for a vague request ("放点英文歌", "来点安静的"):
    pick singers you know fit, then music_play one of them."""
    result = _request("/music/artists")
    return {"ok": True, "artists": result} if isinstance(result, list) else result


@server.tool()
def music_search(query: str) -> dict[str, Any]:
    """What music_play(query) would play: kind (track, artist, all, none), the song or
    singer found, missing_title when only the singer was found, and the first songs."""
    return _request(f"/music/search?q={quote(query)}")


@server.tool()
def music_play(query: str = "") -> dict[str, Any]:
    """Play from the library on the speaker and keep playing that singer's songs.

    query: a singer ("梁静茹"), a song ("勇气") or both ("梁静茹的勇气"); "" plays
    everything shuffled. Names may be homophones or traditional characters.
    Reply with the returned `say` (or a few words of your own); handled=false
    means nothing was found or played: tell the user."""
    return _request("/music/play", {"query": query})


@server.tool()
def music_control(action: Literal["stop", "next", "prev", "resume"]) -> dict[str, Any]:
    """stop (暂停/停止), next (下一首), prev (上一首) or resume (继续播放) the music."""
    return _request("/music/control", {"action": action})


@server.tool()
def music_status() -> dict[str, Any]:
    """Whether music is playing, the current song (title, artist, album) and the position;
    library_tracks is how many songs the library has ("曲库有多少首歌")."""
    return _request("/music/status")


def main():
    print("xiaoqi_music: ready", file=sys.stderr)
    server.run("stdio")


if __name__ == "__main__":
    main()
