"""Per-plate staging: camera moves, light cues, voice threads and rings.

Each plate function receives a Ctx and returns update(t), where t is plate
time in seconds (0 = first frame of the plate's first shot; the render also
covers HANDLE frames before 0 and after the end for transitions). update(t)
must be a pure function of t: motion blur evaluates sub-frames out of order.
"""
import math

import bpy
from mathutils import Vector

import props as Pr
import scene as S
from kit import REG, set_group
from scene import (P_AC, P_BRAIN, P_CURTAIN, P_FLOOR, P_PC, P_PENDANT, P_SPEAKER, P_WASHER)
from studio import ST_PC, ST_SPEAKER, STUDIO


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


def orbit(center, dist, elev_deg, az_deg):
    e, a = math.radians(elev_deg), math.radians(az_deg)
    c = Vector(center)
    return c + Vector((dist * math.cos(e) * math.cos(a), dist * math.cos(e) * math.sin(a), dist * math.sin(e)))


def look(pos, target, lens, fstop, focus=None, roll=0.0):
    cam = REG["cam"]
    pos, target = Vector(pos), Vector(target)
    d = target - pos
    q = d.to_track_quat("-Z", "Y")
    if roll:
        from mathutils import Quaternion
        q = q @ Quaternion((0, 0, 1), math.radians(roll))
    cam.location = pos
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = q
    cam.data.lens = lens
    cam.data.dof.aperture_fstop = fstop
    cam.data.dof.focus_distance = focus if focus is not None else d.length


def look_up(pos, target, up, lens, fstop, focus=None):
    """Like look(), but with the image's up direction given (document-camera POVs)."""
    from mathutils import Matrix
    cam = REG["cam"]
    pos, target, up = Vector(pos), Vector(target), Vector(up)
    f = (target - pos).normalized()
    r = f.cross(up).normalized()
    u = r.cross(f)
    m = Matrix((r, u, -f)).transposed()
    cam.location = pos
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = m.to_quaternion()
    cam.data.lens = lens
    cam.data.dof.aperture_fstop = fstop
    cam.data.dof.focus_distance = focus if focus is not None else (target - pos).length


class Path:
    """Camera keyframes [(t, pos, target, lens, fstop, focus_point_or_None)], smooth in time.

    Positions and targets follow a Catmull-Rom curve through the keys; the
    timing between keys is eased (smoothstep) so the camera never jerks.
    """

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

    def apply(self, t, roll=0.0):
        pos, tgt, lens, fstop, focus = self.at(t)
        look(pos, tgt, lens, fstop, focus=focus, roll=roll)
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
    """Send one pulse along a thread starting at t0, travelling for dur seconds.

    The comet head runs from 0 to 1 + tail so it fully leaves the far end.
    `trail` leaves a faint line behind it; `keep` (seconds) fades that line out.
    """
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


def loop_pulses(name, t, period, dur, phase, strength, tail=0.3, start=0.0, stop=1e9, trail=0.0):
    """Repeating pulses (diorama links breathing, uploads streaming)."""
    if t < start or t > stop + dur:
        Pr.set_thread(name, 0.0, 0.0)
        return
    strength *= THREAD_GAIN
    trail *= THREAD_GAIN
    k = math.floor((t - start - phase) / period)
    t0 = start + phase + k * period
    if t0 > stop:
        t0 -= period
    u = (t - t0) / dur
    if u < 0 or u > 1.0:
        Pr.set_thread(name, 1.0 + tail + 1, strength, tail=tail, trail=trail / max(strength, 1e-6))
        return
    Pr.set_thread(name, u * (1.0 + tail), strength, tail=tail, trail=trail / max(strength, 1e-6))


def decay(t, t0, rate=3.0):
    return math.exp(-max(0.0, t - t0) * rate) if t >= t0 else 0.0


class Ctx:
    def __init__(self, plate, meta, fps, handle):
        self.id = plate["id"]
        self.frames = plate["frames"]
        self.dur = plate["frames"] / fps
        self.lines = plate["lines"]
        self.marks = plate["marks"]
        self.meta = meta
        self.fps = fps
        self.hs = handle / fps

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


def ring_drive(c, t, voice, idle_level=1.6, listen_level=5.0, speak_gain=8.0):
    """Ring level and spin speed from the dialogue (listening, thinking, speaking)."""
    idle = idle_level * (0.75 + 0.25 * math.sin(2 * math.pi * t / 3.4))
    listen, speak, think = 0.0, 0.0, 0.0
    lines = c.lines
    for i, l in enumerate(lines):
        end = l["t"] + l["dur"]
        if l["role"] in ("user", "child"):
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


# ---------------------------------------------------------------- modes

def home_mode(interior=True, pebble=True, city=True):
    for name in ("apartment", "threads_in"):
        show(name, True)
    show("interior", interior)
    show("city", city)
    show("living_pebble", pebble)
    show("living_generic", not pebble)
    for name in ("studio", "st_speaker", "st_pc", "st_stack", "threads_dio", "threads_up", "dome", "cloud",
                 "diorama", "haze"):
        show(name, False)
    threads_off()
    all_groups_off()
    REG["slab_edge"].default_value = 0.0
    for f in REG["xray"]:
        f.default_value = 0.0


def diorama_mode():
    home_mode(interior=False, pebble=True, city=False)
    show("diorama", True)
    show("threads_dio", True)


