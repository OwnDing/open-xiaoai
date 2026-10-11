"""Black product studio: the DIY speaker and the mini PC as heroes, sound rings,
and the exploded software stack of glass layers above the mini PC."""
import math
import random

import bmesh
import bpy
from mathutils import Vector

from kit import REG, anchor, box, emission, light, mesh_object, node, plane, principled, sphere, torus
from props import AMBER, ROSE, VIOLET, brain, mini_pc, pebble_speaker, ramp_colors, thread

STUDIO = Vector((100.0, 0.0, 0.0))
ST_SPEAKER = STUDIO + Vector((-0.17, 0.0, 0.0))
ST_PC = STUDIO + Vector((0.17, 0.02, 0.0))
LAYER_COLORS = [AMBER, ROSE, VIOLET, (0.3, 0.75, 1.0)]


def backdrop(c):
    floor_m = principled("studio_floor", (0.008, 0.008, 0.009), rough=0.38, coat=0.25, spec=0.4)
    plane("studio_floor", 60, 60, STUDIO, floor_m, collection=c)
    # Soft glow wall far behind, tinted per plate (REG["studio_glow"]: color, strength, position).
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
    bg = plane("studio_bg", 14, 7, STUDIO + Vector((0, 4.0, 2.2)), m, rot=(math.pi / 2, 0, 0), collection=c)
    bg.visible_shadow = False
    REG["studio_glow"] = (col.outputs[0], e.inputs["Strength"], mp.inputs["Location"])


def lights(c):
    # Top pools that reveal each hero (S09), rims, a key, and a sweep bar.
    for name, pos in (("st_top_sp", ST_SPEAKER), ("st_top_pc", ST_PC)):
        light(name, "SPOT", pos + Vector((0, 0.05, 1.2)), 0, (1.0, 0.9, 0.82), None, size=0.15,
              spot=(math.radians(24), 0.55), collection=c)
    for side, sx in (("l", -1), ("r", 1)):
        for tgt_name, tgt in (("sp", ST_SPEAKER), ("pc", ST_PC)):
            pos = tgt + Vector((0.34 * sx, 0.6, 0.35))
            rim = light(f"st_rim_{tgt_name}_{side}", "AREA", pos, 0, (0.75, 0.85, 1.0), None, size=0.05,
                        size_y=0.5, collection=c, specular=0.0)
            rim.rotation_euler = (tgt + Vector((0, 0, 0.05)) - pos).to_track_quat("-Z", "Y").to_euler()
    light("st_key", "AREA", STUDIO + Vector((-0.35, -0.75, 0.75)), 0, (1.0, 0.92, 0.85), None,
          size=0.8, rot=(math.radians(50), 0, math.radians(-25)), collection=c)
    # A large soft panel seen only in reflections: gives the aluminium its gradient.
    sb = emission("st_softbox_m", (1.0, 0.95, 0.9), 0.0)
    box_ob = plane("st_softbox", 1.6, 0.6, ST_PC + Vector((-0.25, -1.1, 0.35)), sb, rot=(math.radians(80), 0, math.radians(-12)),
                   collection=c)
    box_ob.visible_camera = False
    box_ob.visible_shadow = False
    REG["st_softbox"] = sb.node_tree.nodes["Emission"].inputs["Strength"]
    light("st_sweep", "AREA", STUDIO + Vector((-1.0, -0.3, 0.25)), 0, (1.0, 0.92, 0.85), None,
          size=0.03, size_y=0.9, rot=(math.radians(90), 0, 0), collection=c, specular=1.0)


def sound_rings(c, n=5):
    """Thin amber rings that expand from the speaker (REG["rings_fx"])."""
    rings = []
    for k in range(n):
        m = emission(f"sring{k}_m", (1.0, 0.6, 0.3), 0.0)
        r = torus(f"sring{k}", 1.0, 0.0035, ST_SPEAKER + Vector((0, 0, 0.04)), m, "st_speaker", zscale=1.0)
        r.visible_shadow = False
        r.scale = (0.0, 0.0, 0.0)
        rings.append((r, m.node_tree.nodes["Emission"].inputs["Strength"]))
    REG["rings_fx"] = rings


