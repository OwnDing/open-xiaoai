"""Plays the library on the speaker, apart from 小七's voice.

The speaker's own miplayer streams each song from the bridge's HTTP server.
It runs as a copy named xqmusic: native TTS stops its clips with
`killall miplayer`, which matches the executable and must not stop the
music. Its ALSA output goes through an extra softvol, "xqmusicvol", on top of
the master volume (a private ALSA config, only for this process). Calling
"你好小七" turns that one down, so the music gets quieter while 小七's
answer keeps its volume.
"""

import asyncio
import json
import random
import re
import shlex
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from xiaozhi.services.audio.health import HEALTH
from xiaozhi.services.music.intent import parse

SPEAKER_DIR = "/tmp/xq-music"
# The softvol spans 51 dB in 255 steps.
STEP_DB = 51 / 255
# A song that ends this soon failed to play (bad file, no network).
QUICK_FAIL_S = 3.0
MAX_FAILURES = 3
# One wait on the speaker covers this long; then it is asked again.
WAIT_S = 30

SETUP = r"""
d=/tmp/xq-music
mkdir -p $d && cd $d || exit 1
[ -x xqmusic ] || cp /usr/bin/miplayer xqmusic
if [ ! -s alsa.conf ]; then
  sed 's#"/etc/asound.conf"#"/tmp/xq-music/asound.conf"#' /usr/share/alsa/alsa.conf > alsa.conf.new
  { cat /etc/asound.conf; cat <<'EOF'

# xiaoqi music: its own volume on top of the master volume
pcm.!default {
    type plug
    slave.pcm "xq_music"
}
pcm.xq_music {
    type softvol
    slave.pcm "Playback"
    control {
        name "xqmusicvol"
        card 0
    }
    min_dB -51.0
    max_dB 0.0
}
EOF
  } > asound.conf && mv alsa.conf.new alsa.conf
fi
amixer cget name=xqmusicvol >/dev/null 2>&1 || head -c 3840 /dev/zero | ALSA_CONFIG_PATH=$d/alsa.conf aplay -q -t raw -f S16_LE -r 48000 -c 2 - 2>/dev/null
"""

START = """
[ -s pid ] && kill $(cat pid) 2>/dev/null
killall xqmusic 2>/dev/null
amixer -q cset name=xqmusicvol {volume}
ALSA_CONFIG_PATH=/tmp/xq-music/alsa.conf ./xqmusic -f {url} >/dev/null 2>&1 </dev/null &
echo $! > pid
echo "pid=$!"
"""

WAIT = """
i=0
while [ $i -lt {seconds} ]; do
  kill -0 {pid} 2>/dev/null || {{ echo ended; exit 0; }}
  sleep 1
  i=$((i+1))
done
echo running
"""

STOP = """
cd /tmp/xq-music 2>/dev/null && [ -s pid ] && kill $(cat pid) 2>/dev/null
killall xqmusic 2>/dev/null
rm -f /tmp/xq-music/pid
true
"""

# Where the speaker reaches the bridge (the address its client connected to).
BRIDGE_ADDRESS = (
    "netstat -tn 2>/dev/null | awk '$6==\"ESTABLISHED\" && $5 ~ /:4399$/ {print $5; exit}'"
)

