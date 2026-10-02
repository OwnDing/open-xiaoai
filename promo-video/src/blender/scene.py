"""Procedural set for the promo: a three-room cutaway apartment and a product studio.

Everything is built from primitives so the film can be rebuilt from source.
Units are metres, Z up. The apartment's open side faces -Y.
Rooms along X: study [-7, -3.5], living room [-3.5, 3.5], bedroom [3.5, 8].
"""
import math
import random

import bmesh
import bpy
from mathutils import Vector

H = 2.7            # wall height
T = 0.12           # wall thickness
STUDIO = Vector((100.0, 0.0, 0.0))
SPEAKER_LIVING = Vector((-0.96, 2.98, 0.42))
FONT_DIGITS = "/System/Library/Fonts/Avenir Next.ttc"

# Runtime registry the plate scripts animate through.
REG = {"groups": {}, "rings": {}, "anchors": {}, "objs": {}, "mats": {}, "colls": {}}


# ---------------------------------------------------------------- utilities

def coll(name):
    if name not in REG["colls"]:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
        REG["colls"][name] = c
    return REG["colls"][name]


def link(ob, collection="apartment"):
    coll(collection).objects.link(ob)
    return ob


def principled(name, color, rough=0.5, metal=0.0, sheen=0.0, coat=0.0, spec=0.5,
               emit=None, strength=0.0, alpha=1.0):
    m = bpy.data.materials.new(name)
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Specular IOR Level"].default_value = spec
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    REG["mats"][name] = m
    return m


def emission(name, color, strength):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    REG["mats"][name] = m
    return m