def glass_layer(name, center, color, c):
    """A rounded glass tile with a glowing rim and a faint inner grid."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(0.17, 0.17, 0.0055), verts=bm.verts)
    ob = mesh_object(name, bm, None, c)
    ob.location = center
    bv = ob.modifiers.new("bevel", "BEVEL")
    bv.width = 0.0026
    bv.segments = 3
    m = bpy.data.materials.new(f"{name}_m")
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    lw = node(nt, "ShaderNodeLayerWeight", Blend=0.15)
    gl = nt.nodes.new("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.25
    gl.inputs["Color"].default_value = (0.9, 0.92, 1.0, 1)
    tsp = nt.nodes.new("ShaderNodeBsdfTransparent")
    tsp.inputs["Color"].default_value = (0.92, 0.94, 1.0, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.08
    nt.links.new(tsp.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    # Rim: the object-space distance to the tile border.
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    ax = nt.nodes.new("ShaderNodeMath")
    ax.operation = "ABSOLUTE"
    nt.links.new(sep.outputs["X"], ax.inputs[0])
    ay = nt.nodes.new("ShaderNodeMath")
    ay.operation = "ABSOLUTE"
    nt.links.new(sep.outputs["Y"], ay.inputs[0])
    mx = nt.nodes.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    nt.links.new(ax.outputs[0], mx.inputs[0])
    nt.links.new(ay.outputs[0], mx.inputs[1])
    rim = nt.nodes.new("ShaderNodeMapRange")
    rim.inputs["From Min"].default_value = 0.075
    rim.inputs["From Max"].default_value = 0.085
    nt.links.new(mx.outputs[0], rim.inputs["Value"])
    # Grid lines inside.
    br = nt.nodes.new("ShaderNodeTexBrick")
    br.inputs["Scale"].default_value = 40.0
    br.inputs["Mortar Size"].default_value = 0.03
    br.inputs["Color1"].default_value = (0, 0, 0, 1)
    br.inputs["Color2"].default_value = (0, 0, 0, 1)
    br.inputs["Mortar"].default_value = (1, 1, 1, 1)
    br.offset = 0.0
    br.inputs["Brick Width"].default_value = 0.5
    br.inputs["Row Height"].default_value = 0.5
    nt.links.new(tc.outputs["Object"], br.inputs["Vector"])
    grid = nt.nodes.new("ShaderNodeMath")
    grid.operation = "MULTIPLY"
    grid.inputs[1].default_value = 0.12
    nt.links.new(br.outputs["Fac"], grid.inputs[0])
    tot = nt.nodes.new("ShaderNodeMath")
    tot.operation = "ADD"
    nt.links.new(rim.outputs[0], tot.inputs[0])
    nt.links.new(grid.outputs[0], tot.inputs[1])
    tot2 = nt.nodes.new("ShaderNodeMath")
    tot2.operation = "ADD"
    nt.links.new(tot.outputs[0], tot2.inputs[0])
    fr = nt.nodes.new("ShaderNodeMath")
    fr.operation = "MULTIPLY"
    fr.inputs[1].default_value = 0.25
    nt.links.new(lw.outputs["Facing"], fr.inputs[0])
    nt.links.new(fr.outputs[0], tot2.inputs[1])
    strength = nt.nodes.new("ShaderNodeValue")
    strength.outputs[0].default_value = 0.0
    st = nt.nodes.new("ShaderNodeMath")
    st.operation = "MULTIPLY"
    nt.links.new(tot2.outputs[0], st.inputs[0])
    nt.links.new(strength.outputs[0], st.inputs[1])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    nt.links.new(st.outputs[0], em.inputs["Strength"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(mix.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(add.outputs[0], out.inputs[0])
    m.surface_render_method = "BLENDED"
    m.use_backface_culling = False
    ob.data.materials.append(m)
    ob.visible_shadow = False
    return ob, strength.outputs[0]


def stack(c):
    layers = []
    for k, col in enumerate(LAYER_COLORS):
        ob, s = glass_layer(f"layer{k}", ST_PC + Vector((0, 0, 0.06)), col, c)
        layers.append((ob, s))
        anchor(f"layer{k}", ST_PC)
        anchor(f"layer{k}_r", ST_PC)
    REG["layers"] = layers
    # The one line that leaves the box: text to the model API, up and to the right.
    top = ST_PC + Vector((0, 0, 0.42))
    thread("api_up", [top, top + Vector((0.12, 0.12, 0.18)), top + Vector((0.45, 0.4, 0.55)),
                      top + Vector((1.1, 0.8, 1.2))], (0.85, 0.9, 1.0), radius=0.0016, collection=c)
    anchor("api_top", top + Vector((0.45, 0.4, 0.55)))


def dust(c):
    pm = emission("st_dust_m", (1.0, 0.8, 0.6), 0.0)
    REG["st_dust"] = []
    rnd = random.Random(11)
    for i in range(160):
        r = rnd.uniform(0.25, 1.6)
        a = rnd.uniform(math.radians(-15), math.radians(195))
        pos = STUDIO + Vector((r * math.cos(a), r * math.sin(a) + 0.2, rnd.uniform(0.02, 0.9)))
        ob = sphere(f"st_dust{i}", rnd.uniform(0.0008, 0.002), pos, pm, seg=8, collection=c)
        ob.visible_shadow = False
        REG["st_dust"].append((ob, pos.copy(), rnd.uniform(0, 6.28), rnd.uniform(0.3, 1.0)))
    REG["st_dust_strength"] = pm.node_tree.nodes["Emission"].inputs["Strength"]


def build():
    c = "studio"
    backdrop(c)
    lights(c)
    pebble_speaker("st_sp", ST_SPEAKER, "st_speaker", rot_z=math.radians(20))
    mini_pc("st_pc", ST_PC, "st_pc", rot_z=math.radians(-18))
    brain("st_brain", ST_PC + Vector((0, 0, 0.2)), 0.07, "st_pc")
    sound_rings(c)
    stack("st_stack")
    dust(c)
