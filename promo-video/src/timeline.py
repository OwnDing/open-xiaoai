"""Lay the film out in time from the real voice-line durations.

Every shot is written as a little script against a cursor: wait, speak a line,
drop a named mark. The result (build/timeline.json) is the single source of
truth for the Blender plates, the HTML compositor and the audio mix.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "build" / "audio" / "voice" / "meta.json").read_text())
FPS = 30
HANDLE = 15  # extra plate frames rendered before and after each plate, for transitions


class Cursor:
    def __init__(self):
        self.t = 0.0
        self.lines = []
        self.marks = {}

    def wait(self, s):
        self.t += s
        return self

    def mark(self, name, offset=0.0):
        self.marks[name] = round(self.t + offset, 3)
        return self

    def line(self, lid, advance=True):
        m = META[lid]
        self.lines.append({"id": lid, "role": m["role"], "t": round(self.t, 3), "dur": m["dur"]})
        if advance:
            self.t += m["dur"]
        return self

    def word_time(self, lid, word):
        """Time of the first word boundary starting with `word` in a placed line."""
        placed = next(l for l in self.lines if l["id"] == lid)
        for w in META[lid]["words"]:
            if w["text"].startswith(word):
                return round(placed["t"] + max(w["t"], 0), 3)
        raise KeyError(f"{word!r} not in {lid}")


def s01(c):
    c.wait(1.6).line("N01").wait(0.5)


def s02(c):
    c.wait(0.35).line("N02").wait(1.1)


def s03(c):
    c.wait(0.6).line("U01").wait(0.55).mark("think").wait(0.0).line("X01").mark("fail", -0.2)
    c.wait(0.25).mark("card").wait(1.7)


def s04(c):
    c.wait(0.45).line("U02").wait(0.6).line("X02").mark("fail", -0.2)
    c.wait(0.25).mark("card").wait(1.7)


def s05(c):
    c.wait(0.5).mark("silos").line("N03")
    c.mark("card", -1.6).wait(1.3)


def s06(c):
    c.wait(0.15).line("N04").mark("collapse", -0.5).wait(0.55)


def s07(c):
    c.wait(1.1).line("N05")
    c.mark("impact", -0.25).wait(2.1)


def s08(c):
    c.wait(0.35).line("N06")
    c.wait(0.3).line("U03").wait(0.3).mark("wake").line("Q00").wait(0.9)


def s09(c):
    c.wait(0.5).line("N07").wait(0.45).line("N08").wait(0.9)


def s10(c):
    c.wait(1.0).line("U04").wait(0.75).mark("ac").wait(0.35).line("Q01").wait(0.9)


def s11(c):
    c.wait(0.5).line("U05").wait(0.45).mark("light_off").wait(0.35).mark("curtain")
    c.wait(0.2).line("Q02").wait(1.0)


def s12(c):
    c.wait(1.2).line("U06").wait(0.55).mark("memory").line("Q03").wait(0.9)


def s13(c):
    c.wait(1.5).line("U07").wait(0.5).mark("study_off").wait(0.35).mark("living_off")
    c.wait(0.35).line("Q04").wait(1.3)


def s14(c):
    c.wait(0.35).line("N09").wait(0.7)


def s15(c):
    c.wait(0.9).line("N10").wait(2.2)


def s16(c):
    c.wait(0.6).line("N11").wait(3.4)


# (shot id, act, plate id or None, builder)
SHOTS = [
    ("S01", 0, "P01", s01),
    ("S02", 0, "P02", s02),
    ("S03", 1, "P03", s03),
    ("S04", 1, "P04", s04),
    ("S05", 1, "P05", s05),
    ("S06", 1, "P05", s06),
    ("S07", 2, "P06", s07),
    ("S08", 2, "P07", s08),
    ("S09", 3, "P08", s09),
    ("S10", 4, "P09", s10),
    ("S11", 4, "P10", s11),
    ("S12", 4, "P11", s12),
    ("S13", 4, "P12", s13),
    ("S14", 4, "P07B", s14),
    ("S15", 5, "P13", s15),
    ("S16", 5, None, s16),
]


def post_marks(sid, c):
    """Marks that depend on word timings inside lines."""
    if sid == "S09":
        for name, lid, word in [
            ("n_voice", "N07", "声音"), ("n_asr", "N07", "识别"), ("n_hermes", "N07", "Hermes"),
            ("n_think", "N07", "思考"), ("n_ha", "N07", "Home"), ("n_devices", "N07", "全"),
            ("n_login", "N08", "小米"), ("n_mijia", "N08", "米"), ("n_other", "N08", "其他"),
        ]:
            c.marks[name] = c.word_time(lid, word)
    if sid == "S08":
        c.marks["left"] = c.word_time("N06", "原来")
        c.marks["right"] = c.word_time("N06", "喊")
    if sid == "S10":
        c.marks["remind"] = c.word_time("Q01", "十点")
    if sid == "S13":
        c.marks["ac25"] = c.word_time("Q04", "卧室")
        c.marks["window"] = c.word_time("Q04", "阳台")
        c.marks["night"] = c.word_time("Q04", "晚安")
    if sid == "S14":
        for i, word in enumerate(["查", "定", "学会", "它"]):
            c.marks[f"card{i}"] = c.word_time("N09", word)
    if sid == "S07":
        c.marks["title"] = c.marks["impact"]


def build():
    shots, plates = [], {}
    t = 0.0
    for sid, act, pid, fn in SHOTS:
        c = Cursor()
        fn(c)
        post_marks(sid, c)
        frames = round(c.t * FPS)
        start_f = round(t * FPS)
        shot = {
            "id": sid, "act": act, "plate": pid,
            "start": start_f, "frames": frames,
            "lines": c.lines, "marks": c.marks,
        }
        if pid == "P07B":
            shot["plate_offset"] = 0  # reuses the warm half of the dual-speaker plate
        elif pid:
            p = plates.setdefault(pid, {"id": pid, "frames": 0, "shots": [], "lines": [], "marks": {}})
            shot["plate_offset"] = p["frames"]
            off = p["frames"] / FPS
            p["shots"].append(sid)
            p["lines"] += [dict(l, t=round(l["t"] + off, 3)) for l in c.lines]
            p["marks"].update({f"{sid}.{k}": round(v + off, 3) for k, v in c.marks.items()})
            p["frames"] += frames
        shots.append(shot)
        t = (start_f + frames) / FPS
    # The S08 split screen needs a warm twin of P07; S14 plays it again as a backdrop.
    plates["P07B"] = dict(plates["P07"], id="P07B", shots=["S08", "S14"])
    assert next(s for s in shots if s["id"] == "S14")["frames"] <= plates["P07B"]["frames"] + HANDLE
    total = shots[-1]["start"] + shots[-1]["frames"]
    tl = {"fps": FPS, "handle": HANDLE, "frames": total, "shots": shots, "plates": plates}
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build" / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))
    for s in shots:
        print(f"{s['id']} {s['plate'] or '--':5} {s['start']/FPS:7.2f}s  {s['frames']/FPS:5.2f}s  "
              + " ".join(l["id"] for l in s["lines"]))
    print(f"total {total/FPS:.2f}s ({total} frames)")
    for p in plates.values():
        print(p["id"], p["frames"] + 2 * HANDLE, "frames")


if __name__ == "__main__":
    build()