def node(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def mesh_object(name, bm, mat=None, collection="apartment", smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    if mat:
        me.materials.append(mat)
    REG["objs"][name] = ob
    return link(ob, collection)


def bevel(ob, width, segments=3, harden=True):
    if width <= 0:
        return ob
    m = ob.modifiers.new("bevel", "BEVEL")
    m.width = width
    m.segments = segments
    m.limit_method = "ANGLE"
    m.harden_normals = harden
    return ob


def box(name, size, loc, mat, bev=0.008, seg=3, rot=(0, 0, 0), collection="apartment"):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    ob = mesh_object(name, bm, mat, collection)
    ob.location = loc
    ob.rotation_euler = rot
    return bevel(ob, min(bev, min(size) * 0.49), seg)


def box_span(name, x0, x1, y0, y1, z0, z1, mat, bev=0.004, collection="apartment"):
    return box(name, (x1 - x0, y1 - y0, z1 - z0), ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
               mat, bev, 2, collection=collection)


def cyl(name, r, h, loc, mat, seg=64, bev=0.004, r2=None, collection="apartment", rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r, radius2=r if r2 is None else r2, depth=h)
    ob = mesh_object(name, bm, mat, collection)
    ob.location = loc
    ob.rotation_euler = rot
    return bevel(ob, bev, 3)


def sphere(name, r, loc, mat, scale=(1, 1, 1), seg=32, collection="apartment"):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=seg // 2, radius=r)
    ob = mesh_object(name, bm, mat, collection)
    ob.location = loc
    ob.scale = scale
    return ob


def torus(name, R, r, loc, mat, collection="apartment", zscale=1.0):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=128,
                                     minor_segments=16, location=loc)
    ob = bpy.context.active_object
    for c in ob.users_collection:
        c.objects.unlink(ob)
    link(ob, collection)
    ob.name = name
    ob.scale.z = zscale
    ob.data.materials.append(mat)
    for p in ob.data.polygons:
        p.use_smooth = True
    REG["objs"][name] = ob
    return ob


def plane(name, sx, sy, loc, mat, rot=(0, 0, 0), collection="apartment"):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    bmesh.ops.scale(bm, vec=Vector((sx, sy, 1)), verts=bm.verts)
    ob = mesh_object(name, bm, mat, collection, smooth=False)
    ob.location = loc
    ob.rotation_euler = rot
    return ob


def text(name, body, size, loc, mat, rot=(math.pi / 2, 0, 0), collection="apartment"):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    if "font" not in REG:
        REG["font"] = bpy.data.fonts.load(FONT_DIGITS)
    cu.font = REG["font"]
    cu.size = size
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    ob = bpy.data.objects.new(name, cu)
    ob.location = loc
    ob.rotation_euler = rot
    cu.materials.append(mat)
    REG["objs"][name] = ob
    return link(ob, collection)


def light(name, kind, loc, energy, color, group=None, size=0.1, size_y=None, rot=(0, 0, 0),
          shadow=True, collection="apartment", spot=None, specular=1.0):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    ld.use_shadow = shadow
    ld.specular_factor = specular
    if kind == "AREA":
        ld.shape = "RECTANGLE" if size_y else "DISK"
        ld.size = size
        if size_y:
            ld.size_y = size_y
    elif kind in ("POINT", "SPOT"):
        ld.shadow_soft_size = size
    elif kind == "SUN":
        ld.angle = size
    if spot:
        ld.spot_size, ld.spot_blend = spot
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    ob.rotation_euler = rot
    link(ob, collection)
    if group:
        REG["groups"].setdefault(group, {"lights": [], "emit": []})["lights"].append((ld, energy))
    REG["objs"][name] = ob
    return ob


def group_emit(group, socket, base):
    REG["groups"].setdefault(group, {"lights": [], "emit": []})["emit"].append((socket, base))


def set_group(group, level):
    g = REG["groups"].get(group)
    if not g:
        return
    for ld, e0 in g["lights"]:
        ld.energy = e0 * level
    for sock, s0 in g["emit"]:
        sock.default_value = s0 * level


def anchor(name, loc):
    REG["anchors"][name] = Vector(loc)


def glow_material(name, color, strength, group):
    """A lamp shade / bulb that glows with its light group."""
    m = principled(name, (0.9, 0.85, 0.78), rough=0.8, emit=color, strength=strength)
    REG.setdefault("glow_mats", set()).add(m.name)
    group_emit(group, m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"], strength)
    return m


WARM = (1.0, 0.62, 0.32)
WARM_SOFT = (1.0, 0.72, 0.45)


# ---------------------------------------------------------------- materials

def make_materials():
    M = {}
    M["wall"] = principled("wall", (0.78, 0.74, 0.69), rough=0.92, spec=0.3)
    M["wall_bed"] = principled("wall_bed", (0.62, 0.66, 0.70), rough=0.92, spec=0.3)
    M["wall_study"] = principled("wall_study", (0.70, 0.66, 0.58), rough=0.92, spec=0.3)
    M["slab"] = principled("slab", (0.05, 0.05, 0.06), rough=0.6)
    M["slab_top"] = principled("slab_top", (0.85, 0.83, 0.8), rough=0.7)

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

    M["rug"] = fabric("rug", (0.62, 0.57, 0.5), scale=260, bump=0.25)
    M["rug_bed"] = fabric("rug_bed", (0.36, 0.4, 0.44), scale=260, bump=0.25)
    M["sofa"] = fabric("sofa", (0.10, 0.19, 0.22), scale=180)
    M["pillow_a"] = fabric("pillow_a", (0.72, 0.46, 0.16), scale=180)
    M["pillow_b"] = fabric("pillow_b", (0.62, 0.3, 0.22), scale=180)
    M["duvet"] = fabric("duvet", (0.86, 0.84, 0.8), scale=150)
    M["bedcover"] = fabric("bedcover", (0.52, 0.56, 0.5), scale=150)
    M["headboard"] = fabric("headboard", (0.28, 0.33, 0.38), scale=180)
    M["curtain"] = fabric("curtain", (0.74, 0.66, 0.55), scale=120, bump=0.1)
    M["oak"] = principled("oak", (0.55, 0.38, 0.22), rough=0.35, coat=0.2)
    M["walnut"] = principled("walnut", (0.2, 0.11, 0.06), rough=0.35, coat=0.3)
    M["black_metal"] = principled("black_metal", (0.03, 0.03, 0.03), rough=0.35, metal=1.0)
    M["brass"] = principled("brass", (0.8, 0.58, 0.3), rough=0.25, metal=1.0)
    M["white_plastic"] = principled("white_plastic", (0.85, 0.85, 0.83), rough=0.3, coat=0.3)
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
    M["laptop"] = principled("laptop", (0.6, 0.6, 0.62), rough=0.3, metal=1.0)
    M["art_a"] = art("art_a", [(0.0, (0.95, 0.55, 0.25)), (0.5, (0.85, 0.3, 0.3)), (1.0, (0.2, 0.18, 0.35))])
    M["art_b"] = art("art_b", [(0.0, (0.9, 0.85, 0.72)), (0.6, (0.35, 0.55, 0.6)), (1.0, (0.1, 0.2, 0.28))])
    return M


def fabric(name, color, scale=200.0, bump=0.18):
    m = principled(name, color, rough=0.95, sheen=0.6, spec=0.2)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Sheen Tint"].default_value = (1, 1, 1, 1)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    wx = node(nt, "ShaderNodeTexWave", Scale=scale, Distortion=1.5, Detail=2.0)
    wy = node(nt, "ShaderNodeTexWave", Scale=scale, Distortion=1.5, Detail=2.0)
    wy.bands_direction = "Y"
    nt.links.new(tc.outputs["Object"], wx.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], wy.inputs["Vector"])
    mul = node(nt, "ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(wx.outputs["Fac"], mul.inputs[0])
    nt.links.new(wy.outputs["Fac"], mul.inputs[1])
    bp = node(nt, "ShaderNodeBump", Strength=bump, Distance=0.002)
    nt.links.new(mul.outputs[0], bp.inputs["Height"])
    nt.links.new(bp.outputs[0], b.inputs["Normal"])
    return m


def art(name, stops):
    m = principled(name, (1, 1, 1), rough=0.7)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    g = nt.nodes.new("ShaderNodeTexGradient")
    g.gradient_type = "SPHERICAL"
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Location"].default_value = (0.15, 0.1, 0)
    mp.inputs["Scale"].default_value = (2.2, 2.2, 2.2)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], g.inputs["Vector"])
    r = nt.nodes.new("ShaderNodeValToRGB")
    els = r.color_ramp.elements
    # Spherical gradient is 1 at the centre, so the first stop maps to 1.0.
    els[0].position, els[0].color = 0.0, (*stops[-1][1], 1)
    els[1].position, els[1].color = 1.0, (*stops[0][1], 1)
    for pos, c in stops[1:-1]:
        els.new(1.0 - pos).color = (*c, 1)
    nt.links.new(g.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    return m


# ---------------------------------------------------------------- the speaker

def speaker(prefix, base, collection):
    """Cylindrical fabric smart speaker with a glass top and a light ring.

    The ring material exposes three controls stored in REG["rings"][prefix]:
    warm (0 = cold white of stock XiaoAI, 1 = amber/violet of the AI),
    level (emission strength) and spin (rotation of the colour gradient).
    """
    R, Hs = 0.068, 0.19
    body_m = fabric(f"{prefix}_fabric", (0.34, 0.33, 0.32), scale=900, bump=0.35)
    top_m = principled(f"{prefix}_top", (0.012, 0.012, 0.014), rough=0.12, coat=1.0, spec=0.8)
    base_m = principled(f"{prefix}_base", (0.02, 0.02, 0.02), rough=0.5)
    cyl(f"{prefix}_body", R, Hs - 0.02, base + Vector((0, 0, 0.01 + (Hs - 0.02) / 2)), body_m,
        bev=0.006, collection=collection)
    cyl(f"{prefix}_foot", R - 0.004, 0.012, base + Vector((0, 0, 0.006)), base_m, bev=0.003,
        collection=collection)
    cyl(f"{prefix}_cap", R - 0.0015, 0.012, base + Vector((0, 0, Hs - 0.006)), top_m, bev=0.004,
        collection=collection)

    # Ring: flowing gradient for the AI, flat cold white for stock XiaoAI.
    m = bpy.data.materials.new(f"{prefix}_ring")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    g = nt.nodes.new("ShaderNodeTexGradient")
    g.gradient_type = "RADIAL"
    nt.links.new(mp.outputs[0], g.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "B_SPLINE"
    stops = [(0.0, (1.0, 0.45, 0.08)), (0.3, (1.0, 0.18, 0.42)), (0.6, (0.45, 0.25, 1.0)),
             (0.82, (1.0, 0.3, 0.3)), (1.0, (1.0, 0.45, 0.08))]
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1)
    els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1)
    for pos, c in stops[1:-1]:
        els.new(pos).color = (*c, 1)
    nt.links.new(g.outputs["Fac"], ramp.inputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.62, 0.8, 1.0, 1)
    nt.links.new(ramp.outputs["Color"], mix.inputs[7])
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(mix.outputs[2], em.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    ring = torus(f"{prefix}_ring", 0.05, 0.0019, base + Vector((0, 0, Hs)), m, collection, zscale=0.45)
    ring.visible_shadow = False
    # A faint glow disc under the glass, so the ring reads as light, not a wire.
    halo_m = bpy.data.materials.new(f"{prefix}_halo")
    hn = halo_m.node_tree
    hn.nodes.clear()
    htc = hn.nodes.new("ShaderNodeTexCoord")
    hg = hn.nodes.new("ShaderNodeTexGradient")
    hg.gradient_type = "SPHERICAL"
    hmp = node(hn, "ShaderNodeMapping")
    hmp.inputs["Scale"].default_value = (1 / 0.062, 1 / 0.062, 1)
    hn.links.new(htc.outputs["Object"], hmp.inputs["Vector"])
    hn.links.new(hmp.outputs[0], hg.inputs["Vector"])
    hr = hn.nodes.new("ShaderNodeValToRGB")
    he = hr.color_ramp.elements
    he[0].position, he[0].color = 0.0, (0, 0, 0, 1)
    he[1].position, he[1].color = 0.5, (0, 0, 0, 1)
    he.new(0.19).color = (1, 1, 1, 1)
    hn.links.new(hg.outputs["Fac"], hr.inputs["Fac"])
    hm2 = hn.nodes.new("ShaderNodeMix")
    hm2.data_type = "RGBA"
    hm2.blend_type = "MULTIPLY"
    hm2.inputs["Factor"].default_value = 1.0
    hn.links.new(hr.outputs["Color"], hm2.inputs[6])
    hcol = hn.nodes.new("ShaderNodeRGB")
    hn.links.new(hcol.outputs[0], hm2.inputs[7])
    hem = hn.nodes.new("ShaderNodeEmission")
    hn.links.new(hm2.outputs[2], hem.inputs["Color"])
    hout = hn.nodes.new("ShaderNodeOutputMaterial")
    hn.links.new(hem.outputs[0], hout.inputs[0])
    halo = cyl(f"{prefix}_halo", 0.062, 0.0005, base + Vector((0, 0, Hs + 0.0003)), halo_m, bev=0,
               collection=collection)
    halo.visible_shadow = False
    # Touch keys on the glass: + and - and a mic dot.
    key_m = principled(f"{prefix}_keys", (0.35, 0.35, 0.36), rough=0.4)
    top = base + Vector((0, 0, Hs + 0.0004))
    for i, ang in enumerate([0, math.pi]):
        c = top + Vector((0.028 * math.cos(ang), 0.028 * math.sin(ang), 0))
        box(f"{prefix}_key{i}h", (0.009, 0.0016, 0.0006), c, key_m, bev=0, collection=collection)
        if i == 0:
            box(f"{prefix}_key{i}v", (0.0016, 0.009, 0.0006), c, key_m, bev=0, collection=collection)
    cyl(f"{prefix}_mic", 0.0022, 0.0006, top + Vector((0, 0.028, 0)), key_m, seg=16, bev=0,
        collection=collection)
    REG["rings"][prefix] = {
        "mix": mix.inputs["Factor"], "strength": em.inputs["Strength"],
        "spin": mp.inputs["Rotation"], "halo": hem.inputs["Strength"], "halo_color": hcol.outputs[0],
        "cold": (0.62, 0.8, 1.0),
    }
    anchor(prefix, base + Vector((0, 0, Hs)))
    return base + Vector((0, 0, Hs))


def set_ring(prefix, warm, level, spin):
    r = REG["rings"][prefix]
    r["mix"].default_value = warm
    r["strength"].default_value = level
    r["spin"].default_value[2] = spin
    cold = r["cold"]
    hot = (1.0, 0.42, 0.32)
    col = [c * (1 - warm) + h * warm for c, h in zip(cold, hot)]
    r["halo_color"].default_value = (*col, 1)
    r["halo"].default_value = level * 0.25


# ---------------------------------------------------------------- apartment

def walls(M):
    # Back wall with the living-room window opening x [0.8, 3.2], z [0.5, 2.4].
    y0, y1 = 5.0, 5.0 + T
    box_span("wall_back_a", -7.0 - T, -3.5, y0, y1, 0, H, M["wall_study"])
    box_span("wall_back_b", -3.5, 0.8, y0, y1, 0, H, M["wall"])
    box_span("wall_back_c", 0.8, 3.2, y0, y1, 0, 0.5, M["wall"])
    box_span("wall_back_d", 0.8, 3.2, y0, y1, 2.4, H, M["wall"])
    box_span("wall_back_e", 3.2, 3.5, y0, y1, 0, H, M["wall"])
    box_span("wall_back_f", 3.5, 8.0 + T, y0, y1, 0, H, M["wall_bed"])
    box_span("wall_left", -7.0 - T, -7.0, 0, y0, 0, H, M["wall_study"])
    # Right wall with the balcony door y [1.2, 3.8], z [0, 2.3].
    box_span("wall_right_a", 8.0, 8.0 + T, 0, 1.2, 0, H, M["wall_bed"])
    box_span("wall_right_b", 8.0, 8.0 + T, 3.8, y0, 0, H, M["wall_bed"])
    box_span("wall_right_c", 8.0, 8.0 + T, 1.2, 3.8, 2.3, H, M["wall_bed"])
    # Partitions with doorways near the open side, y [0.3, 1.2].
    for name, x, mat in [("part_a", -3.5, M["wall"]), ("part_b", 3.5, M["wall"])]:
        box_span(f"{name}_1", x - T / 2, x + T / 2, 1.2, y0, 0, H, mat)
        box_span(f"{name}_2", x - T / 2, x + T / 2, 0, 0.3, 0, H, mat)
        box_span(f"{name}_3", x - T / 2, x + T / 2, 0.3, 1.2, 2.1, H, mat)
    # Floor slab and floors.
    box_span("slab", -7.0 - T - 0.15, 8.0 + T + 0.15, -0.3, 5.0 + T + 0.15, -0.32, -0.02, M["slab"], bev=0.02)
    box_span("floor_all", -7.0, 8.0, 0, 5.0, -0.02, 0.0, M["floor"], bev=0)
    # Interior-only pieces: front wall and ceiling of the living room.
    box_span("wall_front", -3.5, 3.5, -T, 0, 0, H, M["wall"], collection="interior")
    box_span("ceiling", -3.5, 3.5, 0, 5.0, H, H + 0.1, M["wall"], collection="interior")


def window_living(M):
    x0, x1, z0, z1, y = 0.8, 3.2, 0.5, 2.4, 5.06
    f = 0.045
    box_span("win_frame_l", x0, x0 + f, y - 0.04, y + 0.04, z0, z1, M["frame"])
    box_span("win_frame_r", x1 - f, x1, y - 0.04, y + 0.04, z0, z1, M["frame"])
    box_span("win_frame_b", x0, x1, y - 0.05, y + 0.05, z0, z0 + f, M["frame"])
    box_span("win_frame_t", x0, x1, y - 0.04, y + 0.04, z1 - f, z1, M["frame"])
    box_span("win_frame_m", 2.0 - f / 2, 2.0 + f / 2, y - 0.04, y + 0.04, z0, z1, M["frame"])
    g = plane("win_glass", x1 - x0, z1 - z0, (2.0, y, (z0 + z1) / 2), M["glass"], rot=(math.pi / 2, 0, 0))
    g.visible_shadow = False
    # Curtain rod and two pleated panels. Panel origin is at its outer edge.
    cyl("curtain_rod", 0.012, 3.0, (2.0, 4.86, 2.52), M["brass"], rot=(0, math.pi / 2, 0), bev=0.002)
    for side, ox, sign in [("l", 0.55, 1), ("r", 3.45, -1)]:
        bm = bmesh.new()
        nx, nz, w, hgt = 90, 2, 1.45, 2.46
        verts = []
        for j in range(nz + 1):
            row = []
            for i in range(nx + 1):
                u = i / nx
                x = sign * u * w
                yy = 0.035 * math.sin(u * w / 0.11 * 2 * math.pi)
                row.append(bm.verts.new((x, yy, -j / nz * hgt)))
            verts.append(row)
        for j in range(nz):
            for i in range(nx):
                bm.faces.new([verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]])
        ob = mesh_object(f"curtain_{side}", bm, M["curtain"])
        ob.location = (ox, 4.84, 2.49)
        sol = ob.modifiers.new("solid", "SOLIDIFY")
        sol.thickness = 0.006
        ob.scale.x = 0.25
    anchor("curtain", (2.0, 4.8, 1.6))
    anchor("window_living", (2.0, 5.0, 1.45))
    light("window_sky", "AREA", (2.0, 4.95, 1.45), 0, (0.85, 0.9, 1.0), None, size=2.3, size_y=1.8,
          rot=(math.radians(-90), 0, 0), shadow=True, specular=0.6)


