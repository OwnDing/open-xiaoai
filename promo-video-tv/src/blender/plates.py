"""Per-plate staging: camera moves, light cues, voice threads, rings, the TV screens.

Each plate function receives a Ctx and returns update(t), where t is plate time
in seconds (0 = first frame of the plate's first shot; the render also covers
HANDLE frames before 0 and after the end for transitions). update(t) must be a
pure function of t: motion blur evaluates sub-frames out of order.
"""
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

import props as Pr
import room
import studio
import tvset
from kit import REG, set_group
from room import REMOTE, SPEAKER, TV_CENTER
from scene import P_BRAIN, P_LED, P_PC, P_SPEAKER, P_TV
from studio import CASE, STUDIO, TR_PC, TR_SPEAKER, TR_TV, TVS

ROOT = Path(__file__).resolve().parents[2]

# Which TV shows which rendered screen sequence (build/screens/<plate>/<screen>).
SCREENS = {
    "P01": {"tv": "main"}, "P04": {"tv": "main"}, "P05": {"tv": "main"},
    "P06": {"ta": "a", "tb": "c", "tc": "b"},
    "P09": {"trtv": "studio"}, "P10": {"trtv": "studio"},
    "P13": {"tv": "main"}, "P14": {"tv": "main"}, "P15": {"tv": "main"}, "P16": {"tv": "main"}, "P17": {"tv": "main"},
}


# ---------------------------------------------------------------- helpers

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(t, a, b):
    """0 before a, 1 after b, smoothstep in between."""
    if b <= a:
        return 1.0 if t >= a else 0.0
    u = clamp((t - a) / (b - a))
    return u * u * (3 - 2 * u)


def smoother(u):
    u = clamp(u)
    return u * u * u * (u * (6 * u - 15) + 10)


def lerp(a, b, u):
    if isinstance(a, (tuple, list, Vector)):
        return Vector([x + (y - x) * u for x, y in zip(a, b)])
    return a + (b - a) * u


def glide(u, k=0.55):
    """Mostly linear with soft ends, so moves never stop dead inside handles."""
    u = clamp(u)
    return (1 - k) * u + k * u * u * (3 - 2 * u)


def win(t, a, b, fi=0.2, fo=0.2):
    return smooth(t, a, a + fi) * (1 - smooth(t, b - fo, b))


def look(pos, target, lens, fstop, focus=None):
    cam = REG["cam"]
    pos, target = Vector(pos), Vector(target)
    d = target - pos
    cam.location = pos
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = d.to_track_quat("-Z", "Y")
    cam.data.lens = lens
    cam.data.dof.aperture_fstop = fstop
    cam.data.dof.focus_distance = focus if focus is not None else d.length


class Path_:
    """Camera keyframes [(t, pos, target, lens, fstop, focus_point_or_None)], smooth in time."""

    def __init__(self, keys, ease=0.6):
        self.keys = keys
        self.ease = ease

    def at(self, t):
        ks = self.keys
        if t <= ks[0][0]:
            i, u = 0, 0.0
        elif t >= ks[-1][0]:
            i, u = len(ks) - 2, 1.0
        else:
            i = max(j for j in range(len(ks) - 1) if ks[j][0] <= t)
            u = (t - ks[i][0]) / (ks[i + 1][0] - ks[i][0])
        u = glide(u, self.ease)

        def cr(idx):
            p = [Vector(ks[max(0, min(len(ks) - 1, j))][idx]) for j in (i - 1, i, i + 1, i + 2)]
            p0, p1, p2, p3 = p
            u2, u3 = u * u, u * u * u
            return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * u3)
        pos, tgt = cr(1), cr(2)
        lens = lerp(ks[i][3], ks[i + 1][3], smoother(u))
        fstop = lerp(ks[i][4], ks[i + 1][4], smoother(u))
        f0 = ks[i][5] if ks[i][5] is not None else ks[i][2]
        f1 = ks[i + 1][5] if ks[i + 1][5] is not None else ks[i + 1][2]
        fp = lerp(Vector(f0), Vector(f1), smoother(u))
        return pos, tgt, lens, fstop, (fp - pos).length

    def apply(self, t):
        pos, tgt, lens, fstop, focus = self.at(t)
        look(pos, tgt, lens, fstop, focus=focus)
        return pos


