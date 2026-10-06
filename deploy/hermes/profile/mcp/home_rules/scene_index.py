"""The saved scene phrases, kept in SOUL.md between markers.

Hermes reads SOUL.md for every new conversation, so a phrase taught in one
conversation is recognised in the next without relying on the model to note
it in memory. Rewritten at server start and whenever a scene changes.
"""

import os

START = "<!-- scenes:start -->"
END = "<!-- scenes:end -->"
EMPTY = "（还没有）"


def render(scenes):
    """scenes: [(name, summary)] -> the lines between the markers."""
    if not scenes:
        return EMPTY
    return "\n".join(f"- “{name}”：{summary}" if summary else f"- “{name}”" for name, summary in scenes)


def update(text, scenes):
    """text with the block replaced, or None when the markers are missing."""
    start, end = text.find(START), text.find(END)
    if start < 0 or end < start:
        return None
    return text[: start + len(START)] + "\n" + render(scenes) + "\n" + text[end:]


def sync(path, scenes):
    """Rewrite the block in place (keeping CRLF if the file uses it); returns a status string."""
    with open(path, "rb") as f:
        raw = f.read().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    new = update(text, scenes)
    if new is None:
        return f"no scene markers in {path}"
    if new == text:
        return "unchanged"
    data = (new.replace("\n", "\r\n") if crlf else new).encode("utf-8")
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return f"{len(scenes)} scene(s)"