def studio_mode():
    for name in REG["colls"]:
        show(name, False)
    for name in ("studio", "st_speaker", "st_pc"):
        show(name, True)
    all_groups_off()
    threads_off()
    REG["objs"]["sun"].data.energy = 0.0


def brain_state(prefix, root_name, t, grow_t, shrink_t, size=1.0, strength=6.0):
    g = smooth(t, grow_t, grow_t + 0.35) * (1 - smooth(t, shrink_t, shrink_t + 0.4))
    root = REG["objs"][root_name]
    s = size * (0.0001 + g * (0.92 + 0.08 * math.sin(t * 6)))
    root.scale = (s, s, s)
    root.rotation_euler = (0.25 * math.sin(t * 0.7), 0.0, t * 1.4)
    REG[f"{prefix}_strength"].default_value = strength * g
    return g


def device_flash(t, t0):
    return 10 * decay(t, t0 + 0.05, 3.0) if t >= t0 else 0.0


# ---------------------------------------------------------------- P01: the long opening take

def p01(c):
    """S01-S03: macro on the speaker in the dark; the voice thread flies to the
    mini PC; the home lights up; the camera cranes out into the diorama."""
    home_mode(interior=False)
    show("diorama", True)
    show("threads_dio", True)
    sun = REG["objs"]["sun"]
    sun.data.color = (0.55, 0.65, 1.0)
    win = REG["objs"]["window_sky"].data
    win.color = (0.55, 0.68, 1.0)
    m = {k: c.mark(k) for k in ("S02.thread", "S02.arrive", "S02.burst", "pendant", "floor", "ac", "curtain")}
    s2, s3 = c.mark("S02.start"), c.mark("S03.start")
    th, arr, burst = m["S02.thread"], m["S02.arrive"], m["S02.burst"]
    spin = ring_spin(c, "xiaoqi")
    cl, cr = REG["objs"]["curtain_l"], REG["objs"]["curtain_r"]
    sp = P_SPEAKER + Vector((0, 0, -0.03))
    # Macro start: speaker against the window
    # Macro on the speaker (city bokeh behind), pull back as the thread lifts off, follow it to
    # the mini PC, hold on the thinking brain, pull back wide as the room lights up, then crane out.
    win_dir = Vector((2.0, 5.0, 0.95)) - sp
    win_dir.z = 0.0
    win_dir.normalize()
    macro0 = sp - win_dir * 0.5 + Vector((0, 0, 0.13))
    macro1 = sp - win_dir * 0.4 + Vector((0, 0, 0.1))
    front = sp - win_dir * 0.03 + Vector((0, 0, 0.015))
    brain_pt = P_BRAIN + Vector((0, 0, -0.08))
    keys = [
        (-c.hs, macro0, sp + Vector((0, 0, 0.035)), 85, 2.0, front),
        (th - 0.15, macro1, sp + Vector((0, 0, 0.03)), 85, 2.2, front),
        (th + 0.45, Vector((-0.2, 1.7, 0.82)), Vector((-1.25, 3.05, 0.95)), 32, 2.8, Vector((-1.2, 3.0, 0.9))),
        (arr - 0.05, Vector((-1.2, 1.75, 1.0)), Vector((-2.9, 3.2, 0.82)), 40, 2.8, P_PC),
        (burst + 0.3, Vector((-1.6, 2.15, 0.98)), brain_pt, 45, 2.8, brain_pt),
        (burst + 2.1, Vector((-0.7, 0.6, 1.32)), Vector((-1.35, 3.4, 1.3)), 28, 3.5, Vector((-1.2, 3.2, 1.0))),
        (s3 + 0.2, Vector((0.25, -0.75, 1.55)), Vector((-0.6, 3.4, 1.15)), 24, 4.0, Vector((-0.8, 3.2, 1.0))),
        (s3 + 3.4, Vector((0.6, -7.5, 6.5)), Vector((0.4, 2.8, 0.6)), 30, 6.0, Vector((0.4, 2.8, 0.6))),
        (c.dur + c.hs, Vector((0.6, -12.8, 10.4)), Vector((0.5, 2.6, 0.3)), 34, 7.0, Vector((0.5, 2.6, 0.3))),
    ]
    cam = Path(keys, ease=0.35)
    kid_on, kit_on = s3 + 0.9, s3 + 1.3

    def update(t):
        cam.apply(t)
        # Night: moonlight through the window, a dim city, the ring breathing.
        sun.data.energy = 0.35
        win.energy = 18
        # Thread in, think, threads out.
        fire("t_sp_pc", t, th, 1.05, strength=9.0, tail=0.35, trail=1.2, keep=4.0)
        Pr.set_bar("pc", 0.4 + 6.0 * smooth(t, arr - 0.1, arr + 0.1) * (1 - smooth(t, burst + 0.6, burst + 1.4))
                   + 0.6 * smooth(t, burst + 1.4, burst + 2.0))
        brain_state("brain", "brain_root", t, arr - 0.05, burst + 0.35, size=1.0, strength=5.0)
        for name, tgt in (("t_pc_pendant", m["pendant"]), ("t_pc_floor", m["floor"]), ("t_pc_ac", m["ac"]),
                          ("t_pc_curtain", m["curtain"])):
            fire(name, t, burst, max(0.3, tgt - burst), strength=8.0, tail=0.3, trail=1.0, keep=3.0)
        main = smooth(t, m["pendant"], m["pendant"] + 0.2)
        floor = smooth(t, m["floor"], m["floor"] + 0.2)
        groups(living_main=0.7 * main + 0.4 * decay(t, m["pendant"], 6), living_floor=floor,
               living_fill=0.08 * main + 0.35 * smooth(t, s3 + 0.5, s3 + 3.0),
               kid_main=0.6 * smooth(t, kid_on, kid_on + 0.3), kid_desk=0.6 * smooth(t, kid_on, kid_on + 0.3),
               kid_fill=0.3 * smooth(t, kid_on, kid_on + 0.3),
               kit_main=0.6 * smooth(t, kit_on, kit_on + 0.3), kit_under=0.7 * smooth(t, kit_on, kit_on + 0.3),
               kit_fill=0.3 * smooth(t, kit_on, kit_on + 0.3),
               ambient=0.2 + 0.45 * smooth(t, s3 + 1.0, s3 + 3.0))
        REG["ac_l_26"].default_value = 3.0 * smooth(t, m["ac"], m["ac"] + 0.1) + device_flash(t, m["ac"])
        k = smooth(t, m["curtain"], m["curtain"] + 3.0)
        cl.scale.x = cr.scale.x = lerp(0.25, 1.0, k)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
        # Crane: the room's ceiling-less shell becomes the model; city fades, model edge glows,
        # and the links to the other rooms light up as they wake.
        rise = smooth(t, s3 + 0.4, s3 + 2.6)
        REG["city_fade"].default_value = rise
        REG["slab_edge"].default_value = 2.0 * smooth(t, s3 + 2.0, s3 + 4.0)
        for i, name in enumerate(("kidlamp", "kitlamp", "washer", "fridge", "kidcam", "kitcam")):
            loop_pulses(f"d_{name}", t, 2.6, 1.1, 0.25 * i, 5.0, start=kid_on - 0.6, trail=0.5)
        REG["stars"].default_value = 3.0 * smooth(t, s3 + 1.5, s3 + 4.0)
    return update


