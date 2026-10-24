"""Black studio sets: three TVs of other brands (pain 03 and the turn), the trio
(speaker, mini PC, TV with the helper) and the museum case for the retired remote.

The sets share one floor and backdrop; each set has its own collection and its
own lights, and the plates show one set at a time.
"""
import math
import random
from pathlib import Path

import bpy
from mathutils import Vector

import tvset
from kit import REG, anchor, cyl, emission, light, node, plane, principled, sphere
from props import COLD, generic_speaker, mini_pc, brain, pebble_speaker, thread

ROOT = Path(__file__).resolve().parents[2]
STUDIO = Vector((100.0, 0.0, 0.0))
# Pain 03: three TVs on stands, a smart speaker in front that only switches them.
TVS = {"ta": (STUDIO + Vector((-1.78, 0.35, 1.02)), math.radians(16)),
       "tb": (STUDIO + Vector((0.0, 0.62, 1.02)), 0.0),
       "tc": (STUDIO + Vector((1.78, 0.35, 1.02)), math.radians(-16))}
HUB = STUDIO + Vector((0.0, -1.0, 0.36))
# The trio.
TR_SPEAKER = STUDIO + Vector((-0.5, -0.12, 0.0))
TR_PC = STUDIO + Vector((-0.2, -0.06, 0.0))
TR_TV = STUDIO + Vector((0.36, 0.22, 0.36))
TR_TV_W, TR_TV_H = 0.95, 0.535
# The museum case.
CASE = STUDIO + Vector((0.0, 0.0, 0.0))


def backdrop(c):
    floor_m = principled("studio_floor", (0.008, 0.008, 0.009), rough=0.38, coat=0.25, spec=0.4)
    plane("studio_floor", 60, 60, STUDIO, floor_m, collection=c)
    m = bpy.data.materials.new("studio_glow")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Location"].default_value = (-1.6, -0.45, 0)
    mp.inputs["Scale"].default_value = (3.2, 3.6, 0)
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    g = nt.nodes.new("ShaderNodeTexGradient")
    g.gradient_type = "SPHERICAL"
    nt.links.new(mp.outputs[0], g.inputs["Vector"])
    p = nt.nodes.new("ShaderNodeMath")
    p.operation = "POWER"
    p.inputs[1].default_value = 2.2
    nt.links.new(g.outputs["Fac"], p.inputs[0])
    col = nt.nodes.new("ShaderNodeRGB")
    col.outputs[0].default_value = (1.0, 0.5, 0.3, 1)
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(p.outputs[0], mul.inputs[6])
    nt.links.new(col.outputs[0], mul.inputs[7])
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Strength"].default_value = 0.0
    nt.links.new(mul.outputs[2], e.inputs["Color"])
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    bg = plane("studio_bg", 16, 7, STUDIO + Vector((0, 5.0, 2.2)), m, rot=(math.pi / 2, 0, 0), collection=c)
    bg.visible_shadow = False
    REG["studio_glow"] = (col.outputs[0], e.inputs["Strength"], mp.inputs["Location"])


def spot_on(name, target, c, height=1.6, energy=0.0, size_deg=26, color=(1.0, 0.9, 0.82), back=0.05):
    lt = light(name, "SPOT", Vector(target) + Vector((0, back, height)), energy, color, None, size=0.15,
               spot=(math.radians(size_deg), 0.55), collection=c)
    lt.rotation_euler = (Vector(target) - lt.location).to_track_quat("-Z", "Y").to_euler()
    return lt


def pedestal(name, base, height, c):
    m = principled(f"{name}_m", (0.02, 0.02, 0.022), rough=0.4, coat=0.3, metal=0.3)
    cyl(f"{name}_foot", 0.2, 0.02, Vector(base) + Vector((0, 0, 0.01)), m, bev=0.005, collection=c)
    cyl(f"{name}_pole", 0.025, height, Vector(base) + Vector((0, 0, height / 2)), m, seg=24, bev=0, collection=c)


def three_tvs(c):
    w, h = 1.21, 0.68
    for name, (ctr, rz) in TVS.items():
        tvset.tv(name, ctr, w, h, c, rot_z=rz)
        pedestal(f"{name}_ped", Vector((ctr.x, ctr.y + 0.06, 0.0)), ctr.z - h / 2 + 0.02, c)
        spot_on(f"{name}_spot", ctr + Vector((0, 0, -0.4)), c, height=1.9, color=(0.75, 0.85, 1.0), size_deg=34, back=0.6)
    generic_speaker("hubsp", HUB, c)
    cyl("hub_plinth", 0.14, HUB.z, Vector((HUB.x, HUB.y, HUB.z / 2)), principled("hub_m", (0.03, 0.03, 0.033), rough=0.4,
                                                                                     coat=0.3), bev=0.006, collection=c)
    spot_on("hub_spot", HUB + Vector((0, 0, 0.1)), c, height=1.5, color=(0.75, 0.85, 1.0), size_deg=22)
    top = HUB + Vector((0, 0, 0.2))
    for name in TVS:
        led = REG["anchors"][f"{name}_led"]
        mid = (top + led) / 2 + Vector((0, 0, 0.25))
        thread(f"hub_{name}", [top, top.lerp(mid, 0.5) + Vector((0, 0, 0.12)), mid, led], COLD, radius=0.0035,
               collection=c, head_size=0.012)
        anchor(f"hub_{name}_mid", mid)


