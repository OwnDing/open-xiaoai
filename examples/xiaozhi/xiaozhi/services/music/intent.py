"""What a request asks of the music player, read from the recognized text.

Only plain phrasing is taken: "播放梁静茹的勇气", "放首歌", "我想听周杰伦",
"暂停", "下一首", "继续播放", "这是什么歌". Anything else goes to the model
as before. Whether a bare "暂停" or "下一首" is meant for the music is up to
the player: only while there is music to stop or skip.
"""

import re
from dataclasses import dataclass

_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:…~～“”\"'‘’《》<>（）()【】\[\]·\-—]+")
_LEADING = ("你好小七", "小七", "请你", "请", "麻烦你", "麻烦", "帮我", "给我", "帮忙", "那就", "那",
            "嗯", "呃", "额", "哦", "噢", "诶", "好的", "好", "就", "再", "可以", "能不能", "能", "可不可以",
            "你能", "你可以", "你给我", "你帮我", "你", "咱们", "我们", "先")
# A goodbye at the end ("暂停，拜拜") still asks for the music; the bridge ends
# the conversation after it anyway.
_TRAILING = ("好不好", "好吗", "可以吗", "行吗", "行不行", "谢谢你", "谢谢", "拜拜", "再见", "byebye", "bye",
             "一下下", "一下", "吧", "呀", "啊", "哈", "呗", "嘛", "哦", "呢")

