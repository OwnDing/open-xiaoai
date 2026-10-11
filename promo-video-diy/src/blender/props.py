"""Hero props and effects: the DIY speaker, the mini PC and its thinking 'brain',
voice threads, the home's light dome, the cloud, cameras, flame and steam.

Props are built in local coordinates under a parent empty so the same model can
stand in the home and in the studio.
"""
import math
import random

import bmesh
import bpy
from mathutils import Vector

from kit import (REG, anchor, box, coll, cyl, emission, fabric, light, link, mesh_object, node, plane,
                 principled, sphere, torus)

AMBER = (1.0, 0.55, 0.2)
ROSE = (1.0, 0.3, 0.42)
VIOLET = (0.55, 0.32, 1.0)
COLD = (0.55, 0.78, 1.0)


def empty(name, loc, collection, rot=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.location = loc
    e.rotation_euler = rot
    link(e, collection)
    REG["objs"][name] = e
    return e


def parent_all(objs, parent):
    for ob in objs:
        ob.parent = parent


def collect_new(fn):
    """Run fn() and return (result, objects it created)."""
    before = set(bpy.data.objects)
    res = fn()
    return res, [o for o in bpy.data.objects if o not in before]


def ramp_colors(ramp, stops):
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1)
    els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1)
    for pos, c in stops[1:-1]:
        els.new(pos).color = (*c, 1)


def ring_material(name):
    """Flowing amber/rose/violet gradient, or flat cold white (mix factor 0)."""
    m = bpy.data.materials.new(name)
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
    ramp_colors(ramp, [(0.0, (1.0, 0.45, 0.08)), (0.3, ROSE), (0.6, VIOLET), (0.82, (1.0, 0.3, 0.3)),
                       (1.0, (1.0, 0.45, 0.08))])
    nt.links.new(g.outputs["Fac"], ramp.inputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.62, 0.8, 1.0, 1)
    nt.links.new(ramp.outputs["Color"], mix.inputs[7])
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(mix.outputs[2], em.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    return m, {"mix": mix.inputs["Factor"], "strength": em.inputs["Strength"], "spin": mp.inputs["Rotation"]}


def set_ring(prefix, level, spin, warm=None):
    r = REG["rings"][prefix]
    if warm is not None:
        r["mix"].default_value = warm
    r["strength"].default_value = level
    r["spin"].default_value[2] = spin
    if "light" in r:
        w = r["mix"].default_value
        r["light"].energy = r["light_k"] * level
        r["light"].color = [c * (1 - w) + h * w for c, h in zip(COLD, (1.0, 0.5, 0.32))]


# ---------------------------------------------------------------- the DIY speaker

def pebble_speaker(prefix, base, collection, rot_z=0.0):
    """A small round fabric speaker with a light ring on its top edge.

    Returns the parent empty; REG["rings"][prefix] drives the ring.
    """
    def build():
        # Lathe a pebble profile (r, z) around Z.
        prof = [(0.0, 0.0), (0.056, 0.0), (0.064, 0.003), (0.0695, 0.012), (0.072, 0.028),
                (0.0715, 0.046), (0.0685, 0.06), (0.0645, 0.07), (0.061, 0.075)]
        bm = bmesh.new()
        verts = [bm.verts.new((r, 0, z)) for r, z in prof]
        edges = [bm.edges.new((verts[i], verts[i + 1])) for i in range(len(verts) - 1)]
        bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1), angle=2 * math.pi, steps=72,
                       use_duplicate=False)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        body = mesh_object(f"{prefix}_body", bm, fabric(f"{prefix}_fabric", (0.2, 0.19, 0.18), scale=3200,
                                                         bump=0.2), collection)
        top_m = principled(f"{prefix}_top", (0.018, 0.018, 0.02), rough=0.55, spec=0.4)
        cyl(f"{prefix}_cap", 0.0585, 0.004, (0, 0, 0.0755), top_m, bev=0.0015, collection=collection)
        hole_m = principled(f"{prefix}_hole", (0.002, 0.002, 0.002), rough=0.9)
        for k in range(4):
            a = k * math.pi / 2 + math.pi / 4
            cyl(f"{prefix}_mic{k}", 0.0011, 0.0006, (0.022 * math.cos(a), 0.022 * math.sin(a), 0.0777), hole_m,
                seg=12, bev=0, collection=collection)
        dot_m = principled(f"{prefix}_dot", (0.35, 0.33, 0.3), rough=0.35, metal=0.8)
        cyl(f"{prefix}_logo", 0.004, 0.0006, (0, 0, 0.0777), dot_m, seg=24, bev=0, collection=collection)
        m, ctl = ring_material(f"{prefix}_ring")
        ring = torus(f"{prefix}_ring", 0.0605, 0.0016, (0, 0, 0.0758), m, collection, zscale=0.6)
        ring.visible_shadow = False
        foot_m = principled(f"{prefix}_foot", (0.01, 0.01, 0.01), rough=0.7)
        cyl(f"{prefix}_foot", 0.05, 0.003, (0, 0, 0.0015), foot_m, bev=0.001, collection=collection)
        lt = light(f"{prefix}_ringlight", "POINT", (0, 0, 0.11), 0, (1.0, 0.5, 0.32), None, size=0.04,
                   collection=collection)
        ctl["light"] = lt.data
        ctl["light_k"] = 0.05
        ctl["mix"].default_value = 1.0
        REG["rings"][prefix] = ctl
        return body
    _, objs = collect_new(build)
    root = empty(f"{prefix}_root", base, collection, rot=(0, 0, rot_z))
    parent_all(objs, root)
    anchor(prefix, Vector(base) + Vector((0, 0, 0.08)))
    return root


