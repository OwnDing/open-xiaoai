"""The TV (its screen shows an image sequence rendered by src/tvui), the remote with
buttons that press down, and the museum case the remote retires to.

Props are modelled in local coordinates under a parent empty: the TV's screen
faces local -Y, the remote points along local +Y with its buttons on top.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from kit import REG, anchor, box, cyl, emission, light, link, mesh_object, node, plane, principled, sphere, torus
from props import collect_new, empty, parent_all


def uv_plane(name, w, h, loc, mat, rot, collection):
    """A plane with a 0..1 UV map (plane() from kit has none)."""
    ob = plane(name, w, h, loc, mat, rot=rot, collection=collection)
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    for poly in me.polygons:
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x - min(xs)) / (max(xs) - min(xs)), (v.y - min(ys)) / (max(ys) - min(ys)))
    return ob


def screen_material(name):
    """Black glass that shows an image sequence as emission (strength 0 = switched off)."""
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    uv = nt.nodes.new("ShaderNodeUVMap")
    img = nt.nodes.new("ShaderNodeTexImage")
    img.interpolation = "Cubic"
    img.extension = "EXTEND"
    nt.links.new(uv.outputs[0], img.inputs["Vector"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.0
    nt.links.new(img.outputs["Color"], em.inputs["Color"])
    gl = nt.nodes.new("ShaderNodeBsdfPrincipled")
    gl.inputs["Base Color"].default_value = (0.004, 0.004, 0.005, 1)
    gl.inputs["Roughness"].default_value = 0.35
    gl.inputs["Coat Weight"].default_value = 1.0
    gl.inputs["Coat Roughness"].default_value = 0.03
    gl.inputs["Specular IOR Level"].default_value = 0.35
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(gl.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(add.outputs[0], out.inputs[0])
    return m, img, em.inputs["Strength"], (gl.inputs["Coat Weight"], gl.inputs["Specular IOR Level"])


def tv(prefix, center, w, h, collection, rot_z=0.0, stand=None):
    """A thin-bezel TV. stand: None (wall-mounted) or "feet". Registers REG["screens"][prefix]."""
    def build():
        bez = principled(f"{prefix}_bezel", (0.012, 0.012, 0.013), rough=0.35, metal=0.4)
        back = principled(f"{prefix}_back", (0.03, 0.03, 0.032), rough=0.6)
        box(f"{prefix}_body", (w + 0.016, 0.024, h + 0.016), (0, 0.012, 0), bez, bev=0.004, collection=collection)
        box(f"{prefix}_rear", (w * 0.72, 0.04, h * 0.62), (0, 0.044, -h * 0.06), back, bev=0.02, collection=collection)
        m, img, strength, coat = screen_material(f"{prefix}_screen")
        uv_plane(f"{prefix}_screen", w, h, (0, -0.0008, 0), m, (math.pi / 2, 0, 0), collection)
        led = emission(f"{prefix}_led_m", (1.0, 0.06, 0.03), 0.0)
        cyl(f"{prefix}_led", 0.0018, 0.002, (w * 0.0, -0.001, -h / 2 - 0.004), led, seg=12, bev=0,
            rot=(math.pi / 2, 0, 0), collection=collection).visible_shadow = False
        lt = light(f"{prefix}_screenlight", "AREA", (0, -0.03, 0), 0, (0.6, 0.7, 1.0), None, size=w, size_y=h,
                   rot=(-math.pi / 2, 0, 0), collection=collection, specular=0.5)
        lt.data.use_shadow = True
        if stand == "feet":
            for s in (-1, 1):
                box(f"{prefix}_foot{s}", (0.03, 0.22, 0.012), (s * w * 0.38, 0.02, -h / 2 - 0.075), bez, bev=0.004,
                    collection=collection)
                box(f"{prefix}_leg{s}", (0.022, 0.012, 0.075), (s * w * 0.38, 0.02, -h / 2 - 0.035), bez, bev=0.003,
                    collection=collection, rot=(0.25, 0, 0))
        REG.setdefault("screens", {})[prefix] = {"img": img, "strength": strength, "coat": coat, "light": lt.data,
                                                 "w": w, "h": h,
                                                 "led": led.node_tree.nodes["Emission"].inputs["Strength"]}
    _, objs = collect_new(build)
    root = empty(f"{prefix}_root", center, collection, rot=(0, 0, rot_z))
    parent_all(objs, root)
    R = Matrix.Rotation(rot_z, 3, "Z")
    c = Vector(center)
    for tag, (x, z) in {"tl": (-w / 2, h / 2), "tr": (w / 2, h / 2), "br": (w / 2, -h / 2), "bl": (-w / 2, -h / 2),
                        "c": (0, 0)}.items():
        anchor(f"{prefix}_{tag}", c + R @ Vector((x, -0.002, z)))
    anchor(f"{prefix}_led", c + R @ Vector((0, -0.002, -h / 2 - 0.004)))
    REG["screens"][prefix]["center"] = c
    REG["screens"][prefix]["normal"] = R @ Vector((0, -1, 0))
    return root


def bind_screen(prefix, folder, frames):
    """Map an image sequence (####.jpg, frame 1 = plate frame 1) onto a TV's screen."""
    s = REG["screens"][prefix]
    img = bpy.data.images.load(str(folder / "0001.jpg"))
    img.source = "SEQUENCE"
    s["img"].image = img
    iu = s["img"].image_user
    iu.frame_duration = frames
    iu.frame_start = 1
    iu.frame_offset = 0
    iu.use_auto_refresh = True
    iu.use_cyclic = False


def set_screen(prefix, on, rgb=(0.0, 0.0, 0.0), gain=1.0, emit=1.45, light_k=230.0):
    """on: screen brightness 0..1 (the texture already carries the content); rgb: the frame's mean
    linear colour, which drives the light the screen throws into the room."""
    s = REG["screens"][prefix]
    s["strength"].default_value = emit * on * gain
    # The lamps' pin-point highlights read as dead pixels on a lit picture; the glare stays on a dark screen.
    lit = min(1.0, on * gain)
    s["coat"][0].default_value = 1.0 - lit
    s["coat"][1].default_value = 0.35 * (1.0 - lit)
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    s["light"].energy = light_k * lum * on * gain * s["w"] * s["h"]
    m = max(rgb) or 1.0
    s["light"].color = [max(0.02, c / m) for c in rgb] if max(rgb) > 0 else (1, 1, 1)


def set_led(prefix, level):
    REG["screens"][prefix]["led"].default_value = level


# ---------------------------------------------------------------- the remote

def remote(prefix, loc, collection, rot=(0, 0, 0), scale=1.0):
    """A slim graphite remote; REG["remote"][prefix][key] = (button, rest z) for key presses."""
    s = scale
    btn_m = principled(f"{prefix}_btn", (0.012, 0.012, 0.014), rough=0.5, coat=0.3)
    keys = {}

    def build():
        body = principled(f"{prefix}_body", (0.035, 0.035, 0.04), rough=0.42, coat=0.35, metal=0.2)
        box(f"{prefix}_shell", (0.042 * s, 0.168 * s, 0.015 * s), (0, 0, 0.0075 * s), body, bev=0.0065 * s, seg=5,
            collection=collection)
        top = 0.015 * s
        bz = top + 0.0006 * s

        def key(name, ob):
            keys[name] = (ob, ob.location.z)
        red = principled(f"{prefix}_pwr", (0.45, 0.04, 0.03), rough=0.4, coat=0.5)
        key("power", cyl(f"{prefix}_power", 0.0042 * s, 0.002 * s, (0.012 * s, 0.066 * s, bz), red, seg=24, bev=0.0006 * s,
                         collection=collection))
        mic_m = principled(f"{prefix}_mic", (0.02, 0.02, 0.024), rough=0.3, coat=0.6)
        key("mic", cyl(f"{prefix}_mic", 0.0055 * s, 0.002 * s, (-0.009 * s, 0.064 * s, bz), mic_m, seg=24,
                       bev=0.0006 * s, collection=collection))
        ring = principled(f"{prefix}_ring", (0.3, 0.3, 0.32), rough=0.25, metal=1.0)
        cz = 0.018 * s
        t = torus(f"{prefix}_dring", 0.0178 * s, 0.0009 * s, (0, cz, top + 0.0004 * s), ring, collection)
        t.scale.z = 0.5
        for name, (dx, dy, rz) in {"up": (0, 0.0115, 0), "down": (0, -0.0115, 0), "left": (-0.0115, 0, math.pi / 2),
                                   "right": (0.0115, 0, math.pi / 2)}.items():
            key(name, box(f"{prefix}_{name}", (0.011 * s, 0.0065 * s, 0.0022 * s), (dx * s, cz + dy * s, bz), btn_m,
                          bev=0.0012 * s, rot=(0, 0, rz), collection=collection))
        key("ok", cyl(f"{prefix}_ok", 0.0058 * s, 0.0024 * s, (0, cz, bz), btn_m, seg=32, bev=0.0008 * s,
                      collection=collection))
        for name, dx in (("back", -0.012), ("home", 0.0), ("menu", 0.012)):
            key(name, cyl(f"{prefix}_{name}", 0.0038 * s, 0.002 * s, (dx * s, -0.012 * s, bz), btn_m, seg=20,
                          bev=0.0006 * s, collection=collection))
        for name, dx in (("vol", -0.011), ("ch", 0.011)):
            box(f"{prefix}_{name}", (0.0075 * s, 0.026 * s, 0.0024 * s), (dx * s, -0.042 * s, bz), btn_m, bev=0.0016 * s,
                collection=collection)
        for k, (dx, c) in enumerate([(-0.012, (0.1, 0.45, 0.2)), (0.0, (0.55, 0.12, 0.12)), (0.012, (0.15, 0.3, 0.6))]):
            box(f"{prefix}_app{k}", (0.008 * s, 0.006 * s, 0.0016 * s), (dx * s, -0.068 * s, bz),
                principled(f"{prefix}_appm{k}", c, rough=0.4, coat=0.4), bev=0.0008 * s, collection=collection)
        ir = emission(f"{prefix}_ir_m", (1.0, 0.08, 0.04), 0.0)
        box(f"{prefix}_ir", (0.012 * s, 0.0016 * s, 0.006 * s), (0, 0.0838 * s, 0.0075 * s), ir, bev=0.0006 * s,
            collection=collection).visible_shadow = False
        REG.setdefault("remote_ir", {})[prefix] = ir.node_tree.nodes["Emission"].inputs["Strength"]
    _, objs = collect_new(build)
    root = empty(f"{prefix}_root", loc, collection, rot=rot)
    parent_all(objs, root)
    REG.setdefault("remote", {})[prefix] = keys
    anchor(prefix, Vector(loc) + Vector((0, 0, 0.02 * s)))
    return root


def press(prefix, key, depth):
    """depth 0..1: how far the button is pushed in (1 = 1.4 mm)."""
    ob, z0 = REG["remote"][prefix][key]
    ob.location.z = z0 - 0.0014 * depth


# ---------------------------------------------------------------- the museum case

def museum(center, collection, plaque_tex=None):
    c = Vector(center)
    plinth_m = principled("plinth", (0.025, 0.024, 0.023), rough=0.55, coat=0.15)
    box("plinth", (0.5, 0.5, 1.0), c + Vector((0, 0, 0.5)), plinth_m, bev=0.004, collection=collection)
    box("plinth_lip", (0.52, 0.52, 0.025), c + Vector((0, 0, 1.0125)), plinth_m, bev=0.004, collection=collection)
    felt = principled("felt", (0.06, 0.035, 0.03), rough=0.95, sheen=0.6)
    box("felt", (0.44, 0.44, 0.008), c + Vector((0, 0, 1.029)), felt, bev=0.002, collection=collection)
    # Glass hood: thin glass walls with a fresnel sheen, fine bronze edges.
    gm = bpy.data.materials.new("case_glass")
    nt = gm.node_tree
    nt.nodes.clear()
    lw = node(nt, "ShaderNodeLayerWeight", Blend=0.12)
    gl = nt.nodes.new("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.02
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lw.outputs["Fresnel"], mix.inputs["Fac"])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(mix.outputs[0], out.inputs[0])
    gm.surface_render_method = "BLENDED"
    gm.use_backface_culling = False
    S, Hc, z0 = 0.46, 0.46, 1.025
    for name, size, off in [("n", (S, 0.004, Hc), (0, S / 2, Hc / 2)), ("s", (S, 0.004, Hc), (0, -S / 2, Hc / 2)),
                            ("e", (0.004, S, Hc), (S / 2, 0, Hc / 2)), ("w", (0.004, S, Hc), (-S / 2, 0, Hc / 2)),
                            ("t", (S, S, 0.004), (0, 0, Hc))]:
        ob = box(f"case_{name}", size, c + Vector((0, 0, z0)) + Vector(off), gm, bev=0, collection=collection)
        ob.visible_shadow = False
    edge = principled("case_edge", (0.35, 0.25, 0.14), rough=0.3, metal=1.0)
    e = 0.006
    for sx in (-1, 1):
        for sy in (-1, 1):
            box(f"case_post{sx}{sy}", (e, e, Hc), c + Vector((sx * S / 2, sy * S / 2, z0 + Hc / 2)), edge, bev=0,
                collection=collection)
    for k, (size, off) in enumerate([((S, e, e), (0, S / 2, Hc)), ((S, e, e), (0, -S / 2, Hc)),
                                     ((e, S, e), (S / 2, 0, Hc)), ((e, S, e), (-S / 2, 0, Hc))]):
        box(f"case_top{k}", size, c + Vector((0, 0, z0)) + Vector(off), edge, bev=0, collection=collection)
    # A clear acrylic cradle holds the remote tilted towards the visitor.
    acr = principled("acrylic", (0.9, 0.95, 1.0), rough=0.05, alpha=0.25, spec=0.8)
    box("cradle_base", (0.1, 0.08, 0.008), c + Vector((0, 0.01, 1.037)), acr, bev=0.002, collection=collection)
    box("cradle_back", (0.07, 0.008, 0.11), c + Vector((0, 0.045, 1.09)), acr, bev=0.002, collection=collection,
        rot=(math.radians(-22), 0, 0))
    remote("mus_rm", c + Vector((0, 0.0, 1.125)), collection, rot=(math.radians(68), 0, 0), scale=1.0)
    anchor("case_top", c + Vector((0, 0, z0 + Hc)))
    anchor("mus_remote", c + Vector((0, 0.0, 1.12)))
    # Brass plaque on the plinth's front face.
    pm = principled("plaque_m", (0.55, 0.42, 0.22), rough=0.35, metal=1.0)
    if plaque_tex is not None and plaque_tex.exists():
        nt = pm.node_tree
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(plaque_tex))
        tex.interpolation = "Cubic"
        uvn = nt.nodes.new("ShaderNodeUVMap")
        nt.links.new(uvn.outputs[0], tex.inputs["Vector"])
        b = nt.nodes["Principled BSDF"]
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs[6].default_value = (0.62, 0.47, 0.25, 1)
        mix.inputs[7].default_value = (0.05, 0.035, 0.02, 1)
        nt.links.new(tex.outputs["Color"], mix.inputs["Factor"])
        nt.links.new(mix.outputs[2], b.inputs["Base Color"])
        rmix = nt.nodes.new("ShaderNodeMapRange")
        rmix.inputs["To Min"].default_value = 0.3
        rmix.inputs["To Max"].default_value = 0.7
        nt.links.new(tex.outputs["Color"], rmix.inputs["Value"])
        nt.links.new(rmix.outputs[0], b.inputs["Roughness"])
    box("plaque_back", (0.32, 0.006, 0.135), c + Vector((0, -0.253, 0.8)), plinth_m, bev=0.001, collection=collection)
    uv_plane("plaque", 0.3, 0.12, c + Vector((0, -0.2565, 0.8)), pm, (math.pi / 2, 0, 0), collection)
    anchor("plaque", c + Vector((0, -0.26, 0.8)))