_STOP_ANY = re.compile(
    r"(?:暂停|停止|停掉|关掉|关闭|关了|关上|别放|不要放|不放)(?:播放|放歌|音乐|歌曲|歌)"
    r"|(?:音乐|歌曲|歌)(?:先)?(?:暂停|停止|停掉|停了|停下|停|关掉|关了|关上|关闭|别放了|不要放了)"
    r"|把(?:音乐|歌曲|歌|这首歌)(?:暂停|停|关)"
)
_STOP_BARE = re.compile(
    r"(?:暂停|停止|停下来?|停掉|停|别放了?|不要放了?|不放了|不听了|别唱了?|不要唱了?"
    r"|关掉|关了|关闭|关上|关)(?:播放|音乐|歌曲|这首歌|这首|歌)?了?"
)
# "换首周杰伦的歌" names what to play instead; "换一首" alone skips.
_SWITCH = re.compile(r"(?:换一首|换首|换成|换一个|换个|换)(?P<rest>.+)")
_NEXT = re.compile(r"下一首|下首|下一曲|换一首|换首|换个歌|换一个歌|换歌|切歌|切一首|跳过这首|跳过|不想听这首")
_PREV = re.compile(r"上一首|上首|上一曲|前一首|回到上一首")
_REPEAT_ONE = re.compile(r"单曲循环|循环(?:播放)?这首|一直放这首|重复(?:播放)?这首")
_SHUFFLE = re.compile(r"随机播放|随机放|乱序播放|打乱顺序")
_SEQUENCE = re.compile(r"顺序播放|按顺序放|按顺序播放|列表循环|顺序放")
_RESUME = re.compile(r"(?:继续|接着|恢复)(?:播放|放|播|听)?(?:音乐|歌曲|歌|刚才的歌)?")
_SONG = r"(?:是|叫)?(?:一首|首)?(?:什么|啥|哪首|哪一首)(?:歌|歌曲|曲子|音乐)"
_NOW_PLAYING = re.compile(
    rf"(?:这|这个|这首|现在|刚才|正在)(?:放的|播的|唱的)?{_SONG}"
    rf"|(?:放的|播的|唱的){_SONG}"
    r"|这首歌?(?:叫|是)(?:什么|啥)|这歌叫(?:什么|啥)|歌名(?:是|叫)?(?:什么|啥)|叫什么歌"
    r"|谁唱的|谁的歌|哪个歌手"
)
# Questions about the library itself, answered from it.
_LIB_COUNT = re.compile(
    r"(?:曲库|歌库|音乐库|库里|你这|你那).{0,6}?有(?:多少|几)首?(?:歌|歌曲|音乐|曲子)"
    r"|(?:一共|总共|总|共)有(?:多少|几)首?(?:歌|歌曲|音乐|曲子)"
    r"|^有(?:多少|几)首(?:歌|歌曲|音乐|曲子)$"
)
_LIB_ARTISTS = re.compile(r"(?:有|都有)(?:哪些|什么|多少|几个|几位)歌手|都有谁的歌|有谁的歌|歌手都有谁|歌手有哪些")
_LIB_ARTIST_COUNT = re.compile(r"(?P<q>.+?)(?:的歌曲|的歌)?有(?:多少|几)首(?:歌|歌曲)?")
# "曲库里面" is sometimes heard as "酒库里面".
_LIB_HAS = re.compile(r"(?:.{0,2}库(?:里面|里|中)?|你这里?|这里)?(?:有没有(?P<q>.+)|有(?P<q2>.+?)吗)")
_WHOLE_LIBRARY = {"你", "你这", "你这里", "你们", "我们", "咱们", "家里", "这里", "现在", "一共", "总共"}
_ALBUM = re.compile(r"(?:这首歌?|这)?(?:是|出自)?(?:哪张|哪个|什么)专辑|专辑(?:是|叫)?(?:什么|啥|哪张)")
_RANDOM = re.compile(
    r"(?:随便|随机|随意)(?:放|播|来|听|播放)(?:一首|几首|一些|首|点儿|点|一点|些)?(?:歌|音乐|歌曲)?"
)
_PLAY = re.compile(
    r"(?P<verb>播放|播一下|播|放一下|放|来|我想听|我要听|想听|要听|听一下|听|唱)"
    r"(?P<qty>一首|一曲|几首|一些|首|点儿|点|一点|些)?(?P<rest>.*)"
)
# Verbs that mean "play" whatever follows.
_PLAY_VERBS = ("播放", "播一下", "播", "我想听", "我要听", "想听", "要听", "听一下")
_SONG_QTY = ("一首", "一曲", "几首", "首")
_LISTEN_TAIL = re.compile(r"(?:给我们听|给我听|来听听|听听|听)$")
_SINGER_TAIL = re.compile(r"(?:的歌曲|的歌|的音乐|的曲子|的专辑|的作品|唱的|的)$")
_GENERIC = {"", "歌", "音乐", "歌曲", "首歌", "曲子", "好听的", "好听的歌", "好听的音乐", "点音乐", "点歌",
            "音乐吧", "一首歌", "几首歌"}
# Other things one "plays", and questions ("放什么歌好"); these are for the model.
_NOT_MUSIC = re.compile(r"新闻|天气|广播|电台|故事|相声|评书|小说|有声书|视频|电视|电影|节目|动画|白噪音|闹钟"
                        r"|什么|啥|哪")
_MUSIC_WORDS = re.compile(r"歌|曲|音乐|专辑")


@dataclass
class Intent:
    """action: play, stop, next, prev, resume, now_playing, mode or library.

    library: mode is count ("曲库有多少首歌"), artists ("有哪些歌手"), has
    ("有没有周杰伦的歌") or artist_count ("陈奕迅有几首歌"); now_playing with
    mode album asks for the album."""
    action: str
    query: str = ""
    mode: str = ""
    # stop: "停止播放" rather than a bare "停".
    explicit: bool = False
    # play: only if the library knows the name well ("放周杰伦", not "放假").
    strict: bool = False
    # play: clearly asked for music, so "not found" is answered, not passed on.
    music: bool = False
    # play: a bare "播放" also resumes what was stopped.
    resume: bool = False