def show(name, on):
    if name in REG["colls"]:
        REG["colls"][name].hide_render = not on


def groups(**levels):
    for g, v in levels.items():
        set_group(g, v)


def exposure(ev):
    bpy.context.scene.view_settings.exposure = ev


def all_groups_off():
    for g in REG["groups"]:
        set_group(g, 0.0)


def threads_off():
    for name in REG["threads"]:
        Pr.set_thread(name, 0.0, 0.0)


THREAD_GAIN = 0.5


def fire(name, t, t0, dur, strength=6.0, tail=0.35, trail=0.0, keep=None):
    """Send one pulse along a thread starting at t0, travelling for dur seconds."""
    if t < t0:
        Pr.set_thread(name, 0.0, 0.0)
        return False
    strength *= THREAD_GAIN
    trail *= THREAD_GAIN
    u = (t - t0) / dur
    head = u * (1.0 + tail)
    tr = trail
    if keep is not None:
        tr *= 1 - smooth(t, t0 + dur + keep, t0 + dur + keep + 0.8)
    Pr.set_thread(name, head, strength, tail=tail, trail=tr / max(strength, 1e-6) if strength else 0)
    return u >= 1.0


def fire_many(name, t, starts, dur, **kw):
    """Several pulses on one thread: the most recent one that has started wins."""
    past = [s for s in starts if s <= t]
    if not past:
        Pr.set_thread(name, 0.0, 0.0)
        return
    fire(name, t, past[-1], dur, **kw)


def decay(t, t0, rate=3.0):
    return math.exp(-max(0.0, t - t0) * rate) if t >= t0 else 0.0


class Ctx:
    def __init__(self, plate, meta, fps, handle):
        self.id = plate["id"]
        self.frames = plate["frames"]
        self.dur = plate["frames"] / fps
        self.lines = plate["lines"]
        self.marks = plate["marks"]
        self.data = plate.get("data", {})
        self.meta = meta
        self.fps = fps
        self.handle = handle
        self.hs = handle / fps
        self.light = {}
        for prefix, sid in SCREENS.get(self.id, {}).items():
            f = ROOT / "build" / "screens" / self.id / sid / "light.json"
            self.light[prefix] = json.loads(f.read_text()) if f.exists() else None

    def mark(self, name):
        if name in self.marks:
            return self.marks[name]
        hits = [v for k, v in self.marks.items() if k.endswith("." + name)]
        if len(hits) != 1:
            raise KeyError(f"{name}: {len(hits)} matches")
        return hits[0]

    def line(self, lid):
        return next(l for l in self.lines if l["id"] == lid)

    def u(self, t):
        """Camera progress across the whole rendered range, handles included."""
        return clamp((t + self.hs) / (self.dur + 2 * self.hs))

    def env(self, line, t):
        e = self.meta[line["id"]]["env"]
        i = int((t - line["t"]) * self.fps)
        return e[i] if 0 <= i < len(e) else 0.0

    def screen(self, prefix, t, gain=1.0, **kw):
        """Light the TV from its rendered frame (frame f of the plate = screen frame f)."""
        data = self.light.get(prefix)
        if not data:
            tvset.set_screen(prefix, 0.0)
            return 0.0
        f = int(round(t * self.fps)) + self.handle
        f = max(0, min(len(data) - 1, f))
        rgb, on = data[f][:3], data[f][3]
        tvset.set_screen(prefix, 1.0 if on else 0.0, rgb, gain=gain, **kw)
        return on