# ---------------------------------------------------------------- P04: the typical cloud speaker

def p04(c):
    """S04 pain 1: same room, cold and dim, a typical cloud speaker that doesn't understand."""
    home_mode(interior=True, pebble=False)
    REG["objs"]["window_sky"].data.energy = 25
    REG["objs"]["window_sky"].data.color = (0.55, 0.7, 1.0)
    REG["objs"]["sun"].data.energy = 0.3
    spin = ring_spin(c, "generic", idle_level=1.8, listen_level=4.5, speak_gain=5.0)
    gen = Vector((-0.88, 2.9, 0.52))
    fail = c.mark("fail")

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-2.0, 1.78, 0.72), (-1.74, 1.95, 0.7), u)
        look(pos, lerp((-0.98, 3.02, 0.62), (-0.92, 3.0, 0.6), u), 50, 2.2, focus=(pos - gen).length)
        groups(living_floor=0.3, living_main=0.05)
        level, _ = ring_drive(c, t, "generic", idle_level=1.8, listen_level=4.5, speak_gain=5.0)
        if t > fail:
            level *= (0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 40))) * (1 - 0.7 * smooth(t, fail, fail + 0.8))
        Pr.set_ring("gen", level, spin(t), warm=0.0)
    return update


# ---------------------------------------------------------------- P05: the diorama, devices in silos

def p05(c):
    diorama_mode()
    REG["objs"]["sun"].data.energy = 0.45
    REG["objs"]["sun"].data.color = (0.55, 0.65, 1.0)

    def update(t):
        u = glide(c.u(t))
        pos = orbit((0.5, 2.4, 0.4), lerp(17.5, 16.0, u), lerp(42, 38, u), lerp(-103, -84, u))
        look(pos, (0.5, 2.6, 0.5), 33, 6.0)
        groups(living_main=0.35, living_floor=0.5, kid_main=0.35, kit_main=0.35, kit_under=0.5, ambient=0.75,
               living_fill=0.2, kid_fill=0.2, kit_fill=0.2)
        REG["slab_edge"].default_value = 0.0
        Pr.set_ring("sp", 1.2, t * 0.4)
        Pr.set_bar("pc", 0.3)
    return update


# ---------------------------------------------------------------- P06: no secrets -> the turn