def clean(text, names=()):
    t = _PUNCT.sub("", str(text or "")).lower()
    leading = sorted({*_LEADING, *(n.lower() for n in names)}, key=len, reverse=True)
    changed = True
    while changed and t:
        changed = False
        for word in leading:
            if t.startswith(word) and len(t) > len(word):
                t, changed = t[len(word):], True
                break
        for word in _TRAILING:
            if t.endswith(word) and len(t) > len(word):
                t, changed = t[: -len(word)], True
                break
    return t


def _query(rest):
    """(what to look for, whether a singer was named) from what follows the verb."""
    rest = _LISTEN_TAIL.sub("", rest) if len(rest) > 1 else rest
    singer = bool(_SINGER_TAIL.search(rest)) and len(rest) > 2
    return (_SINGER_TAIL.sub("", rest) if singer else rest), singer


def parse(text, names=()):
    """The music request in `text`, or None. `names` are wake words to ignore."""
    t = clean(text, names)
    if not t:
        return None
    short = len(t) <= 10
    if _STOP_ANY.search(t):
        return Intent("stop", explicit=True)
    if _STOP_BARE.fullmatch(t):
        return Intent("stop")
    switch = _SWITCH.fullmatch(t)
    if switch:
        query, singer = _query(switch.group("rest"))
        if query not in _GENERIC and not _NOT_MUSIC.search(query) and not _NEXT.fullmatch(t):
            # "换个灯光" is not about music: without 歌/的 the name must be known.
            music = singer or bool(_MUSIC_WORDS.search(switch.group("rest")))
            return Intent("play", query=query, strict=not music, music=music)
    if short and _NEXT.search(t):
        return Intent("next")
    if short and _PREV.search(t):
        return Intent("prev")
    if short and _REPEAT_ONE.search(t):
        return Intent("mode", mode="repeat_one")
    if short and _SEQUENCE.search(t):
        return Intent("mode", mode="sequence")
    if short and _SHUFFLE.search(t):
        return Intent("mode", mode="shuffle")
    if _RESUME.fullmatch(t):
        return Intent("resume")
    if len(t) <= 12 and _NOW_PLAYING.search(t):
        return Intent("now_playing")
    if len(t) <= 12 and _ALBUM.search(t):
        return Intent("now_playing", mode="album")
    if _LIB_COUNT.search(t):
        return Intent("library", mode="count")
    if _LIB_ARTISTS.search(t):
        return Intent("library", mode="artists")
    has = _LIB_HAS.fullmatch(t)
    if has:
        asked = has.group("q") or has.group("q2")
        query, singer = _query(asked)
        query = re.sub(r"(?:这首歌|这首|这个歌)$", "", query)
        if query and not _NOT_MUSIC.search(query):
            music = singer or bool(_MUSIC_WORDS.search(asked))
            return Intent("library", mode="has", query=query, strict=not music, music=music)
    count = _LIB_ARTIST_COUNT.fullmatch(t)
    if count and not _NOT_MUSIC.search(count.group("q")):
        if count.group("q") in _WHOLE_LIBRARY:  # "你有多少首歌"
            return Intent("library", mode="count")
        return Intent("library", mode="artist_count", query=count.group("q"), music=True)
    if _RANDOM.fullmatch(t):
        return Intent("play", music=True)
    match = _PLAY.fullmatch(t)
    if not match:
        return None
    verb, qty, rest = match.group("verb"), match.group("qty") or "", match.group("rest")
    if not qty and not rest and verb != "播放":
        return None  # "听", "放": too little to go on ("停一下" is often heard as "听一下")
    if verb == "唱" and not qty:
        return None
    query, singer = _query(rest)
    if query in _GENERIC:
        return Intent("play", music=True, resume=verb == "播放" and not qty and not rest)
    if _NOT_MUSIC.search(query):
        return None
    explicit = verb in _PLAY_VERBS or qty in _SONG_QTY or singer or bool(_MUSIC_WORDS.search(query))
    return Intent("play", query=query, strict=not (explicit or qty), music=explicit)
