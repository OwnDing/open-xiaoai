"""Lay the film out in time from the real voice-line durations.

Every shot is written as a little script against a cursor: wait, speak a line,
drop a named mark. The result (build/timeline.json) is the single source of
truth for the Blender plates, the HTML compositor and the audio mix.

Several shots can share one plate (one continuous camera move): the plate's
time runs on across them, and their marks are stored as "<shot>.<mark>".
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "build" / "audio" / "voice" / "meta.json").read_text())
FPS = 24
HANDLE = 12  # extra plate frames rendered before and after each plate, for transitions


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

    def end_of(self, lid):
        placed = next(l for l in self.lines if l["id"] == lid)
        return round(placed["t"] + placed["dur"], 3)

    def word_time(self, lid, word):
        """Time of the first word boundary starting with `word` in a placed line."""
        placed = next(l for l in self.lines if l["id"] == lid)
        for w in META[lid]["words"]:
            if w["text"].startswith(word):
                return round(placed["t"] + max(w["t"], 0), 3)
        raise KeyError(f"{word!r} not in {lid}")


# ---------------------------------------------------------------- prologue

def s01(c):
    c.mark("door", 0.5).wait(2.3).line("U01").wait(0.3).mark("ring", -0.3).line("Q01").wait(0.55)


def s02(c):
    c.wait(0.2).line("U02").wait(0.08).mark("thread")
    c.wait(1.05).mark("arrive").wait(0.45).mark("burst")
    c.wait(0.15).line("Q02", advance=False)
    c.marks["pendant"] = round(c.marks["burst"] + 0.9, 3)
    c.marks["floor"] = round(c.marks["burst"] + 1.12, 3)
    c.marks["ac"] = round(c.marks["burst"] + 1.38, 3)
    c.marks["curtain"] = round(c.marks["burst"] + 1.55, 3)
    c.t = c.end_of("Q02")
    c.wait(0.35)


def s03(c):
    c.wait(0.5).line("N01").mark("title", 0.1).wait(2.7)


# ---------------------------------------------------------------- act 1: pain

def s04(c):
    c.wait(0.35).line("N02").wait(0.35).line("U03").wait(0.5).mark("reply").line("X01").mark("fail", -0.15)
    c.wait(0.3).mark("card").wait(1.75)


def s05(c):
    c.wait(0.3).mark("silos").line("N03").mark("card", -0.9).wait(1.3)


def s06(c):
    c.wait(0.5).mark("glass").wait(0.2).mark("rise").line("N04").wait(0.35).line("N05")
    c.wait(0.75).mark("silence").line("N06").mark("card", -0.2).wait(1.4)


def s07(c):
    c.wait(0.15).mark("w1").wait(0.5).mark("w2").wait(0.5).mark("w3").wait(1.0).mark("collapse").wait(0.75)


# ---------------------------------------------------------------- act 2: turn

def s08(c):
    c.mark("spark", 0.0).wait(0.45).mark("reverse").wait(0.9).line("N07", advance=False)
    c.wait(0.5).mark("solid").wait(0.9).mark("dome")
    c.t = max(c.t, c.end_of("N07"))
    c.wait(0.35).mark("title").wait(2.6)


# ---------------------------------------------------------------- act 3: the recipe

def s09(c):
    c.mark("light_l", 0.25).mark("light_r", 1.0).wait(0.5).line("N08").wait(0.75)


def s10(c):
    c.wait(0.5).line("N09").wait(1.4)


def s11(c):
    c.wait(0.35).mark("sweep").wait(0.2).line("N10").wait(0.9)


def s12(c):
    c.mark("l1", 0.2).mark("l2", 0.75).wait(0.4).line("N11").wait(1.5)


# ---------------------------------------------------------------- act 4: privacy

def s13(c):
    c.mark("wave", 0.25).wait(0.6).line("N12").wait(0.4).line("N13").wait(1.7)


# ---------------------------------------------------------------- act 5: it understands

def s14(c):
    c.wait(0.75).line("U04").mark("thread", 0.1).wait(0.6).line("Q03", advance=False)
    c.marks["arrive"] = round(c.marks["thread"] + 0.6, 3)
    c.marks["ac"] = round(c.marks["thread"] + 1.25, 3)
    c.t = c.end_of("Q03")
    c.wait(1.0)


def s15(c):
    c.wait(0.6).line("U05").wait(0.35).line("Q04").wait(0.35).mark("lapse").wait(2.7).mark("done")
    c.wait(0.25).mark("thread").wait(1.0).mark("arrive").wait(0.1).line("Q05").wait(1.0)


def s16(c):
    c.mark("card", 0.15).wait(1.1).line("U06").wait(0.35).line("Q06").mark("rule", -0.9)
    c.wait(0.25).mark("fly").line("N14").wait(0.7)


# ---------------------------------------------------------------- act 6: it can see

def s17(c):
    c.wait(0.5).line("N15").wait(0.25).mark("alert").line("Q07").wait(1.0)


def s18(c):
    c.wait(0.6).line("K01").wait(0.45).mark("detect", -0.2).line("Q08").wait(0.4).line("N16").wait(0.8)


# ---------------------------------------------------------------- act 7: vision

def s19(c):
    c.wait(0.8).line("N17").wait(0.6).line("N18").wait(2.0)


def s20(c):
    c.wait(0.7).line("N19").wait(3.6)


# (shot id, act, plate id or None, builder)
SHOTS = [
    ("S01", 0, "P01", s01),
    ("S02", 0, "P01", s02),
    ("S03", 0, "P01", s03),
    ("S04", 1, "P04", s04),
    ("S05", 1, "P05", s05),
    ("S06", 1, "P06", s06),
    ("S07", 1, "P06", s07),
    ("S08", 2, "P06", s08),
    ("S09", 3, "P09", s09),
    ("S10", 3, "P10", s10),
    ("S11", 3, "P11", s11),
    ("S12", 3, "P11", s12),
    ("S13", 4, "P13", s13),
    ("S14", 5, "P14", s14),
    ("S15", 5, "P15", s15),
    ("S16", 5, "P16", s16),
    ("S17", 6, "P17", s17),
    ("S18", 6, "P18", s18),
    ("S19", 7, "P19", s19),
    ("S20", 7, None, s20),
]


def post_marks(sid, c):
    """Marks that depend on word timings inside lines."""
    W = c.word_time
    if sid == "S06":
        c.marks["cloud"] = W("N04", "云端")
    if sid == "S10":
        c.marks["ear"] = W("N09", "耳朵")
        c.marks["mouth"] = W("N09", "嘴巴")
    if sid == "S11":
        c.marks["brain"] = W("N10", "大脑")
    if sid == "S12":
        c.marks["l3"] = W("N11", "Hermes")
        c.marks["l4"] = W("N11", "Home")
        c.marks["api"] = round(c.end_of("N11") + 0.15, 3)
    if sid == "S13":
        c.marks["wake"] = W("N12", "唤醒")
        c.marks["asr"] = W("N12", "语音")
        c.marks["text"] = round(c.end_of("N12") - 0.4, 3)
        c.marks["wall"] = W("N13", "不")
        c.marks["send"] = W("N13", "交给")
        c.marks["api"] = W("N13", "大")
        c.marks["reply"] = round(c.marks["api"] + 1.4, 3)
        c.marks["devices"] = round(c.marks["api"] + 2.1, 3)
    if sid == "S14":
        c.marks["remind"] = W("Q03", "十点")
    if sid == "S16":
        c.marks["app"] = W("N14", "不用")
    if sid == "S17":
        c.marks["cam"] = W("N15", "接上")
        c.marks["detect"] = W("N15", "看见")
    if sid == "S18":
        c.marks["count"] = W("Q08", "图")
    if sid == "S19":
        c.marks["k1"] = W("N17", "听")
        c.marks["k2"] = W("N17", "管")
        c.marks["k3"] = W("N17", "守")
        c.marks["claim"] = W("N18", "家")


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
        if pid:
            p = plates.setdefault(pid, {"id": pid, "frames": 0, "shots": [], "lines": [], "marks": {}})
            shot["plate_offset"] = p["frames"]
            off = p["frames"] / FPS
            p["shots"].append(sid)
            p["lines"] += [dict(l, t=round(l["t"] + off, 3)) for l in c.lines]
            p["marks"].update({f"{sid}.{k}": round(v + off, 3) for k, v in c.marks.items()})
            p["marks"][f"{sid}.start"] = round(off, 3)
            p["frames"] += frames
        shots.append(shot)
        t = (start_f + frames) / FPS
    total = shots[-1]["start"] + shots[-1]["frames"]
    tl = {"fps": FPS, "handle": HANDLE, "frames": total, "shots": shots, "plates": plates}
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build" / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))
    for s in shots:
        print(f"{s['id']} {s['plate'] or '--':5} {s['start']/FPS:7.2f}s  {s['frames']/FPS:5.2f}s  "
              + " ".join(l["id"] for l in s["lines"]))
    print(f"total {total/FPS:.2f}s ({total} frames)")
    n = 0
    for p in plates.values():
        n += p["frames"] + 2 * HANDLE
        print(p["id"], p["frames"] + 2 * HANDLE, "frames", ",".join(p["shots"]))
    print("plate frames", n)


if __name__ == "__main__":
    build()
