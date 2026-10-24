"""Hero props shared with 《家的大脑》: the speaker, a typical cloud speaker, the mini PC and
its thinking 'brain', and the glowing voice threads.

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
