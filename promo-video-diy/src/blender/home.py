"""The home: a three-room cutaway apartment that works both as a real-scale
interior and, seen from outside, as a floating diorama.

Rooms along X: kid's room [-7, -3.5], living room [-3.5, 3.5],
kitchen + laundry [3.5, 8]. The open side faces -Y, the back wall is at y = 5.
"""
import math
import random

import bmesh
import bpy
from mathutils import Vector

from kit import (REG, WARM, WARM_SOFT, anchor, art, box, box_span, cyl, emission, fabric, glow_material,
                 group_emit, light, mesh_object, node, plane, principled, sphere, text, torus)

H = 2.7            # wall height
T = 0.12           # wall thickness
COFFEE = Vector((-1.0, 3.0, 0.42))       # top of the coffee table
SPEAKER_HOME = Vector((-0.86, 2.9, 0.42))
MINIPC_HOME = Vector((-3.2, 3.22, 0.575))
DESK = Vector((-5.2, 4.62, 0.70))        # top of the kid's desk
STOVE = Vector((4.42, 4.68, 0.905))      # left burner on the cooktop
WASHER = Vector((7.65, 0.95, 0.0))


# ---------------------------------------------------------------- materials

def wall_material(name, color):
    """Plaster wall that can turn into cold glass (the 'no secrets' shot).

    REG["xray"] collects the mix factors: 0 = solid wall, 1 = transparent glass
    with a cold fresnel edge.
    """
    m = principled(name, color, rough=0.92, spec=0.3)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    out = nt.nodes["Material Output"]
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    lw = node(nt, "ShaderNodeLayerWeight", Blend=0.35)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.45, 0.7, 1.0, 1)
    edge = nt.nodes.new("ShaderNodeMath")
    edge.operation = "MULTIPLY"
    edge.inputs[1].default_value = 0.7
    nt.links.new(lw.outputs["Facing"], edge.inputs[0])
    nt.links.new(edge.outputs[0], em.inputs["Strength"])
    glass = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(tr.outputs[0], glass.inputs[0])
    nt.links.new(em.outputs[0], glass.inputs[1])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.0
    nt.links.new(b.outputs[0], mix.inputs[1])
    nt.links.new(glass.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    m.surface_render_method = "BLENDED"
    m.use_transparent_shadow = True
    REG.setdefault("xray", []).append(mix.inputs["Fac"])
    return m


def tiles(name, color, grout, scale=2.5):
    m = principled(name, color, rough=0.25, coat=0.3)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    br = node(nt, "ShaderNodeTexBrick", Scale=scale, **{"Mortar Size": 0.012, "Bias": 0.0})
    br.offset = 0.0
    br.squash = 1.0
    br.inputs["Color1"].default_value = (*color, 1)
    br.inputs["Color2"].default_value = (*[c * 0.94 for c in color], 1)
    br.inputs["Mortar"].default_value = (*grout, 1)
    br.inputs["Brick Width"].default_value = 0.5
    br.inputs["Row Height"].default_value = 0.5
    nt.links.new(tc.outputs["Object"], br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    return m


def make_materials():
    M = {}
    M["wall"] = wall_material("wall", (0.66, 0.62, 0.57))
    M["wall_kid"] = wall_material("wall_kid", (0.5, 0.58, 0.6))
    M["wall_kit"] = wall_material("wall_kit", (0.7, 0.68, 0.64))
    M["slab"] = principled("slab", (0.03, 0.03, 0.035), rough=0.45, coat=0.4)
    M["slab_edge"] = emission("slab_edge", (1.0, 0.62, 0.32), 0.0)
    REG["slab_edge"] = M["slab_edge"].node_tree.nodes["Emission"].inputs["Strength"]

    # Oak planks: brick texture gives the plank layout, noise adds grain.
    m = principled("floor", (0.4, 0.26, 0.15), rough=0.38, coat=0.15)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (1.0, 5.5, 1.0)
    brick = node(nt, "ShaderNodeTexBrick", Scale=1.2, **{"Mortar Size": 0.004, "Bias": 0.0})
    brick.offset = 0.5
    brick.squash = 1.0
    brick.inputs["Color1"].default_value = (0.36, 0.22, 0.12, 1)
    brick.inputs["Color2"].default_value = (0.46, 0.30, 0.17, 1)
    brick.inputs["Mortar"].default_value = (0.12, 0.07, 0.04, 1)
    nt.links.new(mp.outputs[0], brick.inputs["Vector"])
    grain = node(nt, "ShaderNodeTexNoise", Scale=38.0, Detail=6.0, Roughness=0.6)
    gm = node(nt, "ShaderNodeMapping")
    gm.inputs["Scale"].default_value = (1.0, 16.0, 1.0)
    nt.links.new(tc.outputs["Object"], gm.inputs["Vector"])
    nt.links.new(gm.outputs[0], grain.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "OVERLAY"
    mix.inputs["Factor"].default_value = 0.35
    nt.links.new(brick.outputs["Color"], mix.inputs[6])
    nt.links.new(grain.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    M["floor"] = m
    M["floor_tile"] = tiles("floor_tile", (0.55, 0.53, 0.5), (0.25, 0.24, 0.22), scale=1.6)
    M["backsplash"] = tiles("backsplash", (0.86, 0.85, 0.82), (0.55, 0.54, 0.52), scale=6.0)

    M["rug"] = fabric("rug", (0.62, 0.57, 0.5), scale=260, bump=0.25)
    M["rug_kid"] = fabric("rug_kid", (0.78, 0.62, 0.36), scale=260, bump=0.25)
    M["sofa"] = fabric("sofa", (0.10, 0.19, 0.22), scale=180)
    M["pillow_a"] = fabric("pillow_a", (0.72, 0.46, 0.16), scale=180)
    M["pillow_b"] = fabric("pillow_b", (0.62, 0.3, 0.22), scale=180)
    M["duvet"] = fabric("duvet", (0.86, 0.84, 0.8), scale=150)
    M["kid_cover"] = fabric("kid_cover", (0.95, 0.72, 0.28), scale=150)
    M["kid_cover2"] = fabric("kid_cover2", (0.32, 0.5, 0.72), scale=150)
    M["plush"] = fabric("plush", (0.62, 0.42, 0.26), scale=400, bump=0.4)
    M["curtain"] = fabric("curtain", (0.74, 0.66, 0.55), scale=120, bump=0.1)
    M["chair_fabric"] = fabric("chair_fabric", (0.55, 0.32, 0.22), scale=180)
    M["oak"] = principled("oak", (0.55, 0.38, 0.22), rough=0.35, coat=0.2)
    M["walnut"] = principled("walnut", (0.2, 0.11, 0.06), rough=0.35, coat=0.3)
    M["birch"] = principled("birch", (0.62, 0.5, 0.36), rough=0.45, coat=0.15)
    M["black_metal"] = principled("black_metal", (0.03, 0.03, 0.03), rough=0.35, metal=1.0)
    M["steel"] = principled("steel", (0.62, 0.62, 0.64), rough=0.22, metal=1.0)
    M["brass"] = principled("brass", (0.8, 0.58, 0.3), rough=0.25, metal=1.0)
    M["white_plastic"] = principled("white_plastic", (0.85, 0.85, 0.83), rough=0.3, coat=0.3)
    M["cabinet"] = principled("cabinet", (0.2, 0.25, 0.24), rough=0.45, coat=0.2)
    M["counter"] = principled("counter", (0.86, 0.85, 0.82), rough=0.18, coat=0.6)
    M["ac_body"] = principled("ac_body", (0.9, 0.9, 0.88), rough=0.25, coat=0.4)
    M["ac_slot"] = principled("ac_slot", (0.08, 0.08, 0.09), rough=0.5)
    M["screen_off"] = principled("screen_off", (0.01, 0.01, 0.012), rough=0.08, coat=1.0)
    M["frame"] = principled("frame", (0.12, 0.12, 0.13), rough=0.4, metal=0.6)
    M["glass"] = principled("glass", (0.6, 0.7, 0.75), rough=0.03, alpha=0.1, spec=1.0)
    M["ceramic"] = principled("ceramic", (0.85, 0.82, 0.76), rough=0.25, coat=0.5)
    M["ceramic_dark"] = principled("ceramic_dark", (0.14, 0.12, 0.11), rough=0.3, coat=0.5)
    M["leaf"] = principled("leaf", (0.07, 0.2, 0.08), rough=0.55, sheen=0.3)
    M["leaf2"] = principled("leaf2", (0.12, 0.28, 0.1), rough=0.55, sheen=0.3)
    M["book"] = [principled(f"book{i}", c, rough=0.6) for i, c in enumerate([
        (0.55, 0.16, 0.12), (0.14, 0.24, 0.38), (0.8, 0.72, 0.55), (0.2, 0.32, 0.22),
        (0.7, 0.45, 0.16), (0.12, 0.12, 0.14), (0.62, 0.6, 0.56)])]
    M["toy"] = [principled(f"toy{i}", c, rough=0.35, coat=0.4) for i, c in enumerate([
        (0.85, 0.2, 0.15), (0.15, 0.45, 0.85), (0.95, 0.75, 0.15), (0.2, 0.65, 0.35)])]
    M["art_a"] = art("art_a", [(0.0, (0.95, 0.55, 0.25)), (0.5, (0.85, 0.3, 0.3)), (1.0, (0.2, 0.18, 0.35))])
    M["art_b"] = art("art_b", [(0.0, (0.9, 0.85, 0.72)), (0.6, (0.35, 0.55, 0.6)), (1.0, (0.1, 0.2, 0.28))])
    M["art_kid"] = art("art_kid", [(0.0, (1.0, 0.85, 0.4)), (0.5, (0.45, 0.75, 0.9)), (1.0, (0.2, 0.3, 0.6))])
    return M


# ---------------------------------------------------------------- shell

def window(name, x0, x1, z0, z1, M, y=5.06, mullion=True):
    f = 0.045
    box_span(f"{name}_frame_l", x0, x0 + f, y - 0.04, y + 0.04, z0, z1, M["frame"])
    box_span(f"{name}_frame_r", x1 - f, x1, y - 0.04, y + 0.04, z0, z1, M["frame"])
    box_span(f"{name}_frame_b", x0, x1, y - 0.05, y + 0.05, z0, z0 + f, M["frame"])
    box_span(f"{name}_frame_t", x0, x1, y - 0.04, y + 0.04, z1 - f, z1, M["frame"])
    if mullion:
        xm = (x0 + x1) / 2
        box_span(f"{name}_frame_m", xm - f / 2, xm + f / 2, y - 0.04, y + 0.04, z0, z1, M["frame"])
    g = plane(f"{name}_glass", x1 - x0, z1 - z0, ((x0 + x1) / 2, y, (z0 + z1) / 2), M["glass"],
              rot=(math.pi / 2, 0, 0))
    g.visible_shadow = False


def walls(M):
    y0, y1 = 5.0, 5.0 + T
    # Back wall, with windows: kid's room x[-5.9,-4.5] z[1.0,2.2]; living x[0.8,3.2] z[0.5,2.4];
    # kitchen x[5.95,7.05] z[1.15,2.15].
    spans = [
        (-7.0 - T, -5.9, 0, H, "wall_kid"), (-5.9, -4.5, 0, 1.0, "wall_kid"), (-5.9, -4.5, 2.2, H, "wall_kid"),
        (-4.5, -3.5, 0, H, "wall_kid"),
        (-3.5, 0.8, 0, H, "wall"), (0.8, 3.2, 0, 0.5, "wall"), (0.8, 3.2, 2.4, H, "wall"), (3.2, 3.5, 0, H, "wall"),
        (3.5, 5.95, 0, H, "wall_kit"), (5.95, 7.05, 0, 1.15, "wall_kit"), (5.95, 7.05, 2.15, H, "wall_kit"),
        (7.05, 8.0 + T, 0, H, "wall_kit"),
    ]
    for i, (a, b, za, zb, mat) in enumerate(spans):
        box_span(f"wall_back_{i}", a, b, y0, y1, za, zb, M[mat])
    box_span("wall_left", -7.0 - T, -7.0, 0, y0, 0, H, M["wall_kid"])
    box_span("wall_right", 8.0, 8.0 + T, 0, y0, 0, H, M["wall_kit"])
    # Partitions with doorways near the open side, y [0.3, 1.2].
    for name, x, mat in [("part_a", -3.5, M["wall"]), ("part_b", 3.5, M["wall"])]:
        box_span(f"{name}_1", x - T / 2, x + T / 2, 1.2, y0, 0, H, mat)
        box_span(f"{name}_2", x - T / 2, x + T / 2, 0, 0.3, 0, H, mat)
        box_span(f"{name}_3", x - T / 2, x + T / 2, 0.3, 1.2, 2.1, H, mat)
    # Floor slab, a thin glowing seam under the floor (diorama only) and floors.
    box_span("slab", -7.0 - T - 0.15, 8.0 + T + 0.15, -0.3, 5.0 + T + 0.15, -0.34, -0.06, M["slab"], bev=0.02)
    seam = box_span("slab_seam", -7.0 - T - 0.13, 8.0 + T + 0.13, -0.28, 5.0 + T + 0.13, -0.06, -0.045,
                    M["slab_edge"], bev=0, collection="diorama")
    seam.visible_shadow = False
    box_span("floor_wood", -7.0, 3.5, 0, 5.0, -0.045, 0.0, M["floor"], bev=0)
    box_span("floor_kit", 3.5, 8.0, 0, 5.0, -0.045, 0.0, M["floor_tile"], bev=0)
    # Interior-only pieces: front walls and ceilings (hidden in diorama shots).
    for name, a, b, mat in [("kid", -7.0, -3.5, "wall_kid"), ("liv", -3.5, 3.5, "wall"), ("kit", 3.5, 8.0, "wall_kit")]:
        box_span(f"wall_front_{name}", a, b, -T, 0, 0, H, M[mat], collection="interior")
        box_span(f"ceiling_{name}", a, b, 0, 5.0, H, H + 0.1, M[mat], collection="interior")
    window("win_kid", -5.9, -4.5, 1.0, 2.2, M)
    window("win_liv", 0.8, 3.2, 0.5, 2.4, M)
    window("win_kit", 5.95, 7.05, 1.15, 2.15, M)


def city_backdrop():
    """Night skyline far behind the back windows, only used for interior shots."""
    m = bpy.data.materials.new("city")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    sky = nt.nodes.new("ShaderNodeValToRGB")
    se = sky.color_ramp.elements
    se[0].position, se[0].color = 0.0, (0.07, 0.035, 0.03, 1)
    se[1].position, se[1].color = 0.75, (0.004, 0.007, 0.018, 1)
    se.new(0.35).color = (0.02, 0.018, 0.035, 1)
    nt.links.new(sep.outputs["Y"], sky.inputs["Fac"])
    # Scattered window lights: Voronoi cells, thresholded, only in the lower part.
    vor = node(nt, "ShaderNodeTexVoronoi", Scale=26.0, Randomness=1.0)
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
    low.inputs["From Min"].default_value = 0.62
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
    lights_c = nt.nodes.new("ShaderNodeMix")
    lights_c.data_type = "RGBA"
    lights_c.blend_type = "MULTIPLY"
    lights_c.inputs["Factor"].default_value = 1.0
    nt.links.new(tint.outputs["Color"], lights_c.inputs[6])
    comb = nt.nodes.new("ShaderNodeCombineColor")
    for k in range(3):
        nt.links.new(m2.outputs[0], comb.inputs[k])
    nt.links.new(comb.outputs[0], lights_c.inputs[7])
    em_l = nt.nodes.new("ShaderNodeEmission")
    em_l.inputs["Strength"].default_value = 6.0
    nt.links.new(lights_c.outputs[2], em_l.inputs["Color"])
    em_s = nt.nodes.new("ShaderNodeEmission")
    em_s.inputs["Strength"].default_value = 1.0
    nt.links.new(sky.outputs["Color"], em_s.inputs["Color"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(em_s.outputs[0], add.inputs[0])
    nt.links.new(em_l.outputs[0], add.inputs[1])
    # Daylight / dusk versions, mixed in by "day" (0 night, 1 day) and "dusk".
    day_e = nt.nodes.new("ShaderNodeEmission")
    day_ramp = nt.nodes.new("ShaderNodeValToRGB")
    de = day_ramp.color_ramp.elements
    de[0].position, de[0].color = 0.0, (0.95, 0.9, 0.82, 1)
    de[1].position, de[1].color = 1.0, (0.45, 0.65, 0.95, 1)
    nt.links.new(sep.outputs["Y"], day_ramp.inputs["Fac"])
    nt.links.new(day_ramp.outputs["Color"], day_e.inputs["Color"])
    day_e.inputs["Strength"].default_value = 3.0
    dusk_e = nt.nodes.new("ShaderNodeEmission")
    dusk_ramp = nt.nodes.new("ShaderNodeValToRGB")
    ke = dusk_ramp.color_ramp.elements
    ke[0].position, ke[0].color = 0.0, (1.0, 0.45, 0.2, 1)
    ke[1].position, ke[1].color = 0.8, (0.12, 0.12, 0.3, 1)
    ke.new(0.35).color = (0.85, 0.35, 0.35, 1)
    nt.links.new(sep.outputs["Y"], dusk_ramp.inputs["Fac"])
    nt.links.new(dusk_ramp.outputs["Color"], dusk_e.inputs["Color"])
    dusk_e.inputs["Strength"].default_value = 1.6
    dusk_add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(dusk_e.outputs[0], dusk_add.inputs[0])
    nt.links.new(em_l.outputs[0], dusk_add.inputs[1])
    mix_dusk = nt.nodes.new("ShaderNodeMixShader")
    mix_dusk.inputs["Fac"].default_value = 0.0
    nt.links.new(add.outputs[0], mix_dusk.inputs[1])
    nt.links.new(dusk_add.outputs[0], mix_dusk.inputs[2])
    mixs = nt.nodes.new("ShaderNodeMixShader")
    mixs.inputs["Fac"].default_value = 0.0
    nt.links.new(mix_dusk.outputs[0], mixs.inputs[1])
    nt.links.new(day_e.outputs[0], mixs.inputs[2])
    # Fade to transparent (the crane shot rises out of the room into the void).
    fade = nt.nodes.new("ShaderNodeMixShader")
    fade.inputs["Fac"].default_value = 0.0
    nt.links.new(mixs.outputs[0], fade.inputs[1])
    nt.links.new(nt.nodes.new("ShaderNodeBsdfTransparent").outputs[0], fade.inputs[2])
    m.surface_render_method = "BLENDED"
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(fade.outputs[0], out.inputs[0])
    REG["city_fade"] = fade.inputs["Fac"]
    REG["city_day"] = mixs.inputs["Fac"]
    REG["city_dusk"] = mix_dusk.inputs["Fac"]
    REG["city_lights"] = em_l.inputs["Strength"]
    ob = plane("city", 40, 16, (0.5, 16.0, 4.0), m, rot=(math.pi / 2, 0, 0), collection="city")
    ob.visible_shadow = False
    ob.visible_diffuse = False


# ---------------------------------------------------------------- living room

def plant(name, loc, height, M, pot=0.12):
    x, y, z = loc
    cyl(f"{name}_pot", pot, pot * 1.5, (x, y, z + pot * 0.75), M["ceramic"], seg=32, r2=pot * 0.8, bev=0.01)
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


def ac_unit(prefix, x, y, z, M, values):
    box(f"{prefix}", (0.95, 0.22, 0.3), (x, y, z), M["ac_body"], bev=0.03, seg=4)
    box(f"{prefix}_slot", (0.82, 0.04, 0.03), (x, y - 0.11, z - 0.11), M["ac_slot"], bev=0.01)
    box(f"{prefix}_screen", (0.16, 0.004, 0.06), (x + 0.3, y - 0.111, z + 0.02), M["screen_off"], bev=0.002)
    for val in values:
        mm = emission(f"{prefix}_{val}_m", (0.55, 0.85, 1.0), 0.0)
        text(f"{prefix}_{val}", f"{val}°", 0.05, (x + 0.3, y - 0.114, z + 0.02), mm)
        REG[f"{prefix}_{val}"] = mm.node_tree.nodes["Emission"].inputs["Strength"]


def room_haze(name, x0, x1, y0, y1, z0, z1):
    """A local volume of thin air dust (cheaper and better behaved than world fog)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = mesh_object(name, bm, None, "haze", smooth=False)
    ob.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    ob.scale = (x1 - x0, y1 - y0, z1 - z0)
    m = bpy.data.materials.new(f"{name}_m")
    nt = m.node_tree
    nt.nodes.clear()
    v = nt.nodes.new("ShaderNodeVolumeScatter")
    v.inputs["Density"].default_value = 0.0
    v.inputs["Anisotropy"].default_value = 0.55
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(v.outputs[0], out.inputs["Volume"])
    ob.data.materials.append(m)
    REG[name] = v.inputs["Density"]
    return ob


def living_room(M):
    room_haze("haze_living", -3.44, 3.44, 0.02, 4.95, 0.01, 2.65)
    box_span("rug", -2.6, 0.6, 1.95, 4.05, 0.0, 0.015, M["rug"], bev=0.006)
    # Sofa against the back wall.
    sx, sy = -1.0, 4.45
    for i, dx in enumerate([-1.15, 1.15]):
        for j, dy in enumerate([-0.38, 0.38]):
            cyl(f"sofa_leg{i}{j}", 0.02, 0.08, (sx + dx, sy + dy, 0.04), M["walnut"], seg=16, bev=0.003)
    box("sofa_base", (2.5, 0.95, 0.24), (sx, sy, 0.2), M["sofa"], bev=0.05, seg=4)
    box("sofa_back", (2.5, 0.22, 0.52), (sx, sy + 0.37, 0.58), M["sofa"], bev=0.07, seg=4)
    for i, dx in enumerate([-1.2, 1.2]):
        box(f"sofa_arm{i}", (0.2, 0.95, 0.46), (sx + dx, sy, 0.43), M["sofa"], bev=0.08, seg=4)
    for i, dx in enumerate([-0.54, 0.54]):
        box(f"sofa_seat{i}", (1.08, 0.78, 0.16), (sx + dx, sy - 0.06, 0.4), M["sofa"], bev=0.06, seg=5)
        box(f"sofa_cush{i}", (1.05, 0.2, 0.44), (sx + dx, sy + 0.22, 0.7), M["sofa"], bev=0.08, seg=5,
            rot=(-0.18, 0, 0))
    box("pillow1", (0.42, 0.13, 0.42), (sx - 0.8, sy + 0.1, 0.66), M["pillow_a"], bev=0.06, seg=5,
        rot=(-0.25, 0, 0.2))
    box("pillow2", (0.4, 0.13, 0.4), (sx + 0.85, sy + 0.1, 0.65), M["pillow_b"], bev=0.06, seg=5,
        rot=(-0.25, 0, -0.25))
    box("throw", (0.5, 0.6, 0.03), (sx + 0.6, sy - 0.12, 0.49), M["kid_cover2"], bev=0.012, rot=(0, 0.05, 0.3))
    # Round coffee table with books and a mug; the speakers sit on it.
    cx, cy = COFFEE.x, COFFEE.y
    cyl("ctable_top", 0.42, 0.04, (cx, cy, 0.4), M["oak"], bev=0.012)
    for k in range(3):
        a = k * 2 * math.pi / 3 + 0.4
        cyl(f"ctable_leg{k}", 0.018, 0.38, (cx + 0.27 * math.cos(a), cy + 0.27 * math.sin(a), 0.19),
            M["black_metal"], seg=16, bev=0.003)
    box("book_a", (0.24, 0.17, 0.025), (cx - 0.22, cy - 0.12, 0.4325), M["book"][1], bev=0.003, rot=(0, 0, 0.3))
    box("book_b", (0.22, 0.16, 0.02), (cx - 0.21, cy - 0.11, 0.455), M["book"][2], bev=0.003, rot=(0, 0, 0.12))
    cyl("mug", 0.04, 0.09, (cx - 0.05, cy + 0.27, 0.465), M["ceramic"], seg=32, bev=0.006)
    # Floor lamp beside the sofa.
    fx, fy = -2.85, 4.5
    cyl("flamp_base", 0.16, 0.025, (fx, fy, 0.0125), M["black_metal"], bev=0.006)
    cyl("flamp_pole", 0.011, 1.45, (fx, fy, 0.75), M["brass"], seg=16, bev=0.002)
    shade_m = glow_material("flamp_shade_m", WARM, 3.0, "living_floor")
    cyl("flamp_shade", 0.24, 0.3, (fx, fy, 1.58), shade_m, r2=0.17, bev=0.004)
    light("flamp_light", "POINT", (fx, fy, 1.55), 90, WARM, "living_floor", size=0.08)
    light("flamp_up", "SPOT", (fx, fy, 1.7), 60, WARM, "living_floor", size=0.1, spot=(1.6, 0.8),
          rot=(math.pi, 0, 0))
    anchor("floorlamp", (fx, fy, 1.6))
    # Pendant over the table.
    cyl("pendant_cord", 0.004, 0.62, (cx, cy, H - 0.31), M["black_metal"], seg=8, bev=0)
    dome_m = principled("pendant_dome", (0.06, 0.06, 0.06), rough=0.35, metal=0.8)
    dome = sphere("pendant_dome", 0.3, (cx, cy, 2.08), dome_m, scale=(1, 1, 0.55))
    bmd = bmesh.new()
    bmd.from_mesh(dome.data)
    bmesh.ops.delete(bmd, geom=[v for v in bmd.verts if v.co.z < -0.001], context="VERTS")
    bmd.to_mesh(dome.data)
    bmd.free()
    dome.modifiers.new("solid", "SOLIDIFY").thickness = 0.01
    bulb_m = glow_material("pendant_bulb", (1.0, 0.75, 0.5), 25.0, "living_main")
    sphere("pendant_bulb", 0.05, (cx, cy, 2.07), bulb_m)
    disk_m = glow_material("pendant_disk", (1.0, 0.8, 0.6), 4.0, "living_main")
    cyl("pendant_diffuser", 0.27, 0.004, (cx, cy, 2.075), disk_m, bev=0)
    light("pendant_light", "AREA", (cx, cy, 2.04), 150, (1.0, 0.66, 0.38), "living_main", size=0.5)
    light("pendant_pt", "POINT", (cx, cy, 2.0), 25, (1.0, 0.66, 0.38), "living_main", size=0.1)
    light("living_fill", "AREA", (0.0, 2.5, 2.6), 70, (1.0, 0.74, 0.5), "living_fill", size=6.0,
          size_y=4.5, shadow=False, specular=0.0)
    anchor("pendant", (cx, cy, 2.1))
    # Wall art.
    for i, (x, m) in enumerate([(-1.95, M["art_a"]), (-1.2, M["art_b"])]):
        box(f"art{i}_frame", (0.56, 0.03, 0.72), (x, 4.975, 1.52), M["walnut"], bev=0.004)
        plane(f"art{i}_canvas", 0.5, 0.66, (x, 4.958, 1.52), m, rot=(math.pi / 2, 0, 0))
    # Wall-mounted air conditioner between sofa and window.
    ac_unit("ac_l", 0.05, 4.89, 2.28, M, ("24", "26"))
    anchor("ac_living", (0.05, 4.8, 2.28))
    # Sideboard on the partition wall: the mini PC lives here, between a vase and a plant.
    box("sideboard", (0.42, 1.6, 0.55), (-3.22, 3.2, 0.3), M["walnut"], bev=0.01)
    for k in range(3):
        box(f"sideboard_door{k}", (0.005, 0.5, 0.45), (-3.0, 2.67 + k * 0.53, 0.32), M["oak"], bev=0.002)
    cyl("vase", 0.07, 0.3, (-3.22, 2.62, 0.725), M["ceramic_dark"], seg=32, r2=0.04, bev=0.01)
    plant("plant_side", (-3.24, 3.82, 0.575), 0.35, M, pot=0.09)
    box("side_books", (0.2, 0.14, 0.05), (-3.25, 2.95, 0.6), M["book"][0], bev=0.003, rot=(0, 0, 0.15))
    plant("plant_big", (3.05, 4.5, 0.0), 1.25, M, pot=0.2)
    # Robot vacuum (another brand).
    cyl("vacuum", 0.17, 0.08, (1.9, 1.6, 0.045), M["white_plastic"], bev=0.02)
    cyl("vacuum_top", 0.045, 0.015, (1.9, 1.66, 0.09), M["ac_slot"], bev=0.004)
    anchor("vacuum", (1.9, 1.6, 0.12))
    # Curtain rod and two pleated panels. Panel origin is at its outer edge; scale.x opens/closes.
    cyl("curtain_rod", 0.012, 3.0, (2.0, 4.86, 2.52), M["brass"], rot=(0, math.pi / 2, 0), bev=0.002)
    for side, ox, sign in [("l", 0.55, 1), ("r", 3.45, -1)]:
        bm = bmesh.new()
        nx, nz, w, hgt = 90, 2, 1.45, 2.46
        verts = []
        for j in range(nz + 1):
            row = []
            for i in range(nx + 1):
                u = i / nx
                row.append(bm.verts.new((sign * u * w, 0.035 * math.sin(u * w / 0.11 * 2 * math.pi), -j / nz * hgt)))
            verts.append(row)
        for j in range(nz):
            for i in range(nx):
                bm.faces.new([verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]])
        ob = mesh_object(f"curtain_{side}", bm, M["curtain"])
        ob.location = (ox, 4.84, 2.49)
        ob.modifiers.new("solid", "SOLIDIFY").thickness = 0.006
        ob.scale.x = 0.25
    anchor("curtain", (2.0, 4.8, 1.6))
    light("window_sky", "AREA", (2.0, 4.95, 1.45), 0, (0.85, 0.9, 1.0), None, size=2.3, size_y=1.8,
          rot=(math.radians(-90), 0, 0), shadow=True, specular=0.6)


# ---------------------------------------------------------------- kid's room

def kid_room(M):
    box_span("rug_kid", -6.3, -4.3, 1.6, 3.6, 0, 0.012, M["rug_kid"], bev=0.005)
    dx, dy, dz = DESK
    box("desk_top", (1.3, 0.62, 0.035), (dx, dy, dz - 0.0175), M["birch"], bev=0.008)
    for i, ox in enumerate([-0.6, 0.6]):
        box(f"desk_leg{i}", (0.04, 0.56, dz - 0.035), (dx + ox, dy, (dz - 0.035) / 2), M["white_plastic"], bev=0.004)
    box("desk_drawer", (0.42, 0.5, 0.12), (dx + 0.35, dy, dz - 0.1), M["white_plastic"], bev=0.006)
    # Pencil cup, a stack of books and a small globe.
    cyl("pcup", 0.035, 0.1, (dx + 0.48, dy + 0.18, dz + 0.05), M["toy"][1], seg=24, bev=0.004)
    for k, (cdx, cz) in enumerate([(-0.012, 0.13), (0.01, 0.14), (0.0, 0.135)]):
        cyl(f"pencil_c{k}", 0.004, cz, (dx + 0.48 + cdx, dy + 0.18 + 0.01 * k, dz + 0.07), M["toy"][2], seg=6, bev=0,
            rot=(0.12 * (k - 1), 0.1, 0))
    for k in range(3):
        box(f"kbook{k}", (0.2, 0.27, 0.025), (dx - 0.5, dy + 0.12, dz + 0.0125 + k * 0.026), M["book"][k + 3],
            bev=0.003, rot=(0, 0, 0.05 * k))
    cyl("globe_stand", 0.04, 0.012, (dx - 0.52, dy + 0.14, dz + 0.084), M["black_metal"], bev=0.003)
    sphere("globe", 0.08, (dx - 0.52, dy + 0.14, dz + 0.17), M["toy"][1])
    # Desk lamp with a clip-on camera on its arm.
    lx, ly = dx + 0.42, dy + 0.12
    cyl("dlamp_base", 0.07, 0.02, (lx, ly, dz + 0.01), M["black_metal"], bev=0.005)
    cyl("dlamp_arm1", 0.008, 0.42, (lx, ly - 0.05, dz + 0.21), M["black_metal"], seg=12, bev=0, rot=(0.25, 0, 0))
    cyl("dlamp_arm2", 0.008, 0.36, (lx - 0.06, ly - 0.2, dz + 0.42), M["black_metal"], seg=12, bev=0,
        rot=(1.2, 0, 0.35))
    head_m = glow_material("dlamp_head_m", WARM_SOFT, 6.0, "kid_desk")
    hx, hy, hz = lx - 0.12, ly - 0.36, dz + 0.4
    cyl("dlamp_head", 0.06, 0.1, (hx, hy, hz), head_m, r2=0.03, bev=0.004)
    light("dlamp_light", "SPOT", (hx, hy, hz - 0.05), 22, WARM_SOFT, "kid_desk", size=0.05, spot=(1.9, 0.7))
    light("dlamp_bounce", "POINT", (dx, dy - 0.25, dz + 0.25), 6, WARM_SOFT, "kid_desk", size=0.2, specular=0.0)
    anchor("desklamp", (hx, hy, hz + 0.05))
    REG["desk_cam_pos"] = Vector((lx - 0.035, ly - 0.12, dz + 0.36))
    # Kid's chair.
    cx, cy = dx - 0.05, dy - 0.68
    box("chair_seat", (0.4, 0.38, 0.05), (cx, cy, 0.4), M["chair_fabric"], bev=0.02)
    box("chair_back", (0.4, 0.05, 0.34), (cx, cy - 0.2, 0.62), M["chair_fabric"], bev=0.02, rot=(0.1, 0, 0))
    for i, (ox, oy) in enumerate([(-0.17, -0.16), (0.17, -0.16), (-0.17, 0.16), (0.17, 0.16)]):
        cyl(f"chair_leg{i}", 0.014, 0.38, (cx + ox, cy + oy, 0.19), M["birch"], seg=12, bev=0)
    box("backpack", (0.3, 0.16, 0.36), (cx + 0.32, cy - 0.15, 0.18), M["toy"][0], bev=0.06, seg=4, rot=(0, 0, 0.4))
    # Bed along the left wall, near the open side.
    bx0, bx1, by0, by1 = -6.98, -6.0, 0.3, 2.3
    box_span("kbed_frame", bx0, bx1, by0, by1, 0.0, 0.3, M["birch"], bev=0.015)
    box_span("kbed_mattress", bx0 + 0.03, bx1 - 0.03, by0 + 0.03, by1 - 0.03, 0.3, 0.46, M["duvet"], bev=0.04)
    box_span("kbed_cover", bx0 + 0.01, bx1 - 0.01, by0 + 0.02, by1 - 0.5, 0.42, 0.52, M["kid_cover"], bev=0.04)
    box("kbed_pillow", (0.55, 0.3, 0.12), ((bx0 + bx1) / 2, by1 - 0.25, 0.53), M["duvet"], bev=0.05, seg=5)
    box_span("kbed_head", bx0, bx1, by1 - 0.06, by1, 0.0, 0.9, M["birch"], bev=0.02)
    # A plush bear on the bed.
    px, py = (bx0 + bx1) / 2 + 0.15, by1 - 0.6
    sphere("bear_body", 0.1, (px, py, 0.6), M["plush"], scale=(1, 0.85, 1.1))
    sphere("bear_head", 0.075, (px, py, 0.75), M["plush"])
    for k, ox in enumerate([-0.05, 0.05]):
        sphere(f"bear_ear{k}", 0.025, (px + ox, py, 0.82), M["plush"])
    # Low bookshelf on the left wall.
    bxs = -6.8
    box("kshelf", (0.32, 1.2, 1.1), (bxs, 3.85, 0.55), M["birch"], bev=0.006)
    rnd = random.Random(5)
    for k in range(3):
        z = 0.06 + k * 0.36
        y = 3.3
        while y < 4.38:
            w = rnd.uniform(0.025, 0.05)
            hgt = rnd.uniform(0.18, 0.28)
            if rnd.random() < 0.15:
                y += 0.08
                continue
            box(f"kbook_s{k}_{y:.2f}", (0.22, w, hgt), (bxs + 0.05, y + w / 2, z + hgt / 2 + 0.012),
                rnd.choice(M["book"]), bev=0.003)
            y += w + 0.004
    sphere("ball", 0.11, (-4.6, 1.3, 0.11), M["toy"][0])
    box("blocks0", (0.08, 0.08, 0.08), (-5.6, 2.1, 0.052), M["toy"][2], bev=0.008)
    box("blocks1", (0.08, 0.08, 0.08), (-5.5, 2.15, 0.052), M["toy"][3], bev=0.008, rot=(0, 0, 0.4))
    box("blocks2", (0.08, 0.08, 0.08), (-5.55, 2.12, 0.132), M["toy"][1], bev=0.008, rot=(0, 0, 0.2))
    box("kposter_frame", (0.5, 0.025, 0.64), (-6.2, 4.975, 1.5), M["white_plastic"], bev=0.004)
    plane("kposter", 0.44, 0.58, (-6.2, 4.96, 1.5), M["art_kid"], rot=(math.pi / 2, 0, 0))
    # Ceiling lamp.
    ps_m = glow_material("kid_shade_m", WARM_SOFT, 4.0, "kid_main")
    cyl("kid_ceiling_lamp", 0.26, 0.05, (-5.25, 2.6, 2.62), ps_m, bev=0.01)
    light("kid_light", "AREA", (-5.25, 2.6, 2.55), 170, WARM_SOFT, "kid_main", size=0.6)
    light("kid_fill", "AREA", (-5.25, 2.5, 2.6), 90, WARM_SOFT, "kid_fill", size=3.3, size_y=4.5,
          shadow=False, specular=0.0)
    anchor("kid_light", (-5.25, 2.6, 2.6))


# ---------------------------------------------------------------- kitchen and laundry

def kitchen(M):
    y0, y1 = 4.4, 5.0
    # Base cabinets with a stone counter along the back wall.
    box_span("kbase", 3.62, 7.08, y0 + 0.02, y1, 0.08, 0.86, M["cabinet"], bev=0.006)
    box_span("kbase_toe", 3.62, 7.08, y0 + 0.08, y1, 0.0, 0.08, M["ac_slot"], bev=0)
    for k in range(6):
        x = 3.62 + k * 0.577
        box_span(f"kbase_seam{k}", x - 0.002, x + 0.002, y0 + 0.015, y0 + 0.02, 0.1, 0.84, M["ac_slot"], bev=0)
        box_span(f"kbase_pull{k}", x + 0.2, x + 0.38, y0 - 0.005, y0 + 0.015, 0.78, 0.795, M["steel"], bev=0.002)
    box_span("kcounter", 3.6, 7.1, y0 - 0.02, y1, 0.86, 0.905, M["counter"], bev=0.006)
    box_span("kbacksplash", 3.6, 7.1, y1 - 0.012, y1, 0.905, 1.55, M["backsplash"], bev=0)
    # Gas cooktop: black glass, two burners. The left one holds the pot (S17).
    box_span("cooktop", 4.12, 5.02, 4.5, 4.88, 0.905, 0.915, M["screen_off"], bev=0.004)
    for k, bx in enumerate([STOVE.x, STOVE.x + 0.46]):
        cyl(f"burner{k}_ring", 0.075, 0.012, (bx, STOVE.y, 0.921), M["black_metal"], bev=0.003)
        cyl(f"burner{k}_cap", 0.04, 0.012, (bx, STOVE.y, 0.93), M["black_metal"], bev=0.003)
        for j in range(4):
            a = j * math.pi / 2 + math.pi / 4
            box(f"burner{k}_grate{j}", (0.11, 0.012, 0.01),
                (bx + 0.075 * math.cos(a), STOVE.y + 0.075 * math.sin(a), 0.94), M["black_metal"], bev=0.002,
                rot=(0, 0, a))
        cyl(f"knob{k}", 0.018, 0.015, (bx, 4.505, 0.9), M["steel"], bev=0.004, rot=(math.pi / 2, 0, 0))
    # Pot with lid.
    px, py = STOVE.x, STOVE.y
    cyl("pot", 0.11, 0.13, (px, py, 0.955 + 0.065), M["steel"], seg=48, bev=0.006)
    cyl("pot_lid", 0.112, 0.012, (px, py, 1.09), M["steel"], seg=48, bev=0.005, r2=0.09)
    sphere("pot_knob", 0.016, (px, py, 1.105), M["black_metal"])
    for k, s in enumerate([-1, 1]):
        box(f"pot_handle{k}", (0.05, 0.022, 0.012), (px + s * 0.135, py, 1.06), M["black_metal"], bev=0.004)
    anchor("stove", (px, py, 1.02))
    # Range hood.
    box_span("hood", 4.12, 5.02, 4.55, 5.0, 1.72, 1.86, M["steel"], bev=0.01)
    box_span("hood_chimney", 4.37, 4.77, 4.7, 5.0, 1.86, H, M["steel"], bev=0.006)
    hood_m = glow_material("hood_lamp_m", (1.0, 0.85, 0.7), 2.0, "kit_under")
    box_span("hood_lamp", 4.3, 4.84, 4.65, 4.72, 1.715, 1.72, hood_m, bev=0)
    # Upper cabinets left of the hood and between hood and window.
    for name, a, b in [("kup0", 3.62, 4.08), ("kup1", 5.06, 5.9)]:
        box_span(name, a, b, 4.66, y1, 1.62, 2.4, M["cabinet"], bev=0.006)
    # Under-cabinet strip lights.
    strip_m = glow_material("kit_strip_m", (1.0, 0.82, 0.62), 3.0, "kit_under")
    for name, a, b in [("kstrip0", 3.66, 4.04), ("kstrip1", 5.1, 5.86)]:
        box_span(name, a, b, 4.7, 4.74, 1.605, 1.615, strip_m, bev=0)
        light(f"{name}_l", "AREA", ((a + b) / 2, 4.75, 1.6), 25, (1.0, 0.82, 0.62), "kit_under", size=b - a,
              size_y=0.08, rot=(0, 0, 0), specular=0.3)
    # Sink under the window.
    box_span("sink", 6.15, 6.85, 4.55, 4.88, 0.86, 0.906, M["steel"], bev=0.004)
    box_span("sink_hole", 6.2, 6.8, 4.6, 4.83, 0.88, 0.907, M["black_metal"], bev=0)
    cyl("faucet", 0.012, 0.3, (6.5, 4.93, 1.06), M["steel"], seg=16, bev=0)
    cyl("faucet_spout", 0.01, 0.16, (6.5, 4.86, 1.2), M["steel"], seg=16, bev=0, rot=(math.pi / 2, 0, 0))
    plant("plant_kit", (6.95, 4.75, 0.905), 0.22, M, pot=0.06)
    cyl("kettle", 0.075, 0.18, (5.5, 4.72, 0.995), M["white_plastic"], seg=32, r2=0.06, bev=0.01)
    box("cutting_board", (0.36, 0.24, 0.02), (5.85, 4.65, 0.915), M["oak"], bev=0.004, rot=(0, 0, 0.08))
    # Fridge (another brand) at the right end.
    fx0, fx1 = 7.15, 7.95
    box_span("fridge", fx0, fx1, 4.25, 5.0, 0.0, 1.86, M["steel"], bev=0.02)
    box_span("fridge_seam", (fx0 + fx1) / 2 - 0.003, (fx0 + fx1) / 2 + 0.003, 4.245, 4.25, 0.05, 1.82,
             M["ac_slot"], bev=0)
    for k, s in enumerate([-1, 1]):
        box_span(f"fridge_handle{k}", (fx0 + fx1) / 2 + s * 0.04 - 0.01, (fx0 + fx1) / 2 + s * 0.04 + 0.01,
                 4.21, 4.245, 0.9, 1.5, M["black_metal"], bev=0.004)
    box_span("fridge_panel", fx0 + 0.08, fx0 + 0.24, 4.244, 4.25, 1.3, 1.42, M["screen_off"], bev=0.002)
    anchor("fridge", ((fx0 + fx1) / 2, 4.25, 1.4))
    # Small dining table with two chairs and a pendant.
    tx, ty = 5.55, 2.4
    cyl("dtable_top", 0.45, 0.035, (tx, ty, 0.74), M["birch"], bev=0.01)
    cyl("dtable_stem", 0.04, 0.7, (tx, ty, 0.37), M["black_metal"], seg=24, bev=0)
    cyl("dtable_foot", 0.22, 0.02, (tx, ty, 0.01), M["black_metal"], bev=0.004)
    for k, (ox, oy, rz) in enumerate([(-0.62, -0.1, 0.0), (0.6, 0.15, math.pi)]):
        cx, cy = tx + ox, ty + oy
        box(f"dchair{k}_seat", (0.42, 0.42, 0.04), (cx, cy, 0.46), M["chair_fabric"], bev=0.015)
        box(f"dchair{k}_back", (0.04, 0.4, 0.38), (cx - 0.2 * math.cos(rz), cy, 0.68), M["oak"], bev=0.01)
        for j, (lx, ly) in enumerate([(-0.17, -0.17), (0.17, -0.17), (-0.17, 0.17), (0.17, 0.17)]):
            cyl(f"dchair{k}_leg{j}", 0.013, 0.44, (cx + lx, cy + ly, 0.22), M["oak"], seg=12, bev=0)
    cyl("fruit_bowl", 0.13, 0.05, (tx + 0.05, ty - 0.05, 0.783), M["ceramic"], seg=32, r2=0.08, bev=0.008)
    for k, (ox, oy, mi) in enumerate([(0.02, 0.0, 0), (0.08, -0.06, 2), (-0.02, -0.08, 0)]):
        sphere(f"fruit{k}", 0.04, (tx + 0.05 + ox, ty - 0.05 + oy, 0.83), M["toy"][mi])
    cyl("kpend_cord", 0.004, 0.9, (tx, ty, H - 0.45), M["black_metal"], seg=8, bev=0)
    kp_m = glow_material("kpend_shade", WARM, 3.5, "kit_main")
    cyl("kpend_shade", 0.18, 0.2, (tx, ty, 1.72), kp_m, r2=0.06, bev=0.004)
    light("kpend_light", "SPOT", (tx, ty, 1.66), 160, WARM, "kit_main", size=0.08, spot=(2.0, 0.7))
    light("kit_fill", "AREA", (5.75, 2.5, 2.6), 110, WARM_SOFT, "kit_fill", size=4.3, size_y=4.5,
          shadow=False, specular=0.0)
    anchor("kit_light", (tx, ty, 1.75))
    # Window sky light for day/dusk shots.
    light("kit_window_sky", "AREA", (6.5, 4.95, 1.65), 0, (0.85, 0.9, 1.0), None, size=1.1, size_y=1.0,
          rot=(math.radians(-90), 0, 0), shadow=True, specular=0.5)
    # Backlight for the steam over the pot (forward scattering towards the camera).
    sl = light("steam_light", "SPOT", (STOVE.x + 0.1, 4.97, 1.75), 0, (0.7, 0.8, 1.0), None, size=0.05,
               spot=(math.radians(40), 0.6), shadow=False, specular=0.2)
    sl.rotation_euler = (Vector((STOVE.x, 4.3, 1.15)) - sl.location).to_track_quat("-Z", "Y").to_euler()


def laundry(M):
    """Front-loading washer against the right wall, facing into the room (-X)."""
    x0, x1 = 7.33, 7.97
    y0, y1 = WASHER.y - 0.31, WASHER.y + 0.31
    body_m = principled("washer_body", (0.2, 0.21, 0.23), rough=0.35, metal=0.5, coat=0.5)
    body = box_span("washer", x0, x1, y0, y1, 0.0, 0.86, body_m, bev=0.025)
    drum_m = principled("washer_drum", (0.55, 0.57, 0.6), rough=0.28, metal=1.0)
    cutter = cyl("washer_cutter", 0.19, 0.9, (x0, WASHER.y, 0.42), drum_m, seg=64, bev=0, rot=(0, math.pi / 2, 0))
    cutter.hide_render = True
    cutter.hide_viewport = True
    bo = body.modifiers.new("drum", "BOOLEAN")
    bo.operation = "DIFFERENCE"
    bo.object = cutter
    bo.solver = "EXACT"
    bo.material_mode = "TRANSFER"
    body.modifiers.move(len(body.modifiers) - 1, 0)
    box_span("washer_top", x0 + 0.01, x1, y0 + 0.01, y1 - 0.01, 0.855, 0.865, M["counter"], bev=0.004)
    # Control strip: dial, display (digits written per frame by the plates).
    box_span("washer_strip", x0 - 0.004, x0, y0 + 0.03, y1 - 0.03, 0.72, 0.83, M["ac_body"], bev=0.004)
    cyl("washer_dial", 0.035, 0.02, (x0 - 0.01, y0 + 0.12, 0.775), M["steel"], bev=0.004, rot=(0, math.pi / 2, 0))
    box_span("washer_screen", x0 - 0.006, x0 - 0.004, WASHER.y - 0.05, WASHER.y + 0.13, 0.75, 0.80,
             M["screen_off"], bev=0)
    dm = emission("washer_digits_m", (0.55, 0.85, 1.0), 2.5)
    REG["washer_digits"] = text("washer_digits", "0:42", 0.036, (x0 - 0.0075, WASHER.y + 0.04, 0.775), dm,
                                rot=(math.pi / 2, 0, -math.pi / 2))
    REG["washer_digits_strength"] = dm.node_tree.nodes["Emission"].inputs["Strength"]
    done_m = emission("washer_done_m", (0.3, 1.0, 0.55), 0.0)
    cyl("washer_done", 0.006, 0.003, (x0 - 0.006, y1 - 0.09, 0.775), done_m, seg=16, bev=0,
        rot=(0, math.pi / 2, 0))
    REG["washer_done"] = done_m.node_tree.nodes["Emission"].inputs["Strength"]
    # Door: chrome ring, dark glass, lit drum with clothes that tumble.
    dz = 0.42
    ring = torus("washer_door_ring", 0.192, 0.024, (x0 - 0.025, WASHER.y, dz), M["steel"])
    ring.rotation_euler = (0, math.pi / 2, 0)
    glass_m = principled("washer_glass", (0.5, 0.55, 0.6), rough=0.04, alpha=0.12, spec=1.0, coat=1.0)
    g = cyl("washer_door_glass", 0.17, 0.02, (x0 - 0.03, WASHER.y, dz), glass_m, seg=64, bev=0.008,
            rot=(0, math.pi / 2, 0))
    g.visible_shadow = False
    cyl("washer_drum", 0.19, 0.012, (x0 + 0.44, WASHER.y, dz), drum_m, seg=48, bev=0, rot=(0, math.pi / 2, 0))
    lamp_m = glow_material("washer_lamp_m", (0.75, 0.88, 1.0), 2.5, "washer_run")
    cyl("washer_drum_lamp", 0.17, 0.004, (x0 + 0.41, WASHER.y, dz), lamp_m, seg=48, bev=0, rot=(0, math.pi / 2, 0))
    light("washer_drum_light", "POINT", (x0 + 0.12, WASHER.y, dz), 4.0, (0.75, 0.88, 1.0), "washer_run", size=0.05)
    # Clothes: soft lumps parented to an empty that spins about the drum axis.
    spin = bpy.data.objects.new("washer_spin", None)
    spin.location = (x0 + 0.25, WASHER.y, dz)
    spin.rotation_mode = "XYZ"
    bpy.context.scene.collection.objects.link(spin)
    rnd = random.Random(4)
    cloth = [fabric(f"cloth{i}", c, scale=300) for i, c in
             enumerate([(0.15, 0.3, 0.6), (0.8, 0.8, 0.78), (0.7, 0.25, 0.2), (0.25, 0.5, 0.35)])]
    for i in range(9):
        a = i * 2 * math.pi / 9 + rnd.uniform(-0.2, 0.2)
        r = rnd.uniform(0.06, 0.13)
        lump = sphere(f"cloth_lump{i}", rnd.uniform(0.045, 0.07),
                      (rnd.uniform(-0.08, 0.1), r * math.cos(a), r * math.sin(a)), cloth[i % 4],
                      scale=(1.6, rnd.uniform(0.8, 1.2), rnd.uniform(0.35, 0.55)), seg=16)
        lump.rotation_euler = (rnd.uniform(0, 3.14), rnd.uniform(0, 3.14), rnd.uniform(0, 3.14))
        lump.parent = spin
    REG["washer_spin"] = spin
    anchor("washer", (x0 - 0.02, WASHER.y, 0.86))
    anchor("washer_door", (x0 - 0.03, WASHER.y, dz))
    # Shelf with detergent above, a laundry basket beside it.
    box_span("lshelf", 7.6, 7.98, y0 - 0.05, y1 + 0.05, 1.35, 1.38, M["birch"], bev=0.004)
    for k, (oy, col) in enumerate([(-0.18, 1), (-0.05, 3), (0.12, 2)]):
        box(f"bottle{k}", (0.09, 0.07, 0.2 - 0.03 * k), (7.8, WASHER.y + oy, 1.48 - 0.015 * k), M["toy"][col],
            bev=0.015)
    cyl("lbasket", 0.2, 0.3, (7.65, WASHER.y - 0.62, 0.15), M["rug_kid"], seg=32, r2=0.23, bev=0.01)
    sphere("lbasket_cloth", 0.15, (7.65, WASHER.y - 0.62, 0.3), cloth[1], scale=(1, 1, 0.45))
    # Wall clock on the right wall: its hands spin in the time-lapse.
    ck = Vector((7.985, 1.72, 1.1))
    cyl("clock_rim", 0.15, 0.035, ck, M["black_metal"], seg=64, bev=0.006, rot=(0, math.pi / 2, 0))
    cyl("clock_face", 0.135, 0.004, ck + Vector((-0.018, 0, 0)), M["duvet"], seg=64, bev=0, rot=(0, math.pi / 2, 0))
    for k in range(12):
        a = k * math.pi / 6
        L = 0.03 if k % 3 == 0 else 0.016
        box(f"clock_tick{k}", (0.003, 0.006, L),
            ck + Vector((-0.022, 0.11 * math.sin(a), 0.11 * math.cos(a))), M["black_metal"], bev=0,
            rot=(-a, 0, 0))
    for name, L, w in (("clock_h", 0.07, 0.009), ("clock_m", 0.11, 0.006)):
        e = bpy.data.objects.new(name, None)
        e.location = ck + Vector((-0.026, 0, 0))
        bpy.context.scene.collection.objects.link(e)
        hand = box(f"{name}_hand", (0.003, w, L), (0, 0, L / 2 - 0.012), M["black_metal"], bev=0)
        hand.parent = e
        REG[name] = e
    sphere("clock_pin", 0.008, ck + Vector((-0.03, 0, 0)), M["brass"])
    anchor("clock", ck)
