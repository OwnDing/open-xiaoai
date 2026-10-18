"""The music library: every playable file under the music folder, and the
names people use to ask for it.

Tags give title and artist; the folders fill in what they lack
(音乐/<歌手>/[<专辑>]/...). The same song kept twice (a copied folder, or as
both MP3 and FLAC) is listed once, in the format the speaker handles best.
Names are also compared by their pinyin without tones, so the recognizer's
homophones ("梁静如") and traditional characters ("一千個傷心的理由") still
find the song.
"""

import hashlib
import json
import os
import random
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache

from pypinyin import lazy_pinyin

from xiaozhi.services.music.tags import read_tags

# Folders that say nothing about who sings ("音乐/music/梁静茹/...").
GENERIC_DIRS = {
    "音乐", "我的音乐", "歌曲", "music", "my music", "musics", "songs", "song", "mp3", "flac",
    "itunes", "itunes media", "baidumusic", "下载", "download", "downloads", "media",
}
ARTIST_SPLIT = re.compile(r"\s*(?:[,，、&/;；]|\bfeat\.?|\bft\.?|\bwith\b)\s*", re.IGNORECASE)
TRACK_NUMBER = re.compile(r"^\s*\d{1,3}(?:\s*[-._、]\s*|\s+)")
BRACKETS = re.compile(r"[\(（\[【][^\)）\]】]*[\)）\]】]")
# Between a singer and a song in a request: "周杰伦 青花瓷", "青花瓷 - 周杰伦", "青花瓷（周杰伦）".
SEPARATORS = re.compile(r"[\s\-–—/|·、,，:：()（）\[\]【】《》]+")
# A query at least this close to a name finds it.
MATCH = 0.8
# Bump when tags are read differently, so the cached index is read again.
INDEX_VERSION = 2