def generic_speaker(prefix, base, collection):
    """A typical cloud smart speaker: tall fabric cylinder, flat cold ring on glass."""
    def build():
        R, Hs = 0.068, 0.19
        body_m = fabric(f"{prefix}_fabric", (0.34, 0.33, 0.32), scale=900, bump=0.35)
        top_m = principled(f"{prefix}_top", (0.012, 0.012, 0.014), rough=0.12, coat=1.0, spec=0.8)
        base_m = principled(f"{prefix}_base", (0.02, 0.02, 0.02), rough=0.5)
        cyl(f"{prefix}_body", R, Hs - 0.02, (0, 0, 0.01 + (Hs - 0.02) / 2), body_m, bev=0.006, collection=collection)
        cyl(f"{prefix}_foot", R - 0.004, 0.012, (0, 0, 0.006), base_m, bev=0.003, collection=collection)
        cyl(f"{prefix}_cap", R - 0.0015, 0.012, (0, 0, Hs - 0.006), top_m, bev=0.004, collection=collection)
        m, ctl = ring_material(f"{prefix}_ring")
        ring = torus(f"{prefix}_ring", 0.05, 0.0019, (0, 0, Hs), m, collection, zscale=0.45)
        ring.visible_shadow = False
        lt = light(f"{prefix}_ringlight", "POINT", (0, 0, Hs + 0.05), 0, COLD, None, size=0.03,
                   collection=collection)
        ctl["light"] = lt.data
        ctl["light_k"] = 0.05
        ctl["mix"].default_value = 0.0
        REG["rings"][prefix] = ctl
    _, objs = collect_new(build)
    root = empty(f"{prefix}_root", base, collection)
    parent_all(objs, root)
    anchor(prefix, Vector(base) + Vector((0, 0, 0.19)))
    return root


# ---------------------------------------------------------------- the mini PC

def mini_pc(prefix, base, collection, rot_z=0.0):
    """Anodised aluminium box with a light bar on its front (local -Y)."""
    W, Hh = 0.128, 0.046

    def build():
        alu = principled(f"{prefix}_alu", (0.2, 0.205, 0.215), rough=0.32, metal=1.0)
        top = principled(f"{prefix}_topm", (0.035, 0.036, 0.04), rough=0.22, metal=0.6, coat=0.6)
        dark = principled(f"{prefix}_dark", (0.01, 0.01, 0.012), rough=0.6)
        box(f"{prefix}_body", (W, W, Hh), (0, 0, Hh / 2 + 0.003), alu, bev=0.011, seg=5, collection=collection)
        box(f"{prefix}_top", (W - 0.018, W - 0.018, 0.002), (0, 0, Hh + 0.0028), top, bev=0.006, seg=3,
            collection=collection)
        cyl(f"{prefix}_foot", 0.05, 0.004, (0, 0, 0.002), dark, bev=0.001, collection=collection)
        # Side vents.
        for s in (-1, 1):
            for k in range(9):
                box(f"{prefix}_vent{s}_{k}", (0.002, 0.006 * 0 + 0.07, 0.0016),
                    (s * (W / 2 + 0.0002), 0, 0.012 + k * 0.0034), dark, bev=0, collection=collection)
        # Front light bar (amber -> violet gradient along X) and a power dot.
        m = bpy.data.materials.new(f"{prefix}_bar")
        nt = m.node_tree
        nt.nodes.clear()
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp_colors(ramp, [(0.0, AMBER), (0.55, ROSE), (1.0, VIOLET)])
        nt.links.new(sep.outputs["X"], ramp.inputs["Fac"])
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 0.0
        nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], out.inputs[0])
        bar = box(f"{prefix}_bar", (0.07, 0.0016, 0.0022), (0, -W / 2 - 0.0002, 0.012), m, bev=0,
                  collection=collection)
        bar.visible_shadow = False
        pm = emission(f"{prefix}_pwr", (1.0, 0.85, 0.7), 2.0)
        cyl(f"{prefix}_pwr", 0.0012, 0.001, (0.05, -W / 2 - 0.0003, 0.035), pm, seg=12, bev=0,
            collection=collection, rot=(math.pi / 2, 0, 0))
        lt = light(f"{prefix}_barlight", "AREA", (0, -W / 2 - 0.02, 0.012), 0, (1.0, 0.5, 0.35), None,
                   size=0.08, size_y=0.01, rot=(math.radians(90), 0, 0), collection=collection, specular=0.3)
        REG[f"{prefix}_bar"] = (em.inputs["Strength"], lt.data)
    _, objs = collect_new(build)
    root = empty(f"{prefix}_root", base, collection, rot=(0, 0, rot_z))
    parent_all(objs, root)
    anchor(prefix, Vector(base) + Vector((0, 0, 0.05)))
    return root


