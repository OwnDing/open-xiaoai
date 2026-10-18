"""Title, artist, album and length of an audio file, read from its tags.

Only what the music library needs, without extra packages: ID3v2.2-2.4 and
ID3v1 (MP3), Vorbis comments and STREAMINFO (FLAC), RIFF/WAVE INFO. Chinese
MP3s from the 2000s often keep GBK bytes in tags marked Latin-1; those come
back as Chinese, not mojibake.

`audio_start`/`audio_end` bound the MP3 frames (tags excluded), so a song
can be resumed from the middle by sending the speaker the bytes from there.
"""

import os
import struct

FIELDS = ("title", "artist", "album", "albumartist")

_ID3_FRAMES = {
    "TIT2": "title", "TT2": "title",
    "TPE1": "artist", "TP1": "artist",
    "TALB": "album", "TAL": "album",
    "TPE2": "albumartist", "TP2": "albumartist",
}
_VORBIS_KEYS = {"TITLE": "title", "ARTIST": "artist", "ALBUM": "album", "ALBUMARTIST": "albumartist"}
_RIFF_KEYS = {b"INAM": "title", b"IART": "artist", b"IPRD": "album"}

_MP3_BITRATES = {
    (1, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (1, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_MP3_RATES = {1: (44100, 48000, 32000), 2: (22050, 24000, 16000), 25: (11025, 12000, 8000)}
# The first frame is looked for this far after the ID3 tag.
_SYNC_SEARCH = 256 * 1024


def read_tags(path):
    """{"title", "artist", "album", "albumartist", "duration", "audio_start",
    "audio_end"}; unknown values are None. Never raises for a bad file."""
    info = dict.fromkeys(FIELDS + ("duration", "audio_start", "audio_end"))
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(10)
            f.seek(0)
            ext = os.path.splitext(path)[1].lower()
            if ext == ".flac" or head[:4] == b"fLaC":
                _read_flac(f, info)
            elif ext == ".wav" or head[:4] == b"RIFF":
                _read_wav(f, size, info)
            elif ext == ".mp3" or head[:3] == b"ID3":
                _read_mp3(f, size, info)
    except (OSError, ValueError, struct.error, IndexError):
        pass
    return info


def decode_text(raw):
    """Bytes of unknown encoding: UTF-8, else GBK (Chinese MP3s), else Latin-1."""
    if not raw:
        return ""
    if all(b < 0x80 for b in raw):
        return raw.decode("ascii")
    for encoding in ("utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "utf-8" or any("一" <= ch <= "鿿" for ch in text):
            return text
    return raw.decode("latin-1")


def _regbk(text):
    """GBK bytes that a tagger turned into Latin-1 characters ("Áº¾²Èã" for
    梁静茹) back to Chinese. Only text with no ASCII letters is tried, so
    "Céline Dion" stays as it is."""
    high = [ch for ch in text if "\x80" <= ch <= "\xff"]
    if len(high) < 2 or any(ch > "\xff" or ch.isascii() and ch.isalpha() for ch in text):
        return text
    try:
        fixed = text.encode("latin-1").decode("gb18030")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return fixed if any("一" <= ch <= "鿿" for ch in fixed) else text


def _clean(text):
    text = _regbk(text.replace("\x00", "").strip())
    return text or None


def _syncsafe(data):
    return (data[0] << 21) | (data[1] << 14) | (data[2] << 7) | data[3]


def _id3_text(data):
    """First value of an ID3 text frame."""
    if not data:
        return None
    encoding, body = data[0], data[1:]
    if encoding == 0:
        return _clean(decode_text(body.split(b"\x00", 1)[0]))
    if encoding == 3:
        return _clean(body.split(b"\x00", 1)[0].decode("utf-8", "replace"))
    # UTF-16 (1: with BOM, 2: big endian); values end with a 2-byte NUL.
    end = 0
    while end + 1 < len(body) and body[end:end + 2] != b"\x00\x00":
        end += 2
    body = body[:end]
    if encoding == 1:
        codec = "utf-16" if body[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-16-le"
    else:
        codec = "utf-16-be"
    return _clean(body.decode(codec, "replace"))


def _read_id3v2(f, info):
    """Parse an ID3v2 tag at the current position; returns its total size."""
    start = f.tell()
    header = f.read(10)
    if len(header) < 10 or header[:3] != b"ID3":
        f.seek(start)
        return 0
    major, flags = header[3], header[5]
    size = _syncsafe(header[6:10])
    total = 10 + size + (10 if major == 4 and flags & 0x10 else 0)
    tag = f.read(size)
    if major < 4 and flags & 0x80:  # whole-tag unsynchronisation
        tag = tag.replace(b"\xff\x00", b"\xff")
    pos = 0
    if flags & 0x40 and major >= 3:  # extended header
        ext = tag[:4]
        pos = _syncsafe(ext) if major == 4 else 4 + struct.unpack(">I", ext)[0]
    id_len, head_len = (3, 6) if major == 2 else (4, 10)
    while pos + head_len <= len(tag):
        frame_id = tag[pos:pos + id_len]
        if not frame_id.strip(b"\x00") or not frame_id.isalnum():
            break
        if major == 2:
            frame_size = int.from_bytes(tag[pos + 3:pos + 6], "big")
            frame_flags = 0
        else:
            raw = tag[pos + 4:pos + 8]
            # iTunes wrote plain sizes into v2.4 tags; a syncsafe size never
            # has a high bit set.
            frame_size = _syncsafe(raw) if major == 4 and not any(b & 0x80 for b in raw) \
                else struct.unpack(">I", raw)[0]
            frame_flags = int.from_bytes(tag[pos + 8:pos + 10], "big")
        data = tag[pos + head_len:pos + head_len + frame_size]
        pos += head_len + frame_size
        key = _ID3_FRAMES.get(frame_id.decode("latin-1"))
        if not key or info.get(key):
            continue
        if major == 4:
            if frame_flags & 0x000C:  # compressed or encrypted
                continue
            if frame_flags & 0x0002:
                data = data.replace(b"\xff\x00", b"\xff")
            if frame_flags & 0x0001:  # data length indicator
                data = data[4:]
        elif major == 3:
            if frame_flags & 0x00C0:
                continue
            if frame_flags & 0x0020:  # grouping identity
                data = data[1:]
        info[key] = _id3_text(data)
    f.seek(start + total)
    return total


def _read_id3v1(f, size, info):
    if size < 128:
        return 0
    f.seek(size - 128)
    tag = f.read(128)
    if tag[:3] != b"TAG":
        return 0
    for key, (lo, hi) in (("title", (3, 33)), ("artist", (33, 63)), ("album", (63, 93))):
        if not info.get(key):
            info[key] = _clean(decode_text(tag[lo:hi].split(b"\x00", 1)[0]).strip())
    return 128


def _ape_footer_size(f, end):
    if end < 32:
        return 0
    f.seek(end - 32)
    footer = f.read(32)
    if footer[:8] != b"APETAGEX":
        return 0
    tag_size = struct.unpack("<I", footer[12:16])[0]
    has_header = struct.unpack("<I", footer[20:24])[0] & 0x80000000
    return tag_size + (32 if has_header else 0)


def _mp3_frame(header):
    """(version, layer, bitrate kbps, sample rate, padding, channels) or None."""
    if len(header) < 4 or header[0] != 0xFF or header[1] & 0xE0 != 0xE0:
        return None
    version = {0: 25, 2: 2, 3: 1}.get((header[1] >> 3) & 3)
    layer = {1: 3, 2: 2, 3: 1}.get((header[1] >> 1) & 3)
    bitrate_index, rate_index = header[2] >> 4, (header[2] >> 2) & 3
    if not version or not layer or bitrate_index in (0, 15) or rate_index == 3:
        return None
    table = _MP3_BITRATES[(1 if version == 1 else 2, layer)]
    channels = 1 if header[3] >> 6 == 3 else 2
    return version, layer, table[bitrate_index], _MP3_RATES[version][rate_index], (header[2] >> 1) & 1, channels


def _frame_length(version, layer, bitrate, rate, padding):
    if layer == 1:
        return (12 * bitrate * 1000 // rate + padding) * 4
    if layer == 3 and version != 1:
        return 72 * bitrate * 1000 // rate + padding
    return 144 * bitrate * 1000 // rate + padding


def _read_mp3(f, size, info):
    tag_end = 0
    while True:  # some files carry two ID3v2 tags
        f.seek(tag_end)
        read = _read_id3v2(f, info)
        if not read:
            break
        tag_end += read
    end = size - _read_id3v1(f, size, info)
    end -= _ape_footer_size(f, end)
    f.seek(tag_end)
    data = f.read(_SYNC_SEARCH)
    pos = 0
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 4 > len(data):
            return
        frame = _mp3_frame(data[pos:pos + 4])
        if frame:
            length = _frame_length(*frame[:5])
            following = data[pos + length:pos + length + 4]
            # A real frame is followed by another one (or the end of the data read).
            if length > 4 and (len(following) < 4 or _mp3_frame(following)):
                break
        pos += 1
    version, layer, bitrate, rate, _, channels = frame
    start = tag_end + pos
    info["audio_start"], info["audio_end"] = start, end
    samples_per_frame = 384 if layer == 1 else (1152 if layer == 2 or version == 1 else 576)
    side_info = (32 if channels == 2 else 17) if version == 1 else (17 if channels == 2 else 9)
    xing = data[pos + 4 + side_info:pos + 4 + side_info + 12]
    frames = None
    if xing[:4] in (b"Xing", b"Info") and struct.unpack(">I", xing[4:8])[0] & 1:
        frames = struct.unpack(">I", xing[8:12])[0]
    elif data[pos + 36:pos + 40] == b"VBRI":
        frames = struct.unpack(">I", data[pos + 50:pos + 54])[0]
    if frames:
        info["duration"] = frames * samples_per_frame / rate
    elif bitrate:
        info["duration"] = (end - start) * 8 / (bitrate * 1000)


def _read_flac(f, info):
    _read_id3v2(f, {})
    if f.read(4) != b"fLaC":
        return
    while True:
        header = f.read(4)
        if len(header) < 4:
            return
        last, kind = header[0] & 0x80, header[0] & 0x7F
        length = int.from_bytes(header[1:4], "big")
        block = f.read(length)
        if kind == 0 and len(block) >= 18:
            packed = int.from_bytes(block[10:18], "big")
            rate, total = packed >> 44, packed & 0xFFFFFFFFF
            if rate and total:
                info["duration"] = total / rate
        elif kind == 4:
            _read_vorbis_comment(block, info)
        if last:
            return


def _read_vorbis_comment(block, info):
    vendor = struct.unpack("<I", block[:4])[0]
    pos = 4 + vendor
    count = struct.unpack("<I", block[pos:pos + 4])[0]
    pos += 4
    for _ in range(count):
        length = struct.unpack("<I", block[pos:pos + 4])[0]
        entry = block[pos + 4:pos + 4 + length].decode("utf-8", "replace")
        pos += 4 + length
        name, _, value = entry.partition("=")
        key = _VORBIS_KEYS.get(name.upper())
        if key and not info.get(key):
            info[key] = _clean(value)


def _read_wav(f, size, info):
    if f.read(12)[8:12] != b"WAVE":
        return
    byte_rate = data_size = None
    while f.tell() + 8 <= size:
        chunk_id, length = struct.unpack("<4sI", f.read(8))
        body_at = f.tell()
        if chunk_id == b"fmt ":
            byte_rate = struct.unpack("<I", f.read(16)[8:12])[0]
        elif chunk_id == b"data":
            data_size = min(length, size - body_at)
        elif chunk_id == b"LIST" and f.read(4) == b"INFO":
            end = body_at + length
            while f.tell() + 8 <= end:
                key, item_length = struct.unpack("<4sI", f.read(8))
                value = f.read(item_length)
                if item_length % 2:
                    f.read(1)
                field = _RIFF_KEYS.get(key)
                if field and not info.get(field):
                    info[field] = _clean(decode_text(value.split(b"\x00", 1)[0]))
        f.seek(body_at + length + (length % 2))
    if byte_rate and data_size:
        info["duration"] = data_size / byte_rate