def ring_drive(c, t, voice, idle_level=1.6, listen_level=5.0, speak_gain=8.0):
    """Ring level and spin speed from the dialogue (listening, thinking, speaking)."""
    idle = idle_level * (0.75 + 0.25 * math.sin(2 * math.pi * t / 3.4))
    listen, speak, think = 0.0, 0.0, 0.0
    lines = c.lines
    for i, l in enumerate(lines):
        end = l["t"] + l["dur"]
        if l["role"] == "user":
            reply = next((m for m in lines[i + 1:] if m["role"] == voice), None)
            if reply is None:
                continue
            listen = max(listen, smooth(t, l["t"] - 0.05, l["t"] + 0.25) * (1 - smooth(t, reply["t"], reply["t"] + 0.2)))
            think = max(think, smooth(t, end, end + 0.2) * (1 - smooth(t, reply["t"], reply["t"] + 0.2)))
        elif l["role"] == voice and l["t"] - 0.1 <= t <= end + 0.3:
            speak = max(speak, c.env(l, t) * (1 - smooth(t, end, end + 0.3)))
            listen = max(listen, 0.55 * (1 - smooth(t, end, end + 0.4)))
    level = idle * (1 - listen) + listen * (listen_level + 0.6 * math.sin(t * 9)) + speak_gain * speak
    spin_speed = 0.35 + 1.2 * listen + 4.5 * think
    return level, spin_speed


class Spin:
    """Integrated spin angle, precomputed so any (sub)frame gets the same value."""

    def __init__(self, c, speed_fn, dt=1 / 480):
        self.t0 = -c.hs - 1.0
        self.dt = dt
        n = int((c.dur + 2 * c.hs + 2.0) / dt) + 2
        self.a = [0.0] * n
        for i in range(1, n):
            self.a[i] = self.a[i - 1] + speed_fn(self.t0 + i * dt) * dt

    def __call__(self, t):
        f = (t - self.t0) / self.dt
        i = max(0, min(len(self.a) - 2, int(f)))
        return self.a[i] + (self.a[i + 1] - self.a[i]) * (f - i)


def ring_spin(c, voice, **kw):
    return Spin(c, lambda t: ring_drive(c, t, voice, **kw)[1])


def brain_state(prefix, root_name, t, grow_t, shrink_t, size=1.0, strength=6.0):
    g = smooth(t, grow_t, grow_t + 0.35) * (1 - smooth(t, shrink_t, shrink_t + 0.4))
    root = REG["objs"][root_name]
    s = size * (0.0001 + g * (0.92 + 0.08 * math.sin(t * 6)))
    root.scale = (s, s, s)
    root.rotation_euler = (0.25 * math.sin(t * 0.7), 0.0, t * 1.4)
    REG[f"{prefix}_strength"].default_value = strength * g
    return g


# ---------------------------------------------------------------- modes

ROOM_COLLS = ("room", "city", "threads_room")
STUDIO_COLLS = ("studio", "st_tvs", "st_trio", "st_museum")


def room_mode(pebble=True, dust=False):
    for name in ROOM_COLLS:
        show(name, True)
    show("living_pebble", pebble)
    show("living_generic", not pebble)
    show("dust", dust)
    for name in STUDIO_COLLS:
        show(name, False)
    threads_off()
    all_groups_off()
    for p in REG["screens"]:
        tvset.set_screen(p, 0.0)
        tvset.set_led(p, 0.0)
    groups(moon=1.0, window=1.0)


def studio_mode(*sets):
    for name in REG["colls"]:
        show(name, False)
    for name in ("studio",) + sets:
        show(name, True)
    all_groups_off()
    threads_off()
    for p in REG["screens"]:
        tvset.set_screen(p, 0.0)
        tvset.set_led(p, 0.0)


def evening(k=1.0):
    """The warm living room in the evening, TV on."""
    groups(floor=0.75 * k, table=0.7 * k, slat=0.7 * k, console=0.6 * k, cove=0.3 * k, fill=0.12 * k,
           window=0.8, moon=1.0)


def studio_glow(color, strength, pos=(-1.6, -0.45, 0)):
    col, s, loc = REG["studio_glow"]
    col.default_value = (*color, 1)
    s.default_value = strength
    loc.default_value = pos


def lights_set(**kw):
    for name, e in kw.items():
        REG["objs"][name].data.energy = e


