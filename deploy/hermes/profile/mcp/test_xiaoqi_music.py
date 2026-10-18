"""Unit tests for the xiaoqi_music MCP server (a fake bridge on localhost, no speaker).

    cd deploy/hermes/profile/mcp && python3 -m unittest test_xiaoqi_music
"""

import json
import os
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


class _Server:
    def __init__(self, name, instructions=""):
        self.name = name

    def tool(self):
        return lambda fn: fn


sys.modules.setdefault("mcp", types.ModuleType("mcp"))
sys.modules.setdefault("mcp.server", types.ModuleType("mcp.server"))
sys.modules.setdefault("mcp.server.mcpserver", types.SimpleNamespace(MCPServer=_Server))

from xiaoqi_music import server as music  # noqa: E402


class FakeBridge(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def reply(self, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        url = urlsplit(self.path)
        FakeBridge.calls.append(("GET", url.path, parse_qs(url.query)))
        if url.path == "/music/artists":
            return self.reply([{"artist": "梁静茹", "songs": 16}])
        if url.path == "/music/search":
            return self.reply({"kind": "track", "title": "勇气"})
        self.reply({"playing": True})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeBridge.calls.append(("POST", self.path, body))
        self.reply({"handled": True, "say": "好的。"})


class MusicToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeBridge)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        FakeBridge.calls = []
        env = patch.dict(os.environ, {"MUSIC_URL": f"http://127.0.0.1:{self.httpd.server_address[1]}/"})
        env.start()
        self.addCleanup(env.stop)

    def test_tools_call_the_bridge(self):
        self.assertEqual(music.music_artists(), {"ok": True, "artists": [{"artist": "梁静茹", "songs": 16}]})
        self.assertEqual(music.music_search("梁静茹的勇气")["title"], "勇气")
        self.assertEqual(music.music_play("梁静茹")["say"], "好的。")
        music.music_control("next")
        self.assertTrue(music.music_status()["playing"])
        self.assertEqual(FakeBridge.calls[1], ("GET", "/music/search", {"q": ["梁静茹的勇气"]}))
        self.assertEqual(FakeBridge.calls[2], ("POST", "/music/play", {"query": "梁静茹"}))
        self.assertEqual(FakeBridge.calls[3], ("POST", "/music/control", {"action": "next"}))

    def test_a_bridge_that_is_down_is_reported(self):
        with patch.dict(os.environ, {"MUSIC_URL": "http://127.0.0.1:9"}):
            result = music.music_play("梁静茹")
        self.assertFalse(result["ok"])
        self.assertIn("音乐服务不可用", result["error"])


if __name__ == "__main__":
    unittest.main()