def p06(c):
    """S06 walls turn to glass and every room streams up into the cloud; S07 hold;
    S08 time reverses: streams fall back, walls solidify, a dome closes, the sky clears."""
    diorama_mode()
    show("threads_dio", False)
    show("threads_up", True)
    show("cloud", True)
    show("dome", True)
    sun = REG["objs"]["sun"]
    sun.data.color = (0.55, 0.65, 1.0)
    glass, rise = c.mark("glass"), c.mark("rise")
    cloud_t, silence = c.mark("cloud"), c.mark("silence")
    s8 = c.mark("S08.start")
    rev, solid, dome_t = c.mark("reverse"), c.mark("solid"), c.mark("dome")
    ups = REG["ups"]
    REG["flags"] = {}
    for k in ups:
        REG["anchors"][f"frag{k}"] = Vector((0, 0, -100))
    house = Vector((0.5, 2.5, 1.0))
    keys = [
        (-c.hs, Vector((0.6, -12.5, 1.9)), Vector((0.5, 3.5, 2.0)), 24, 8.0, house),
        (rise + 2.5, Vector((0.7, -12.8, 1.8)), Vector((0.5, 4.0, 3.2)), 22, 8.0, house),
        (silence, Vector((0.8, -13.0, 1.7)), Vector((0.5, 4.0, 3.9)), 21, 8.0, house),
        (s8, Vector((0.8, -13.0, 1.7)), Vector((0.5, 4.0, 4.0)), 21, 8.0, house),
        (s8 + 1.2, Vector((0.8, -13.1, 1.8)), Vector((0.5, 4.0, 3.7)), 21, 8.0, house),
        (dome_t + 0.4, Vector((0.6, -13.0, 3.6)), Vector((0.5, 2.8, 2.2)), 26, 8.0, house),
        (c.dur + c.hs, Vector((0.5, -16.5, 6.0)), Vector((0.5, 2.6, 1.2)), 28, 8.0, house),
    ]
    cam = Path(keys, ease=0.5)

    def update(t):
        cam.apply(t)
        back = smooth(t, rev, rev + 1.6)
        x = smooth(t, glass, glass + 1.8) * (1 - smooth(t, rev + 0.8, solid + 0.6))
        for f in REG["xray"]:
            f.default_value = 0.88 * x
        warm = smooth(t, solid - 0.2, solid + 1.0)
        groups(living_main=0.3 + 0.6 * warm, living_floor=0.45 + 0.55 * warm, kid_main=0.3 + 0.5 * warm,
               kit_main=0.3 + 0.5 * warm, kit_under=0.4 + 0.4 * warm, kid_desk=0.6 * warm,
               living_fill=0.15 + 0.2 * warm, kid_fill=0.15 + 0.2 * warm, kit_fill=0.15 + 0.2 * warm,
               ambient=0.7 - 0.3 * warm)
        sun.data.energy = 0.45
        # The cloud churns overhead, then thins away after the reversal.
        cl = REG["cloud"]
        cl["w"].default_value = 0.06 * t
        cl["density"].default_value = 1.4 * (1 - smooth(t, rev + 0.6, rev + 3.2))
        cl["glow"].default_value = 0.35 + 0.5 * smooth(t, cloud_t, cloud_t + 1.0)
        sv = REG["servers"]
        sv["w"].default_value = 0.8 * t
        sv["strength"].default_value = (2.0 + 10.0 * smooth(t, cloud_t - 0.3, cloud_t + 0.6)) * (1 - smooth(t, rev, rev + 1.2))
        # Streams: each room pulses upward; after the reversal the warm twins fall back down.
        intensity = smooth(t, rise, rise + 1.0) * (1 + 0.6 * smooth(t, silence - 0.4, silence + 0.4))
        for k in ups:
            per = 1.7 + 0.37 * (k % 4)
            if t < rev:
                loop_pulses(f"up{k}", t, per, 1.25, 0.21 * k, 7.0 * intensity, tail=0.28, start=rise, stop=rev - 0.1,
                            trail=0.6 * intensity)
                Pr.set_thread(f"down{k}", 0.0, 0.0)
            else:
                Pr.set_thread(f"up{k}", 0.0, 0.0)
                fire(f"down{k}", t, rev + 0.06 * k, 1.1, strength=7.0, tail=0.35, trail=0.0)
            th = REG["threads"][f"up{k}"]
            vis = not th["bead"].hide_render
            REG["flags"][f"frag{k}"] = round(th["head"].default_value, 3) if vis else 0
            if vis:
                REG["anchors"][f"frag{k}"] = th["bead"].location.copy()
        REG["stars"].default_value = 4.0 * smooth(t, rev + 1.5, dome_t + 1.5)
        dm = REG["dome"]
        dm["reveal"].default_value = -0.05 + 1.15 * smooth(t, dome_t, dome_t + 1.6)
        dm["strength"].default_value = 1.6 * smooth(t, dome_t - 0.1, dome_t + 0.2)
        REG["slab_edge"].default_value = 1.5 * warm
        Pr.set_ring("sp", 1.5 + 2 * warm, t * 0.5)
        Pr.set_bar("pc", 0.3 + 1.5 * warm)
        # A soft flash on the spark that starts the reversal.
        REG["bloom"].inputs["Strength"].default_value = 0.5 + 0.8 * decay(t, s8, 2.5)
    return update


# ---------------------------------------------------------------- studio plates

def studio_common(t, glow=(1.0, 0.5, 0.3), glow_s=0.5, glow_pos=(-1.6, -0.45, 0), softbox=0.6):
    col, strength, loc = REG["studio_glow"]
    col.default_value = (*glow, 1)
    strength.default_value = glow_s
    loc.default_value = glow_pos
    for ob, p0, ph, sp in REG["st_dust"]:
        ob.location = p0 + Vector((0.03 * math.sin(t * 0.3 * sp + ph), 0.02 * math.cos(t * 0.25 * sp + ph),
                                   0.02 * math.sin(t * 0.2 * sp + 2 * ph)))
    REG["st_dust_strength"].default_value = 3.0
    REG["st_softbox"].default_value = softbox


def lights_set(**kw):
    for name, e in kw.items():
        REG["objs"][name].data.energy = e