def remote_presses(prefix, t, presses, flash=True):
    """Buttons go down for ~90 ms per press; the IR window blinks."""
    keys = REG["remote"][prefix]
    depth = {k: 0.0 for k in keys}
    ir = 0.0
    for pt, k in presses:
        if pt - 0.02 <= t <= pt + 0.16:
            d = smooth(t, pt - 0.02, pt + 0.02) * (1 - smooth(t, pt + 0.08, pt + 0.16))
            depth[k] = max(depth.get(k, 0.0), d)
            ir = max(ir, 1.0 if pt <= t <= pt + 0.07 else 0.0)
    for k, d in depth.items():
        tvset.press(prefix, k, d)
    if flash:
        REG["remote_ir"][prefix].default_value = 3.0 * ir


# ---------------------------------------------------------------- P01: the opening take

def p01(c):
    """S01-S03: macro on the remote in the dark; the voice thread flies to the mini PC; IR wakes the TV;
    the camera pulls back over the sofa as episode 2 plays, then settles on the remote for the title."""
    room_mode(pebble=True, dust=True)
    m = {k: c.mark(k) for k in ("focus", "thread", "arrive", "ir", "tv_on", "app", "search", "play", "ep", "ep2",
                                "verify")}
    s3, title = c.mark("S03.start"), c.mark("title")
    spin = ring_spin(c, "xiaoqi")
    rm = REMOTE + Vector((0, 0, 0.012))
    sp = P_SPEAKER + Vector((0, 0, -0.03))
    tv = P_TV
    keys = [
        (-c.hs, rm + Vector((0.1, -0.52, 0.075)), rm + Vector((0.0, 0.6, 0.07)), 42, 1.8, rm),
        (m["focus"] - 0.2, rm + Vector((0.085, -0.47, 0.072)), rm + Vector((0.01, 0.6, 0.07)), 42, 1.8, rm),
        (m["focus"] + 0.9, rm + Vector((0.08, -0.45, 0.074)), rm + Vector((0.06, 0.6, 0.075)), 42, 2.0, sp),
        (m["thread"] - 0.1, rm + Vector((0.06, -0.43, 0.09)), rm + Vector((0.08, 0.6, 0.1)), 42, 2.2, sp),
        (m["arrive"], Vector((-0.55, 2.15, 0.98)), Vector((0.6, 4.7, 0.82)), 32, 2.8, P_PC),
        (m["tv_on"] + 0.2, Vector((-0.3, 2.15, 0.95)), Vector((0.2, 5.4, 1.05)), 32, 3.2, tv),
        (m["verify"] + 0.4, Vector((-0.45, 0.5, 0.98)), Vector((0.05, 5.2, 0.98)), 26, 4.0, tv),
        (s3 + 0.4, Vector((-0.38, 0.62, 0.96)), Vector((0.03, 5.2, 0.96)), 27, 4.0, tv),
        (title - 0.4, rm + Vector((0.07, -0.44, 0.07)), rm + Vector((0.0, 0.6, 0.06)), 35, 2.4, rm),
        (c.dur + c.hs, rm + Vector((0.06, -0.38, 0.06)), rm + Vector((0.0, 0.6, 0.055)), 35, 2.4, rm),
    ]
    cam = Path_(keys, ease=0.45)
    T = m

    def update(t):
        cam.apply(t)
        on = smooth(t, T["tv_on"], T["tv_on"] + 0.6)
        groups(moon=1.0, window=0.9, slat=0.55 * on, console=0.5 * on, floor=0.0, table=0.25 * on, cove=0.0,
               fill=0.05 * on, beam=1.0 - 0.4 * on)
        REG["objs"]["moonbeam"].data.energy = 420 * (1.0 - 0.5 * on)
        exposure(0.6 - 0.35 * on)
        room.set_dust(t, 0.5 * (1 - smooth(t, T["thread"], T["thread"] + 0.8)) + 0.35 * smooth(t, title - 0.5, title + 0.5))
        fire("t_sp_pc", t, T["thread"], 0.85, strength=9.0, tail=0.35, trail=1.2, keep=2.0)
        Pr.set_bar("pc", 0.5 + 6.0 * smooth(t, T["arrive"] - 0.1, T["arrive"] + 0.1) * (1 - smooth(t, T["verify"], T["verify"] + 1.0))
                   + 0.5 * smooth(t, T["verify"], T["verify"] + 1.0))
        brain_state("brain", "brain_root", t, T["arrive"] - 0.05, T["verify"] + 0.3, size=1.0, strength=5.0)
        fire("t_ir", t, T["ir"], 0.35, strength=8.0, tail=0.4, trail=0.6, keep=0.3)
        fire_many("t_pc_tv", t, [T["app"] - 0.45, T["search"] - 0.4, T["play"] - 0.4, T["ep"] - 0.35], 0.4,
                  strength=7.0, tail=0.4, trail=0.6, keep=0.2)
        tvset.set_led("tv", 2.5 * (1 - smooth(t, T["tv_on"] - 0.1, T["tv_on"])))
        c.screen("tv", t)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
    return update


