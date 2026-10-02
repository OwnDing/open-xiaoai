"""Per-plate staging: camera moves, light cues and the speaker ring.

Each plate function receives a Ctx and returns update(t), where t is plate
time in seconds (0 = first frame of the plate's first shot; the render also
covers HANDLE frames before 0 and after the end for transitions).
"""
import math

from mathutils import Vector

import scene as S
from scene import REG, STUDIO


# ---------------------------------------------------------------- helpers

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(t, a, b):
    """0 before a, 1 after b, smoothstep in between."""
    if b <= a:
        return 1.0 if t >= a else 0.0
    u = clamp((t - a) / (b - a))
    return u * u * (3 - 2 * u)


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


def show(name, on):
    REG["colls"][name].hide_render = not on


def groups(**levels):
    for g, v in levels.items():
        S.set_group(g, v)


def exposure(ev):
    import bpy
    bpy.context.scene.view_settings.exposure = ev


def all_groups_off():
    for g in REG["groups"]:
        S.set_group(g, 0.0)


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
        for k, v in self.marks.items():
            if k == name or k.endswith("." + name):
                return v
        raise KeyError(name)

    def u(self, t):
        """Camera progress across the whole rendered range, handles included."""
        return clamp((t + self.hs) / (self.dur + 2 * self.hs))

    def env(self, line, t):
        e = self.meta[line["id"]]["env"]
        i = int((t - line["t"]) * self.fps)
        return e[i] if 0 <= i < len(e) else 0.0


def ring_drive(c, t, voice):
    """Ring level and spin speed from the dialogue.

    voice: role whose lines make this ring talk ("xiaoai" or "xiaoqi").
    Listening while the user speaks and until the reply, voice-reactive while
    speaking, slow breathing otherwise.
    """
    idle = 2.6 + 0.9 * math.sin(2 * math.pi * t / 3.4)
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
    level = idle * (1 - listen) + listen * (6.0 + 0.8 * math.sin(t * 9)) + 9.0 * speak
    spin_speed = 0.35 + 1.2 * listen + 4.5 * think
    return level, spin_speed


class Spin:
    """Integrates spin speed so the gradient never jumps."""

    def __init__(self):
        self.t, self.a = None, 0.0

    def __call__(self, t, speed):
        if self.t is not None:
            self.a += speed * (t - self.t)
        self.t = t
        return self.a


def apartment_mode(interior):
    show("apartment", True)
    show("studio", False)
    show("interior", interior)
    show("city", interior)


def studio_mode():
    show("apartment", False)
    show("interior", False)
    show("city", False)
    show("studio", True)
    all_groups_off()
    REG["objs"]["sun"].data.energy = 0.0


def living_ring_light(level, warm):
    lt = REG["objs"]["sp_ringlight"].data
    lt.energy = 0.05 * level
    lt.color = (1.0, 0.5, 0.35) if warm > 0.5 else (0.6, 0.78, 1.0)


# ---------------------------------------------------------------- plates

SP = S.SPEAKER_LIVING + Vector((0, 0, 0.175))   # just under the ring


def p01(c):
    """S01 night living room, slow push toward the speaker on the table."""
    apartment_mode(True)
    all_groups_off()
    groups(living_floor=0.75, living_main=0.08)
    spin = Spin()

    def update(t):
        u = glide(c.u(t))
        look(lerp((-2.85, 0.45, 1.38), (-1.95, 1.5, 0.98), u), lerp((-0.95, 3.4, 0.8), SP, u),
             lerp(30, 38, u), 2.0, focus=(Vector(lerp((-2.85, 0.45, 1.38), (-1.95, 1.5, 0.98), u)) - SP).length)
        level, sp = ring_drive(c, t, "xiaoai")
        S.set_ring("sp", 0.0, level, spin(t, sp))
        living_ring_light(level, 0)
    return update


def p02(c):
    """S02 macro of the ring, breathing in the dark."""
    apartment_mode(True)
    all_groups_off()
    groups(living_floor=0.75, living_main=0.08)
    spin = Spin()
    center = SP + Vector((0, 0, 0.012))

    def update(t):
        u = glide(c.u(t))
        pos = orbit(center, lerp(0.62, 0.52, u), lerp(30, 36, u), lerp(-128, -106, u))
        look(pos, center + Vector((0, 0, -0.035)), 85, 1.8, focus=(pos - center).length - 0.02)
        level = 1.6 + 0.9 * math.sin(2 * math.pi * (t + 0.6) / 3.0)
        S.set_ring("sp", 0.0, level, spin(t, 0.3))
        living_ring_light(level, 0)
    return update


