import os
import struct
import tempfile
import unittest

from xiaozhi.services.music.intent import parse
from xiaozhi.services.music.library import MusicLibrary, similarity
from xiaozhi.services.music.tags import read_tags


def id3_frame(frame_id, text, encoding=0):
    if encoding == 0:
        body = text.encode("gbk")
    elif encoding == 1:
        body = text.encode("utf-16")
    else:
        body = text.encode("utf-8")
    data = bytes([encoding]) + body
    return frame_id.encode() + struct.pack(">I", len(data)) + b"\x00\x00" + data


def syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def mp3_bytes(frames=1000, tags=b"", id3v1=None):
    """MPEG-1 layer III, 128 kbps, 44.1 kHz, stereo, with a Xing header."""
    tag = b"ID3\x03\x00\x00" + syncsafe(len(tags)) + tags if tags else b""
    header = b"\xff\xfb\x90\x00"
    frame_len = 144 * 128000 // 44100
    first = bytearray(header + bytes(frame_len - 4))
    first[36:48] = b"Xing" + struct.pack(">II", 1, frames)
    audio = bytes(first) + (header + bytes(frame_len - 4)) * 3
    tail = b""
    if id3v1:
        title, artist, album = (s.encode("gbk").ljust(30, b"\x00") for s in id3v1)
        tail = b"TAG" + title + artist + album + bytes(35)
    return tag + audio + tail, len(tag), len(tag) + len(audio)