# ---------------------------------------------------------------- P04: a typical cloud speaker, the TV is just a switch

def p04(c):
    room_mode(pebble=False)
    ir, on, fail = c.mark("ir"), c.mark("tv_on"), c.mark("fail")
    spin = ring_spin(c, "generic", idle_level=1.8, listen_level=4.5, speak_gain=5.0)
    gen = SPEAKER + Vector((0, 0, 0.12))

    def update(t):
        u = glide(c.u(t))
        pos = lerp((0.72, 2.1, 0.7), (0.56, 2.16, 0.7), u)
        tgt = lerp((0.0, 4.2, 0.9), (-0.05, 4.2, 0.92), u)
        f = smooth(t, on + 0.3, on + 1.3) * (1 - smooth(t, c.mark("reply") - 0.4, c.mark("reply") + 0.4))
        look(pos, tgt, 25, 2.4, focus=lerp((pos - gen).length, (pos - P_TV).length, f))
        groups(floor=0.6, table=0.45, moon=1.0, window=1.0, fill=0.15, cove=0.12)
        exposure(0.35)
        fire("t_gen_ir", t, ir, 0.3, strength=6.0, tail=0.4, trail=0.4, keep=0.2)
        tvset.set_led("tv", 2.5 * (1 - smooth(t, on - 0.1, on)))
        c.screen("tv", t)
        level, _ = ring_drive(c, t, "generic", idle_level=1.8, listen_level=4.5, speak_gain=5.0)
        if t > fail:
            level *= (0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 40))) * (1 - 0.7 * smooth(t, fail, fail + 0.8))
        Pr.set_ring("gen", level, spin(t), warm=0.0)
    return update


# ---------------------------------------------------------------- P05: 37 presses of the remote

def p05(c):
    room_mode(pebble=True)
    presses = c.data["S05.presses"]
    tvf = c.mark("tvfocus")
    rm = REMOTE + Vector((0, 0, 0.015))
    dpad = REMOTE + Vector((0.018 * math.sin(math.radians(28)), 0.018 * math.cos(math.radians(28)), 0.016))

    def update(t):
        k = smooth(t, tvf - 0.3, tvf + 0.9)
        u = glide(c.u(t))
        pos = lerp(rm + Vector((0.13, -0.27, 0.115)), rm + Vector((0.1, -0.31, 0.13)), u)
        tgt = lerp(dpad + Vector((0.0, 0.01, 0.0)), P_TV + Vector((0.12, 0.0, -0.06)), k)
        lens = lerp(80, 60, k)
        focus = lerp((pos - dpad).length, (pos - P_TV).length, smooth(t, tvf - 0.1, tvf + 0.7))
        look(pos, tgt, lens, lerp(2.0, 2.8, k), focus=focus)
        groups(floor=0.45, table=0.35, moon=1.0, window=0.9, fill=0.1)
        REG["objs"]["moonbeam"].data.energy = 300
        exposure(0.35)
        remote_presses("rm", t, presses)
        c.screen("tv", t)
        Pr.set_ring("sp", 0.0, 0.0)
    return update


# ---------------------------------------------------------------- P06: three TVs, three voices; the turn