def p03(c):
    """S03 pain 1: low medium shot, cold and dim."""
    apartment_mode(True)
    all_groups_off()
    groups(living_floor=0.55, living_main=0.1)
    spin = Spin()

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-2.12, 1.72, 0.74), (-1.86, 1.84, 0.72), u)
        look(pos, lerp((-0.95, 3.02, 0.62), (-0.9, 3.0, 0.6), u), 50, 2.2, focus=(pos - SP).length)
        level, sp = ring_drive(c, t, "xiaoai")
        fail = c.mark("fail")
        if t > fail:
            # A short, unsure flicker after the non-answer.
            level *= 0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 40)) * (1 - smooth(t, fail, fail + 0.6))
        S.set_ring("sp", 0.0, level, spin(t, sp))
        living_ring_light(level, 0)
    return update


def p04(c):
    """S04 pain 2: side close-up, window and curtains soft behind."""
    apartment_mode(True)
    all_groups_off()
    groups(living_floor=0.55, living_main=0.1)
    spin = Spin()

    def update(t):
        u = glide(c.u(t))
        # Aim below the ring so the whole speaker clears the 2.39:1 letterbox.
        pos = lerp((-2.05, 2.46, 0.74), (-1.8, 2.58, 0.72), u)
        look(pos, lerp((-0.85, 3.05, 0.5), (-0.88, 3.02, 0.5), u), 55, 2.0, focus=(pos - SP).length)
        level, sp = ring_drive(c, t, "xiaoai")
        fail = c.mark("fail")
        if t > fail:
            level *= 0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 40)) * (1 - smooth(t, fail, fail + 0.6))
        S.set_ring("sp", 0.0, level, spin(t, sp))
        living_ring_light(level, 0)
    return update


DOLL = Vector((0.5, 2.4, 0.4))


def p05(c):
    """S05/S06 pain 3: the whole home from above, every room its own island."""
    apartment_mode(False)
    all_groups_off()
    groups(living_floor=0.8, living_main=0.55, study=0.8, bed_lamp=0.9, bed_main=0.35, ambient=1.0)
    spin = Spin()

    def update(t):
        u = glide(c.u(t))
        pos = orbit(DOLL, lerp(17.0, 15.6, u), lerp(38, 34, u), lerp(-104, -80, u))
        look(pos, DOLL, 34, 4.0)
        level, sp = ring_drive(c, t, "xiaoai")
        S.set_ring("sp", 0.0, level, spin(t, sp))
        living_ring_light(level, 0)
    return update


def studio_particles(t, converge=0.0, burst=0.0, strength=3.0):
    ring = STUDIO + Vector((0, 0, 0.19))
    for ob, base, ph, spd in REG["particles"]:
        drift = Vector((0.05 * math.sin(t * 0.3 * spd + ph), 0.05 * math.cos(t * 0.23 * spd + ph * 1.3),
                        0.04 * math.sin(t * 0.4 * spd + ph * 0.7) + 0.015 * t))
        p = base + drift
        if converge > 0:
            p = p.lerp(ring, converge * (0.75 + 0.25 * math.sin(ph)))
        if burst > 0:
            p = ring + (p - ring) * (1 + 1.8 * burst * spd)
        ob.location = p
    REG["particle_strength"].default_value = strength


def studio_glow(warm, strength):
    col, st = REG["studio_glow"]
    cold, hot = (0.2, 0.3, 0.55), (0.75, 0.32, 0.22)
    col.default_value = (*[a * (1 - warm) + b * warm for a, b in zip(cold, hot)], 1)
    st.default_value = strength


def p06(c):
    """S07 the reveal: a light sweeps the speaker, the ring turns warm on the hit."""
    studio_mode()
    spin = Spin()
    hit = c.mark("impact")
    sweep = REG["objs"]["st_sweep"]
    ring_lt = REG["objs"]["st_ringlight"].data
    center = STUDIO + Vector((0, 0, 0.1))

    def update(t):
        u = glide(c.u(t), 0.8)
        pos = orbit(center, lerp(1.0, 0.78, u), lerp(3, 24, u), lerp(-58, -96, u))
        look(pos, center + Vector((0, 0, lerp(0.0, 0.1, u))), 50, 2.8)
        s = smooth(t, -0.3, 1.5)
        sweep.location = STUDIO + Vector((lerp(-0.9, 0.9, s), -0.4, 0.14))
        sweep.data.energy = 2.5 * math.sin(math.pi * s) if 0 < s < 1 else 0.0
        S.set_group("st_rim", smooth(t, 0.2, 1.6) * (0.7 + 0.5 * smooth(t, hit, hit + 0.4)))
        S.set_group("st_key", 0.15 + 0.5 * smooth(t, hit, hit + 0.6))
        warm = smooth(t, hit - 0.05, hit + 0.25)
        flare = math.exp(-max(0.0, t - hit) * 3.0) if t >= hit else 0.0
        level = lerp(0.8 + 0.3 * math.sin(t * 5), 5.5 + 0.8 * math.sin(t * 2), warm) + 18 * flare
        S.set_ring("st", warm, level, spin(t, 0.4 + 2.5 * warm))
        ring_lt.energy = 0.6 * level * warm
        studio_glow(warm, 0.35 + 0.6 * warm + 1.0 * flare)
        conv = smooth(t, 0.0, hit) * 0.92 * (1 - warm)
        studio_particles(t, converge=conv, burst=smooth(t, hit, hit + 1.4), strength=2.0 + 6 * flare + 2 * warm)
    return update