class TagTests(unittest.TestCase):
    def write(self, name, data):
        path = os.path.join(self.dir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_id3v2_gbk_and_utf16_text_and_xing_length(self):
        tags = id3_frame("TIT2", "勇气") + id3_frame("TPE1", "梁静茹", 1) + id3_frame("TALB", "勇气", 3)
        data, start, end = mp3_bytes(1000, tags)
        info = read_tags(self.write("a.mp3", data))
        self.assertEqual((info["title"], info["artist"], info["album"]), ("勇气", "梁静茹", "勇气"))
        self.assertAlmostEqual(info["duration"], 1000 * 1152 / 44100, places=2)
        self.assertEqual((info["audio_start"], info["audio_end"]), (start, end))

    def test_id3v1_fills_what_v2_lacks_and_is_not_audio(self):
        data, start, end = mp3_bytes(10, id3_frame("TIT2", "偶阵雨"), id3v1=("x", "梁静茹", "崇拜"))
        info = read_tags(self.write("b.mp3", data))
        self.assertEqual((info["title"], info["artist"], info["album"]), ("偶阵雨", "梁静茹", "崇拜"))
        self.assertEqual(info["audio_end"], end)

    def test_flac_vorbis_comment_and_streaminfo(self):
        info_block = bytearray(34)
        info_block[10:18] = ((44100 << 44) | (1 << 41) | (15 << 36) | 441000).to_bytes(8, "big")
        comments = [b"TITLE=\xe5\xb0\x8f\xe5\xb0\x8f", b"ARTIST=\xe5\xae\xb9\xe7\xa5\x96\xe5\x84\xbf"]
        vorbis = struct.pack("<I", 3) + b"lib" + struct.pack("<I", len(comments))
        vorbis += b"".join(struct.pack("<I", len(c)) + c for c in comments)
        data = (b"fLaC" + bytes([0]) + len(info_block).to_bytes(3, "big") + bytes(info_block)
                + bytes([0x84]) + len(vorbis).to_bytes(3, "big") + vorbis + bytes(100))
        info = read_tags(self.write("c.flac", data))
        self.assertEqual((info["title"], info["artist"]), ("小小", "容祖儿"))
        self.assertAlmostEqual(info["duration"], 10.0)

    def test_wav_length(self):
        fmt = struct.pack("<HHIIHH", 1, 2, 48000, 192000, 4, 16)
        data = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
        data += b"data" + struct.pack("<I", 19200) + bytes(19200)
        self.assertAlmostEqual(read_tags(self.write("d.wav", data))["duration"], 0.1)

    def test_gbk_turned_into_latin1_characters_is_repaired(self):
        tags = id3_frame("TPE1", "梁静茹".encode("gbk").decode("latin-1"), 1)
        tags += id3_frame("TIT2", "Céline", 1)
        info = read_tags(self.write("f.mp3", mp3_bytes(10, tags)[0]))
        self.assertEqual((info["artist"], info["title"]), ("梁静茹", "Céline"))

    def test_broken_file_gives_no_tags(self):
        info = read_tags(self.write("e.mp3", b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f"))
        self.assertIsNone(info["title"])
        self.assertEqual(read_tags(os.path.join(self.dir.name, "missing.mp3"))["title"], None)


def entry(size=100, **tags):
    return {"size": size, "mtime": 0, "tags": tags}


LIBRARY = [
    ("音乐/梁静茹/勇气.mp3", entry(title="勇气", artist="梁静茹", duration=240.0, audio_start=100, audio_end=4000100)),
    ("音乐/music/梁静茹/勇气.mp3", entry(title="勇气", artist="梁静茹")),
    ("音乐/梁静茹/偶阵雨 - 梁静茹.flac", entry(300, title="偶阵雨", artist="梁静茹")),
    ("音乐/梁静茹/偶阵雨.mp3", entry()),
    ("音乐/张学友/一千個傷心的理由.mp3", entry()),
    ("音乐/周杰伦/安静.mp3", entry()),
    ("音乐/S.H.E/安静了.mp3", entry()),
    ("音乐/Britney Spears/Alien - Britney Spears.mp3", entry()),
    ("音乐/陈奕迅/The Key/陈奕迅 - 主旋律.mp3", entry()),
    ("音乐/陈奕迅/认了吧/07 好久不见.mp3", entry()),
    ("音乐/HEBE/不醉不会 - 田馥甄.flac", entry(title="不醉不会", artist="田馥甄")),
    ("音乐/Hunger Games/Arcade Fire - Abraham's Daughter.mp3", entry()),
    ("音乐/music/外婆的澎湖湾.mp3", entry()),
    ("音乐/刘德华/天意.mp3", entry()),
    ("音乐/劉德華/冰雨.mp3", entry()),
    ("音乐/李宗盛,梁静茹/理性与感性作品音乐会/15 明明白白我的心.mp3", entry()),
]


def library():
    lib = MusicLibrary("/nowhere")
    lib.tracks = lib.build(LIBRARY)
    lib.by_id = {t.id: t for t in lib.tracks}
    lib.scanned_at = 1
    return lib


def keep_order(tracks):
    pass


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.lib = library()

    def find(self, query):
        return self.lib.find(query, shuffle=keep_order)

    def test_same_song_is_listed_once_in_the_preferred_format(self):
        titles = sorted(t.title for t in self.lib.tracks)
        self.assertEqual(titles.count("勇气"), 1)
        rain = [t for t in self.lib.tracks if t.title == "偶阵雨"]
        self.assertEqual([t.ext for t in rain], ["mp3"])

    def test_names_come_from_folders_and_file_names(self):
        by_path = {t.path: t for t in self.lib.tracks}
        alien = by_path["音乐/Britney Spears/Alien - Britney Spears.mp3"]
        self.assertEqual((alien.title, alien.artist), ("Alien", "Britney Spears"))
        key = by_path["音乐/陈奕迅/The Key/陈奕迅 - 主旋律.mp3"]
        self.assertEqual((key.title, key.artist, key.album), ("主旋律", "陈奕迅", "The Key"))
        self.assertEqual(by_path["音乐/陈奕迅/认了吧/07 好久不见.mp3"].title, "好久不见")
        hebe = by_path["音乐/HEBE/不醉不会 - 田馥甄.flac"]
        self.assertEqual(hebe.artists, ["田馥甄", "HEBE"])
        both = by_path["音乐/李宗盛,梁静茹/理性与感性作品音乐会/15 明明白白我的心.mp3"]
        self.assertEqual(both.artists, ["李宗盛", "梁静茹"])
        self.assertEqual(by_path["音乐/music/外婆的澎湖湾.mp3"].artists, [])

    def test_a_song_by_title(self):
        found = self.find("勇气")
        self.assertEqual((found.kind, found.title, found.artist), ("track", "勇气", "梁静茹"))
        self.assertEqual(found.tracks[0].title, "勇气")
        # The rest of the queue is the same singer's.
        self.assertTrue(all("梁静茹" in t.artists for t in found.tracks))

    def test_exact_title_beats_a_longer_one(self):
        self.assertEqual(self.find("安静").tracks[0].path, "音乐/周杰伦/安静.mp3")

    def test_singer_and_song(self):
        found = self.find("梁静茹的偶阵雨")
        self.assertEqual((found.kind, found.title), ("track", "偶阵雨"))
        found = self.find("周杰伦唱的安静")
        self.assertEqual((found.kind, found.title, found.artist), ("track", "安静", "周杰伦"))

    def test_singer_and_song_without_de(self):
        for query in ["周杰伦 安静", "安静 周杰伦", "周杰伦安静", "周杰伦 - 安静", "安静（周杰伦）", "梁静如偶阵雨"]:
            found = self.find(query)
            self.assertEqual((found.kind, found.title), ("track", "安静" if "安静" in query else "偶阵雨"), query)

    def test_a_title_with_de_in_it_is_not_split(self):
        found = self.find("外婆的澎湖湾")
        self.assertEqual((found.kind, found.title), ("track", "外婆的澎湖湾"))

    def test_singer_homophones_and_aliases(self):
        found = self.find("梁静如")
        self.assertEqual((found.kind, found.artist), ("artist", "梁静茹"))
        self.assertEqual(len(found.tracks), 3)  # 勇气, 偶阵雨, 明明白白我的心
        self.assertEqual(self.find("hebe").kind, "artist")
        self.assertEqual(self.find("田馥甄").artist, "田馥甄")

    def test_a_singer_in_traditional_characters_is_the_same_singer(self):
        found = self.find("刘德华")
        self.assertEqual(sorted(t.title for t in found.tracks), ["冰雨", "天意"])

    def test_traditional_characters_and_english(self):
        self.assertEqual(self.find("一千个伤心的理由").artist, "张学友")
        self.assertEqual(self.find("alien").title, "Alien")
        self.assertEqual(self.find("Abraham's Daughter").kind, "track")

    def test_an_alias_is_answered_with_the_singers_name(self):
        self.lib.aliases = {"Britney Spears": ["布兰妮"]}
        found = self.find("布兰妮")
        self.assertEqual((found.kind, found.artist), ("artist", "Britney Spears"))

    def test_singer_found_but_not_the_song(self):
        found = self.find("梁静茹的情歌")
        self.assertEqual((found.kind, found.artist, found.missing_title), ("artist", "梁静茹", "情歌"))

    def test_nothing_or_anything(self):
        self.assertEqual(self.find("不存在的东西xyz").kind, "none")
        found = self.find("")
        self.assertEqual((found.kind, len(found.tracks)), ("all", len(self.lib.tracks)))

    def test_similarity(self):
        self.assertEqual(similarity("梁静茹", "梁静茹"), 1.0)
        self.assertGreater(similarity("梁静如", "梁静茹"), 0.95)
        self.assertLess(similarity("勇敢", "勇气"), 0.8)

    def test_scan_reads_the_folder_and_caches_tags(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "音乐", "梁静茹"))
            os.makedirs(os.path.join(root, "音乐", "Podcasts"))
            data, _, _ = mp3_bytes(10, id3_frame("TIT2", "勇气"))
            for rel in ("音乐/梁静茹/勇气.mp3", "音乐/Podcasts/news.mp3", "音乐/梁静茹/x.wma"):
                with open(os.path.join(root, *rel.split("/")), "wb") as f:
                    f.write(data)
            index = os.path.join(root, "index.json")
            lib = MusicLibrary(root, exclude_dirs=["Podcasts"], index_path=index)
            self.assertEqual(lib.scan(), 1)
            self.assertEqual((lib.tracks[0].title, lib.tracks[0].artist), ("勇气", "梁静茹"))
            self.assertTrue(os.path.exists(index))
            self.assertEqual(MusicLibrary(root, exclude_dirs=["Podcasts"], index_path=index).scan(), 1)


class IntentTests(unittest.TestCase):
    def check(self, text, action, **fields):
        intent = parse(text, ["你好小七"])
        self.assertIsNotNone(intent, text)
        self.assertEqual(intent.action, action, text)
        for key, value in fields.items():
            self.assertEqual(getattr(intent, key), value, f"{text}: {key}")

    def test_play_requests(self):
        self.check("播放梁静茹的勇气。", "play", query="梁静茹的勇气", strict=False, music=True)
        self.check("你好小七，放一首梁静茹的勇气吧", "play", query="梁静茹的勇气", music=True)
        self.check("我想听周杰伦", "play", query="周杰伦", music=True)
        self.check("放几首陈奕迅的歌", "play", query="陈奕迅", music=True)
        self.check("来点梁静茹的歌给我听", "play", query="梁静茹", music=True)
        self.check("给我放首歌", "play", query="", music=True)
        self.check("来点音乐", "play", query="")
        self.check("随便放几首歌", "play", query="")
        self.check("播放", "play", query="", resume=True)
        self.check("放周杰伦", "play", query="周杰伦", strict=True, music=False)
        self.check("换首周杰伦的歌", "play", query="周杰伦", music=True)
        self.check("呃，换成张惠妹的", "play", query="张惠妹", music=True)

    def test_not_music(self):
        for text in ["放假了吗", "播放新闻", "我想听相声", "放什么歌好呢", "听", "听一下", "关灯", "来了",
                     "今天天气怎么样", "换个灯光"]:
            intent = parse(text)
            if intent is not None:  # "换个灯光" may only play a name the library knows exactly
                self.assertTrue(intent.strict, text)

    def test_library_questions(self):
        self.check("我们现在曲库总共有多少首歌？", "library", mode="count")
        self.check("你有多少首歌", "library", mode="count")
        self.check("那你知道有哪些歌手吗", "library", mode="artists")
        self.check("曲库里有没有周杰伦的歌", "library", mode="has", query="周杰伦", music=True)
        self.check("有没有偶阵雨这首歌", "library", mode="has", query="偶阵雨", music=True)
        self.check("有没有梁静茹", "library", mode="has", query="梁静茹", strict=True)
        self.check("陈奕迅有几首歌", "library", mode="artist_count", query="陈奕迅")
        self.check("有周杰伦的青花瓷吗？", "library", mode="has", query="周杰伦的青花瓷", strict=True)
        self.check("嗯，我们酒库里面有周杰伦的青花瓷吗？", "library", mode="has", query="周杰伦的青花瓷")
        self.check("有人吗", "library", strict=True)
        self.check("这首歌是哪张专辑的", "now_playing", mode="album")
        self.check("有没有下雨", "library", strict=True)  # the player passes it on: no such name
        self.assertIsNone(parse("明天有没有天气预报"))

    def test_controls(self):
        self.check("暂停", "stop", explicit=False)
        self.check("停一下", "stop")
        self.check("好的，别放了", "stop")
        self.check("暂停音乐", "stop", explicit=True)
        self.check("暂停，拜拜", "stop")
        self.check("下一首，谢谢", "next")
        self.check("暂停播放吧，再见", "stop", explicit=True)
        self.check("把音乐关了", "stop", explicit=True)
        self.check("下一首", "next")
        self.check("换一首", "next")
        self.check("换首歌吧", "next")
        self.check("切歌", "next")
        self.check("上一首", "prev")
        self.check("继续播放", "resume")
        self.check("接着放", "resume")
        self.check("继续", "resume")
        self.check("这是什么歌", "now_playing")
        self.check("这首歌叫什么", "now_playing")
        self.check("这是谁唱的", "now_playing")
        for text in ["这是首什么歌？", "这首是什么歌", "现在放的是哪首歌", "这叫什么歌", "这是谁的歌",
                     "这歌叫什么名字", "刚才放的什么歌"]:
            self.check(text, "now_playing")
        self.check("单曲循环", "mode", mode="repeat_one")
        self.check("随机播放", "mode", mode="shuffle")


if __name__ == "__main__":
    unittest.main()