def trio(c):
    pebble_speaker("tr_sp", TR_SPEAKER, c, rot_z=math.radians(20))
    mini_pc("tr_pc", TR_PC, c, rot_z=math.radians(-12))
    brain("tr_brain", TR_PC + Vector((0, 0, 0.2)), 0.07, c)
    tvset.tv("trtv", TR_TV, TR_TV_W, TR_TV_H, c, rot_z=math.radians(-8), stand="feet")
    for name, tgt in (("tr_top_sp", TR_SPEAKER), ("tr_top_pc", TR_PC), ("tr_top_tv", TR_TV + Vector((0, 0, -0.36)))):
        spot_on(name, tgt, c, height=1.3 if name != "tr_top_tv" else 1.9, size_deg=24 if name != "tr_top_tv" else 40)
    for side, sx in (("l", -1), ("r", 1)):
        for tgt_name, tgt in (("sp", TR_SPEAKER), ("pc", TR_PC)):
            pos = tgt + Vector((0.34 * sx, 0.6, 0.35))
            rim = light(f"tr_rim_{tgt_name}_{side}", "AREA", pos, 0, (0.75, 0.85, 1.0), None, size=0.05, size_y=0.5,
                        collection=c, specular=0.0)
            rim.rotation_euler = (tgt + Vector((0, 0, 0.05)) - pos).to_track_quat("-Z", "Y").to_euler()
    light("tr_key", "AREA", STUDIO + Vector((-0.5, -0.9, 0.8)), 0, (1.0, 0.92, 0.85), None, size=0.8,
          rot=(math.radians(50), 0, math.radians(-25)), collection=c)
    # The thread from the speaker into the mini PC, and on into the TV.
    sp_top = TR_SPEAKER + Vector((0, 0, 0.085))
    pc_top = TR_PC + Vector((0, 0, 0.06))
    thread("tr_sp_pc", [sp_top, sp_top + Vector((0.05, 0.02, 0.12)), (sp_top + pc_top) / 2 + Vector((0, 0.03, 0.16)),
                        pc_top + Vector((-0.02, 0, 0.1)), pc_top], (1.0, 0.55, 0.2), radius=0.0018, collection=c,
           head_size=0.006)
    tvc = REG["anchors"]["trtv_c"]
    thread("tr_pc_tv", [pc_top, pc_top + Vector((0.05, 0.0, 0.15)), (pc_top + tvc) / 2 + Vector((0, -0.08, 0.2)),
                        tvc + Vector((-0.12, -0.12, 0.05)), tvc + Vector((0, -0.01, 0))], (0.55, 0.32, 1.0),
           radius=0.002, collection=c, head_size=0.007)


def museum_set(c):
    tex = ROOT / "build" / "textures" / "plaque.png"
    tvset.museum(CASE, c, plaque_tex=tex)
    spot_on("mus_spot", CASE + Vector((0, 0, 1.1)), c, height=1.7, size_deg=20, color=(1.0, 0.9, 0.78), back=-0.15)
    spot_on("mus_rim", CASE + Vector((0, 0.1, 1.1)), c, height=0.8, size_deg=30, color=(0.7, 0.8, 1.0), back=1.2)
    light("mus_front", "AREA", CASE + Vector((0.25, -0.9, 1.25)), 0.0, (1.0, 0.9, 0.8), None, size=0.6, collection=c,
          specular=0.6).rotation_euler = ((CASE + Vector((0, 0, 1.12))) - (CASE + Vector((0.25, -0.9, 1.25)))).to_track_quat(
        "-Z", "Y").to_euler()
    light("mus_plaque", "SPOT", CASE + Vector((0, -0.9, 0.5)), 0.0, (1.0, 0.86, 0.7), None, size=0.1,
          spot=(math.radians(18), 0.5), collection=c, rot=(math.radians(-70), 0, 0)).rotation_euler = (
        (CASE + Vector((0, -0.25, 0.8))) - (CASE + Vector((0, -0.9, 0.5)))).to_track_quat("-Z", "Y").to_euler()


def dust(c, center, n=160, spread=(1.0, 0.8, 1.2), seed=11, name="st_dust", size=1.0):
    pm = emission(f"{name}_m", (1.0, 0.85, 0.65), 0.0)
    items = []
    rnd = random.Random(seed)
    for i in range(n):
        pos = Vector(center) + Vector([rnd.uniform(-s, s) for s in spread])
        ob = sphere(f"{name}{i}", rnd.uniform(0.0006, 0.0014) * size, pos, pm, seg=8, collection=c)
        ob.visible_shadow = False
        items.append((ob, pos.copy(), rnd.uniform(0, 6.28), rnd.uniform(0.3, 1.0)))
    REG[name] = (items, pm.node_tree.nodes["Emission"].inputs["Strength"])


def set_dust(name, t, strength):
    items, s = REG[name]
    for ob, p0, ph, sp in items:
        ob.location = p0 + Vector((0.03 * math.sin(t * 0.3 * sp + ph), 0.02 * math.cos(t * 0.25 * sp + ph),
                                   0.02 * math.sin(t * 0.2 * sp + 2 * ph) - 0.005 * t * sp))
    s.default_value = strength


def build():
    backdrop("studio")
    three_tvs("st_tvs")
    trio("st_trio")
    museum_set("st_museum")
    dust("st_museum", CASE + Vector((0, 0.35, 1.45)), name="mus_dust", spread=(0.45, 0.35, 0.5), n=120, size=0.7)
    dust("st_trio", STUDIO + Vector((0, 0.2, 0.7)), name="tr_dust", n=70, size=0.7)
