"""Shared building blocks for the procedural sets: primitives, materials, lights.

Units are metres, Z up. Everything registers itself in REG so the plate
scripts can animate it by name.
"""
import math
import random

import bmesh
import bpy
from mathutils import Vector

FONT_DIGITS = "/System/Library/Fonts/Avenir Next.ttc"

# Runtime registry the plate scripts animate through.
REG = {"groups": {}, "rings": {}, "anchors": {}, "objs": {}, "mats": {}, "colls": {}, "threads": {}}

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


