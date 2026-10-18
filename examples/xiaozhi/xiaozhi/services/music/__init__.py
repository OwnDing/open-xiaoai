"""小七's music: songs from a local folder, played on the speaker.

The library (library.py) is read from the folder mounted at
`music.library`; the speaker fetches each song from the bridge over HTTP
(server.py) and plays it with its own player (player.py). Requests arrive
from the xiaozhi provider ("播放梁静茹的勇气", "暂停") and from Hermes' music
tool; "你好小七" turns the music down until the conversation ends.
"""

import asyncio
import os
import threading
import time

from xiaozhi.ref import set_music
from xiaozhi.services.audio.health import HEALTH
from xiaozhi.services.music import server
from xiaozhi.services.music.library import MusicLibrary
from xiaozhi.services.music.player import NOT_HANDLED, MusicError, MusicPlayer, MusicSettings, shell_results


class MusicService:
    def __init__(self, settings, loop, run_shell, session_active=lambda: False,
                 end_after_reply=None, names=()):
        self.settings = settings
        self.loop = loop
        self.library = MusicLibrary(settings.library, settings.formats, settings.exclude_dirs,
                                    settings.aliases, settings.index_path)
        self.player = MusicPlayer(self.library, shell_results(run_shell), settings, session_active)
        self.end_after_reply = end_after_reply
        self.names = tuple(names)

    def start(self):
        server.serve(self, self.settings.http_port)
        threading.Thread(target=self._scan_loop, name="music-scan", daemon=True).start()
        asyncio.run_coroutine_threadsafe(self.player.watchdog(), self.loop)
        print(f"🎵 音乐服务已启动：曲库 {self.settings.library}，端口 {self.settings.http_port}")

    def _scan_loop(self):
        while True:
            self.rescan()
            time.sleep(max(60.0, float(self.settings.rescan_minutes) * 60))

    def rescan(self):
        before = len(self.library.tracks) if self.library.ready else None
        started = time.monotonic()
        try:
            count = self.library.scan()
        except Exception as error:
            print(f"❌ 读取曲库失败: {error}")
            HEALTH.emit("music_scan_error", error=str(error)[:200])
            return {"error": str(error)}
        if count != before:
            print(f"🎵 曲库共 {count} 首（{time.monotonic() - started:.1f}s）")
            HEALTH.emit("music_scan", tracks=count, seconds=round(time.monotonic() - started, 1))
        return {"tracks": count}

    def _call(self, coro, timeout=20):
        """Run on the bridge's loop from an HTTP thread."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def _answered(self, text, result):
        if result.get("handled"):
            print(f"🎵 音乐请求: {text} -> {result.get('say')!r}")
            if result.get("end") and self.end_after_reply:
                # The conversation ends once this is answered, and the
                # music comes back to full volume.
                self.end_after_reply()
        return result

    # ---- requests -------------------------------------------------------

    def command(self, text):
        """A spoken request, from the xiaozhi provider."""
        return self._answered(text, self._call(self.player.command(text, self.names)))

    def play_query(self, query):
        """Play what `query` finds ("" plays everything), for Hermes' tool."""
        if not self.library.ready:
            return {"handled": False, "error": "曲库还在整理"}
        found = self.library.find(query)
        if found.kind == "none":
            return {**NOT_HANDLED, "error": f"曲库里没有{query}"}

        async def play():
            try:
                return await self.player.play_found(found)
            except MusicError as error:
                return {"handled": False, "error": str(error)}

        result = self._answered(query, self._call(play()))
        return {**result, "status": self.player.status()}

    def control(self, action):
        """stop, next, prev or resume, for Hermes' tool."""
        actions = {
            "stop": self.player.stop,
            "next": lambda: self.player.skip(1),
            "prev": lambda: self.player.skip(-1),
            "resume": self.player.resume,
        }
        if action not in actions:
            return {"handled": False, "error": f"unknown action {action!r}"}
        if action != "stop" and not self.player.queue:
            return {"handled": False, "error": "没有可以继续的歌单，先点歌"}

        async def run():
            try:
                await actions[action]()
                return {"handled": True}
            except MusicError as error:
                return {"handled": False, "error": str(error)}

        result = self._call(run())
        if result.get("handled") and self.end_after_reply:
            self.end_after_reply()
        return {**result, "status": self.player.status()}

    def status(self):
        return {**self.player.status(), "library_ready": self.library.ready,
                "library_tracks": len(self.library.tracks)}

    def search(self, query, limit=10):
        found = self.library.find(query, shuffle=lambda tracks: None)
        return {
            "kind": found.kind, "artist": found.artist, "title": found.title,
            "missing_title": found.missing_title, "score": round(found.score, 2),
            "count": len(found.tracks),
            "tracks": [{"title": t.title, "artist": t.artist, "album": t.album}
                       for t in found.tracks[:limit]],
        }

    def artists(self):
        return [{"artist": name, "songs": count} for name, count in self.library.artists()]

    # ---- conversation ---------------------------------------------------

    async def on_wake(self):
        await self.player.duck()

    async def on_session_end(self):
        # An exit cancelled by a new conversation must not bring the music back.
        if not self.player.session_active():
            await self.player.unduck()


def start_music(config, loop, run_shell, session_active, end_after_reply, names=()):
    """The music service, or None when it is off or has no folder."""
    settings = MusicSettings.from_config(config)
    if not settings.enabled:
        return None
    if not os.path.isdir(settings.library):
        print(f"⚠️ 没有找到音乐目录 {settings.library}，不启用音乐")
        return None
    service = MusicService(settings, loop, run_shell, session_active, end_after_reply, names)
    set_music(service)
    service.start()
    return service