def p09(c):
    """S09: two pools of light reveal the speaker and the mini PC."""
    studio_mode()
    l_on, r_on = c.mark("light_l"), c.mark("light_r")
    mid = (ST_SPEAKER + ST_PC) / 2

    def update(t):
        u = glide(c.u(t))
        pos = mid + lerp((0.0, -1.02, 0.36), (0.0, -0.86, 0.29), u)
        look(pos, mid + Vector((0, 0, 0.05)), 50, 3.2, focus=(pos - mid).length)
        a = smooth(t, l_on, l_on + 0.45)
        b = smooth(t, r_on, r_on + 0.45)
        lights_set(st_top_sp=28 * a, st_top_pc=28 * b, st_rim_sp_l=4 * a, st_rim_sp_r=4 * a,
                   st_rim_pc_l=4 * b, st_rim_pc_r=4 * b, st_key=0.7 * max(a, b))
        studio_common(t, glow_s=0.25 * max(a, b))
        Pr.set_ring("st_sp", 1.2 * a + 1.0 * a * (0.5 + 0.5 * math.sin(t * 2.2)), t * 0.4)
        Pr.set_bar("st_pc", 1.5 * b)
    return update


def p10(c):
    """S10: macro orbit of the speaker; it listens (ear) and speaks (rings ripple out)."""
    studio_mode()
    ear, mouth = c.mark("ear"), c.mark("mouth")
    ctr = ST_SPEAKER + Vector((0, 0, 0.045))

    def update(t):
        u = glide(c.u(t))
        pos = orbit(ctr, lerp(0.64, 0.55, u), lerp(14, 20, u), lerp(-124, -84, u))
        fwd = (ctr - pos).normalized()
        right = fwd.cross(Vector((0, 0, 1))).normalized()
        # Keep the speaker in the right third; the left is for the caption.
        look(pos, ctr - right * 0.055 + Vector((0, 0, -0.006)), 85, 2.4, focus=(pos - ctr).length - 0.04)
        sweep = smooth(t, 0.0, 2.2)
        REG["objs"]["st_sweep"].location = ST_SPEAKER + Vector((lerp(-0.6, 0.6, sweep), -0.25, 0.16))
        lights_set(st_top_sp=16, st_rim_sp_l=4, st_rim_sp_r=4, st_key=0.5, st_sweep=0.25 * math.sin(math.pi * sweep),
                   st_top_pc=6, st_rim_pc_l=1, st_rim_pc_r=1)
        studio_common(t, glow_s=0.35, glow_pos=(-1.5, -0.45, 0))
        listen = smooth(t, ear - 0.1, ear + 0.2) * (1 - smooth(t, mouth - 0.2, mouth + 0.1))
        speak = smooth(t, mouth, mouth + 0.15)
        level = 1.8 + 4.5 * listen + speak * (4.0 + 1.6 * (0.5 + 0.5 * math.sin(t * 7.5)) * (0.6 + 0.4 * math.sin(t * 3.1)))
        Pr.set_ring("st_sp", level, 0.4 * t + 2.0 * listen * t)
        for k, (ob, s) in enumerate(REG["rings_fx"]):
            t0 = mouth + 0.05 + 0.32 * k
            v = clamp((t - t0) / 1.8)
            on = t >= t0
            # Stay well in front of the lens (camera is ~0.55 m away): a ring sweeping past it strobes the frame.
            r = 0.085 + 0.24 * (1 - (1 - v) ** 2)
            ob.scale = (r, r, 0.6) if on else (0, 0, 0)
            ob.hide_render = not on or v >= 1
            s.default_value = 1.1 * smooth(t, t0, t0 + 0.14) * (1 - v) ** 1.5 if on else 0.0
        Pr.set_bar("st_pc", 0.6)
    return update


def p11(c):
    """S11 the mini PC hero, its bar wakes on 'brain'; S12 glass layers rise out of it."""
    studio_mode()
    show("st_stack", True)
    show("st_speaker", False)
    sweep_t, brain_t = c.mark("sweep"), c.mark("brain")
    s12 = c.mark("S12.start")
    lt = [c.mark("l1"), c.mark("l2"), c.mark("l3"), c.mark("l4")]
    api = c.mark("S12.api")
    pc = ST_PC + Vector((0, 0, 0.03))
    fr = pc + Vector((0.064 * math.sin(math.radians(-18)), -0.064 * math.cos(math.radians(-18)), -0.005))
    keys = [
        (-c.hs, orbit(pc, 0.62, 9, -114), pc + Vector((-0.075, 0, 0.0)), 60, 11.0, fr),
        (s12 - 0.3, orbit(pc, 0.52, 13, -97), pc + Vector((-0.065, 0, 0.01)), 60, 11.0, fr),
        (s12 + 2.4, orbit(pc + Vector((0, 0, 0.14)), 1.05, 18, -74), pc + Vector((0, 0, 0.15)), 36, 8.0,
         pc + Vector((0, 0, 0.14))),
        (c.dur + c.hs, orbit(pc + Vector((0, 0, 0.17)), 1.15, 21, -58), pc + Vector((0, 0, 0.17)), 33, 8.0,
         pc + Vector((0, 0, 0.17))),
    ]
    cam = Path(keys, ease=0.5)
    layers = REG["layers"]

    def update(t):
        cam.apply(t)
        sw = smooth(t, sweep_t, sweep_t + 1.4)
        REG["objs"]["st_sweep"].location = ST_PC + Vector((lerp(-0.55, 0.55, sw), -0.3, 0.1))
        lights_set(st_top_pc=16 * (1 - 0.6 * smooth(t, s12, s12 + 1.5)), st_rim_pc_l=4, st_rim_pc_r=4,
                   st_key=2.2 * (1 - 0.6 * smooth(t, s12, s12 + 1.5)),
                   st_sweep=3.0 * math.sin(math.pi * sw), st_top_sp=0, st_rim_sp_l=0, st_rim_sp_r=0)
        studio_common(t, glow=(0.75, 0.45, 1.0), glow_s=0.35 + 0.25 * smooth(t, s12, s12 + 2), glow_pos=(-1.5, -0.42, 0),
                      softbox=6.0 * (1 - 0.7 * smooth(t, s12, s12 + 1.5)))
        REG["bloom"].inputs["Strength"].default_value = 0.25 + 0.25 * smooth(t, s12, s12 + 1.0)
        wake = smooth(t, brain_t - 0.1, brain_t + 0.3)
        Pr.set_bar("st_pc", 0.15 + 0.8 * wake * (1 - 0.3 * smooth(t, s12, s12 + 1)) + 0.8 * decay(t, brain_t, 4))
        brain_state("st_brain", "st_brain_root", t, brain_t, lt[0] + 0.2, size=1.0, strength=5.0)
        for k, (ob, s) in enumerate(layers):
            r = smooth(t, lt[k], lt[k] + 0.9)
            z = 0.06 + r * (0.075 + 0.085 * k)
            ob.location = ST_PC + Vector((0, 0, z))
            ob.rotation_euler = (0, 0, math.radians(-18) + 0.15 * (1 - r))
            ob.hide_render = r <= 0.0
            s.default_value = 1.2 * r + 2.0 * decay(t, lt[k] + 0.5, 3)
            REG["anchors"][f"layer{k}"] = ob.location + Vector((0.0, 0, 0.0))
            REG["anchors"][f"layer{k}_r"] = ob.location + Vector((0.09, -0.03, 0.0))
        fire("api_up", t, api, 1.1, strength=6.0, tail=0.35, trail=1.0)
        Pr.set_ring("st_sp", 0.0, 0.0)
    return update