def p07(c, warm):
    """S08 split screen halves: the same speaker, stock (cold) or AI (warm)."""
    studio_mode()
    spin = Spin()
    ring_lt = REG["objs"]["st_ringlight"].data
    center = STUDIO + Vector((0, 0, 0.1))
    groups(st_rim=1.0, st_key=0.5)

    def update(t):
        u = glide(c.u(t))
        pos = orbit(center, lerp(0.98, 0.82, u), lerp(26, 22, u), lerp(-84, -94, u) if warm else lerp(-96, -86, u))
        look(pos, center + Vector((0, 0, 0.03)), 55, 2.5)
        if warm:
            level, sp = ring_drive(c, t, "xiaoqi")
            level += 1.5
        else:
            level, sp = 1.8 + 0.5 * math.sin(2 * math.pi * t / 3.0), 0.3
        S.set_ring("st", 1.0 if warm else 0.0, level, spin(t, sp))
        ring_lt.energy = 0.35 * level
        ring_lt.color = (1.0, 0.5, 0.35) if warm else (0.6, 0.78, 1.0)
        studio_glow(1.0 if warm else 0.0, 0.7)
        studio_particles(t, strength=2.5)
    return update


def p08(c):
    """S09 background for the architecture diagram: the warm home at night."""
    apartment_mode(False)
    all_groups_off()
    groups(living_floor=1.0, living_main=1.0, study=1.0, bed_lamp=1.0, bed_main=0.8, ambient=0.9)
    spin = Spin()

    def update(t):
        u = glide(c.u(t))
        pos = orbit(DOLL, 17.5, lerp(44, 40, u), lerp(-122, -66, u))
        look(pos, DOLL, 32, 4.0)
        S.set_ring("sp", 1.0, 3.0 + math.sin(t * 2), spin(t, 0.8))
        living_ring_light(3.0, 1)
    return update


AC_L = Vector((0.05, 4.78, 2.3))


def p09(c):
    """S10 the same sentence again: the AC changes, focus pulls from speaker to AC."""
    apartment_mode(True)
    all_groups_off()
    groups(living_main=0.6, living_floor=0.9)
    exposure(-0.35)
    spin = Spin()
    ac = c.mark("ac")

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-0.95, 1.62, 0.55), (-0.88, 1.8, 0.56), u)
        target = pos + Vector((0.264, 1.98, 0.425))
        f = smooth(t, ac + 0.1, ac + 1.0)
        focus = lerp((pos - SP).length, (pos - AC_L).length, f)
        look(pos, target, 24, 1.8, focus=focus)
        REG["ac_l_24"].default_value = 3.0 * (1 - smooth(t, ac + 0.15, ac + 0.2))
        flash = math.exp(-max(0.0, t - ac - 0.2) * 3) if t > ac + 0.2 else 0.0
        REG["ac_l_26"].default_value = 3.0 * smooth(t, ac + 0.2, ac + 0.25) + 10 * flash
        level, sp = ring_drive(c, t, "xiaoqi")
        S.set_ring("sp", 1.0, level, spin(t, sp))
        living_ring_light(level, 1)
    return update


def p10(c):
    """S11 wide living room: main light off, curtains close."""
    apartment_mode(True)
    all_groups_off()
    spin = Spin()
    off, cur = c.mark("light_off"), c.mark("curtain")
    exposure(-0.2)
    cl, cr = REG["objs"]["curtain_l"], REG["objs"]["curtain_r"]

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-0.4, 0.32, 1.42), (-0.2, 0.62, 1.36), u)
        look(pos, lerp((0.2, 5.0, 1.12), (0.3, 5.0, 1.1), u), 21, 4.0, focus=3.2)
        main = 1.0 - smooth(t, off, off + 0.12)
        groups(living_main=main, living_floor=0.6 + 0.1 * main)
        k = smooth(t, cur, cur + 2.6)
        cl.scale.x = cr.scale.x = lerp(0.25, 1.0, k)
        level, sp = ring_drive(c, t, "xiaoqi")
        S.set_ring("sp", 1.0, level, spin(t, sp))
        living_ring_light(level, 1)
    return update