def city_backdrop():
    """Night skyline far behind the living window, only used for interior shots."""
    m = bpy.data.materials.new("city")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # Sky gradient (object Z of a vertical plane is its local Y).
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
    nt.links.new(m2.outputs[0], comb.inputs[0])
    nt.links.new(m2.outputs[0], comb.inputs[1])
    nt.links.new(m2.outputs[0], comb.inputs[2])
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
    # Daylight version: bright hazy sky, mixed in by "day".
    day_e = nt.nodes.new("ShaderNodeEmission")
    day_ramp = nt.nodes.new("ShaderNodeValToRGB")
    de = day_ramp.color_ramp.elements
    de[0].position, de[0].color = 0.0, (0.95, 0.9, 0.82, 1)
    de[1].position, de[1].color = 1.0, (0.45, 0.65, 0.95, 1)
    nt.links.new(sep.outputs["Y"], day_ramp.inputs["Fac"])
    nt.links.new(day_ramp.outputs["Color"], day_e.inputs["Color"])
    day_e.inputs["Strength"].default_value = 3.0
    mixs = nt.nodes.new("ShaderNodeMixShader")
    mixs.inputs["Fac"].default_value = 0.0
    nt.links.new(add.outputs[0], mixs.inputs[1])
    nt.links.new(day_e.outputs[0], mixs.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(mixs.outputs[0], out.inputs[0])
    REG["city_day"] = mixs.inputs["Fac"]
    ob = plane("city", 34, 14, (2.0, 16.0, 4.0), m, rot=(math.pi / 2, 0, 0), collection="city")
    ob.visible_shadow = False
    ob.visible_diffuse = False


def living_room(M):
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
    # Round coffee table with the speaker, a mug and books.
    cx, cy = -1.0, 3.0
    cyl("ctable_top", 0.42, 0.04, (cx, cy, 0.4), M["oak"], bev=0.012)
    for k in range(3):
        a = k * 2 * math.pi / 3 + 0.4
        cyl(f"ctable_leg{k}", 0.018, 0.38, (cx + 0.27 * math.cos(a), cy + 0.27 * math.sin(a), 0.19),
            M["black_metal"], seg=16, bev=0.003)
    box("book_a", (0.24, 0.17, 0.025), (cx - 0.2, cy - 0.1, 0.4325), M["book"][1], bev=0.003, rot=(0, 0, 0.3))
    box("book_b", (0.22, 0.16, 0.02), (cx - 0.19, cy - 0.09, 0.455), M["book"][2], bev=0.003, rot=(0, 0, 0.12))
    cyl("mug", 0.04, 0.09, (cx + 0.22, cy + 0.12, 0.465), M["ceramic"], seg=32, bev=0.006)
    speaker("sp", SPEAKER_LIVING, "apartment")
    light("sp_ringlight", "POINT", SPEAKER_LIVING + Vector((0, 0, 0.24)), 0, (1, 0.5, 0.35), None, size=0.03)
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
    bm = dome.data
    # Cut the lower half off the dome.
    bmd = bmesh.new()
    bmd.from_mesh(bm)
    bmesh.ops.delete(bmd, geom=[v for v in bmd.verts if v.co.z < -0.001], context="VERTS")
    bmd.to_mesh(bm)
    bmd.free()
    sol = dome.modifiers.new("solid", "SOLIDIFY")
    sol.thickness = 0.01
    bulb_m = glow_material("pendant_bulb", (1.0, 0.75, 0.5), 25.0, "living_main")
    sphere("pendant_bulb", 0.05, (cx, cy, 2.07), bulb_m)
    disk_m = glow_material("pendant_disk", (1.0, 0.8, 0.6), 4.0, "living_main")
    cyl("pendant_diffuser", 0.27, 0.004, (cx, cy, 2.075), disk_m, bev=0)
    light("pendant_light", "AREA", (cx, cy, 2.04), 150, (1.0, 0.66, 0.38), "living_main", size=0.5)
    light("pendant_pt", "POINT", (cx, cy, 2.0), 25, (1.0, 0.66, 0.38), "living_main", size=0.1)
    light("living_fill", "AREA", (0.0, 2.5, 2.6), 70, (1.0, 0.74, 0.5), "living_main", size=6.0,
          size_y=4.5, shadow=False, specular=0.0)
    anchor("pendant", (cx, cy, 2.1))
    # Wall art.
    for i, (x, m) in enumerate([(-1.95, M["art_a"]), (-1.2, M["art_b"])]):
        box(f"art{i}_frame", (0.56, 0.03, 0.72), (x, 4.975, 1.52), M["walnut"], bev=0.004)
        plane(f"art{i}_canvas", 0.5, 0.66, (x, 4.958, 1.52), m, rot=(math.pi / 2, 0, 0))
    # Wall-mounted air conditioner between sofa and window.
    ax, az = 0.05, 2.28
    box("ac_l", (0.95, 0.22, 0.3), (ax, 4.89, az), M["ac_body"], bev=0.03, seg=4)
    box("ac_l_slot", (0.82, 0.04, 0.03), (ax, 4.78, az - 0.11), M["ac_slot"], bev=0.01)
    box("ac_l_screen", (0.16, 0.004, 0.06), (ax + 0.3, 4.779, az + 0.02), M["screen_off"], bev=0.002)
    for val in ("24", "26"):
        mm = emission(f"ac_l_{val}_m", (0.55, 0.85, 1.0), 0.0)
        text(f"ac_l_{val}", f"{val}°", 0.05, (ax + 0.3, 4.776, az + 0.02), mm)
        REG[f"ac_l_{val}"] = mm.node_tree.nodes["Emission"].inputs["Strength"]
    anchor("ac_living", (ax, 4.8, az))
    # Sideboard on the partition wall, with a plant and a vase.
    box("sideboard", (0.42, 1.6, 0.55), (-3.22, 3.2, 0.3), M["walnut"], bev=0.01)
    for k in range(3):
        box(f"sideboard_door{k}", (0.005, 0.5, 0.45), (-3.0, 2.67 + k * 0.53, 0.32), M["oak"], bev=0.002)
    cyl("vase", 0.07, 0.3, (-3.22, 2.7, 0.72), M["ceramic_dark"], seg=32, r2=0.04, bev=0.01)
    plant("plant_side", (-3.22, 3.7, 0.575), 0.35, M, pot=0.09)
    plant("plant_big", (3.05, 4.5, 0.0), 1.25, M, pot=0.2)
    # Robot vacuum (another brand).
    cyl("vacuum", 0.17, 0.08, (1.9, 1.6, 0.045), M["white_plastic"], bev=0.02)
    cyl("vacuum_top", 0.045, 0.015, (1.9, 1.66, 0.09), M["ac_slot"], bev=0.004)
    anchor("vacuum", (1.9, 1.6, 0.12))
    window_living(M)


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


def study(M):
    box_span("rug_study", -6.4, -4.2, 2.2, 4.3, 0, 0.012, M["rug_bed"], bev=0.005)
    dx, dy = -5.3, 4.6
    box("desk_top", (1.5, 0.66, 0.04), (dx, dy, 0.74), M["oak"], bev=0.008)
    for i, ox in enumerate([-0.7, 0.7]):
        box(f"desk_leg{i}", (0.04, 0.6, 0.72), (dx + ox, dy, 0.36), M["black_metal"], bev=0.004)
    box("laptop_base", (0.34, 0.24, 0.015), (dx - 0.1, dy - 0.05, 0.768), M["laptop"], bev=0.004)
    scr_m = principled("laptop_screen", (0.02, 0.02, 0.03), rough=0.1, emit=(0.4, 0.55, 1.0), strength=1.5)
    group_emit("study", scr_m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"], 1.5)
    box("laptop_lid", (0.34, 0.012, 0.22), (dx - 0.1, dy + 0.075, 0.87), scr_m, bev=0.004, rot=(-0.25, 0, 0))
    # Desk lamp (another brand) with its head over the desk.
    lx = dx + 0.55
    cyl("dlamp_base", 0.07, 0.02, (lx, dy + 0.1, 0.77), M["black_metal"], bev=0.005)
    cyl("dlamp_arm1", 0.008, 0.42, (lx, dy + 0.1, 0.98), M["black_metal"], seg=12, bev=0, rot=(0.25, 0, 0))
    cyl("dlamp_arm2", 0.008, 0.36, (lx, dy - 0.07, 1.2), M["black_metal"], seg=12, bev=0, rot=(1.2, 0, 0))
    head_m = glow_material("dlamp_head_m", WARM_SOFT, 6.0, "study")
    cyl("dlamp_head", 0.06, 0.1, (lx, dy - 0.22, 1.15), head_m, r2=0.03, bev=0.004)
    light("dlamp_light", "SPOT", (lx, dy - 0.22, 1.1), 60, WARM_SOFT, "study", size=0.03,
          spot=(1.9, 0.6))
    anchor("desklamp", (lx, dy - 0.22, 1.2))
    # Chair.
    cx, cy = dx - 0.1, dy - 0.75
    box("chair_seat", (0.46, 0.44, 0.06), (cx, cy, 0.46), M["sofa"], bev=0.02)
    box("chair_back", (0.46, 0.05, 0.42), (cx, cy - 0.23, 0.72), M["sofa"], bev=0.02, rot=(0.1, 0, 0))
    for i, (ox, oy) in enumerate([(-0.2, -0.18), (0.2, -0.18), (-0.2, 0.18), (0.2, 0.18)]):
        cyl(f"chair_leg{i}", 0.014, 0.44, (cx + ox, cy + oy, 0.22), M["black_metal"], seg=12, bev=0)
    # Bookshelf on the left wall.
    bx = -6.82
    box("shelf_frame", (0.34, 1.5, 2.0), (bx, 2.9, 1.0), M["walnut"], bev=0.006)
    rnd = random.Random(7)
    for k in range(5):
        z = 0.08 + k * 0.4
        box(f"shelf_board{k}", (0.32, 1.44, 0.025), (bx + 0.03, 2.9, z), M["oak"], bev=0.003)
        y = 2.2
        while y < 3.55:
            w = rnd.uniform(0.025, 0.05)
            hgt = rnd.uniform(0.22, 0.32)
            if rnd.random() < 0.12:
                y += 0.1
                continue
            box(f"book_s{k}_{y:.2f}", (0.24, w, hgt), (bx + 0.05, y + w / 2, z + 0.0125 + hgt / 2),
                rnd.choice(M["book"]), bev=0.003)
            y += w + 0.004
    plant("plant_study", (-3.95, 4.55, 0.0), 0.8, M, pot=0.16)
    # Ceiling pendant for the study.
    cyl("study_cord", 0.004, 0.5, (-5.2, 2.8, H - 0.25), M["black_metal"], seg=8, bev=0)
    ps_m = glow_material("study_shade_m", WARM_SOFT, 4.0, "study")
    cyl("study_shade", 0.2, 0.18, (-5.2, 2.8, 2.12), ps_m, r2=0.08, bev=0.004)
    light("study_light", "AREA", (-5.2, 2.8, 2.0), 150, WARM_SOFT, "study", size=0.4)
    light("study_fill", "AREA", (-5.25, 2.5, 2.6), 90, WARM_SOFT, "study", size=3.3, size_y=4.5,
          shadow=False, specular=0.0)
    anchor("study_light", (-5.2, 2.8, 2.15))


def bedroom(M):
    bx = 5.75
    box_span("rug_bed", 4.2, 7.3, 1.2, 3.4, 0, 0.012, M["rug_bed"], bev=0.005)
    box("bed_frame", (1.95, 2.15, 0.3), (bx, 3.88, 0.2), M["walnut"], bev=0.02)
    box("headboard", (2.05, 0.12, 1.05), (bx, 4.92, 0.55), M["headboard"], bev=0.05, seg=4)
    box("mattress", (1.85, 2.02, 0.22), (bx, 3.9, 0.45), M["duvet"], bev=0.05, seg=4)
    box("duvet", (1.92, 1.45, 0.1), (bx, 3.4, 0.6), M["bedcover"], bev=0.05, seg=5)
    box("duvet_fold", (1.92, 0.28, 0.12), (bx, 4.05, 0.62), M["duvet"], bev=0.05, seg=5)
    for i, ox in enumerate([-0.45, 0.45]):
        box(f"bed_pillow{i}", (0.66, 0.36, 0.14), (bx + ox, 4.58, 0.64), M["duvet"], bev=0.065, seg=6,
            rot=(-0.35, 0, 0))
    for i, ox in enumerate([-1.3, 1.3]):
        box(f"nightstand{i}", (0.48, 0.42, 0.5), (bx + ox, 4.72, 0.25), M["oak"], bev=0.01)
        cyl(f"blamp_base{i}", 0.06, 0.2, (bx + ox, 4.72, 0.6), M["ceramic_dark"], seg=24, r2=0.035, bev=0.01)
        sm = glow_material(f"blamp_shade{i}", WARM, 3.5, "bed_lamp")
        cyl(f"blamp_shade{i}", 0.13, 0.16, (bx + ox, 4.72, 0.78), sm, r2=0.1, bev=0.004)
        light(f"blamp_light{i}", "POINT", (bx + ox, 4.72, 0.77), 35, WARM, "bed_lamp", size=0.05)
    anchor("bedlamp", (bx + 1.3, 4.72, 0.8))
    # Bedroom AC above the bed: off until sleep mode sets 25°.
    az = 2.3
    box("ac_b", (0.95, 0.22, 0.3), (bx, 4.89, az), M["ac_body"], bev=0.03, seg=4)
    box("ac_b_slot", (0.82, 0.04, 0.03), (bx, 4.78, az - 0.11), M["ac_slot"], bev=0.01)
    box("ac_b_screen", (0.16, 0.004, 0.06), (bx + 0.3, 4.779, az + 0.02), M["screen_off"], bev=0.002)
    mm = emission("ac_b_25_m", (0.55, 0.85, 1.0), 0.0)
    text("ac_b_25", "25°", 0.05, (bx + 0.3, 4.776, az + 0.02), mm)
    REG["ac_b_25"] = mm.node_tree.nodes["Emission"].inputs["Strength"]
    anchor("ac_bed", (bx, 4.8, az))
    # Wardrobe on the partition.
    box("wardrobe", (0.6, 1.8, 2.2), (3.86, 3.25, 1.1), M["white_plastic"], bev=0.01)
    for k in range(3):
        box(f"wardrobe_seam{k}", (0.004, 0.004, 2.1), (4.162, 2.65 + k * 0.6, 1.1), M["ac_slot"], bev=0)
    # Balcony door on the right wall, one pane slid open.
    x = 8.0
    f = 0.05
    box_span("bal_frame_t", x - 0.03, x + T, 1.2, 3.8, 2.25, 2.3, M["frame"])
    box_span("bal_frame_b", x - 0.03, x + T, 1.2, 3.8, 0, 0.04, M["frame"])
    box_span("bal_frame_l", x - 0.03, x + T, 1.2, 1.2 + f, 0, 2.3, M["frame"])
    box_span("bal_frame_r", x - 0.03, x + T, 3.8 - f, 3.8, 0, 2.3, M["frame"])
    # Fixed pane (rear) and sliding pane (front, pulled open towards y=1.2 side).
    for name, y0, y1, xo in [("bal_pane_a", 2.5, 3.78, x + 0.07), ("bal_pane_b", 1.6, 2.9, x + 0.02)]:
        box_span(f"{name}_f", xo - 0.015, xo + 0.015, y0, y1, 0.04, 2.25, M["frame"])
        g = plane(f"{name}_g", y1 - y0 - 0.08, 2.1, (xo, (y0 + y1) / 2, 1.145), M["glass"],
                  rot=(math.pi / 2, 0, math.pi / 2))
        g.visible_shadow = False
    # Alert outline that blinks when sleep mode finds the door open.
    al = emission("bal_alert_m", (1.0, 0.35, 0.08), 0.0)
    REG["bal_alert"] = al.node_tree.nodes["Emission"].inputs["Strength"]
    for name, sz, loc in [
        ("bal_al_t", (0.02, 2.6, 0.02), (x - 0.04, 2.5, 2.27)),
        ("bal_al_b", (0.02, 2.6, 0.02), (x - 0.04, 2.5, 0.03)),
        ("bal_al_l", (0.02, 0.02, 2.26), (x - 0.04, 1.21, 1.15)),
        ("bal_al_r", (0.02, 0.02, 2.26), (x - 0.04, 3.79, 1.15)),
    ]:
        o = box(name, sz, loc, al, bev=0)
        o.visible_shadow = False
    anchor("balcony", (x, 2.5, 1.3))
    light("bed_main", "AREA", (5.75, 2.6, 2.55), 170, WARM_SOFT, "bed_main", size=0.8)
    light("bed_fill", "AREA", (5.75, 2.5, 2.6), 110, WARM_SOFT, "bed_main", size=4.3, size_y=4.5,
          shadow=False, specular=0.0)
    ceil_m = glow_material("bed_ceiling_m", WARM_SOFT, 5.0, "bed_main")
    cyl("bed_ceiling_lamp", 0.28, 0.05, (5.75, 2.6, 2.62), ceil_m, bev=0.01)
    anchor("bed_light", (5.75, 2.6, 2.6))


# ---------------------------------------------------------------- studio

def studio():
    c = "studio"
    floor_m = principled("studio_floor", (0.012, 0.012, 0.014), rough=0.3, coat=0.5, spec=0.5)
    plane("studio_floor", 60, 60, STUDIO, floor_m, collection=c)
    # Soft glow behind the speaker, tinted with the ring state.
    m = bpy.data.materials.new("studio_glow")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    # Centre the falloff at x=0.5, y=0.14 of the plane (about speaker height).
    mp.inputs["Location"].default_value = (-1.6, -0.5, 0)
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
    col.outputs[0].default_value = (0.25, 0.35, 0.6, 1)
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(p.outputs[0], mul.inputs[6])
    nt.links.new(col.outputs[0], mul.inputs[7])
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Strength"].default_value = 0.5
    nt.links.new(mul.outputs[2], e.inputs["Color"])
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    bg = plane("studio_bg", 14, 7, STUDIO + Vector((0, 5.0, 3.0)), m, rot=(math.pi / 2, 0, 0), collection=c)
    bg.visible_shadow = False
    REG["studio_glow"] = (col.outputs[0], e.inputs["Strength"])
    speaker("st", STUDIO.copy(), c)
    # Lights: two rims, a soft top key and a sweep light for the reveal.
    for side, sx in (("l", -1), ("r", 1)):
        pos = STUDIO + Vector((0.42 * sx, 0.75, 0.55))
        rim = light(f"st_rim_{side}", "AREA", pos, 22, (0.6, 0.75, 1.0), "st_rim", size=0.06, size_y=0.7,
                    collection=c, specular=0.0)
        rim.rotation_euler = (STUDIO + Vector((0, 0, 0.12)) - pos).to_track_quat("-Z", "Y").to_euler()
    light("st_key", "AREA", STUDIO + Vector((-0.4, -0.7, 1.1)), 9, (1.0, 0.92, 0.85), "st_key",
          size=0.9, rot=(math.radians(40), 0, math.radians(-30)), collection=c)
    light("st_sweep", "AREA", STUDIO + Vector((-1.0, -0.35, 0.18)), 0, (1.0, 0.9, 0.8), None,
          size=0.05, size_y=0.8, rot=(math.radians(90), 0, 0), collection=c, specular=0.15)
    light("st_ringlight", "POINT", STUDIO + Vector((0, 0, 0.23)), 0, (1, 0.5, 0.3), None, size=0.04,
          collection=c)
    # Floating dust particles, animated by the plates.
    pm = emission("particle", (1.0, 0.8, 0.6), 4.0)
    REG["particles"] = []
    rnd = random.Random(11)
    for i in range(140):
        # Keep dust behind and beside the speaker, away from the camera paths.
        r = rnd.uniform(0.3, 1.8)
        a = rnd.uniform(math.radians(-10), math.radians(190))
        pos = STUDIO + Vector((r * math.cos(a), r * math.sin(a) + 0.15, rnd.uniform(0.02, 0.8)))
        s = rnd.uniform(0.0008, 0.0022)
        ob = sphere(f"particle{i}", s, pos, pm, seg=8, collection=c)
        ob.visible_shadow = False
        REG["particles"].append((ob, pos.copy(), rnd.uniform(0, 6.28), rnd.uniform(0.3, 1.0)))
    REG["particle_strength"] = pm.node_tree.nodes["Emission"].inputs["Strength"]


# ---------------------------------------------------------------- world & render

def world_setup():
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    bg = w.node_tree.nodes["Background"]
    REG["world"] = bg
    bg.inputs["Color"].default_value = (0.006, 0.009, 0.018, 1)
    bg.inputs["Strength"].default_value = 1.0
    # Moonlight / daylight sun.
    light("sun", "SUN", (0, 0, 10), 0.0, (0.55, 0.65, 1.0), None, size=math.radians(2),
          rot=(math.radians(55), 0, math.radians(120)))
    # Soft skylight over the diorama so dark rooms still read.
    light("sky_fill", "AREA", (0.5, 2.5, 7.0), 250, (0.45, 0.55, 0.9), "ambient", size=16, size_y=8,
          shadow=False, specular=0.2)


def set_day(day):
    """0 = night, 1 = sunny afternoon."""
    bg = REG["world"]
    n, d = (0.006, 0.009, 0.018), (0.8, 0.72, 0.62)
    bg.inputs["Color"].default_value = (*[a * (1 - day) + b * day for a, b in zip(n, d)], 1)
    bg.inputs["Strength"].default_value = 1.0 if day < 0.5 else 0.22
    sun = REG["objs"]["sun"].data
    if day > 0.5:
        sun.energy = 6.5
        sun.color = (1.0, 0.7, 0.42)
        sun.angle = math.radians(1.0)
        # Low golden-hour sun raking through the window across the coffee table.
        d = Vector((-0.78, -0.55, -0.3)).normalized()
        REG["objs"]["sun"].rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        REG["objs"]["window_sky"].data.energy = 150
        REG["objs"]["window_sky"].data.color = (0.9, 0.92, 1.0)
    REG["city_day"].default_value = day


def haze(density):
    """Thin world fog so sunbeams read in the air."""
    w = bpy.context.scene.world
    nt = w.node_tree
    v = nt.nodes.new("ShaderNodeVolumeScatter")
    v.inputs["Density"].default_value = density
    v.inputs["Anisotropy"].default_value = 0.6
    nt.links.new(v.outputs[0], nt.nodes["World Output"].inputs["Volume"])
    sc = bpy.context.scene
    sc.eevee.volumetric_start = 0.1
    sc.eevee.volumetric_end = 12.0
    sc.eevee.volumetric_tile_size = "4"
    sc.eevee.volumetric_samples = 64


def render_setup(res=1.0, samples=48):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = int(1920 * res)
    sc.render.resolution_y = int(1080 * res)
    sc.render.resolution_percentage = 100
    sc.render.fps = 30
    sc.eevee.taa_render_samples = samples
    sc.eevee.use_raytracing = True
    sc.eevee.ray_tracing_method = "SCREEN"
    sc.eevee.use_fast_gi = True
    sc.eevee.fast_gi_method = "GLOBAL_ILLUMINATION"
    sc.eevee.use_shadows = True
    sc.eevee.shadow_ray_count = 2
    sc.eevee.shadow_step_count = 8
    sc.render.use_motion_blur = False
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Punchy", "Punchy"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            pass
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 93
    # Compositor: bloom plus a touch of lens dispersion.
    ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
    ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    sc.compositing_node_group = ng
    rl = ng.nodes.new("CompositorNodeRLayers")
    gl = ng.nodes.new("CompositorNodeGlare")
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Quality"].default_value = "High"
    gl.inputs["Threshold"].default_value = 1.2
    gl.inputs["Strength"].default_value = 0.55
    gl.inputs["Size"].default_value = 0.8
    ld = ng.nodes.new("CompositorNodeLensdist")
    ld.inputs["Dispersion"].default_value = 0.012
    out = ng.nodes.new("NodeGroupOutput")
    ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ng.links.new(gl.outputs["Image"], ld.inputs["Image"])
    ng.links.new(ld.outputs["Image"], out.inputs[0])
    REG["bloom"] = gl


def camera():
    cd = bpy.data.cameras.new("Cam")
    cd.sensor_width = 36
    cd.clip_start = 0.01
    cd.clip_end = 300
    cd.dof.use_dof = True
    cd.dof.aperture_blades = 7
    cd.dof.aperture_rotation = 0.3
    ob = bpy.data.objects.new("Cam", cd)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    REG["cam"] = ob
    return ob


def build(res=1.0, samples=48):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    random.seed(3)
    M = make_materials()
    walls(M)
    living_room(M)
    study(M)
    bedroom(M)
    city_backdrop()
    studio()
    world_setup()
    render_setup(res, samples)
    camera()
    # Lamp shades and bulbs glow; they must not trap their own light.
    for ob in bpy.data.objects:
        if ob.type == "MESH" and any(m and m.name in REG.get("glow_mats", ()) for m in ob.data.materials):
            ob.visible_shadow = False
    return M