# ---------------------------------------------------------------- P13: dome background for the explainer

def p13(c):
    diorama_mode()
    show("dome", True)
    REG["objs"]["sun"].data.energy = 0.4

    def update(t):
        u = glide(c.u(t))
        pos = orbit((0.5, 2.5, 1.0), lerp(23, 21, u), lerp(20, 24, u), lerp(-98, -82, u))
        look(pos, (0.5, 2.6, 1.3), 34, 8.0)
        groups(living_main=0.8, living_floor=1.0, kid_main=0.6, kit_main=0.6, kit_under=0.6, kid_desk=0.6,
               living_fill=0.3, kid_fill=0.3, kit_fill=0.3, ambient=0.4)
        REG["dome"]["reveal"].default_value = 1.1
        REG["dome"]["strength"].default_value = 1.4
        REG["stars"].default_value = 4.0
        REG["slab_edge"].default_value = 1.5
        for i, name in enumerate(REG["dio_targets"]):
            loop_pulses(f"d_{name}", t, 3.2, 1.2, 0.27 * i, 4.0, trail=0.4)
        Pr.set_ring("sp", 2.5, t * 0.5)
        Pr.set_bar("pc", 2.0)
    return update


# ---------------------------------------------------------------- P14: same sentence, understood

def p14(c):
    home_mode(interior=True)
    REG["city_dusk"].default_value = 1.0
    REG["objs"]["window_sky"].data.energy = 30
    REG["objs"]["window_sky"].data.color = (1.0, 0.6, 0.45)
    th, arr, ac = c.mark("thread"), c.mark("arrive"), c.mark("ac")
    remind = c.mark("remind")
    spin = ring_spin(c, "xiaoqi")
    sp = P_SPEAKER + Vector((0, 0, -0.03))
    ac_pt = Vector((0.05, 4.78, 2.28))

    def update(t):
        u = glide(c.u(t))
        f = smooth(t, ac - 0.55, ac + 0.45)
        pos = lerp((-1.5, 2.12, 0.66), (-1.42, 2.2, 0.68), u)
        target = lerp(sp + Vector((0.08, 0.1, 0.04)), Vector((-0.25, 4.1, 1.85)), f)
        focus = lerp((pos - sp).length, (pos - ac_pt).length, f)
        look(pos, target, 30, 1.8, focus=focus)
        groups(living_main=0.45, living_floor=0.8, living_fill=0.15)
        fire("t_sp_pc", t, th, 0.6, strength=8.0, tail=0.4, trail=0.8, keep=1.5)
        fire("t_pc_ac", t, arr + 0.05, ac - arr - 0.05, strength=8.0, tail=0.35, trail=0.8, keep=2.0)
        REG["ac_l_24"].default_value = 3.0 * (1 - smooth(t, ac + 0.1, ac + 0.15))
        REG["ac_l_26"].default_value = 3.0 * smooth(t, ac + 0.15, ac + 0.2) + device_flash(t, ac + 0.15)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level + 4 * decay(t, remind, 3), spin(t))
        Pr.set_bar("pc", 1.0)
    return update


# ---------------------------------------------------------------- P15: the washer (another brand) reports back

