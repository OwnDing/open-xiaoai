"""The living room, built around the TV wall.

The room is closed (four walls and a ceiling): every shot is from inside it.
x runs along the TV wall, y from the sofa (front wall, y = 0) to the TV wall
(y = ROOM_Y), z up. The window is in the right-hand wall (x = ROOM_X).
"""
import math
import random

import bmesh
import bpy
from mathutils import Vector

from kit import (REG, WARM, WARM_SOFT, anchor, box, box_span, cyl, emission, fabric, glow_material, light,
                 mesh_object, node, plane, principled, sphere)

ROOM_X, ROOM_Y, H = 3.3, 5.6, 2.8
TV_CENTER = Vector((0.0, 5.52, 1.32))
TV_W, TV_H = 1.45, 0.816
TABLE = Vector((0.0, 3.0, 0.40))         # top of the coffee table
SPEAKER = Vector((0.2, 3.12, 0.40))
REMOTE = Vector((-0.1, 2.94, 0.40))
CONSOLE_TOP = 0.58
MINIPC = Vector((0.86, 5.33, CONSOLE_TOP))
SOFA = Vector((0.0, 1.35, 0.0))


def plaster(name, color):
    m = principled(name, color, rough=0.9, spec=0.3)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = node(nt, "ShaderNodeTexNoise", Scale=6.0, Detail=8.0, Roughness=0.65)
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    bp = node(nt, "ShaderNodeBump", Strength=0.06, Distance=0.01)
    nt.links.new(nz.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs[0], b.inputs["Normal"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 0.12
    mix.inputs[6].default_value = (*color, 1)
    nt.links.new(nz.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    return m


def oak_floor():
    m = principled("floor", (0.4, 0.26, 0.15), rough=0.32, coat=0.2)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (5.5, 1.0, 1.0)
    brick = node(nt, "ShaderNodeTexBrick", Scale=1.2, **{"Mortar Size": 0.004, "Bias": 0.0})
    brick.offset = 0.5
    brick.squash = 1.0
    brick.inputs["Color1"].default_value = (0.34, 0.21, 0.12, 1)
    brick.inputs["Color2"].default_value = (0.44, 0.29, 0.17, 1)
    brick.inputs["Mortar"].default_value = (0.1, 0.06, 0.035, 1)
    nt.links.new(mp.outputs[0], brick.inputs["Vector"])
    grain = node(nt, "ShaderNodeTexNoise", Scale=38.0, Detail=6.0, Roughness=0.6)
    gm = node(nt, "ShaderNodeMapping")
    gm.inputs["Scale"].default_value = (16.0, 1.0, 1.0)
    nt.links.new(tc.outputs["Object"], gm.inputs["Vector"])
    nt.links.new(gm.outputs[0], grain.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "OVERLAY"
    mix.inputs["Factor"].default_value = 0.35
    nt.links.new(brick.outputs["Color"], mix.inputs[6])
    nt.links.new(grain.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    return m


def make_materials():
    M = {}
    M["wall"] = plaster("wall", (0.56, 0.53, 0.49))
    M["ceiling"] = plaster("ceiling", (0.62, 0.6, 0.57))
    M["floor"] = oak_floor()
    M["walnut"] = principled("walnut", (0.17, 0.095, 0.05), rough=0.38, coat=0.3)
    M["slat"] = principled("slat", (0.24, 0.14, 0.075), rough=0.5, coat=0.1)
    M["slat_back"] = principled("slat_back", (0.02, 0.018, 0.016), rough=0.8)
    M["oak"] = principled("oak", (0.5, 0.34, 0.2), rough=0.35, coat=0.2)
    M["black_metal"] = principled("black_metal", (0.03, 0.03, 0.03), rough=0.35, metal=1.0)
    M["brass"] = principled("brass", (0.8, 0.58, 0.3), rough=0.25, metal=1.0)
    M["stone"] = principled("stone", (0.16, 0.155, 0.15), rough=0.28, coat=0.5)
    M["ceramic"] = principled("ceramic", (0.85, 0.82, 0.76), rough=0.25, coat=0.5)
    M["ceramic_dark"] = principled("ceramic_dark", (0.14, 0.12, 0.11), rough=0.3, coat=0.5)
    M["white_plastic"] = principled("white_plastic", (0.85, 0.85, 0.83), rough=0.3, coat=0.3)
    M["glass"] = principled("glass", (0.6, 0.7, 0.75), rough=0.03, alpha=0.08, spec=1.0)
    M["frame"] = principled("frame", (0.1, 0.1, 0.11), rough=0.4, metal=0.6)
    M["rug"] = fabric("rug", (0.5, 0.46, 0.41), scale=260, bump=0.25)
    M["sofa"] = fabric("sofa", (0.36, 0.33, 0.3), scale=180)
    M["pillow_a"] = fabric("pillow_a", (0.72, 0.46, 0.16), scale=180)
    M["pillow_b"] = fabric("pillow_b", (0.2, 0.3, 0.34), scale=180)
    M["throw"] = fabric("throw", (0.55, 0.3, 0.22), scale=150)
    M["sheer"] = principled("sheer", (0.9, 0.88, 0.84), rough=0.9, alpha=0.55, sheen=0.5)
    M["leaf"] = principled("leaf", (0.07, 0.2, 0.08), rough=0.55, sheen=0.3)
    M["leaf2"] = principled("leaf2", (0.12, 0.28, 0.1), rough=0.55, sheen=0.3)
    M["book"] = [principled(f"book{i}", c, rough=0.6) for i, c in enumerate([
        (0.55, 0.16, 0.12), (0.14, 0.24, 0.38), (0.8, 0.72, 0.55), (0.2, 0.32, 0.22),
        (0.7, 0.45, 0.16), (0.12, 0.12, 0.14), (0.62, 0.6, 0.56)])]
    return M


# ---------------------------------------------------------------- pieces

def plant(name, loc, height, M, pot=0.12):
    x, y, z = loc
    cyl(f"{name}_pot", pot, pot * 1.5, (x, y, z + pot * 0.75), M["ceramic_dark"], seg=32, r2=pot * 0.8, bev=0.01)
    rnd = random.Random(hash(name) & 0xffff)
    n = int(10 + height * 14)
    for i in range(n):
        u = i / n
        a = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(0.2, 1.0) * height * 0.32 * (0.4 + u)
        zz = z + pot * 1.5 + height * (0.25 + 0.75 * u) * rnd.uniform(0.7, 1.0)
        s = height * rnd.uniform(0.09, 0.16)
        leaf = sphere(f"{name}_leaf{i}", s, (x + r * math.cos(a), y + r * math.sin(a), zz),
                      M["leaf"] if i % 3 else M["leaf2"], scale=(1.0, 0.45, 0.22), seg=16)
        leaf.rotation_euler = (rnd.uniform(-0.6, 0.6), rnd.uniform(-0.5, 0.5), a)
    cyl(f"{name}_stem", 0.012, height * 0.8, (x, y, z + pot * 1.5 + height * 0.4), M["leaf2"], seg=8, bev=0)


def shell(M):
    X, Y = ROOM_X, ROOM_Y
    T = 0.12
    box_span("floor", -X, X, 0, Y, -0.05, 0.0, M["floor"], bev=0)
    box_span("ceiling", -X - T, X + T, -T, Y + T, H, H + 0.1, M["ceiling"], bev=0)
    box_span("wall_back", -X - T, X + T, Y, Y + T, 0, H, M["wall"], bev=0)
    box_span("wall_front", -X - T, X + T, -T, 0, 0, H, M["wall"], bev=0)
    box_span("wall_left", -X - T, -X, 0, Y, 0, H, M["wall"], bev=0)
    # Right wall with a wide window y [1.3, 4.5], z [0.3, 2.55].
    wy0, wy1, wz0, wz1 = 1.3, 4.5, 0.3, 2.55
    box_span("wall_r0", X, X + T, 0, wy0, 0, H, M["wall"], bev=0)
    box_span("wall_r1", X, X + T, wy1, Y, 0, H, M["wall"], bev=0)
    box_span("wall_r2", X, X + T, wy0, wy1, 0, wz0, M["wall"], bev=0)
    box_span("wall_r3", X, X + T, wy0, wy1, wz1, H, M["wall"], bev=0)
    f = 0.045
    for name, a, b, c, d in [("l", wy0, wy0 + f, wz0, wz1), ("r", wy1 - f, wy1, wz0, wz1), ("b", wy0, wy1, wz0, wz0 + f),
                             ("t", wy0, wy1, wz1 - f, wz1), ("m", (wy0 + wy1) / 2 - f / 2, (wy0 + wy1) / 2 + f / 2, wz0, wz1)]:
        box_span(f"win_{name}", X - 0.02, X + 0.06, a, b, c, d, M["frame"], bev=0.002)
    g = plane("win_glass", wy1 - wy0, wz1 - wz0, (X + 0.02, (wy0 + wy1) / 2, (wz0 + wz1) / 2), M["glass"],
              rot=(math.pi / 2, 0, math.pi / 2))
    g.visible_shadow = False
    # Skirting.
    for name, a, b, c, d in [("bk", -X, X, Y - 0.015, Y), ("lf", -X, -X + 0.015, 0, Y), ("fr", -X, X, 0, 0.015)]:
        box_span(f"skirt_{name}", a, b, c, d, 0, 0.08, M["wall"], bev=0.002)
    # Sheer curtains, gathered at both ends of the window.
    cyl("curtain_rod", 0.01, wy1 - wy0 + 0.6, (X - 0.12, (wy0 + wy1) / 2, wz1 + 0.12), M["brass"],
        rot=(math.pi / 2, 0, 0), bev=0.002)
    for side, y0, sign in (("a", wy0 - 0.25, 1), ("b", wy1 + 0.25, -1)):
        bm = bmesh.new()
        nx, nz, w, hgt = 60, 2, 0.75, wz1 + 0.1
        rows = []
        for j in range(nz + 1):
            rows.append([bm.verts.new((0.04 * math.sin(i / nx * w / 0.07 * 2 * math.pi), sign * i / nx * w, -j / nz * hgt))
                         for i in range(nx + 1)])
        for j in range(nz):
            for i in range(nx):
                bm.faces.new([rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]])
        ob = mesh_object(f"curtain_{side}", bm, M["sheer"])
        ob.location = (X - 0.12, y0, wz1 + 0.11)
        ob.visible_shadow = False
    # Moonlight and the city glow through the window.
    light("window_sky", "AREA", (X - 0.05, (wy0 + wy1) / 2, (wz0 + wz1) / 2), 22, (0.55, 0.68, 1.0), "window",
          size=wz1 - wz0, size_y=wy1 - wy0, rot=(0, math.radians(90), 0), specular=0.6)
    anchor("window", (X, (wy0 + wy1) / 2, 1.4))


def city_backdrop():
    """Night skyline beyond the window."""
    m = bpy.data.materials.new("city")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    sky = nt.nodes.new("ShaderNodeValToRGB")
    se = sky.color_ramp.elements
    se[0].position, se[0].color = 0.0, (0.05, 0.03, 0.03, 1)
    se[1].position, se[1].color = 0.8, (0.004, 0.007, 0.02, 1)
    se.new(0.35).color = (0.02, 0.02, 0.04, 1)
    nt.links.new(sep.outputs["Y"], sky.inputs["Fac"])
    vor = node(nt, "ShaderNodeTexVoronoi", Scale=30.0, Randomness=1.0)
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (2.4, 1.0, 1.0)
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], vor.inputs["Vector"])
    dot = nt.nodes.new("ShaderNodeMapRange")
    dot.inputs["From Min"].default_value = 0.12
    dot.inputs["From Max"].default_value = 0.02
    nt.links.new(vor.outputs["Distance"], dot.inputs["Value"])
    pick = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(vor.outputs["Color"], pick.inputs[0])
    keep = nt.nodes.new("ShaderNodeMath")
    keep.operation = "GREATER_THAN"
    keep.inputs[1].default_value = 0.45
    nt.links.new(pick.outputs[0], keep.inputs[0])
    low = nt.nodes.new("ShaderNodeMapRange")
    low.inputs["From Min"].default_value = 0.6
    low.inputs["From Max"].default_value = 0.4
    nt.links.new(sep.outputs["Y"], low.inputs["Value"])
    m1 = nt.nodes.new("ShaderNodeMath")
    m1.operation = "MULTIPLY"
    nt.links.new(dot.outputs[0], m1.inputs[0])
    nt.links.new(keep.outputs[0], m1.inputs[1])
    m2 = nt.nodes.new("ShaderNodeMath")
    m2.operation = "MULTIPLY"
    nt.links.new(m1.outputs[0], m2.inputs[0])
    nt.links.new(low.outputs[0], m2.inputs[1])
    tint = nt.nodes.new("ShaderNodeValToRGB")
    te = tint.color_ramp.elements
    te[0].position, te[0].color = 0.0, (1.0, 0.55, 0.22, 1)
    te[1].position, te[1].color = 1.0, (0.55, 0.75, 1.0, 1)
    te.new(0.5).color = (1.0, 0.85, 0.6, 1)
    nt.links.new(pick.outputs[1], tint.inputs["Fac"])
    lc = nt.nodes.new("ShaderNodeMix")
    lc.data_type = "RGBA"
    lc.blend_type = "MULTIPLY"
    lc.inputs["Factor"].default_value = 1.0
    nt.links.new(tint.outputs["Color"], lc.inputs[6])
    comb = nt.nodes.new("ShaderNodeCombineColor")
    for k in range(3):
        nt.links.new(m2.outputs[0], comb.inputs[k])
    nt.links.new(comb.outputs[0], lc.inputs[7])
    em_l = nt.nodes.new("ShaderNodeEmission")
    em_l.inputs["Strength"].default_value = 5.0
    nt.links.new(lc.outputs[2], em_l.inputs["Color"])
    em_s = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(sky.outputs["Color"], em_s.inputs["Color"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(em_s.outputs[0], add.inputs[0])
    nt.links.new(em_l.outputs[0], add.inputs[1])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(add.outputs[0], out.inputs[0])
    REG["city_lights"] = em_l.inputs["Strength"]
    REG["city_sky"] = em_s.inputs["Strength"]
    ob = plane("city", 40, 16, (16.0, 3.0, 3.0), m, rot=(math.pi / 2, 0, math.pi / 2), collection="city")
    ob.visible_shadow = False
    ob.visible_diffuse = False


def tv_wall(M):
    """Walnut slats behind the TV, a hidden LED grazing them, and the floating console."""
    x0, x1 = -1.75, 1.75
    box_span("slat_back", x0, x1, ROOM_Y - 0.03, ROOM_Y, 0, H, M["slat_back"], bev=0)
    n = int((x1 - x0) / 0.05)
    for i in range(n):
        x = x0 + 0.025 + i * 0.05
        box_span(f"slat{i}", x - 0.017, x + 0.017, ROOM_Y - 0.06, ROOM_Y - 0.03, 0.0, H, M["slat"], bev=0.002)
    strip = glow_material("slat_led_m", (1.0, 0.7, 0.42), 6.0, "slat")
    box_span("slat_led", x0, x1, ROOM_Y - 0.12, ROOM_Y - 0.1, H - 0.03, H - 0.02, strip, bev=0)
    light("slat_light", "AREA", (0, ROOM_Y - 0.11, H - 0.04), 70, (1.0, 0.68, 0.4), "slat", size=x1 - x0, size_y=0.05,
          specular=0.3)
    # Floating walnut console.
    cx0, cx1, cy0, cy1, cz0 = -1.3, 1.3, 5.12, ROOM_Y - 0.06, 0.22
    box_span("console", cx0, cx1, cy0, cy1, cz0, CONSOLE_TOP, M["walnut"], bev=0.006)
    for k in range(1, 4):
        x = cx0 + k * (cx1 - cx0) / 4
        box_span(f"console_seam{k}", x - 0.002, x + 0.002, cy0 - 0.002, cy0, cz0 + 0.02, CONSOLE_TOP - 0.02, M["slat_back"], bev=0)
    under = glow_material("console_led_m", (1.0, 0.65, 0.38), 3.0, "console")
    box_span("console_led", cx0 + 0.05, cx1 - 0.05, cy0 + 0.05, cy0 + 0.07, cz0 - 0.012, cz0 - 0.004, under, bev=0)
    light("console_light", "AREA", (0, cy0 + 0.12, cz0 - 0.02), 18, (1.0, 0.65, 0.38), "console", size=2.4, size_y=0.08,
          specular=0.2)
    # Things on the console.
    plant("plant_console", (-0.98, 5.36, CONSOLE_TOP), 0.32, M, pot=0.07)
    cyl("vase", 0.06, 0.26, (-0.62, 5.36, CONSOLE_TOP + 0.13), M["ceramic"], seg=32, r2=0.035, bev=0.01)
    for k in range(3):
        box(f"cbook{k}", (0.24, 0.17, 0.028), (0.38, 5.36, CONSOLE_TOP + 0.014 + k * 0.029), M["book"][k + 1], bev=0.003,
            rot=(0, 0, 0.06 * (k - 1)))


def seating(M):
    sx, sy = SOFA.x, SOFA.y
    box_span("rug", -1.7, 1.7, 1.75, 4.3, 0.0, 0.014, M["rug"], bev=0.006)
    for i, dx in enumerate([-1.15, 1.15]):
        for j, dy in enumerate([-0.38, 0.38]):
            cyl(f"sofa_leg{i}{j}", 0.02, 0.08, (sx + dx, sy + dy, 0.04), M["walnut"], seg=16, bev=0.003)
    box("sofa_base", (2.6, 0.95, 0.24), (sx, sy, 0.2), M["sofa"], bev=0.05, seg=4)
    box("sofa_back", (2.6, 0.22, 0.52), (sx, sy - 0.37, 0.58), M["sofa"], bev=0.07, seg=4)
    for i, dx in enumerate([-1.25, 1.25]):
        box(f"sofa_arm{i}", (0.2, 0.95, 0.46), (sx + dx, sy, 0.43), M["sofa"], bev=0.08, seg=4)
    for i, dx in enumerate([-0.57, 0.57]):
        box(f"sofa_seat{i}", (1.12, 0.78, 0.16), (sx + dx, sy + 0.06, 0.4), M["sofa"], bev=0.06, seg=5)
        box(f"sofa_cush{i}", (1.08, 0.2, 0.46), (sx + dx, sy - 0.22, 0.71), M["sofa"], bev=0.08, seg=5,
            rot=(0.18, 0, 0))
    box("pillow1", (0.44, 0.13, 0.44), (sx - 0.85, sy - 0.08, 0.68), M["pillow_a"], bev=0.06, seg=5, rot=(0.25, 0, -0.2))
    box("pillow2", (0.42, 0.13, 0.42), (sx + 0.88, sy - 0.08, 0.67), M["pillow_b"], bev=0.06, seg=5, rot=(0.25, 0, 0.25))
    box("throw", (0.55, 0.62, 0.03), (sx + 0.45, sy + 0.1, 0.495), M["throw"], bev=0.012, rot=(0, 0.04, -0.3))
    anchor("sofa", (sx, sy, 0.6))
    # Coffee table: stone top on black legs, with the speaker, the remote, a mug and books.
    tx, ty = TABLE.x, TABLE.y
    box_span("ctable_top", tx - 0.62, tx + 0.62, ty - 0.32, ty + 0.32, TABLE.z - 0.035, TABLE.z, M["stone"], bev=0.008)
    for i, (ox, oy) in enumerate([(-0.56, -0.26), (0.56, -0.26), (-0.56, 0.26), (0.56, 0.26)]):
        box(f"ctable_leg{i}", (0.03, 0.03, TABLE.z - 0.035), (tx + ox, ty + oy, (TABLE.z - 0.035) / 2), M["black_metal"],
            bev=0.004)
    cyl("mug", 0.04, 0.09, (tx - 0.42, ty + 0.14, TABLE.z + 0.045), M["ceramic"], seg=32, bev=0.006)
    # Floor lamp beside the sofa (drum shade on a tall stem).
    fx, fy = -1.72, 1.05
    cyl("flamp_base", 0.16, 0.025, (fx, fy, 0.0125), M["black_metal"], bev=0.006)
    cyl("flamp_pole", 0.011, 1.45, (fx, fy, 0.75), M["brass"], seg=16, bev=0.002)
    shade_m = glow_material("flamp_shade_m", WARM, 2.5, "floor")
    cyl("flamp_shade", 0.22, 0.3, (fx, fy, 1.56), shade_m, r2=0.19, bev=0.004)
    light("flamp_light", "POINT", (fx, fy, 1.53), 60, WARM, "floor", size=0.08)
    light("flamp_down", "SPOT", (fx, fy, 1.45), 70, WARM, "floor", size=0.12, spot=(1.7, 0.7))
    anchor("floorlamp", (fx, fy, 1.6))
    # Side table with a small mushroom lamp on the other side.
    stx, sty = 1.62, 1.35
    cyl("stable_top", 0.24, 0.025, (stx, sty, 0.55), M["walnut"], bev=0.006)
    cyl("stable_stem", 0.025, 0.54, (stx, sty, 0.27), M["black_metal"], seg=16, bev=0)
    cyl("stable_foot", 0.17, 0.015, (stx, sty, 0.0075), M["black_metal"], bev=0.004)
    tl_m = glow_material("tlamp_shade_m", WARM_SOFT, 3.0, "table")
    sphere("tlamp_shade", 0.12, (stx, sty, 0.8), tl_m, scale=(1, 1, 0.62))
    cyl("tlamp_stem", 0.012, 0.2, (stx, sty, 0.67), M["brass"], seg=12, bev=0)
    light("tlamp_light", "POINT", (stx, sty, 0.76), 22, WARM_SOFT, "table", size=0.06)


def side_walls(M):
    # Bookshelf and a big plant on the left wall.
    bx = -ROOM_X + 0.17
    box_span("shelf", -ROOM_X, -ROOM_X + 0.34, 3.4, 4.95, 0, 2.0, M["oak"], bev=0.006)
    rnd = random.Random(5)
    for k in range(5):
        z = 0.06 + k * 0.4
        box_span(f"shelf_board{k}", -ROOM_X + 0.02, -ROOM_X + 0.34, 3.42, 4.93, z - 0.02, z, M["walnut"], bev=0.002)
        y = 3.46
        while y < 4.88:
            w = rnd.uniform(0.025, 0.05)
            hgt = rnd.uniform(0.2, 0.32)
            if rnd.random() < 0.18:
                y += 0.1
                continue
            box(f"sbook{k}_{y:.2f}", (0.24, w, hgt), (bx, y + w / 2, z + hgt / 2), rnd.choice(M["book"]), bev=0.003)
            y += w + 0.004
    plant("plant_big", (-2.75, 5.1, 0.0), 1.3, M, pot=0.2)
    plant("plant_win", (2.85, 4.95, 0.0), 1.0, M, pot=0.17)
    # Art behind the sofa.
    for i, (x, c) in enumerate([(-0.5, (0.75, 0.42, 0.25)), (0.5, (0.25, 0.4, 0.5))]):
        box(f"art{i}_frame", (0.7, 0.03, 0.9), (x, 0.02, 1.5), M["walnut"], bev=0.004)
        plane(f"art{i}", 0.62, 0.82, (x, 0.04, 1.5), principled(f"art{i}_m", c, rough=0.8), rot=(math.pi / 2, 0, 0))


def lights():
    # A warm cove around the ceiling, a soft room fill, the moon.
    for name, loc, sx, sy in [("cove_a", (0, 0.3, H - 0.05), 6.2, 0.1), ("cove_b", (0, ROOM_Y - 0.3, H - 0.05), 6.2, 0.1),
                              ("cove_c", (-ROOM_X + 0.3, ROOM_Y / 2, H - 0.05), 0.1, 5.0)]:
        light(name, "AREA", loc, 40, (1.0, 0.7, 0.45), "cove", size=sx, size_y=sy, rot=(math.pi, 0, 0), shadow=False,
              specular=0.1)
    light("room_fill", "AREA", (0, 2.8, H - 0.1), 40, (0.85, 0.85, 1.0), "fill", size=5.5, size_y=4.5, rot=(0, 0, 0),
          shadow=False, specular=0.0)
    ob = light("moon", "SUN", (5, 3, 6), 0.25, (0.55, 0.65, 1.0), "moon", size=math.radians(1.5))
    # A moonbeam through the window onto the coffee table (the opening macro).
    beam = light("moonbeam", "SPOT", (ROOM_X - 0.25, 2.75, 2.1), 0, (0.6, 0.72, 1.0), None, size=0.2,
                 spot=(math.radians(16), 0.7), specular=1.0)
    beam.rotation_euler = (REMOTE + Vector((0.05, 0.05, 0.0)) - beam.location).to_track_quat("-Z", "Y").to_euler()
    d = Vector((-1.0, -0.15, -0.55)).normalized()
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def dust(collection="dust", n=140, center=TABLE + Vector((0.0, 0.0, 0.25)), spread=(0.9, 0.7, 0.45), seed=7):
    """Specks floating in the air, lit like dust in a beam (macro shots only)."""
    pm = emission("dust_m", (0.85, 0.9, 1.0), 0.0)
    REG["dust"] = []
    rnd = random.Random(seed)
    for i in range(n):
        p = Vector(center) + Vector([rnd.uniform(-s, s) for s in spread])
        ob = sphere(f"dust{i}", rnd.uniform(0.0006, 0.0016), p, pm, seg=8, collection=collection)
        ob.visible_shadow = False
        REG["dust"].append((ob, p.copy(), rnd.uniform(0, 6.28), rnd.uniform(0.3, 1.0)))
    REG["dust_strength"] = pm.node_tree.nodes["Emission"].inputs["Strength"]


def set_dust(t, strength):
    for ob, p0, ph, sp in REG["dust"]:
        ob.location = p0 + Vector((0.03 * math.sin(t * 0.3 * sp + ph), 0.02 * math.cos(t * 0.25 * sp + ph),
                                   0.015 * math.sin(t * 0.2 * sp + 2 * ph) - 0.004 * t * sp))
    REG["dust_strength"].default_value = strength


def build(M):
    shell(M)
    city_backdrop()
    tv_wall(M)
    seating(M)
    side_walls(M)
    lights()
    dust()