def p06(c):
    studio_mode("st_tvs")
    tvs, spark, wake = c.mark("tvs"), c.mark("spark"), c.mark("wake")
    s8, scan, thr = c.mark("S08.start"), c.mark("scan"), c.mark("S08.thread")
    lines_t = c.mark("S06.c")
    ctr = TVS["tb"][0]
    keys = [
        (-c.hs, STUDIO + Vector((0.5, -4.1, 1.75)), STUDIO + Vector((0.05, 0.3, 0.72)), 30, 6.0, ctr),
        (s8, STUDIO + Vector((-0.25, -3.85, 1.65)), STUDIO + Vector((0.0, 0.3, 0.74)), 30, 6.0, ctr),
        (s8 + 1.0, STUDIO + Vector((-0.25, -3.8, 1.65)), STUDIO + Vector((0.0, 0.3, 0.76)), 30, 6.0, ctr),
        (c.dur + c.hs, STUDIO + Vector((0.0, -2.55, 1.28)), ctr + Vector((0, 0, -0.05)), 42, 4.0, ctr),
    ]
    cam = Path_(keys, ease=0.5)

    def update(t):
        cam.apply(t)
        dark = smooth(t, spark - 0.2, spark + 0.4)
        warm = smooth(t, wake, wake + 1.2)
        cold = smooth(t, tvs - 0.5, tvs + 0.5) * (1 - dark)
        lights_set(ta_spot=40 * cold, tc_spot=40 * cold, tb_spot=40 * cold * (1 - warm) + 14 * warm,
                   hub_spot=26 * cold)
        REG["objs"]["tb_spot"].data.color = lerp((0.75, 0.85, 1.0), (1.0, 0.75, 0.5), warm)
        studio_glow(lerp((0.4, 0.6, 1.0), (1.0, 0.55, 0.3), warm), 0.25 * cold + 0.45 * warm, pos=(-1.6, -0.45, 0))
        for name in ("ta", "tb", "tc"):
            c.screen(name, t)
            tvset.set_led(name, 2.0 * (1 - smooth(t, tvs - 0.6, tvs - 0.5)) * (1 - dark) + (
                2.5 * dark * (1 - smooth(t, wake - 0.1, wake)) if name == "tb" else 0))
        for i, name in enumerate(("ta", "tb", "tc")):
            fire(f"hub_{name}", t, lines_t + 0.15 * i, 0.6, strength=5.0, tail=0.5, trail=1.4, keep=2.2)
            if t > spark:
                Pr.set_thread(f"hub_{name}", 0.0, 0.0)
        Pr.set_ring("hubsp", 1.5 * (1 - dark), t * 0.4, warm=0.0)
        REG["bloom"].inputs["Strength"].default_value = 0.45 + 0.6 * decay(t, s8, 2.5)
    return update


# ---------------------------------------------------------------- studio: the trio, the eyes and hands

def p09(c):
    studio_mode("st_trio")
    l1, l2, l3 = c.mark("l1"), c.mark("l2"), c.mark("l3")
    mid = STUDIO + Vector((0.02, 0.05, 0.22))

    def update(t):
        u = glide(c.u(t))
        pos = STUDIO + lerp(Vector((0.08, -2.0, 0.62)), Vector((0.04, -1.8, 0.58)), u)
        tgt = STUDIO + Vector((0.06, 0.0, 0.3))
        look(pos, tgt, 32, 4.0, focus=(pos - mid).length)
        a, b, k = smooth(t, l1, l1 + 0.45), smooth(t, l2, l2 + 0.45), smooth(t, l3, l3 + 0.45)
        lights_set(tr_top_sp=26 * a, tr_top_pc=26 * b, tr_top_tv=30 * k, tr_rim_sp_l=4 * a, tr_rim_sp_r=4 * a,
                   tr_rim_pc_l=4 * b, tr_rim_pc_r=4 * b, tr_key=0.8 * max(a, b))
        studio_glow((1.0, 0.5, 0.3), 0.3 * max(a, b, k))
        studio.set_dust("tr_dust", t, 1.2 * max(a, b))
        Pr.set_ring("tr_sp", 1.2 * a + 1.0 * a * (0.5 + 0.5 * math.sin(t * 2.2)), t * 0.4)
        Pr.set_bar("tr_pc", 1.5 * b)
        tvset.set_led("trtv", 2.0 * (1 - smooth(t, l3, l3 + 0.2)))
        c.screen("trtv", t)
    return update


