"""Lay the film out in time from the real voice-line durations.

Every shot is written as a little script against a cursor: wait, speak a line,
drop a named mark. The result (build/timeline.json) is the single source of
truth for the TV screens, the Blender plates, the HTML compositor and the mix.

Several shots can share one plate (one continuous camera move): the plate's
time runs on across them, and their marks are stored as "<shot>.<mark>".
Shots can also carry data (S05's 37 remote presses), shifted the same way.
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
        self.data = {}

    def wait(self, s):
        self.t += s
        return self

    def mark(self, name, offset=0.0):
        self.marks[name] = round(self.t + offset, 3)
        return self

    def at(self, name, t):
        self.marks[name] = round(t, 3)
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

    def start_of(self, lid):
        return next(l for l in self.lines if l["id"] == lid)["t"]

    def word_time(self, lid, word, nth=0):
        """Time of the nth word boundary starting with `word` in a placed line."""
        placed = next(l for l in self.lines if l["id"] == lid)
        hits = [w for w in META[lid]["words"] if w["text"].startswith(word)]
        if len(hits) <= nth:
            raise KeyError(f"{word!r} not in {lid}")
        return round(placed["t"] + max(hits[nth]["t"], 0), 3)


# ---------------------------------------------------------------- remote presses (S05)

# Launcher 电视直播 -> 奇异果; tab 电视剧 -> 搜索; keyboard A -> W (overshoot to X), W -> G;
# across the keyboard into the first result; episodes 1 -> 3 (overshoot) -> 2, OK.
PRESS_KEYS = (["left"] * 3 + ["ok"]
              + ["up", "left", "left", "ok"]
              + ["down"] * 3 + ["right"] * 5 + ["left", "ok"]
              + ["up"] * 2 + ["left"] * 4 + ["ok"]
              + ["right"] * 6 + ["ok"]
              + ["down", "right", "right", "left", "ok"])
assert len(PRESS_KEYS) == 37


def press_schedule(t0, t1):
    """Presses spread over [t0, t1]: slow at first, then faster; a beat of loading after each OK."""
    gaps = []
    n = len(PRESS_KEYS)
    for i, k in enumerate(PRESS_KEYS):
        u = i / (n - 1)
        g = 0.3 - 0.16 * u
        if i and PRESS_KEYS[i - 1] == "ok":
            g += 0.22
        gaps.append(g)
    gaps[0] = 0.0
    total = sum(gaps)
    t, out = t0, []
    for k, g in zip(PRESS_KEYS, gaps):
        t += g * (t1 - t0) / total
        out.append([round(t, 3), k])
    return out


# ---------------------------------------------------------------- prologue

def s01(c):
    c.wait(1.9).mark("focus", -0.15).line("U01").wait(0.3).line("Q01").wait(0.35)


def s02(c):
    """The magic in one take: thread to the mini PC, IR power-on, app, search, play, episode 2, verified."""
    c.wait(0.2).line("U02").wait(0.05).mark("thread")
    c.wait(0.85).mark("arrive").wait(0.45).mark("ir")
    c.wait(0.35).mark("tv_on").wait(0.65).mark("launcher")
    c.wait(0.55).mark("app").wait(0.55).mark("search")
    c.wait(0.6).mark("play").wait(0.55).mark("ep").wait(0.6).mark("ep2").wait(0.45).mark("verify")
    c.wait(0.25).line("Q02").wait(0.45)


def s03(c):
    c.wait(0.4).line("N01").mark("title", 0.1).wait(3.0)


# ---------------------------------------------------------------- act 1: only a switch

def s04(c):
    c.wait(0.3).line("N02").wait(0.3).line("U03").wait(0.3).mark("ack").line("X01")
    c.marks["ir"] = round(c.marks["ack"] + 0.15, 3)
    c.marks["tv_on"] = round(c.marks["ir"] + 0.3, 3)
    c.wait(0.9).line("U04").wait(0.5).mark("reply").line("X02").mark("fail", -0.15)
    c.wait(0.3).mark("card").wait(1.8)


def s05(c):
    c.wait(0.5).line("N03").wait(0.7)
    c.data["presses"] = press_schedule(0.45, c.t - 0.15)
    c.at("last", c.data["presses"][-1][0])
    c.wait(0.25).mark("card").wait(1.6)


def s06(c):
    c.wait(0.3).mark("tvs").wait(0.3).line("N04").wait(0.15)
    c.mark("card", -1.6).wait(1.3)


def s07(c):
    c.wait(0.15).mark("w1").wait(0.5).mark("w2").wait(0.5).mark("w3").wait(1.0).mark("collapse").wait(0.75)


# ---------------------------------------------------------------- act 2: the turn

def s08(c):
    c.mark("spark").wait(0.25).mark("led").wait(0.35).line("N05", advance=False)
    c.wait(0.4).mark("wake")
    c.t = c.end_of("N05")
    c.wait(0.3).mark("claim").wait(2.5)


# ---------------------------------------------------------------- act 3: eyes and hands

def s09(c):
    c.mark("l1", 0.25).mark("l2", 0.9).mark("l3", 1.55).wait(0.5).line("N06").wait(0.6)


def s10(c):
    c.wait(0.3).line("N07").wait(0.8)


def s11(c):
    c.wait(0.25).line("N08").wait(0.9)


def s12(c):
    c.wait(0.4).line("N09").wait(1.7)


# ---------------------------------------------------------------- act 4: one sentence each

def s13(c):
    """The opening sentence, replayed step by step; step 6 lands on "第二集" in N11."""
    c.wait(0.4).line("N10").wait(0.3).line("N11").wait(1.0)


def s14(c):
    c.wait(0.5).line("U06").wait(0.3).mark("seek").line("Q04")
    c.wait(0.45).line("U05").wait(0.3).mark("next").line("Q03")
    c.wait(0.45).line("U07").wait(0.25).mark("vol").line("Q05").wait(0.8)


def s15(c):
    c.wait(0.5).line("U08").wait(0.2).mark("app").wait(1.1).mark("daily").wait(1.0).mark("all")
    c.wait(0.5).line("Q06").wait(1.6)


def s16(c):
    c.wait(0.5).line("U09").wait(0.2).mark("app").wait(0.9).mark("click").wait(0.6).mark("type")
    c.wait(0.6).mark("enter").wait(0.8).mark("page").wait(0.3).line("Q07").wait(1.4)


def s17(c):
    c.wait(0.5).line("U10").wait(0.3).mark("off").wait(0.4).line("Q08").wait(1.4)


# ---------------------------------------------------------------- act 5: the remote retires

def s18(c):
    c.wait(0.6).line("N12").wait(0.6).mark("retire").line("N13").wait(2.6)


def s19(c):
    c.wait(0.7).line("N14").wait(3.6)


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
    ("S11", 3, "P10", s11),
    ("S12", 3, "P10", s12),
    ("S13", 4, "P13", s13),
    ("S14", 4, "P14", s14),
    ("S15", 4, "P15", s15),
    ("S16", 4, "P16", s16),
    ("S17", 4, "P17", s17),
    ("S18", 5, "P18", s18),
    ("S19", 5, None, s19),
]


def post_marks(sid, c):
    """Marks that depend on word timings inside lines."""
    W = c.word_time
    if sid == "S05":
        c.marks["tvfocus"] = W("N03", "拼")
    if sid == "S06":
        c.marks["a"] = W("N04", "按")
        c.marks["b"] = W("N04", "换")
        c.marks["c"] = W("N04", "管")
    if sid == "S08":
        c.marks["scan"] = W("N05", "每")
        c.marks["thread"] = W("N05", "小七")
    if sid == "S09":
        c.marks["b1"] = W("N06", "音箱")
        c.marks["b2"] = W("N06", "迷你")
        c.marks["b3"] = W("N06", "电视")
    if sid == "S10":
        c.marks["scan"] = W("N07", "不")
        c.marks["read"] = W("N07", "读完")
    if sid == "S11":
        c.marks["type"] = W("N08", "打字")
        c.marks["click"] = W("N08", "点")
        c.marks["keys"] = W("N08", "按", 1)
        c.marks["media"] = W("N08", "控制")
    if sid == "S12":
        c.marks["n1"] = round(c.start_of("N09") - 0.1, 3)
        c.marks["n2"] = round(c.start_of("N09") + 0.45, 3)
        c.marks["n3"] = round(c.start_of("N09") + 1.0, 3)
        c.marks["ir"] = W("N09", "红外")
        c.marks["lan"] = W("N09", "局域网")
    if sid == "S13":
        k6 = W("N11", "第二集")
        k1 = c.start_of("N10") + 0.25
        for i in range(6):
            c.marks[f"k{i + 1}"] = round(k1 + (k6 - k1) * i / 5, 3)
        c.marks["ok"] = W("N11", "开始")
    if sid == "S18":
        for i, w in enumerate(("开机", "找", "选集", "上网", "听歌")):
            c.marks[f"k{i + 1}"] = W("N12", w)
        c.marks["claim"] = W("N12", "电视")


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
            "lines": c.lines, "marks": c.marks, "data": c.data,
        }
        if pid:
            p = plates.setdefault(pid, {"id": pid, "frames": 0, "shots": [], "lines": [], "marks": {}, "data": {}})
            shot["plate_offset"] = p["frames"]
            off = p["frames"] / FPS
            p["shots"].append(sid)
            p["lines"] += [dict(l, t=round(l["t"] + off, 3)) for l in c.lines]
            p["marks"].update({f"{sid}.{k}": round(v + off, 3) for k, v in c.marks.items()})
            p["marks"][f"{sid}.start"] = round(off, 3)
            p["marks"][f"{sid}.end"] = round(off + frames / FPS, 3)
            if "presses" in c.data:
                p["data"][f"{sid}.presses"] = [[round(pt + off, 3), k] for pt, k in c.data["presses"]]
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
