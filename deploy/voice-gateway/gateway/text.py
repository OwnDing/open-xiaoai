"""Text cleaning and streaming sentence segmentation for low-latency TTS."""

from __future__ import annotations

import re

# Strip markdown formatting so TTS never reads asterisks, hashes or URLs.
_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MD_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MD_LIST = re.compile(r"(?m)^\s*[-*+]\s+")
_MD_BOLD_ITALIC = re.compile(r"\*{1,3}([^*\n]+)\*{1,3}|_{1,3}([^_\n]+)_{1,3}|~~([^~\n]+)~~")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
# Emoji blocks (Supplementary planes + dingbats/misc symbols).
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "\u200d"
    "]+",
    re.UNICODE,
)
_SPOKEN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

FIRST_PUNCT = set("，。！？；：,.!?;:\n…")
STRONG_PUNCT = set("。！？!?\n…")
SOFT_PUNCT = set("，；,;：:")


def clean_markdown(text: str) -> str:
    """Remove Markdown markup and emoji while keeping natural speech punctuation."""
    if not text:
        return ""
    text = _CODE_FENCE.sub("", text)
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_LIST.sub("", text)
    text = _MD_BOLD_ITALIC.sub(lambda m: m.group(1) or m.group(2) or m.group(3) or "", text)
    text = _EMOJI.sub("", text)
    text = text.replace("*", "").replace("#", "")
    text = _MULTI_SPACE.sub(" ", text)
    return text


def spoken_len(text: str) -> int:
    return len(_SPOKEN.findall(text))


def _is_protected_punct(buf: str, idx: int) -> bool:
    """Avoid splitting decimals (26.5), clock times (11:30), or comma-grouped numbers (1,000)."""
    ch = buf[idx]
    if ch in (".", ":", ","):
        prev_digit = idx > 0 and buf[idx - 1].isdigit()
        next_digit = idx + 1 < len(buf) and buf[idx + 1].isdigit()
        if prev_digit and next_digit:
            return True
        # At the very end of the buffer after a digit, wait for the next chunk
        # before treating `.` or `:` as sentence-ending.
        if prev_digit and idx + 1 == len(buf) and ch in (".", ":"):
            return True
    return False


class SentenceSplitter:
    """Incremental splitter matching low-latency first-sentence TTS behavior.

    - First segment cuts at the first punctuation mark once at least 2 spoken
      characters have accumulated, so audio starts while the LLM is still
      streaming.
    - Subsequent segments cut at strong sentence boundaries (。！？!?\n), or at
      soft clause boundaries (，；:;) once the segment is long enough.
    """

    def __init__(self, first_min_chars: int = 2, soft_min_chars: int = 28, max_chars: int = 90):
        self.first_min_chars = first_min_chars
        self.soft_min_chars = soft_min_chars
        self.max_chars = max_chars
        self._buf = ""
        self._is_first = True

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self._buf += chunk
        emitted: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            seg = clean_markdown(self._buf[:cut]).strip()
            self._buf = self._buf[cut:].lstrip()
            if seg and spoken_len(seg) > 0:
                emitted.append(seg)
                self._is_first = False
        return emitted

    def flush(self) -> list[str]:
        seg = clean_markdown(self._buf).strip()
        self._buf = ""
        if seg and spoken_len(seg) > 0:
            self._is_first = False
            return [seg]
        return []

    def _find_cut(self) -> int | None:
        buf = self._buf
        if not buf:
            return None
        spoken = 0
        for i, ch in enumerate(buf):
            if _SPOKEN.match(ch):
                spoken += 1
                if spoken >= self.max_chars:
                    return i + 1
                continue
            if _is_protected_punct(buf, i):
                continue
            if self._is_first:
                if ch in FIRST_PUNCT and spoken >= self.first_min_chars:
                    return i + 1
            else:
                if ch in STRONG_PUNCT and spoken >= 1:
                    return i + 1
                if ch in SOFT_PUNCT and spoken >= self.soft_min_chars:
                    return i + 1
        return None