def p15(c):
    home_mode(interior=True)
    lapse, done = c.mark("lapse"), c.mark("done")
    th = c.mark("S15.thread")
    win = REG["objs"]["kit_window_sky"].data
    digits = REG["washer_digits"]
    spin_e = REG["washer_spin"]
    hands = (REG["clock_h"], REG["clock_m"])
    key = REG["objs"]["sun"]
    spin_ring = ring_spin(c, "xiaoqi")

    def drum_angle(t):
        # Drum speed ramps down to a stop at `done`; integrate analytically (piecewise).
        w0 = 5.0
        if t <= lapse:
            return w0 * t
        a = w0 * lapse
        if t <= done:
            return a + 2.5 * w0 * (t - lapse)          # time-lapse: spins faster
        a += 2.5 * w0 * (done - lapse)
        dtt = min(t - done, 0.9)
        return a + 2.5 * w0 * (dtt - dtt * dtt / 1.8)  # decelerate to 0 in 0.9 s

    def update(t):
        u = glide(c.u(t))
        pos = lerp((6.2, 0.5, 0.72), (6.36, 0.58, 0.7), u)
        look(pos, lerp((7.7, 1.16, 0.64), (7.7, 1.12, 0.62), u), 24, 3.5, focus=(pos - Vector((7.33, 0.95, 0.45))).length)
        lp = smooth(t, lapse, done)
        # Dusk to night: the warm raking light fades, the room lights carry the scene.
        key.data.energy = 0.0
        win.energy = lerp(60, 6, lp)
        win.color = lerp((1.0, 0.55, 0.35), (0.5, 0.62, 1.0), lp)
        REG["city_dusk"].default_value = 1.0 - lp
        groups(kit_main=lerp(0.4, 0.7, lp), kit_under=lerp(0.4, 0.7, lp), kit_fill=lerp(0.1, 0.25, lp),
               living_main=0.6, living_floor=0.6,
               washer_run=1.0 - smooth(t, done, done + 0.6))
        spin_e.rotation_euler.x = drum_angle(t)
        # Display: 0:42 counting down through the time-lapse, then 0:00 and the green done light.
        mins = 42 if t < lapse else max(0, int(round(42 * (1 - (t - lapse) / max(done - lapse, 1e-3)))))
        digits.data.body = f"0:{mins:02d}"
        blink = (0.5 + 0.5 * math.cos((t - done) * 2 * math.pi * 1.4)) if t > done else 1.0
        REG["washer_digits_strength"].default_value = 2.5 * blink
        REG["washer_done"].default_value = 6.0 * smooth(t, done, done + 0.1)
        # Clock hands: 10 minutes of real time per second during the lapse.
        minutes = 0.0 if t < lapse else min(t, done) - lapse
        hands[1].rotation_euler.x = -(math.radians(240) + 2 * math.pi * minutes * 42 / 60 / (done - lapse))
        hands[0].rotation_euler.x = -(math.radians(150) + 2 * math.pi * minutes * 42 / 720 / (done - lapse))
        fire("t_washer_pc", t, th, 1.0, strength=9.0, tail=0.3, trail=0.6, keep=1.5)
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin_ring(t))
    return update


# ---------------------------------------------------------------- P16: three days ago, a rule taught by voice

def p16(c):
    home_mode(interior=True)
    S.set_day(1.0)
    show("haze", True)
    REG["haze_living"].default_value = 0.035
    fly = c.mark("fly")
    spin = ring_spin(c, "xiaoqi")
    mid = Vector((-2.05, 3.05, 0.55))

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-1.75, 0.55, 1.12), (-1.9, 0.95, 1.0), u)
        look(pos, lerp(mid + Vector((0.15, 0, 0.05)), mid, u), 30, 3.2, focus=(pos - mid).length)
        fire("t_sp_pc", t, fly, 1.3, strength=8.0, tail=0.4, trail=0.8, keep=1.5)
        arrive = fly + 1.3
        Pr.set_bar("pc", 0.8 + 6.0 * decay(t, arrive, 2.5))
        brain_state("brain", "brain_root", t, arrive - 0.1, arrive + 1.2, size=0.8, strength=5.0)
        p = Pr.point_at("t_sp_pc", clamp((t - fly) / 1.3))
        REG["anchors"]["flyer"] = p
        level, _ = ring_drive(c, t, "xiaoqi")
        Pr.set_ring("sp", level, spin(t))
    return update


# ---------------------------------------------------------------- P17: the kitchen camera sees the fire