@lru_cache(maxsize=16384)
def normalize(text):
    """Lower case letters and digits only: "A-Lin" and "a lin" compare equal."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in text if ch.isalnum())


@lru_cache(maxsize=16384)
def pinyin(text):
    return "".join(lazy_pinyin(normalize(text)))


def similarity(query, name):
    """How well `query` names `name`, 0..1; homophones count as a near match."""
    q, n = normalize(query), normalize(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    pq, pn = pinyin(q), pinyin(n)
    if pq == pn:
        return 0.97
    score = SequenceMatcher(None, pq, pn).ratio()
    # "梁静" for 梁静茹, "britney" for Britney Spears; one character is too little.
    if len(q) >= 2 and q in n:
        score = max(score, 0.75 + 0.2 * len(q) / len(n))
    return score


def split_artists(text):
    return [part.strip() for part in ARTIST_SPLIT.split(text or "") if part.strip()]


def title_base(title):
    """"勇气 (Live)" is asked for as "勇气"."""
    return BRACKETS.sub("", title).strip() or title


@dataclass
class Track:
    id: str
    path: str  # relative to the library root, with "/"
    ext: str
    title: str
    artists: list = field(default_factory=list)
    album: str = ""
    duration: float = None
    audio_start: int = None
    audio_end: int = None
    size: int = 0
    mtime: float = 0
    # Other ways people may name it ("A - B" in a file name with no tags).
    alt_titles: list = field(default_factory=list)

    @property
    def artist(self):
        return self.artists[0] if self.artists else ""

    def label(self):
        return f"{self.artist}的{self.title}" if self.artist else self.title


@dataclass
class Found:
    """What a request found. kind: track, artist, all, or none."""
    kind: str
    tracks: list = field(default_factory=list)
    artist: str = ""
    title: str = ""
    # An artist was found but not the song asked for ("梁静茹的勇气").
    missing_title: str = ""
    # How well the request named it (1: exactly, 0.97: a homophone).
    score: float = 0.0


class MusicLibrary:
    def __init__(self, root, formats=("mp3", "flac", "wav", "m4a"), exclude_dirs=(),
                 aliases=None, index_path=None):
        self.root = root
        self.formats = [f.lower().lstrip(".") for f in formats]
        self.exclude_dirs = {d.lower() for d in exclude_dirs}
        # {"田馥甄": ["HEBE"]}: every name in a group finds the others' songs.
        self.aliases = aliases or {}
        self.index_path = index_path
        self.tracks = []
        self.by_id = {}
        self.scanned_at = None
        self._lock = threading.Lock()

    @property
    def ready(self):
        return self.scanned_at is not None

    # ---- scanning -------------------------------------------------------

    def scan(self):
        """(Re)read the folder; tags are read again only for new or changed files."""
        cached = self._load_cache()
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d.lower() not in self.exclude_dirs)
            for name in sorted(filenames):
                ext = os.path.splitext(name)[1].lower().lstrip(".")
                if ext in self.formats:
                    files.append(os.path.join(dirpath, name))
        raw = []
        for full in files:
            rel = os.path.relpath(full, self.root).replace(os.sep, "/")
            try:
                stat = os.stat(full)
            except OSError:
                continue
            entry = cached.get(rel)
            if not entry or entry.get("size") != stat.st_size or entry.get("mtime") != stat.st_mtime:
                entry = {"size": stat.st_size, "mtime": stat.st_mtime, "tags": read_tags(full)}
            raw.append((rel, entry))
        self._save_cache({rel: entry for rel, entry in raw})
        tracks = self.build(raw)
        with self._lock:
            self.tracks = tracks
            self.by_id = {t.id: t for t in tracks}
            self.scanned_at = time.time()
        return len(tracks)

    def build(self, raw):
        """Tracks from [(relative path, {"size", "mtime", "tags"})]."""
        folder_artists = set()
        for rel, _ in raw:
            artist, _ = self._folders(rel)
            folder_artists.update(normalize(a) for a in split_artists(artist))
        known = folder_artists | {normalize(a) for e in (entry for _, entry in raw)
                                  for a in split_artists(e["tags"].get("artist"))}
        tracks = [self._track(rel, entry, known) for rel, entry in raw]
        return self._dedupe(tracks)

    def _folders(self, rel):
        """(artist, album) from the folders a file sits in."""
        parts = [p for p in rel.split("/")[:-1] if p.lower() not in GENERIC_DIRS]
        artist = parts[0] if parts else ""
        album = parts[1] if len(parts) > 1 else ""
        return artist, re.sub(r"^单曲\s*-\s*", "", album)

    def _track(self, rel, entry, known):
        tags = entry["tags"]
        folder_artist, folder_album = self._folders(rel)
        stem = os.path.splitext(rel.rsplit("/", 1)[-1])[0]
        stem = TRACK_NUMBER.sub("", stem).strip() or stem
        title, artists, alt = tags.get("title"), split_artists(tags.get("artist")), []
        if not title or not artists:
            parts = [p.strip() for p in stem.split(" - ")] if " - " in stem else []
            if len(parts) == 2:
                first, second = parts
                if all(normalize(a) in known for a in split_artists(first)):
                    name_title, name_artists = second, split_artists(first)
                elif all(normalize(a) in known for a in split_artists(second)):
                    name_title, name_artists = first, split_artists(second)
                else:  # can't tell which half is the singer
                    name_title, name_artists, alt = stem, [], parts
                title = title or name_title
                artists = artists or name_artists
            title = title or stem
        if folder_artist:
            for name in split_artists(folder_artist):
                if normalize(name) not in {normalize(a) for a in artists}:
                    artists.append(name)
        ext = os.path.splitext(rel)[1].lower().lstrip(".")
        return Track(
            id=hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12], path=rel, ext=ext,
            title=title, artists=artists, album=tags.get("album") or folder_album,
            duration=tags.get("duration"), audio_start=tags.get("audio_start"),
            audio_end=tags.get("audio_end"), size=entry["size"], mtime=entry["mtime"],
            alt_titles=[a for a in alt if normalize(a) != normalize(title)],
        )

    def _dedupe(self, tracks):
        def rank(track):
            fmt = self.formats.index(track.ext) if track.ext in self.formats else len(self.formats)
            return fmt, -(track.size or 0)

        best = {}
        for track in tracks:
            key = (pinyin(title_base(track.title)), pinyin(track.artist))
            if key not in best or rank(track) < rank(best[key]):
                best[key] = track
        kept = {id(t) for t in best.values()}
        return [t for t in tracks if id(t) in kept]

    def _load_cache(self):
        if not self.index_path:
            return {}
        try:
            with open(self.index_path, encoding="utf-8") as f:
                index = json.load(f)
        except (OSError, ValueError):
            return {}
        return index.get("entries", {}) if index.get("version") == INDEX_VERSION else {}

    def _save_cache(self, entries):
        if not self.index_path:
            return
        tmp = f"{self.index_path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": INDEX_VERSION, "entries": entries}, f, ensure_ascii=False)
            os.replace(tmp, self.index_path)
        except OSError as error:
            print(f"⚠️ 曲库索引保存失败: {error}")

    # ---- lookup ---------------------------------------------------------

    def path_of(self, track):
        return os.path.join(self.root, *track.path.split("/"))

    def artists(self):
        """Every singer with how many songs, most songs first."""
        counts = {}
        for track in self.tracks:
            for name in track.artists:
                counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda item: -item[1])

    def _alias_group(self, name):
        """`name` and its aliases ("Britney Spears", "布兰妮", "小甜甜")."""
        for key, others in self.aliases.items():
            group = [key, *others]
            if any(normalize(g) == normalize(name) for g in group):
                return group
        return [name]

    def _names(self, track):
        return [n for name in track.artists for n in self._alias_group(name)]

    def _artist_score(self, query, track):
        return max((similarity(query, name) for name in self._names(track)), default=0.0)

    def _title_score(self, query, track):
        names = [track.title, title_base(track.title), *track.alt_titles]
        return max(similarity(query, name) for name in names)

    def by_artist(self, query):
        """(score, tracks) of the singer `query` names best; the same name in
        traditional characters (劉德華 for 刘德华) counts as the same singer."""
        scored = [(self._artist_score(query, t), t) for t in self.tracks]
        best = max((s for s, _ in scored), default=0.0)
        if best < MATCH:
            return best, []
        return best, [t for s, t in scored if s >= min(best - 0.02, 0.95)]

    def by_title(self, query, tracks=None):
        """(score, tracks) whose title `query` names best."""
        scored = [(self._title_score(query, t), t) for t in (self.tracks if tracks is None else tracks)]
        best = max((s for s, _ in scored), default=0.0)
        if best < MATCH:
            return best, []
        return best, [t for s, t in scored if s >= best - 0.001]

    def find(self, query, shuffle=random.shuffle):
        """What to play for `query`: "梁静茹的勇气", "梁静茹", "勇气", "" (anything)."""
        with self._lock:
            tracks = list(self.tracks)
        if not tracks:
            return Found("none")
        query = (query or "").strip()
        if not normalize(query):
            queue = list(tracks)
            shuffle(queue)
            return Found("all", queue)

        options = []
        title_score, titled = self.by_title(query)
        if titled:
            options.append((title_score, "track", titled[0], ""))
        artist_score, sung = self.by_artist(query)
        if sung:
            # An exact singer wins over a song that happens to share the name.
            options.append((artist_score + 0.005, "artist", sung, ""))
        for left, right in self._singer_and_song(query, tracks):
            a_score, a_tracks = self.by_artist(left)
            if not a_tracks:
                continue
            t_score, t_tracks = self.by_title(right, a_tracks)
            if t_tracks:
                options.append((min(a_score, t_score) + 0.01, "track", t_tracks[0], ""))
            else:
                options.append((a_score - 0.1, "artist", a_tracks, right))
        if not options:
            return Found("none")
        score, kind, value, missing = max(options, key=lambda option: option[0])
        score = min(score, 1.0)
        if kind == "track":
            others = [t for t in tracks if t is not value and value.artist and value.artist in t.artists]
            shuffle(others)
            return Found("track", [value, *others], artist=value.artist, title=value.title, score=score)
        queue = list(value)
        shuffle(queue)
        artist = self._display_artist(query if not missing else query[: len(query) - len(missing)], queue)
        return Found("artist", queue, artist=artist, missing_title=missing, score=score)

    def _singer_and_song(self, query, tracks):
        """Ways `query` may name a singer and a song: "梁静茹的勇气", "周杰伦唱的安静",
        "周杰伦 青花瓷", "青花瓷 - 周杰伦", "青花瓷（周杰伦）", "周杰伦青花瓷"."""
        pairs = []
        for match in re.finditer(r"(?:唱)?的", query):
            pairs.append((query[:match.start()], query[match.end():]))
        parts = [p for p in SEPARATORS.split(query) if normalize(p)]
        if len(parts) == 2:
            pairs += [(parts[0], parts[1]), (parts[1], parts[0])]
        q = normalize(query)
        names = {normalize(alias): alias for t in tracks for name in t.artists
                 for alias in self._alias_group(name)}
        for key, name in names.items():
            n = len(key)
            if n >= 2 and len(q) > n:  # by pinyin too: "梁静如偶阵雨"
                if pinyin(q[:n]) == pinyin(key):
                    pairs.append((name, q[n:]))
                if pinyin(q[-n:]) == pinyin(key):
                    pairs.append((name, q[:-n]))
        seen = set()
        return [pair for pair in pairs if normalize(pair[0]) and normalize(pair[1])
                and not (pair in seen or seen.add(pair))]

    def _display_artist(self, query, tracks):
        """The singer's name as the library spells it."""
        query = re.sub(r"(?:唱)?的$", "", query)
        names = [n for t in tracks for n in t.artists]

        def score(name):  # an alias ("布兰妮") stands for the singer it names
            return max(similarity(query, alias) for alias in self._alias_group(name)), names.count(name)

        return max(names, key=score, default=query)

    def describe(self, track):
        return asdict(track)