DEFAULT_REPLIES = {
    "play_track": "好的，{artist}的{title}。",
    "play_title": "好的，{title}。",
    "play_artist": "好的，播放{artist}的歌。",
    "play_missing": "没找到{title}，先放{artist}的歌。",
    "play_all": "好的，先放{artist}的{title}。",
    "play_all_title": "好的，先放{title}。",
    "not_found": "曲库里没找到{query}。",
    "now_playing": "这是{artist}的{title}。",
    "now_playing_title": "这首是{title}。",
    "now_playing_album": "这首是{artist}的{title}，出自{album}。",
    "now_playing_no_album": "这首是{artist}的{title}，不知道是哪张专辑。",
    "library_count": "曲库里一共有{count}首歌，{singers}位歌手。",
    "library_artists": "曲库里有{singers}位歌手，歌比较多的有{top}。",
    "library_has_track": "有，{artist}的{title}。",
    "library_has_artist": "有，{artist}的歌有{count}首。",
    "library_missing_title": "有{artist}的歌，但没有{title}。",
    "library_missing": "曲库里没有{query}。",
    "not_ready": "曲库还在整理，等一下再试。",
    "error": "音箱没有响应，等一下再试。",
    "stop": "",
    "next": "",
    "prev": "",
    "resume": "",
    "mode_repeat_one": "好的，单曲循环。",
    "mode_shuffle": "好的，随机播放。",
    "mode_sequence": "好的，顺序播放。",
}
NOT_HANDLED = {"handled": False, "say": "", "end": False}


class MusicError(Exception):
    pass


@dataclass
class MusicSettings:
    enabled: bool = False
    library: str = "/music"
    http_port: int = 4400
    # How the speaker reaches the bridge's HTTP server; empty: the address its
    # client connected to.
    base_url: str = ""
    # How much quieter the music gets while 小七 listens and answers (dB).
    duck_db: float = 20.0
    # The music's own level below 小七's voice (dB, 0: as loud).
    music_db: float = 0.0
    # Ducking ends this long after the wake word at the latest when no
    # conversation follows (the wake prompt plays before one starts).
    duck_hold_s: float = 8.0
    formats: list = field(default_factory=lambda: ["mp3", "flac", "wav", "m4a"])
    exclude_dirs: list = field(default_factory=lambda: ["Podcasts", "Lyrics", "Images", "Album Artwork"])
    aliases: dict = field(default_factory=dict)
    replies: dict = field(default_factory=dict)
    index_path: str = "/app/logs/music-index.json"
    rescan_minutes: float = 10.0

    @classmethod
    def from_config(cls, config):
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (config or {}).items() if k in known})


def shell_results(run_shell):
    """XiaoAI.run_shell answers with the client's JSON ({"stdout", "stderr",
    "exit_code"}); the player reads .stdout like SpeakerManager's results."""
    async def run(script, timeout=10000):
        raw = await run_shell(script, timeout)
        if isinstance(raw, (str, bytes)):
            data = json.loads(raw)
            return SimpleNamespace(stdout=data.get("stdout") or "", stderr=data.get("stderr") or "",
                                   exit_code=data.get("exit_code", 0))
        return raw
    return run


def softvol(db):
    """xqmusicvol's value for `db` below full volume."""
    return max(0, min(255, round(255 - max(0.0, db) / STEP_DB)))