def p17(c):
    home_mode(interior=True)
    cam_t, alert = c.mark("cam"), c.mark("alert")
    win = REG["objs"]["kit_window_sky"].data
    stove = Vector((4.42, 4.68, 1.0))
    kitcam = REG["objs"]["kitcam_root"]
    b_end = alert + 0.4
    REG["flags"] = {"pov": 0}

    REG["objs"]["steam_light"].data.energy = 14.0

    def update(t):
        win.energy = 30
        win.color = (0.5, 0.62, 1.0)
        groups(kit_under=0.08, living_floor=0.4, kit_fill=0.04)
        Pr.set_flame("flame", t, 1.0)
        st = REG["steam"]
        st["rise"].default_value = -0.45 * t
        st["density"].default_value = 60.0
        REG["kitcam_led"].default_value = 3.0 * (0.5 + 0.5 * math.sin(t * 5.0)) + 8 * decay(t, cam_t, 3)
        if t < cam_t:
            # A: low close-up on the pot and the flame; the wall camera blinks far behind.
            u = smooth(t, -c.hs, cam_t)
            pos = lerp((3.86, 3.86, 0.98), (3.96, 3.98, 1.0), u)
            look(pos, lerp(stove + Vector((0.12, 0, -0.04)), stove + Vector((0.08, 0, 0.2)), smooth(t, 0.2, cam_t)),
                 36, 2.2, focus=(pos - stove).length)
        elif t < b_end:
            # B: the camera's own view, wide, slowly zooming in.
            v = smooth(t, cam_t, b_end)
            cpos = REG["anchors"]["kitcam"]
            d = (stove - cpos).normalized()
            pos = cpos + d * lerp(1.2, 1.6, v)
            look(pos, lerp(stove + Vector((0.15, -0.2, -0.05)), stove + Vector((0.05, -0.05, 0.0)), v),
                 lerp(18, 24, v), 16.0)
        else:
            # C: wide of the dark kitchen; the alarm thread leaves the camera for the doorway.
            v = smooth(t, b_end, c.dur + c.hs)
            pos = lerp((4.15, 0.75, 1.45), (4.3, 0.95, 1.42), v)
            look(pos, lerp((5.6, 4.2, 1.35), (5.5, 4.2, 1.35), v), 22, 4.0, focus=4.0)
        fire("t_kitcam_pc", t, alert - 0.3, 1.6, strength=9.0, tail=0.3, trail=0.5)
        REG["flags"]["pov"] = 1 if cam_t <= t < b_end else 0
    return update


# ---------------------------------------------------------------- P18: homework under the desk lamp

def p18(c):
    home_mode(interior=True)
    detect = c.mark("detect")
    n16 = c.line("N16")["t"]
    ws = REG["anchors"]["worksheet"]
    kidcam = REG["objs"]["kidcam_root"]
    win = REG["objs"]["window_sky"].data
    REG["flags"] = {"pov": 0}

    def update(t):
        groups(kid_desk=1.0, living_floor=0.3)
        win.energy = 0
        REG["kidcam_led"].default_value = 2.5 + 6 * decay(t, detect, 3)
        if t < detect:
            u = smooth(t, -c.hs, detect + 0.3)
            pos = lerp((-5.1, 3.96, 1.16), (-5.16, 4.1, 1.05), u)
            look(pos, lerp(ws + Vector((0.04, 0.05, 0.02)), ws + Vector((0.0, 0.02, 0.0)), u), 40, 2.8,
                 focus=(pos - ws).length)
        elif t < n16 + 0.2:
            v = smooth(t, detect, n16)
            pos = ws + lerp(Vector((0.03, -0.06, 0.46)), Vector((0.02, -0.07, 0.38)), v)
            look_up(pos, ws + lerp(Vector((0.0, -0.01, 0)), Vector((0.0, -0.06, 0)), v), (0, 1, 0),
                    lerp(28, 32, v), 16.0)
        else:
            v = smooth(t, n16 + 0.2, c.dur + c.hs)
            pos = lerp((-4.55, 3.05, 1.18), (-4.35, 2.75, 1.25), v)
            look(pos, lerp((-5.25, 4.55, 0.92), (-5.25, 4.55, 0.95), v), 32, 3.2, focus=(pos - ws).length)
        fire("t_kidcam_pc", t, detect + 0.1, 1.5, strength=7.0, tail=0.3, trail=0.5)
        REG["flags"]["pov"] = 1 if detect <= t < n16 + 0.2 else 0
    return update


# ---------------------------------------------------------------- P19: the vision

def p19(c):
    diorama_mode()
    show("dome", True)
    claim = c.mark("claim")

    def update(t):
        u = smoother(c.u(t))
        pos = lerp((0.6, -13.5, 6.0), (0.5, -27.0, 4.6), u)
        look(pos, lerp((0.5, 2.6, 0.9), (0.5, 2.6, 3.6), u), lerp(28, 30, u), 8.0)
        dawn = smooth(t, 0.0, c.dur)
        REG["dawn"].default_value = 1.1 * dawn
        REG["stars"].default_value = 4.0 * (1 - 0.6 * dawn)
        REG["objs"]["sun"].data.energy = 0.3 + 0.6 * dawn
        REG["objs"]["sun"].data.color = lerp((0.55, 0.65, 1.0), (1.0, 0.62, 0.42), dawn)
        groups(living_main=0.9, living_floor=1.0, kid_main=0.7, kit_main=0.7, kit_under=0.6, kid_desk=0.5,
               ambient=0.35 + 0.3 * dawn)
        REG["dome"]["reveal"].default_value = 1.1
        REG["dome"]["strength"].default_value = 1.3 + 1.2 * decay(t, claim, 1.2) + 0.5 * smooth(t, claim, claim + 1)
        REG["slab_edge"].default_value = 1.5
        for i, name in enumerate(REG["dio_targets"]):
            loop_pulses(f"d_{name}", t, 3.0, 1.2, 0.23 * i, 4.5, trail=0.45)
        Pr.set_ring("sp", 2.5 + 0.8 * math.sin(t * 1.7), t * 0.5)
        Pr.set_bar("pc", 2.0)
    return update


PLATES = {
    "P01": p01, "P04": p04, "P05": p05, "P06": p06, "P09": p09, "P10": p10, "P11": p11, "P13": p13,
    "P14": p14, "P15": p15, "P16": p16, "P17": p17, "P18": p18, "P19": p19,
}

# Plates seen only heavily blurred render at half resolution.
HALF_RES = {"P13"}
# Plates with fast camera moves get motion blur.
MOTION_BLUR = {"P01", "P06"}