def p10(c):
    """S10-S12: the studio TV close up; 小七's eyes read it, its hands work it; S12 is a blurred background."""
    studio_mode("st_trio")
    s11, s12 = c.mark("S11.start"), c.mark("S12.start")
    typ = c.mark("type")
    ctr = REG["anchors"]["trtv_c"]
    n = REG["screens"]["trtv"]["normal"]
    side = Vector((n.y, -n.x, 0))

    def update(t):
        u = glide(c.u(t))
        d = lerp(1.25, 0.98, u)
        pos = ctr + n * d + side * lerp(0.2, 0.08, u) + Vector((0, 0, lerp(-0.12, -0.06, u)))
        look(pos, ctr + side * 0.02 + Vector((0, 0, 0.01)), 36, 2.8, focus=(pos - ctr).length)
        lights_set(tr_top_sp=10, tr_top_pc=12, tr_top_tv=22, tr_key=0.35)
        studio_glow((0.75, 0.45, 1.0), 0.3)
        fire_many("tr_pc_tv", t, [typ - 0.5, c.mark("click") - 0.45, c.mark("keys") - 0.4, c.mark("media") - 0.4], 0.45,
                  strength=6.0, tail=0.4, trail=0.6, keep=0.2)
        Pr.set_bar("tr_pc", 1.0)
        c.screen("trtv", t)
    return update


# ---------------------------------------------------------------- the demos in the warm room

def p13(c):
    """S13: the opening sentence replayed step by step, the TV in a medium shot."""
    room_mode(pebble=True)
    k1 = c.mark("k1")

    def update(t):
        u = glide(c.u(t))
        pos = lerp((0.55, 2.75, 1.12), (0.45, 3.05, 1.14), u)
        tgt = lerp((-0.42, 5.5, 1.32), (-0.42, 5.5, 1.34), u)
        look(pos, tgt, 34, 3.2, focus=(pos - P_TV).length)
        exposure(0.3)
        on = c.screen("tv", t)
        evening(0.8)
        tvset.set_led("tv", 2.5 * (1 - smooth(t, k1, k1 + 0.15)))
        fire_many("t_pc_tv", t, [c.mark(f"k{i}") - 0.35 for i in range(2, 6)], 0.35, strength=7.0, tail=0.4,
                  trail=0.5, keep=0.15)
        Pr.set_bar("pc", 1.2)
        Pr.set_ring("sp", 1.6, t * 0.4)
    return update


def p14(c):
    """S14: over the sofa's shoulder; seek, next episode, volume."""
    room_mode(pebble=True)
    spin = ring_spin(c, "xiaoqi")
    marks = [c.mark("seek"), c.mark("next"), c.mark("vol")]

    def update(t):
        u = glide(c.u(t))
        pos = lerp((0.82, 0.62, 0.97), (0.62, 0.66, 0.98), u)
        tgt = lerp((-0.12, 5.5, 1.12), (-0.1, 5.5, 1.13), u)
        look(pos, tgt, 34, 3.0, focus=(pos - P_TV).length)
        exposure(0.3)
        evening(0.85)
        c.screen("tv", t)
        fire_many("t_pc_tv", t, [m - 0.3 for m in marks], 0.35, strength=7.0, tail=0.4, trail=0.5, keep=0.15)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
        Pr.set_bar("pc", 1.2)
    return update


def p15(c):
    """S15: from the side, the speaker in the foreground; the music app, step by step."""
    room_mode(pebble=True)
    spin = ring_spin(c, "xiaoqi")
    marks = [c.mark("app"), c.mark("daily"), c.mark("all")]
    th = c.line("U08")["t"] + c.line("U08")["dur"]

    def update(t):
        u = glide(c.u(t))
        pos = lerp((1.5, 1.95, 0.98), (1.4, 2.1, 0.98), u)
        tgt = lerp((0.05, 4.6, 0.88), (0.05, 4.6, 0.9), u)
        look(pos, tgt, 27, 3.2, focus=(pos - P_TV).length)
        exposure(0.3)
        evening(0.75)
        c.screen("tv", t)
        fire("t_sp_pc", t, th - 0.05, 0.7, strength=8.0, tail=0.35, trail=0.8, keep=0.8)
        fire_many("t_pc_tv", t, [m - 0.4 for m in marks], 0.4, strength=7.0, tail=0.4, trail=0.5, keep=0.15)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
        Pr.set_bar("pc", 1.2 + 4 * decay(t, th + 0.65, 3))
    return update