class MusicPlayer:
    def __init__(self, library, run_shell, settings, session_active=lambda: False, clock=time.monotonic):
        self.library = library
        self.run_shell = run_shell
        self.settings = settings
        self.session_active = session_active
        self.clock = clock
        self.replies = {**DEFAULT_REPLIES, **(settings.replies or {})}
        self.queue = []
        self.index = 0
        self.mode = "sequence"
        self.playing = False
        self.pid = None
        self.started_at = None
        self.offset = 0.0
        # Where the current song was when it was stopped.
        self.position = 0.0
        self.ducked = False
        self._duck_until = 0.0
        self._token = 0
        self._failures = 0
        self._base_url = None
        self._lock = asyncio.Lock()
        self._tasks = set()

    # ---- state ----------------------------------------------------------

    @property
    def current(self):
        return self.queue[self.index] if self.queue else None

    def elapsed(self):
        if not self.playing or self.started_at is None:
            return self.position
        return self.offset + self.clock() - self.started_at

    def status(self):
        track = self.current
        return {
            "playing": self.playing,
            "ducked": self.ducked,
            "mode": self.mode,
            "position": round(self.elapsed(), 1),
            "queue_length": len(self.queue),
            "index": self.index,
            "track": None if not track else {
                "id": track.id, "title": track.title, "artist": track.artist,
                "album": track.album, "duration": track.duration, "path": track.path,
            },
        }

    def _level(self, ducked=None):
        ducked = self.ducked if ducked is None else ducked
        return softvol(self.settings.music_db + (self.settings.duck_db if ducked else 0))

    # ---- requests -------------------------------------------------------

    def _reply(self, key, end=True, **fields):
        template = self.replies.get(key, "")
        try:
            say = template.format(**fields)
        except (KeyError, IndexError, ValueError):
            say = template
        return {"handled": True, "say": say, "end": end}

    async def command(self, text, names=()):
        """{"handled", "say", "end"} for what was said; not handled: not about music."""
        intent = parse(text, names)
        if not intent:
            return NOT_HANDLED
        try:
            return await self._command(intent)
        except MusicError as error:
            print(f"❌ 音乐播放失败: {error}")
            HEALTH.emit("music_error", error=str(error)[:200])
            return self._reply("error")

    async def _command(self, intent):
        action = intent.action
        if action == "stop":
            if not (self.playing or intent.explicit or await self._left_playing()):
                return NOT_HANDLED
            await self.stop()
            return self._reply("stop")
        if action in ("next", "prev"):
            if not self.queue:
                return NOT_HANDLED
            await self.skip(1 if action == "next" else -1)
            return self._reply(action)
        if action == "mode":
            if not self.playing:
                if intent.mode != "shuffle":
                    return NOT_HANDLED
                self.mode = "shuffle"
                return await self.play_found(self.library.find(""))
            await self.set_mode(intent.mode)
            return self._reply(f"mode_{intent.mode}")
        if action == "resume":
            if self.playing:
                return self._reply("resume")
            if not self.queue:
                return NOT_HANDLED
            await self.resume()
            return self._reply("resume")
        if action == "library":
            return self._library(intent)
        if action == "now_playing":
            track = self.current
            if not self.playing or not track:
                return NOT_HANDLED
            if intent.mode == "album":
                key = "now_playing_album" if track.album else "now_playing_no_album"
                return self._reply(key, artist=track.artist or "这首歌", title=track.title, album=track.album)
            if track.artist:
                return self._reply("now_playing", artist=track.artist, title=track.title)
            return self._reply("now_playing_title", title=track.title)

        if intent.resume and self.queue:
            # A bare "播放": keep what is on, or go on with what was stopped.
            if not self.playing:
                await self.resume()
            return self._reply("resume")
        if not self.library.ready:
            return self._reply("not_ready", end=False) if intent.music else NOT_HANDLED
        found = self.library.find(intent.query)
        weak = found.kind == "none" or (intent.strict and (found.score < 0.95 or found.missing_title))
        if weak:
            if intent.music:
                return self._reply("not_found", end=False, query=intent.query)
            return NOT_HANDLED
        return await self.play_found(found)

    def _library(self, intent):
        """Answers about the library itself; the conversation goes on after them."""
        if not self.library.ready:
            return self._reply("not_ready", end=False)
        tracks = self.library.tracks
        singers = {}
        for track in tracks:
            if track.artist:
                singers[track.artist] = singers.get(track.artist, 0) + 1
        if intent.mode == "count":
            return self._reply("library_count", end=False, count=len(tracks), singers=len(singers))
        if intent.mode == "artists":
            top = sorted(singers, key=lambda name: -singers[name])[:6]
            return self._reply("library_artists", end=False, singers=len(singers), top="、".join(top))
        found = self.library.find(intent.query)
        # "有没有梁静茹的勇气": the singer is known even if the song is not.
        weak = found.kind in ("none", "all") or (
            intent.strict and found.score < (0.85 if found.missing_title else 0.95))
        if intent.mode == "artist_count" and found.kind == "track":
            weak = True  # "勇气有几首歌" names no singer
        if weak:
            if intent.music:
                return self._reply("library_missing", end=False, query=intent.query)
            return NOT_HANDLED
        if found.kind == "track" and intent.mode == "has":
            return self._reply("library_has_track", end=False, artist=found.artist or "", title=found.title)
        if found.missing_title:
            return self._reply("library_missing_title", end=False, artist=found.artist, title=found.missing_title)
        if found.kind == "track":  # artist_count for a song's singer
            found = self.library.find(found.artist)
        return self._reply("library_has_artist", end=False, artist=found.artist, count=len(found.tracks))

    async def play_found(self, found):
        if not found.tracks:
            return self._reply("not_found", end=False, query="")
        await self.play(found.tracks)
        HEALTH.emit("music_request", kind=found.kind, artist=found.artist, title=found.title,
                    missing=found.missing_title, queue=len(found.tracks))
        if found.kind == "track":
            if found.artist:
                return self._reply("play_track", artist=found.artist, title=found.title)
            return self._reply("play_title", title=found.title)
        if found.kind == "artist":
            if found.missing_title:
                return self._reply("play_missing", artist=found.artist, title=found.missing_title)
            return self._reply("play_artist", artist=found.artist)
        # "随便放首歌": say which one it picked.
        first = found.tracks[0]
        if first.artist:
            return self._reply("play_all", artist=first.artist, title=first.title)
        return self._reply("play_all_title", title=first.title)

    # ---- playback -------------------------------------------------------

    async def play(self, tracks, index=0):
        async with self._lock:
            self.queue = list(tracks)
            self.index = index
            self.position = 0.0
            self._failures = 0
            self._base_url = None  # the bridge's address may have changed
            await self._start(0.0)

    async def skip(self, step):
        async with self._lock:
            if not self.queue:
                return
            self.index = (self.index + step) % len(self.queue)
            self._failures = 0
            await self._start(0.0)

    async def resume(self):
        async with self._lock:
            track = self.current
            if not track:
                return
            offset = self.position if self._resumable(track) else 0.0
            if track.duration and offset > track.duration - 5:
                self.index = (self.index + 1) % len(self.queue)
                offset = 0.0
            self._failures = 0
            await self._start(offset)

    async def stop(self):
        async with self._lock:
            self._token += 1
            if self.playing:
                self.position = self.elapsed()
            self.playing = False
            self.pid = None
            try:
                await self.run_shell(STOP, 5000)
            except Exception as error:
                print(f"⚠️ 停止音乐失败: {error}")
            HEALTH.emit("music_stop", position=round(self.position, 1))
            print("⏹️ 音乐已停止")

    async def set_mode(self, mode, shuffle=random.shuffle):
        """repeat_one keeps the song; sequence and shuffle reorder what is still to come."""
        async with self._lock:
            self.mode = mode
            if mode == "repeat_one" or not self.queue:
                return
            current, rest = self.queue[self.index], self.queue[:self.index] + self.queue[self.index + 1:]
            if mode == "sequence":
                rest.sort(key=lambda t: t.path)
            else:
                shuffle(rest)
            self.queue, self.index = [current, *rest], 0

    async def _left_playing(self):
        """Music the speaker still plays from before the bridge restarted."""
        try:
            result = await self.run_shell("pidof xqmusic", 3000)
        except Exception:
            return False
        return bool((result.stdout or "").strip())

    @staticmethod
    def _resumable(track):
        return (track.ext == "mp3" and track.duration and track.audio_start is not None
                and track.audio_end)

    async def _speaker_base_url(self):
        if self.settings.base_url:
            return self.settings.base_url.rstrip("/")
        if not self._base_url:
            try:
                result = await self.run_shell(BRIDGE_ADDRESS, 5000)
            except Exception as error:
                raise MusicError(f"问音箱桥接地址失败: {error}") from error
            host = (result.stdout or "").strip().rsplit(":", 1)[0]
            if not host:
                raise MusicError("音箱上找不到桥接的地址")
            self._base_url = f"http://{host}:{self.settings.http_port}"
        return self._base_url

    async def _start(self, offset):
        """Play the current song from `offset` seconds (caller holds the lock)."""
        track = self.current
        base = await self._speaker_base_url()
        url = f"{base}/music/track/{track.id}.{track.ext}"
        if offset >= 1:
            url += f"?start={int(offset)}"
        script = SETUP + START.format(volume=self._level(), url=shlex.quote(url))
        self._token += 1
        token = self._token
        try:
            result = await self.run_shell(script, 8000)
        except Exception as error:
            self.playing = False
            raise MusicError(f"启动播放失败: {error}") from error
        match = re.search(r"pid=(\d+)", result.stdout or "")
        if not match:
            self.playing = False
            raise MusicError(f"启动播放失败: {(result.stderr or result.stdout or '').strip()[:200]}")
        self.pid = int(match.group(1))
        self.playing = True
        self.started_at = self.clock()
        self.offset = offset
        self.position = offset
        print(f"🎵 播放: {track.label()} ({track.path}){f' 从 {int(offset)} 秒' if offset >= 1 else ''}")
        HEALTH.emit("music_play", id=track.id, path=track.path, offset=int(offset), index=self.index,
                    queue=len(self.queue), ducked=self.ducked)
        self._spawn(self._watch(token, self.pid, track))

    def _spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _watch(self, token, pid, track):
        """Wait for the song to end on the speaker, then play the next one."""
        while token == self._token:
            try:
                result = await self.run_shell(WAIT.format(seconds=WAIT_S, pid=pid), (WAIT_S + 10) * 1000)
            except Exception:
                await asyncio.sleep(2)  # link hiccup: ask again
                continue
            if token != self._token:
                return
            if "ended" in (result.stdout or ""):
                break
            if track.duration and self.elapsed() > track.duration + 60:
                print(f"⚠️ 歌曲超时未结束，跳到下一首: {track.path}")
                await self.run_shell(STOP, 5000)
                break
        async with self._lock:
            if token != self._token:
                return
            played = self.clock() - self.started_at
            self._failures = self._failures + 1 if played < QUICK_FAIL_S else 0
            HEALTH.emit("music_end", id=track.id, played=round(played, 1), failures=self._failures)
            if self._failures >= MAX_FAILURES:
                print("❌ 连续几首都放不了，停止播放")
                self.playing = False
                self.pid = None
                self.position = 0.0
                return
            if self._failures:
                print(f"⚠️ 放不了，跳过: {track.path}")
            if self.mode != "repeat_one" or self._failures:
                self.index = (self.index + 1) % len(self.queue)
            try:
                await self._start(0.0)
            except MusicError as error:
                print(f"❌ {error}")
                HEALTH.emit("music_error", error=str(error)[:200])

    # ---- ducking --------------------------------------------------------

    async def duck(self):
        """Quieter music while 小七 listens and answers."""
        self._duck_until = self.clock() + self.settings.duck_hold_s
        if self.ducked:
            return
        self.ducked = True
        async with self._lock:
            if self.playing:
                await self._fade(self._level(False), self._level(True))
                HEALTH.emit("music_duck")

    async def unduck(self):
        if not self.ducked:
            return
        self.ducked = False
        async with self._lock:
            if self.playing and not self.ducked:
                await self._fade(self._level(True), self._level(False))
                HEALTH.emit("music_unduck")

    async def _fade(self, start, end, steps=4):
        levels = [round(start + (end - start) * (i + 1) / steps) for i in range(steps)]
        script = "; ".join(f"amixer -q cset name=xqmusicvol {v}; sleep 0.05" for v in levels)
        try:
            await self.run_shell(script, 3000)
        except Exception as error:
            print(f"⚠️ 调整音乐音量失败: {error}")

    async def watchdog(self, interval=2.0):
        """A wake word with no conversation after it (or one 小爱同学 took
        over) leaves no session to end; restore the volume anyway."""
        while True:
            await asyncio.sleep(interval)
            if self.ducked and self.clock() > self._duck_until and not self.session_active():
                await self.unduck()
