"""HTTP for the music: the speaker fetches songs here, and the xiaozhi
provider and Hermes' music tool send requests here.

    GET  /music/track/<id>.<ext>[?start=<s>]  the file (Range supported);
                                              start: an MP3 from that second
    GET  /music/status                        what is playing
    GET  /music/search?q=<text>               what a request would play
    GET  /music/artists                       singers and their song counts
    POST /music/command {"text"}              a spoken request -> {"handled", "say", "end"}
    POST /music/play    {"query"}             play what the query finds
    POST /music/control {"action"}            stop, next, prev, resume
    POST /music/rescan                        read the folder again
"""

import json
import os
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

CHUNK = 64 * 1024
CONTENT_TYPES = {"mp3": "audio/mpeg", "flac": "audio/flac", "wav": "audio/wav", "m4a": "audio/mp4"}
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def track_span(track, size, start_s):
    """Bytes [begin, end) to send for `track` played from `start_s` seconds.

    MP3 frames stand alone, so a song resumes by sending the frames from
    about that point on (the player finds the next frame header)."""
    if (start_s > 0 and track.ext == "mp3" and track.duration and track.audio_start is not None
            and track.audio_end):
        span = track.audio_end - track.audio_start
        return track.audio_start + int(span * min(start_s / track.duration, 0.99)), track.audio_end
    return 0, size


def byte_range(header, length):
    """(first, last) byte of a Range header within `length`, None for all, False if unsatisfiable."""
    match = RANGE.match((header or "").strip())
    if not match or length <= 0:
        return None
    first, last = match.groups()
    if not first:
        if not last:
            return None
        first, last = max(0, length - int(last)), length - 1
    else:
        first, last = int(first), min(int(last), length - 1) if last else length - 1
    if first >= length or first > last:
        return False
    return first, last


class MusicHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service):
        self.service = service
        super().__init__(address, MusicRequestHandler)


class MusicRequestHandler(BaseHTTPRequestHandler):
    server_version = "XiaoqiMusic/1.0"

    def log_message(self, fmt, *args):
        pass  # the speaker fetches often; requests are logged by the player

    @property
    def service(self):
        return self.server.service

    def do_HEAD(self):
        self._route(head=True)

    def do_GET(self):
        self._route(head=False)

    def _route(self, head):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path.startswith("/music/track/"):
            return self._track(unquote(url.path.rsplit("/", 1)[-1]), query, head)
        if url.path == "/music/status":
            return self._json(self.service.status(), head=head)
        if url.path == "/music/search":
            return self._json(self.service.search(query.get("q", [""])[0]), head=head)
        if url.path == "/music/artists":
            return self._json(self.service.artists(), head=head)
        self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        try:
            if path == "/music/command":
                result = self.service.command(str(body.get("text") or ""))
            elif path == "/music/play":
                result = self.service.play_query(str(body.get("query") or ""))
            elif path == "/music/control":
                result = self.service.control(str(body.get("action") or ""))
            elif path == "/music/rescan":
                result = self.service.rescan()
            else:
                return self.send_error(404)
        except Exception as error:
            print(f"❌ 音乐请求出错: {path} {body}")
            traceback.print_exc()
            return self._json({"error": f"{type(error).__name__}: {error}"}, 500)
        self._json(result)

    def _json(self, data, status=200, head=False):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head:
            self.wfile.write(payload)

    def _track(self, name, query, head):
        track = self.service.library.by_id.get(name.split(".", 1)[0])
        if not track:
            return self.send_error(404)
        path = self.service.library.path_of(track)
        try:
            size = os.path.getsize(path)
            start_s = float(query.get("start", ["0"])[0] or 0)
        except (OSError, ValueError):
            return self.send_error(404)
        begin, end = track_span(track, size, start_s)
        length = end - begin
        wanted = byte_range(self.headers.get("Range"), length)
        if wanted is False:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{length}")
            self.end_headers()
            return
        first, last = wanted or (0, length - 1)
        self.send_response(206 if wanted else 200)
        self.send_header("Content-Type", CONTENT_TYPES.get(track.ext, "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(last - first + 1))
        if wanted:
            self.send_header("Content-Range", f"bytes {first}-{last}/{length}")
        self.end_headers()
        if head:
            return
        try:
            with open(path, "rb") as f:
                f.seek(begin + first)
                remaining = last - first + 1
                while remaining > 0:
                    chunk = f.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # the player stopped or skipped


def serve(service, port):
    server = MusicHTTPServer(("0.0.0.0", port), service)
    threading.Thread(target=server.serve_forever, name="music-http", daemon=True).start()
    return server