def p16(c):
    """S16: from the bookshelf side; the browser."""
    room_mode(pebble=True)
    spin = ring_spin(c, "xiaoqi")
    marks = [c.mark("app"), c.mark("click"), c.mark("type"), c.mark("enter")]

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-1.95, 2.55, 1.22), (-1.75, 2.75, 1.2), u)
        tgt = lerp((0.25, 5.5, 1.28), (0.22, 5.5, 1.28), u)
        look(pos, tgt, 36, 3.0, focus=(pos - P_TV).length)
        exposure(0.3)
        evening(0.85)
        c.screen("tv", t, gain=0.8)
        fire_many("t_pc_tv", t, [m - 0.35 for m in marks], 0.35, strength=7.0, tail=0.4, trail=0.5, keep=0.15)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
        Pr.set_bar("pc", 1.2)
    return update


def p17(c):
    """S17: wide over the sofa; the TV goes to standby and the room settles into lamplight."""
    room_mode(pebble=True)
    off = c.mark("off")
    spin = ring_spin(c, "xiaoqi")

    def update(t):
        u = glide(c.u(t))
        pos = lerp((0.05, 0.42, 1.55), (0.0, 0.3, 1.66), u)
        look(pos, lerp((0.0, 4.2, 0.92), (0.0, 4.2, 0.95), u), 22, 5.0, focus=(pos - Vector((0, 3.0, 0.5))).length)
        exposure(0.3)
        k = smooth(t, off, off + 1.5)
        groups(floor=0.75, table=0.7, slat=0.7 * (1 - 0.8 * k), console=0.6 * (1 - 0.8 * k), cove=0.3 * (1 - k),
               fill=0.12 * (1 - 0.5 * k), window=0.8, moon=1.0)
        c.screen("tv", t)
        tvset.set_led("tv", 2.5 * smooth(t, off + 0.2, off + 0.3))
        fire("t_pc_tv", t, off - 0.35, 0.35, strength=7.0, tail=0.4, trail=0.5, keep=0.15)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
        Pr.set_bar("pc", 1.0)
    return update


# ---------------------------------------------------------------- P18: the museum

def p18(c):
    studio_mode("st_museum")
    retire = c.mark("retire")
    tgt = CASE + Vector((0, 0, 1.06))

    def update(t):
        u = smoother(c.u(t))
        pos = lerp(CASE + Vector((0.18, -2.1, 1.32)), CASE + Vector((0.04, -1.05, 1.19)), u)
        look(pos, lerp(tgt + Vector((0, 0, -0.06)), tgt + Vector((0, 0, 0.0)), u), lerp(48, 55, u), 2.8,
             focus=(pos - (CASE + Vector((0, -0.02, 1.1)))).length)
        k = smooth(t, -0.5, 1.2)
        lights_set(mus_spot=60 * k, mus_rim=8 * k, mus_front=6 * k, mus_plaque=6 * k + 4 * smooth(t, retire, retire + 0.8))
        studio_glow((1.0, 0.55, 0.32), 0.22 * k)
        studio.set_dust("mus_dust", t, 1.6 * k)
        REG["bloom"].inputs["Strength"].default_value = 0.45 + 0.25 * smooth(t, retire, retire + 1.0)
    return update


PLATES = {
    "P01": p01, "P04": p04, "P05": p05, "P06": p06, "P09": p09, "P10": p10,
    "P13": p13, "P14": p14, "P15": p15, "P16": p16, "P17": p17, "P18": p18,
}
# Plates seen only heavily blurred render at half resolution.
HALF_RES = set()
# Plates with fast camera moves get motion blur.
MOTION_BLUR = set()
