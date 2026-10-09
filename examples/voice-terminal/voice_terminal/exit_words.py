"""Goodbye words that end a conversation at once, matched like the 小爱 bridge does."""

DEFAULT_EXIT_WORDS = ["拜拜", "再见", "退出", "退下", "没事了", "不用了", "结束对话", "bye", "goodbye"]
# Said around an exit word without changing what it means.
_FILLERS = ("你好", "您好", "好的", "好吧", "好", "行", "嗯", "哦", "那", "那就",
            "谢谢", "谢了", "ok", "okay")
_PARTICLES = "吧啦了呀啊哈哦喔嘛呗"


def _plain(text):
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def match_exit_words(text, words, keywords=()):
    """The exit word `text` asks to end the conversation with, or None.

    Only when that is all it says: "拜拜", "好的，谢谢，再见", "你好小七，拜拜".
    While awake the wake word goes to the recognizer like any speech, at times
    misheard ("你好小青", "亲"), so at most one character outside the wake words
    may be left over; "关灯，拜拜" or "用英语怎么说再见" go to the server as usual.
    """
    rest = _plain(text)
    exits = sorted({w for w in map(_plain, words) if w}, key=len, reverse=True)
    found = None
    while rest:
        word = next((w for w in exits if rest.endswith(w)), None)
        if word:
            found = found or word
        else:
            word = next((w for w in _FILLERS if rest.endswith(w)), None)
            if not word and rest[-1] in _PARTICLES:
                word = rest[-1]
            if not word:
                break
        rest = rest[: -len(word)]
    if not found:
        return None
    names = {k for k in map(_plain, keywords) if k}
    names |= {k[i:] for k in names for i in range(len(k) - 1)}  # 小七 for 你好小七
    leading = sorted(names | set(_FILLERS), key=len, reverse=True)
    while rest:
        word = next((w for w in leading if rest.startswith(w)), None)
        if not word:
            break
        rest = rest[len(word):]
    name_chars = set("".join(names))
    return found if sum(ch not in name_chars for ch in rest) <= 1 else None