def set_bar(prefix, level):
    s, lt = REG[f"{prefix}_bar"]
    s.default_value = level
    lt.energy = 0.08 * level


def brain(prefix, center, radius, collection, n=90, seed=3):
    """A constellation of points joined to their nearest neighbours: the AI 'thinking'.

    Returns the parent empty (scale it to grow/shrink, rotate it to turn) and
    registers the emission strength in REG[prefix + "_strength"].
    """
    rnd = random.Random(seed)
    pts = []
    while len(pts) < n:
        v = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)))
        if 0.25 < v.length <= 1.0:
            pts.append(v * radius)
    m = bpy.data.materials.new(f"{prefix}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -radius
    mr.inputs["From Max"].default_value = radius
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp_colors(ramp, [(0.0, AMBER), (0.5, ROSE), (1.0, VIOLET)])
    nt.links.new(mr.outputs[0], ramp.inputs["Fac"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.0
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    REG[f"{prefix}_strength"] = em.inputs["Strength"]
    root = empty(f"{prefix}_root", center, collection)
    # Nodes.
    bm = bmesh.new()
    for p in pts:
        r = radius * rnd.uniform(0.022, 0.04)
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
        bmesh.ops.translate(bm, vec=p, verts=res["verts"])
    dots = mesh_object(f"{prefix}_dots", bm, m, collection)
    dots.visible_shadow = False
    dots.parent = root
    # Links: each point to its two nearest neighbours.
    cu = bpy.data.curves.new(f"{prefix}_links", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius * 0.006
    cu.bevel_resolution = 0
    seen = set()
    for i, p in enumerate(pts):
        near = sorted(range(len(pts)), key=lambda j: (pts[j] - p).length)[1:3]
        for j in near:
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            sp = cu.splines.new("POLY")
            sp.points.add(1)
            sp.points[0].co = (*p, 1)
            sp.points[1].co = (*pts[j], 1)
    cu.materials.append(m)
    lk = bpy.data.objects.new(f"{prefix}_links", cu)
    lk.visible_shadow = False
    link(lk, collection)
    lk.parent = root
    root.scale = (0, 0, 0)
    return root


# ---------------------------------------------------------------- voice threads

def catmull(points, samples=240):
    """Centripetal-ish Catmull-Rom through control points, resampled by arc length."""
    P = [Vector(p) for p in points]
    P = [P[0] + (P[0] - P[1])] + P + [P[-1] + (P[-1] - P[-2])]
    dense = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(40):
            t = k / 40
            t2, t3 = t * t, t * t * t
            dense.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                                + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    dense.append(P[-2])
    acc = [0.0]
    for a, b in zip(dense, dense[1:]):
        acc.append(acc[-1] + (b - a).length)
    L = acc[-1]
    out, j = [], 0
    for k in range(samples + 1):
        s = L * k / samples
        while j < len(acc) - 2 and acc[j + 1] < s:
            j += 1
        u = (s - acc[j]) / max(acc[j + 1] - acc[j], 1e-9)
        out.append(dense[j].lerp(dense[j + 1], u))
    return out, L


def thread(name, points, color, radius=0.004, collection="threads", head_light=0.0, sides=6, head_size=None):
    """A glowing tube along a smooth path, revealed by a travelling pulse.

    Material controls (REG["threads"][name]): head (0..1 position of the pulse
    front along the path), tail (length of the bright comet, 0..1), trail
    (brightness left behind the pulse), strength.
    """
    pts, L = catmull(points)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    rings = []
    up = Vector((0, 0, 1))
    for i, p in enumerate(pts):
        d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        a = d.cross(up)
        if a.length < 1e-4:
            a = d.cross(Vector((1, 0, 0)))
        a.normalize()
        b = a.cross(d).normalized()
        rings.append([bm.verts.new(p + radius * (math.cos(2 * math.pi * k / sides) * a
                                                 + math.sin(2 * math.pi * k / sides) * b)) for k in range(sides)])
    n = len(pts) - 1
    for i in range(n):
        for k in range(sides):
            f = bm.faces.new([rings[i][k], rings[i][(k + 1) % sides], rings[i + 1][(k + 1) % sides],
                              rings[i + 1][k]])
            for loop, (u, v) in zip(f.loops, [(i / n, k / sides), (i / n, (k + 1) / sides),
                                              ((i + 1) / n, (k + 1) / sides), ((i + 1) / n, k / sides)]):
                loop[uv_layer].uv = (u, v)
    m = bpy.data.materials.new(f"{name}_m")
    nt = m.node_tree
    nt.nodes.clear()
    uv = nt.nodes.new("ShaderNodeUVMap")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(uv.outputs[0], sep.inputs[0])
    head = nt.nodes.new("ShaderNodeValue")
    tail = nt.nodes.new("ShaderNodeValue")
    trail = nt.nodes.new("ShaderNodeValue")
    strength = nt.nodes.new("ShaderNodeValue")
    head.outputs[0].default_value = 0.0
    tail.outputs[0].default_value = 0.25
    trail.outputs[0].default_value = 0.0
    strength.outputs[0].default_value = 0.0
    # d = head - s; comet = clamp(1 - d / tail) when d >= 0
    d = nt.nodes.new("ShaderNodeMath")
    d.operation = "SUBTRACT"
    nt.links.new(head.outputs[0], d.inputs[0])
    nt.links.new(sep.outputs["X"], d.inputs[1])
    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    nt.links.new(d.outputs[0], div.inputs[0])
    nt.links.new(tail.outputs[0], div.inputs[1])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.use_clamp = True
    inv.inputs[0].default_value = 1.0
    nt.links.new(div.outputs[0], inv.inputs[1])
    pw = nt.nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.inputs[1].default_value = 2.0
    nt.links.new(inv.outputs[0], pw.inputs[0])
    behind = nt.nodes.new("ShaderNodeMath")
    behind.operation = "GREATER_THAN"
    behind.inputs[1].default_value = -0.002
    nt.links.new(d.outputs[0], behind.inputs[0])
    comet = nt.nodes.new("ShaderNodeMath")
    comet.operation = "MULTIPLY"
    nt.links.new(pw.outputs[0], comet.inputs[0])
    nt.links.new(behind.outputs[0], comet.inputs[1])
    tr = nt.nodes.new("ShaderNodeMath")
    tr.operation = "MULTIPLY"
    nt.links.new(behind.outputs[0], tr.inputs[0])
    nt.links.new(trail.outputs[0], tr.inputs[1])
    vis = nt.nodes.new("ShaderNodeMath")
    vis.operation = "MAXIMUM"
    nt.links.new(comet.outputs[0], vis.inputs[0])
    nt.links.new(tr.outputs[0], vis.inputs[1])
    st = nt.nodes.new("ShaderNodeMath")
    st.operation = "MULTIPLY"
    nt.links.new(vis.outputs[0], st.inputs[0])
    nt.links.new(strength.outputs[0], st.inputs[1])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    nt.links.new(st.outputs[0], em.inputs["Strength"])
    tsp = nt.nodes.new("ShaderNodeBsdfTransparent")
    alpha = nt.nodes.new("ShaderNodeMath")
    alpha.operation = "MINIMUM"
    alpha.inputs[1].default_value = 1.0
    a2 = nt.nodes.new("ShaderNodeMath")
    a2.operation = "MULTIPLY"
    a2.inputs[1].default_value = 4.0
    nt.links.new(vis.outputs[0], a2.inputs[0])
    nt.links.new(a2.outputs[0], alpha.inputs[0])
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(alpha.outputs[0], mix.inputs["Fac"])
    nt.links.new(tsp.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(mix.outputs[0], out.inputs[0])
    m.surface_render_method = "BLENDED"
    ob = mesh_object(name, bm, m, collection)
    ob.visible_shadow = False
    ob.visible_diffuse = False
    ob.visible_glossy = False
    # Bright head bead (and optionally a little light that travels with it).
    hm = emission(f"{name}_head_m", color, 0.0)
    hs = head_size or radius * 2.6
    bead = sphere(f"{name}_head", hs, pts[0], hm, seg=12, collection=collection)
    bead.visible_shadow = False
    hl = None
    if head_light > 0:
        hl = light(f"{name}_hl", "POINT", pts[0], 0, color, None, size=0.02, collection=collection)
        hl.data.use_shadow = False
    REG["threads"][name] = {
        "pts": pts, "len": L, "head": head.outputs[0], "tail": tail.outputs[0], "trail": trail.outputs[0],
        "strength": strength.outputs[0], "bead": bead, "bead_s": hm.node_tree.nodes["Emission"].inputs["Strength"],
        "light": hl, "light_k": head_light, "ob": ob,
    }
    return ob


def point_at(name, u):
    th = REG["threads"][name]
    pts = th["pts"]
    u = max(0.0, min(1.0, u))
    f = u * (len(pts) - 1)
    i = min(int(f), len(pts) - 2)
    return pts[i].lerp(pts[i + 1], f - i)


def set_thread(name, head, strength, tail=0.25, trail=0.0, bead=None):
    """head: pulse front position (0..1, may run past 1 so the comet leaves)."""
    th = REG["threads"][name]
    th["head"].default_value = head
    th["tail"].default_value = max(tail, 1e-3)
    th["trail"].default_value = trail
    th["strength"].default_value = strength
    on = 0.0 < head < 1.0 + 1e-6 and strength > 0
    b = th["bead"]
    b.hide_render = not on
    if on:
        b.location = point_at(name, head)
        th["bead_s"].default_value = strength * 2.5 if bead is None else bead
    if th["light"] is not None:
        th["light"].hide_render = not on
        if on:
            th["light"].location = b.location
            th["light"].data.energy = th["light_k"] * strength


# ---------------------------------------------------------------- the home's dome and the cloud

def dome(name, center, radii, collection="dome"):
    """Translucent shell over the diorama: fresnel glow, cell lines, and a rising
    reveal edge (REG["dome"]: reveal 0..1, strength)."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=96, v_segments=48, radius=1.0)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.02], context="VERTS")
    ob = mesh_object(name, bm, None, collection)
    ob.location = center
    ob.scale = radii
    m = bpy.data.materials.new(f"{name}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    lw = node(nt, "ShaderNodeLayerWeight", Blend=0.25)
    fres = nt.nodes.new("ShaderNodeMath")
    fres.operation = "POWER"
    fres.inputs[1].default_value = 2.5
    nt.links.new(lw.outputs["Facing"], fres.inputs[0])
    vor = node(nt, "ShaderNodeTexVoronoi", Scale=14.0)
    vor.feature = "DISTANCE_TO_EDGE"
    nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
    cell = nt.nodes.new("ShaderNodeMapRange")
    cell.inputs["From Min"].default_value = 0.012
    cell.inputs["From Max"].default_value = 0.0
    nt.links.new(vor.outputs["Distance"], cell.inputs["Value"])
    cellf = nt.nodes.new("ShaderNodeMath")
    cellf.operation = "MULTIPLY"
    nt.links.new(cell.outputs[0], cellf.inputs[0])
    nt.links.new(lw.outputs["Facing"], cellf.inputs[1])
    cellw = nt.nodes.new("ShaderNodeMath")
    cellw.operation = "MULTIPLY"
    cellw.inputs[1].default_value = 0.22
    nt.links.new(cellf.outputs[0], cellw.inputs[0])
    # Reveal: visible where z <= reveal, with a bright band at the edge.
    reveal = nt.nodes.new("ShaderNodeValue")
    reveal.outputs[0].default_value = 1.0
    dz = nt.nodes.new("ShaderNodeMath")
    dz.operation = "SUBTRACT"
    nt.links.new(reveal.outputs[0], dz.inputs[0])
    nt.links.new(sep.outputs["Z"], dz.inputs[1])
    vis = nt.nodes.new("ShaderNodeMath")
    vis.operation = "GREATER_THAN"
    vis.inputs[1].default_value = 0.0
    nt.links.new(dz.outputs[0], vis.inputs[0])
    band = nt.nodes.new("ShaderNodeMapRange")
    band.inputs["From Min"].default_value = 0.06
    band.inputs["From Max"].default_value = 0.0
    nt.links.new(dz.outputs[0], band.inputs["Value"])
    bandv = nt.nodes.new("ShaderNodeMath")
    bandv.operation = "MULTIPLY"
    nt.links.new(band.outputs[0], bandv.inputs[0])
    nt.links.new(vis.outputs[0], bandv.inputs[1])
    bandk = nt.nodes.new("ShaderNodeMath")
    bandk.operation = "MULTIPLY"
    bandk.inputs[1].default_value = 3.0
    nt.links.new(bandv.outputs[0], bandk.inputs[0])
    base = nt.nodes.new("ShaderNodeMath")
    base.operation = "ADD"
    nt.links.new(fres.outputs[0], base.inputs[0])
    nt.links.new(cellw.outputs[0], base.inputs[1])
    base2 = nt.nodes.new("ShaderNodeMath")
    base2.operation = "ADD"
    base2.inputs[1].default_value = 0.015
    nt.links.new(base.outputs[0], base2.inputs[0])
    baseb = nt.nodes.new("ShaderNodeMath")
    baseb.operation = "MULTIPLY"
    nt.links.new(base2.outputs[0], baseb.inputs[0])
    nt.links.new(vis.outputs[0], baseb.inputs[1])
    tot = nt.nodes.new("ShaderNodeMath")
    tot.operation = "ADD"
    nt.links.new(baseb.outputs[0], tot.inputs[0])
    nt.links.new(bandk.outputs[0], tot.inputs[1])
    strength = nt.nodes.new("ShaderNodeValue")
    strength.outputs[0].default_value = 0.0
    st = nt.nodes.new("ShaderNodeMath")
    st.operation = "MULTIPLY"
    nt.links.new(tot.outputs[0], st.inputs[0])
    nt.links.new(strength.outputs[0], st.inputs[1])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.58, 0.28, 1)
    nt.links.new(st.outputs[0], em.inputs["Strength"])
    tsp = nt.nodes.new("ShaderNodeBsdfTransparent")
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(tsp.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(add.outputs[0], out.inputs[0])
    m.surface_render_method = "BLENDED"
    m.use_backface_culling = False
    ob.data.materials.append(m)
    ob.visible_shadow = False
    ob.visible_diffuse = False
    ob.visible_glossy = False
    REG["dome"] = {"reveal": reveal.outputs[0], "strength": strength.outputs[0], "ob": ob}
    return ob


def cloud(name, center, size, collection="cloud"):
    """A churning volumetric cloud deck with rows of server lights in its belly."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = mesh_object(name, bm, None, collection, smooth=False)
    ob.location = center
    ob.scale = size
    m = bpy.data.materials.new(f"{name}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (2.2, 1.6, 3.0)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.noise_dimensions = "4D"
    nz.inputs["Scale"].default_value = 1.6
    nz.inputs["Detail"].default_value = 5.0
    nz.inputs["Roughness"].default_value = 0.6
    nt.links.new(mp.outputs[0], nz.inputs["Vector"])
    # Vertical falloff: dense in the middle of the deck, soft top and bottom.
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    ab0 = nt.nodes.new("ShaderNodeMath")
    ab0.operation = "ABSOLUTE"
    nt.links.new(sep.outputs["Z"], ab0.inputs[0])
    lump = nt.nodes.new("ShaderNodeTexNoise")
    lump.inputs["Scale"].default_value = 2.5
    lump.inputs["Detail"].default_value = 2.0
    lmp = node(nt, "ShaderNodeMapping")
    lmp.inputs["Scale"].default_value = (2.0, 1.5, 0.3)
    nt.links.new(tc.outputs["Object"], lmp.inputs["Vector"])
    nt.links.new(lmp.outputs[0], lump.inputs["Vector"])
    lk = nt.nodes.new("ShaderNodeMath")
    lk.operation = "MULTIPLY_ADD"
    lk.inputs[1].default_value = 0.55
    lk.inputs[2].default_value = -0.27
    nt.links.new(lump.outputs["Fac"], lk.inputs[0])
    ab = nt.nodes.new("ShaderNodeMath")
    ab.operation = "ADD"
    nt.links.new(ab0.outputs[0], ab.inputs[0])
    nt.links.new(lk.outputs[0], ab.inputs[1])
    fall = nt.nodes.new("ShaderNodeMapRange")
    fall.inputs["From Min"].default_value = 0.5
    fall.inputs["From Max"].default_value = 0.05
    nt.links.new(ab.outputs[0], fall.inputs["Value"])
    # Horizontal edge falloff.
    lx = nt.nodes.new("ShaderNodeMath")
    lx.operation = "ABSOLUTE"
    nt.links.new(sep.outputs["X"], lx.inputs[0])
    fx = nt.nodes.new("ShaderNodeMapRange")
    fx.inputs["From Min"].default_value = 0.5
    fx.inputs["From Max"].default_value = 0.3
    nt.links.new(lx.outputs[0], fx.inputs["Value"])
    ly = nt.nodes.new("ShaderNodeMath")
    ly.operation = "ABSOLUTE"
    nt.links.new(sep.outputs["Y"], ly.inputs[0])
    fy = nt.nodes.new("ShaderNodeMapRange")
    fy.inputs["From Min"].default_value = 0.5
    fy.inputs["From Max"].default_value = 0.3
    nt.links.new(ly.outputs[0], fy.inputs["Value"])
    shape = nt.nodes.new("ShaderNodeMapRange")
    shape.inputs["From Min"].default_value = 0.47
    shape.inputs["From Max"].default_value = 0.68
    nt.links.new(nz.outputs["Fac"], shape.inputs["Value"])
    d1 = nt.nodes.new("ShaderNodeMath")
    d1.operation = "MULTIPLY"
    nt.links.new(shape.outputs[0], d1.inputs[0])
    nt.links.new(fall.outputs[0], d1.inputs[1])
    d2 = nt.nodes.new("ShaderNodeMath")
    d2.operation = "MULTIPLY"
    nt.links.new(d1.outputs[0], d2.inputs[0])
    nt.links.new(fx.outputs[0], d2.inputs[1])
    d3 = nt.nodes.new("ShaderNodeMath")
    d3.operation = "MULTIPLY"
    nt.links.new(d2.outputs[0], d3.inputs[0])
    nt.links.new(fy.outputs[0], d3.inputs[1])
    dens = nt.nodes.new("ShaderNodeValue")
    dens.outputs[0].default_value = 1.2
    d4 = nt.nodes.new("ShaderNodeMath")
    d4.operation = "MULTIPLY"
    nt.links.new(d3.outputs[0], d4.inputs[0])
    nt.links.new(dens.outputs[0], d4.inputs[1])
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.3, 0.36, 0.46, 1)
    vol.inputs["Anisotropy"].default_value = 0.2
    nt.links.new(d4.outputs[0], vol.inputs["Density"])
    # Faint cold self-glow so the underside reads against black.
    vol.inputs["Emission Color"].default_value = (0.25, 0.42, 0.75, 1)
    glow = nt.nodes.new("ShaderNodeMath")
    glow.operation = "MULTIPLY"
    glow.inputs[1].default_value = 0.0
    nt.links.new(d3.outputs[0], glow.inputs[0])
    nt.links.new(glow.outputs[0], vol.inputs["Emission Strength"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    ob.data.materials.append(m)
    REG["cloud"] = {"w": nz.inputs["W"], "density": dens.outputs[0], "glow": glow.inputs[1], "ob": ob}
    return ob


def server_lights(name, center, nx, ny, pitch, collection="cloud"):
    """Rows of tiny LEDs, blinking by a 4D noise pattern (REG["servers"] w, strength)."""
    bm = bmesh.new()
    rnd = random.Random(9)
    for i in range(nx):
        for j in range(ny):
            if rnd.random() < 0.84:
                continue
            res = bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(pitch * 0.22, pitch * 0.12, pitch * 0.05), verts=res["verts"])
            bmesh.ops.translate(bm, vec=((i - nx / 2) * pitch + rnd.uniform(-0.1, 0.1) * pitch,
                                         (j - ny / 2) * pitch * 0.6, rnd.uniform(-0.3, 0.3)),
                                verts=res["verts"])
    m = bpy.data.materials.new(f"{name}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.noise_dimensions = "4D"
    nz.inputs["Scale"].default_value = 3.0
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    gt = nt.nodes.new("ShaderNodeMapRange")
    gt.inputs["From Min"].default_value = 0.45
    gt.inputs["From Max"].default_value = 0.6
    gt.inputs["To Min"].default_value = 0.15
    nt.links.new(nz.outputs["Fac"], gt.inputs["Value"])
    strength = nt.nodes.new("ShaderNodeValue")
    strength.outputs[0].default_value = 0.0
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(gt.outputs[0], mul.inputs[0])
    nt.links.new(strength.outputs[0], mul.inputs[1])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.7, 0.88, 1.0, 1)
    nt.links.new(mul.outputs[0], em.inputs["Strength"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    ob = mesh_object(name, bm, m, collection, smooth=False)
    ob.location = center
    ob.visible_shadow = False
    REG["servers"] = {"w": nz.inputs["W"], "strength": strength.outputs[0]}
    return ob


# ---------------------------------------------------------------- cameras, flame, steam

def security_camera(prefix, base, aim, collection, scale=1.0, white=True):
    """Small home camera: rounded body, glass lens, status LED. Faces `aim`."""
    def build():
        body_m = principled(f"{prefix}_body", (0.88, 0.88, 0.86) if white else (0.05, 0.05, 0.055),
                            rough=0.3, coat=0.5)
        lens_m = principled(f"{prefix}_lens", (0.005, 0.005, 0.008), rough=0.04, coat=1.0, spec=1.0)
        rim_m = principled(f"{prefix}_rim", (0.08, 0.08, 0.09), rough=0.3, metal=0.8)
        s = scale
        box(f"{prefix}_shell", (0.07 * s, 0.075 * s, 0.065 * s), (0, 0, 0), body_m, bev=0.02 * s, seg=4,
            collection=collection)
        cyl(f"{prefix}_rim", 0.022 * s, 0.006 * s, (0, -0.038 * s, 0.004 * s), rim_m, bev=0.002 * s,
            collection=collection, rot=(math.pi / 2, 0, 0))
        cyl(f"{prefix}_lens", 0.016 * s, 0.006 * s, (0, -0.040 * s, 0.004 * s), lens_m, bev=0.003 * s,
            collection=collection, rot=(math.pi / 2, 0, 0))
        led = emission(f"{prefix}_led", (0.3, 0.6, 1.0), 0.0)
        cyl(f"{prefix}_led", 0.0025 * s, 0.002 * s, (0.024 * s, -0.0385 * s, -0.02 * s), led, seg=12, bev=0,
            collection=collection, rot=(math.pi / 2, 0, 0))
        REG[f"{prefix}_led"] = led.node_tree.nodes["Emission"].inputs["Strength"]
    _, objs = collect_new(build)
    root = empty(f"{prefix}_root", base, collection)
    d = (Vector(aim) - Vector(base)).normalized()
    root.rotation_euler = d.to_track_quat("-Y", "Z").to_euler()
    parent_all(objs, root)
    anchor(prefix, base)
    return root


def flame(prefix, center, radius, collection="apartment", n=26):
    """Blue gas flame: a ring of small tongues (REG[prefix]: tongues, strength)."""
    m = bpy.data.materials.new(f"{prefix}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp_colors(ramp, [(0.0, (0.15, 0.35, 1.0)), (0.5, (0.08, 0.18, 1.0)), (1.0, (0.45, 0.2, 0.9))])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    fade = nt.nodes.new("ShaderNodeMapRange")
    fade.inputs["From Min"].default_value = 1.0
    fade.inputs["From Max"].default_value = 0.2
    nt.links.new(sep.outputs["Z"], fade.inputs["Value"])
    strength = nt.nodes.new("ShaderNodeValue")
    strength.outputs[0].default_value = 0.0
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(fade.outputs[0], mul.inputs[0])
    nt.links.new(strength.outputs[0], mul.inputs[1])
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    nt.links.new(mul.outputs[0], em.inputs["Strength"])
    tsp = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(fade.outputs[0], mix.inputs["Fac"])
    nt.links.new(tsp.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(mix.outputs[0], out.inputs[0])
    m.surface_render_method = "BLENDED"
    tongues = []
    for k in range(n):
        a = 2 * math.pi * k / n
        c = Vector(center) + Vector((radius * math.cos(a), radius * math.sin(a), 0))
        t = cyl(f"{prefix}_t{k}", 0.0065, 0.026, c + Vector((0, 0, 0.011)), m, seg=12, bev=0, r2=0.0005,
                collection=collection)
        t.rotation_euler = (-0.55 * math.sin(a), 0.55 * math.cos(a), 0)
        t.visible_shadow = False
        tongues.append(t)
    lt = light(f"{prefix}_light", "POINT", Vector(center) + Vector((0, 0, 0.03)), 0, (0.35, 0.5, 1.0), None,
               size=0.05, collection=collection)
    REG[prefix] = {"tongues": tongues, "strength": strength.outputs[0], "light": lt.data}


def set_flame(prefix, t, level):
    f = REG[prefix]
    f["strength"].default_value = 4.5 * level
    f["light"].energy = 4.0 * level
    for k, tg in enumerate(f["tongues"]):
        flick = 0.85 + 0.25 * math.sin(t * 23 + k * 1.7) * math.sin(t * 7.3 + k * 0.9)
        tg.scale = (1, 1, max(0.01, level * flick))


def steam(prefix, base, height, radius, collection="apartment"):
    """Rising wisps above the pot: noise-driven volume in a tall box."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    ob = mesh_object(prefix, bm, None, collection, smooth=False)
    ob.location = Vector(base) + Vector((0, 0, height / 2))
    ob.scale = (radius * 2, radius * 2, height)
    m = bpy.data.materials.new(f"{prefix}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    off = nt.nodes.new("ShaderNodeVectorMath")
    off.operation = "ADD"
    rise = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(tc.outputs["Object"], off.inputs[0])
    nt.links.new(rise.outputs[0], off.inputs[1])
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (2.2, 2.2, 1.6)
    nt.links.new(off.outputs[0], mp.inputs["Vector"])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 3.2
    nz.inputs["Detail"].default_value = 6.0
    nz.inputs["Roughness"].default_value = 0.65
    nz.inputs["Distortion"].default_value = 2.5
    nt.links.new(mp.outputs[0], nz.inputs["Vector"])
    shape = nt.nodes.new("ShaderNodeMapRange")
    shape.inputs["From Min"].default_value = 0.44
    shape.inputs["From Max"].default_value = 0.7
    nt.links.new(nz.outputs["Fac"], shape.inputs["Value"])
    # Radial falloff widening with height, and fade towards the top.
    rx = nt.nodes.new("ShaderNodeVectorMath")
    rx.operation = "LENGTH"
    xy = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs["X"], xy.inputs["X"])
    nt.links.new(sep.outputs["Y"], xy.inputs["Y"])
    nt.links.new(xy.outputs[0], rx.inputs[0])
    hz = nt.nodes.new("ShaderNodeMapRange")
    hz.inputs["From Min"].default_value = -0.5
    hz.inputs["From Max"].default_value = 0.5
    hz.inputs["To Min"].default_value = 0.18
    hz.inputs["To Max"].default_value = 0.5
    nt.links.new(sep.outputs["Z"], hz.inputs["Value"])
    rr = nt.nodes.new("ShaderNodeMath")
    rr.operation = "DIVIDE"
    nt.links.new(rx.outputs["Value"], rr.inputs[0])
    nt.links.new(hz.outputs[0], rr.inputs[1])
    rf = nt.nodes.new("ShaderNodeMapRange")
    rf.inputs["From Min"].default_value = 1.0
    rf.inputs["From Max"].default_value = 0.2
    nt.links.new(rr.outputs[0], rf.inputs["Value"])
    top = nt.nodes.new("ShaderNodeMapRange")
    top.inputs["From Min"].default_value = 0.5
    top.inputs["From Max"].default_value = -0.2
    nt.links.new(sep.outputs["Z"], top.inputs["Value"])
    bot = nt.nodes.new("ShaderNodeMapRange")
    bot.inputs["From Min"].default_value = -0.5
    bot.inputs["From Max"].default_value = -0.4
    nt.links.new(sep.outputs["Z"], bot.inputs["Value"])
    d = shape
    for f in (rf, top, bot):
        mm = nt.nodes.new("ShaderNodeMath")
        mm.operation = "MULTIPLY"
        nt.links.new(d.outputs[0], mm.inputs[0])
        nt.links.new(f.outputs[0], mm.inputs[1])
        d = mm
    dens = nt.nodes.new("ShaderNodeValue")
    dens.outputs[0].default_value = 0.0
    dd = nt.nodes.new("ShaderNodeMath")
    dd.operation = "MULTIPLY"
    nt.links.new(d.outputs[0], dd.inputs[0])
    nt.links.new(dens.outputs[0], dd.inputs[1])
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.9, 0.92, 0.95, 1)
    vol.inputs["Anisotropy"].default_value = 0.5
    nt.links.new(dd.outputs[0], vol.inputs["Density"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    ob.data.materials.append(m)
    REG[prefix] = {"rise": rise.inputs["Z"], "density": dens.outputs[0]}
    return ob


# ---------------------------------------------------------------- the worksheet

def worksheet(name, center, size, image_path, collection="apartment", rot_z=0.0):
    img = bpy.data.images.load(str(image_path))
    m = principled(f"{name}_m", (1, 1, 1), rough=0.75, spec=0.25)
    nt = m.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Cubic"
    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    ob = plane(name, size[0], size[1], center, m, rot=(0, 0, rot_z), collection=collection)
    # Planes from kit have no UVs; add a simple 0..1 map.
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    for poly in me.polygons:
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x - min(xs)) / (max(xs) - min(xs)), (v.y - min(ys)) / (max(ys) - min(ys)))
    return ob