def p11(c):
    """S12 'three days ago': sunny afternoon, the speaker remembers."""
    apartment_mode(True)
    all_groups_off()
    S.set_day(1.0)
    spin = Spin()
    mem = c.mark("memory")

    def update(t):
        u = glide(c.u(t))
        pos = lerp((-2.38, 1.5, 0.98), (-2.08, 1.8, 0.88), u)
        look(pos, lerp((-0.95, 3.05, 0.66), (-0.9, 3.0, 0.62), u), 42, 2.0, focus=(pos - SP).length)
        level, sp = ring_drive(c, t, "xiaoqi")
        pulse = math.exp(-max(0.0, t - mem) * 2.5) if t > mem else 0.0
        S.set_ring("sp", 1.0, level + 6 * pulse, spin(t, sp + 6 * pulse))
        living_ring_light(level, 1)
    return update


def p12(c):
    """S13 'I'm going to sleep': lights go out room by room, AC to 25°, door alert."""
    apartment_mode(False)
    all_groups_off()
    spin = Spin()
    m = {k: c.mark(k) for k in ("study_off", "living_off", "ac25", "window", "night")}
    sun = REG["objs"]["sun"].data
    sun.color = (0.55, 0.65, 1.0)

    def update(t):
        u = glide(c.u(t), 0.7)
        pos = lerp((0.6, -12.2, 10.6), (4.5, -7.2, 6.9), u)
        target = lerp((1.0, 2.5, 0.5), (5.6, 3.0, 0.8), u)
        look(pos, target, lerp(33, 40, u), 4.0)
        so = 1 - smooth(t, m["study_off"], m["study_off"] + 0.12)
        lo = 1 - smooth(t, m["living_off"], m["living_off"] + 0.12)
        bo = 1 - smooth(t, m["living_off"] + 0.35, m["living_off"] + 0.5)
        groups(study=so, living_main=lo, living_floor=lo, bed_main=bo,
               bed_lamp=1.0 - 0.45 * (1 - bo) - 0.55 * smooth(t, m["night"], m["night"] + 1.4),
               ambient=0.9 - 0.4 * (1 - lo))
        sun.energy = 0.5 * smooth(t, m["living_off"], m["living_off"] + 1.5)
        flash = math.exp(-max(0.0, t - m["ac25"]) * 3) if t > m["ac25"] else 0.0
        REG["ac_b_25"].default_value = 3.0 * smooth(t, m["ac25"], m["ac25"] + 0.1) + 10 * flash
        w = t - m["window"]
        REG["bal_alert"].default_value = (6.0 * (0.55 + 0.45 * math.cos(w * 2 * math.pi * 1.2))) if w > 0 else 0.0
        level, sp = ring_drive(c, t, "xiaoqi")
        S.set_ring("sp", 1.0, level, spin(t, sp))
        living_ring_light(level, 1)
    return update


def p13(c):
    """S15 outro: dark home, only the ring breathing; rise up and away."""
    apartment_mode(False)
    all_groups_off()
    groups(ambient=0.45)
    sun = REG["objs"]["sun"].data
    sun.color = (0.55, 0.65, 1.0)
    sun.energy = 0.5
    REG["ac_b_25"].default_value = 2.0
    spin = Spin()

    def update(t):
        u = c.u(t)
        e = u * u * u * (u * (6 * u - 15) + 10)   # smootherstep: the rise eases in and out
        p0, p1 = Vector((-1.35, 2.2, 1.25)), Vector((0.5, -12.4, 11.2))
        t0, t1 = SP, DOLL + Vector((0, 0.1, -0.1))
        pos, target = p0.lerp(p1, e), t0.lerp(t1, smooth(e, 0.0, 0.6))
        look(pos, target, lerp(32, 34, e), lerp(2.2, 5.0, e), focus=(pos - SP).length)
        level = 3.2 + 1.2 * math.sin(2 * math.pi * t / 3.6)
        S.set_ring("sp", 1.0, level, spin(t, 0.4))
        REG["objs"]["sp_ringlight"].data.energy = 0.12 * level
    return update


PLATES = {
    "P01": p01, "P02": p02, "P03": p03, "P04": p04, "P05": p05, "P06": p06,
    "P07": lambda c: p07(c, False), "P07B": lambda c: p07(c, True),
    "P08": p08, "P09": p09, "P10": p10, "P11": p11, "P12": p12, "P13": p13,
}

# Plates that are only ever seen heavily blurred render at half resolution.
HALF_RES = {"P08"}
