"""Assemble the whole set: the home, its props and threads, the sky, the studio,
and the render settings (2.39:1 plate, 24 fps, bloom + anamorphic streaks).
"""
import math
import random
from pathlib import Path

import bpy
from mathutils import Vector

import home
import props as Pr
import studio
from home import COFFEE, DESK, H, MINIPC_HOME, SPEAKER_HOME, STOVE, WASHER
from kit import REG, coll, light, node, set_group  # noqa: F401  (set_group re-exported for plates)

ROOT = Path(__file__).resolve().parents[2]
PLATE_W, PLATE_H = 1920, 800

# Where things are, for threads and cameras.
P_SPEAKER = SPEAKER_HOME + Vector((0, 0, 0.085))
P_PC = MINIPC_HOME + Vector((0.0, 0.0, 0.055))
P_BRAIN = MINIPC_HOME + Vector((0.0, 0.0, 0.32))
P_PENDANT = Vector((COFFEE.x, COFFEE.y, 2.05))
P_FLOOR = Vector((-2.85, 4.5, 1.62))
P_AC = Vector((0.05, 4.76, 2.24))
P_CURTAIN = Vector((2.0, 4.72, 1.9))
P_KIDCAM = None   # set in build (depends on the desk lamp)
P_KITCAM = Vector((7.86, 3.9, 2.32))
P_WASHER = Vector((7.3, WASHER.y, 0.9))
P_FRIDGE = Vector((7.55, 4.2, 1.45))
P_KITLAMP = Vector((5.55, 2.4, 1.78))
P_KIDLAMP = Vector((-5.25, 2.6, 2.55))
P_VACUUM = Vector((1.9, 1.6, 0.14))
DORM_CENTER = Vector((0.5, 2.5, -0.35))


# ---------------------------------------------------------------- world

def world_setup():
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    nt = w.node_tree
    bg = nt.nodes["Background"]
    out = nt.nodes["World Output"]
    bg.inputs["Color"].default_value = (0.006, 0.009, 0.018, 1)
    bg.inputs["Strength"].default_value = 1.0
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # Stars: tiny Voronoi points on the view direction.
    vor = node(nt, "ShaderNodeTexVoronoi", Scale=420.0, Randomness=1.0)
    nt.links.new(tc.outputs["Generated"], vor.inputs["Vector"])
    dot = nt.nodes.new("ShaderNodeMapRange")
    dot.inputs["From Min"].default_value = 0.06
    dot.inputs["From Max"].default_value = 0.0
    nt.links.new(vor.outputs["Distance"], dot.inputs["Value"])
    pick = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(vor.outputs["Color"], pick.inputs[0])
    few = nt.nodes.new("ShaderNodeMath")
    few.operation = "GREATER_THAN"
    few.inputs[1].default_value = 0.72
    nt.links.new(pick.outputs[0], few.inputs[0])
    sd = nt.nodes.new("ShaderNodeMath")
    sd.operation = "MULTIPLY"
    nt.links.new(dot.outputs[0], sd.inputs[0])
    nt.links.new(few.outputs[0], sd.inputs[1])
    stars = nt.nodes.new("ShaderNodeValue")
    stars.outputs[0].default_value = 0.0
    sk = nt.nodes.new("ShaderNodeMath")
    sk.operation = "MULTIPLY"
    nt.links.new(sd.outputs[0], sk.inputs[0])
    nt.links.new(stars.outputs[0], sk.inputs[1])
    se = nt.nodes.new("ShaderNodeEmission")
    se.inputs["Color"].default_value = (0.8, 0.88, 1.0, 1)
    nt.links.new(sk.outputs[0], se.inputs["Strength"])
    # Dawn: warm horizon band under a deep blue, by the direction's Z.
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    dr = nt.nodes.new("ShaderNodeValToRGB")
    Pr.ramp_colors(dr, [(0.0, (0.0, 0.0, 0.0)), (0.44, (0.0, 0.0, 0.0)), (0.49, (0.35, 0.12, 0.06)),
                        (0.515, (0.9, 0.42, 0.18)), (0.55, (0.32, 0.18, 0.3)), (0.66, (0.05, 0.07, 0.16)),
                        (1.0, (0.01, 0.015, 0.04))])
    zr = nt.nodes.new("ShaderNodeMapRange")
    zr.inputs["From Min"].default_value = -1.0
    zr.inputs["From Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], zr.inputs["Value"])
    nt.links.new(zr.outputs[0], dr.inputs["Fac"])
    dawn = nt.nodes.new("ShaderNodeValue")
    dawn.outputs[0].default_value = 0.0
    de = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(dr.outputs["Color"], de.inputs["Color"])
    nt.links.new(dawn.outputs[0], de.inputs["Strength"])
    a1 = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(bg.outputs[0], a1.inputs[0])
    nt.links.new(se.outputs[0], a1.inputs[1])
    a2 = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(a1.outputs[0], a2.inputs[0])
    nt.links.new(de.outputs[0], a2.inputs[1])
    nt.links.new(a2.outputs[0], out.inputs["Surface"])
    REG["world"] = bg
    REG["stars"] = stars.outputs[0]
    REG["dawn"] = dawn.outputs[0]
    REG["world_volume"] = (nt, out)
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
    sun = REG["objs"]["sun"]
    if day > 0.5:
        sun.data.energy = 6.5
        sun.data.color = (1.0, 0.7, 0.42)
        sun.data.angle = math.radians(1.0)
        d = Vector((-0.78, -0.55, -0.3)).normalized()
        sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        REG["objs"]["window_sky"].data.energy = 150
        REG["objs"]["window_sky"].data.color = (0.9, 0.92, 1.0)
    REG["city_day"].default_value = day


def haze(density, end=14.0, anisotropy=0.6):
    """Thin world fog so light beams read in the air."""
    nt, out = REG["world_volume"]
    v = nt.nodes.new("ShaderNodeVolumeScatter")
    v.inputs["Density"].default_value = density
    v.inputs["Anisotropy"].default_value = anisotropy
    nt.links.new(v.outputs[0], out.inputs["Volume"])
    REG["haze"] = v.inputs["Density"]
    sc = bpy.context.scene
    sc.eevee.volumetric_start = 0.05
    sc.eevee.volumetric_end = end
    sc.eevee.volumetric_tile_size = "4"
    sc.eevee.volumetric_samples = 64


# ---------------------------------------------------------------- render

def render_setup(res=1.0, samples=48):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = int(PLATE_W * res)
    sc.render.resolution_y = int(PLATE_H * res)
    sc.render.resolution_percentage = 100
    sc.render.fps = 24
    sc.eevee.taa_render_samples = samples
    sc.eevee.use_raytracing = True
    sc.eevee.ray_tracing_method = "SCREEN"
    sc.eevee.use_fast_gi = True
    sc.eevee.fast_gi_method = "GLOBAL_ILLUMINATION"
    sc.eevee.use_shadows = True
    sc.eevee.shadow_ray_count = 2
    sc.eevee.shadow_step_count = 8
    sc.eevee.shadow_pool_size = "2048"
    sc.eevee.volumetric_tile_size = "4"
    sc.eevee.volumetric_samples = 48
    sc.eevee.volumetric_end = 40.0
    sc.render.use_motion_blur = False
    sc.render.motion_blur_shutter = 0.5
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            pass
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 94
    # Compositor: bloom, horizontal anamorphic streaks, a touch of lens dispersion.
    ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
    ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    sc.compositing_node_group = ng
    rl = ng.nodes.new("CompositorNodeRLayers")
    bl = ng.nodes.new("CompositorNodeGlare")
    bl.inputs["Type"].default_value = "Bloom"
    bl.inputs["Quality"].default_value = "High"
    bl.inputs["Threshold"].default_value = 1.0
    bl.inputs["Strength"].default_value = 0.5
    bl.inputs["Size"].default_value = 0.8
    st = ng.nodes.new("CompositorNodeGlare")
    st.inputs["Type"].default_value = "Streaks"
    st.inputs["Quality"].default_value = "High"
    st.inputs["Threshold"].default_value = 3.0
    st.inputs["Streaks"].default_value = 2
    st.inputs["Streaks Angle"].default_value = 0.0
    st.inputs["Fade"].default_value = 0.93
    st.inputs["Strength"].default_value = 0.35
    st.inputs["Saturation"].default_value = 0.8
    st.inputs["Tint"].default_value = (0.65, 0.78, 1.0, 1.0)
    ld = ng.nodes.new("CompositorNodeLensdist")
    ld.inputs["Dispersion"].default_value = 0.01
    out = ng.nodes.new("NodeGroupOutput")
    ng.links.new(rl.outputs["Image"], bl.inputs["Image"])
    ng.links.new(bl.outputs["Image"], st.inputs["Image"])
    ng.links.new(st.outputs["Image"], ld.inputs["Image"])
    ng.links.new(ld.outputs["Image"], out.inputs[0])
    REG["bloom"] = bl
    REG["streaks"] = st


# Small decorative lights that never need to cast shadows.
NO_SHADOW = ("ringlight", "barlight", "_hl", "washer_drum_light", "flame_light", "dlamp_bounce", "kstrip")


def shadow_budget():
    """Keep the virtual shadow maps inside the pool: an overflowing pool drops a
    different set of shadow pages every frame, and lights and shadows flicker."""
    for ob in bpy.data.objects:
        if ob.type != "LIGHT":
            continue
        ld = ob.data
        if any(k in ob.name for k in NO_SHADOW):
            ld.use_shadow = False
        big = ld.type == "SUN" or (ld.type == "AREA" and max(ld.size, getattr(ld, "size_y", 0)) >= 1.0)
        ld.shadow_maximum_resolution = 0.02 if big else 0.006


def camera():
    cd = bpy.data.cameras.new("Cam")
    cd.sensor_width = 36
    cd.clip_start = 0.005
    cd.clip_end = 400
    cd.dof.use_dof = True
    cd.dof.aperture_blades = 7
    cd.dof.aperture_rotation = 0.3
    cd.dof.aperture_ratio = 1.25   # slightly oval bokeh, anamorphic feel
    ob = bpy.data.objects.new("Cam", cd)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    REG["cam"] = ob
    return ob


# ---------------------------------------------------------------- threads

def arc(a, b, lift, mid_shift=(0, 0, 0)):
    """Control points for a graceful arc from a to b."""
    a, b = Vector(a), Vector(b)
    m = (a + b) / 2 + Vector((0, 0, lift)) + Vector(mid_shift)
    return [a, a.lerp(m, 0.5) + Vector((0, 0, lift * 0.35)), m, b.lerp(m, 0.5) + Vector((0, 0, lift * 0.35)), b]


AMBER, ROSE, VIOLET = Pr.AMBER, Pr.ROSE, Pr.VIOLET


def home_threads():
    c = "threads_in"
    door_kid = Vector((-3.5, 0.75, 1.55))
    door_kit = Vector((3.5, 0.75, 1.6))
    # Voice in: speaker -> mini PC.
    Pr.thread("t_sp_pc", [P_SPEAKER, P_SPEAKER + Vector((-0.25, 0.1, 0.55)), Vector((-2.1, 3.25, 1.45)),
                          P_PC + Vector((0.45, 0.0, 0.35)), P_PC], AMBER, radius=0.004, collection=c, head_light=0.6)
    # Commands out: mini PC -> devices.
    Pr.thread("t_pc_pendant", [P_PC, P_PC + Vector((0.4, 0.05, 0.6)), Vector((-1.9, 3.1, 1.95)), P_PENDANT],
              ROSE, radius=0.0034, collection=c, head_light=0.4)
    Pr.thread("t_pc_floor", [P_PC, P_PC + Vector((0.25, 0.45, 0.45)), Vector((-2.95, 4.25, 1.5)), P_FLOOR],
              VIOLET, radius=0.0034, collection=c, head_light=0.4)
    Pr.thread("t_pc_ac", [P_PC, P_PC + Vector((0.5, 0.25, 0.8)), Vector((-1.4, 4.2, 2.35)), Vector((-0.5, 4.6, 2.3)),
                          P_AC], AMBER, radius=0.0034, collection=c, head_light=0.4)
    Pr.thread("t_pc_curtain", [P_PC, P_PC + Vector((0.6, 0.0, 0.9)), Vector((-0.8, 3.6, 2.3)), Vector((1.0, 4.4, 2.2)),
                               P_CURTAIN], ROSE, radius=0.0034, collection=c, head_light=0.4)
    Pr.thread("t_pc_sp", [P_PC, P_PC + Vector((0.45, 0.0, 0.35)), Vector((-2.1, 3.25, 1.45)),
                          P_SPEAKER + Vector((-0.25, 0.1, 0.55)), P_SPEAKER], VIOLET, radius=0.004, collection=c,
              head_light=0.5)
    # Laundry: washer -> through the kitchen doorway -> mini PC.
    Pr.thread("t_washer_pc", [P_WASHER, P_WASHER + Vector((-0.6, 0.0, 0.7)), Vector((5.6, 0.9, 1.8)), door_kit,
                              Vector((1.2, 1.6, 1.75)), Vector((-1.8, 2.9, 1.4)), P_PC], (0.45, 0.8, 1.0),
              radius=0.0035, collection=c, head_light=0.5)
    # Kitchen camera -> mini PC.
    Pr.thread("t_kitcam_pc", [P_KITCAM, P_KITCAM + Vector((-0.8, -0.6, -0.2)), Vector((5.2, 1.4, 1.9)), door_kit,
                              Vector((1.0, 1.7, 1.8)), Vector((-1.8, 2.9, 1.4)), P_PC], (1.0, 0.42, 0.25),
              radius=0.0035, collection=c, head_light=0.5)
    # Desk camera -> through the kid's doorway -> mini PC.
    Pr.thread("t_kidcam_pc", [P_KIDCAM, P_KIDCAM + Vector((0.2, -0.6, 0.35)), Vector((-4.3, 1.8, 1.7)), door_kid,
                              Vector((-2.8, 1.4, 1.5)), Vector((-2.6, 2.8, 1.1)), P_PC], AMBER,
              radius=0.0034, collection=c, head_light=0.4)


def diorama_threads():
    c = "threads_dio"
    hub = P_PC + Vector((0, 0, 0.1))
    targets = {
        "kidlamp": P_KIDLAMP, "kidcam": P_KIDCAM, "pendant": P_PENDANT, "floor": P_FLOOR, "ac": P_AC,
        "curtain": P_CURTAIN, "speaker": P_SPEAKER, "kitlamp": P_KITLAMP, "washer": P_WASHER, "fridge": P_FRIDGE,
        "kitcam": P_KITCAM, "vacuum": P_VACUUM,
    }
    cols = [AMBER, ROSE, VIOLET]
    for i, (k, p) in enumerate(targets.items()):
        dist = (Vector(p) - hub).length
        lift = 0.9 + 0.22 * dist
        Pr.thread(f"d_{k}", arc(hub, p, lift), cols[i % 3], radius=0.011, collection=c, head_size=0.03)
    REG["dio_targets"] = list(targets)
    # Upload streams: from every room up into the cloud deck (cold), and their reversed twins.
    rnd = random.Random(21)
    starts = [P_SPEAKER, P_KIDCAM, P_KITCAM, P_WASHER, P_FRIDGE, P_AC, P_KIDLAMP, P_PENDANT, P_KITLAMP,
              P_SPEAKER + Vector((0.3, -0.4, 0)), Vector((-5.5, 1.5, 0.6)), Vector((5.0, 1.2, 0.9))]
    ups = []
    for i, s in enumerate(starts):
        s = Vector(s)
        top = Vector((s.x * 1.25 + rnd.uniform(-1.5, 1.5), s.y + rnd.uniform(1.0, 4.0), 9.0))
        pts = [s, s + Vector((rnd.uniform(-0.3, 0.3), rnd.uniform(-0.2, 0.4), 1.6)),
               s.lerp(top, 0.5) + Vector((rnd.uniform(-0.8, 0.8), 0, 0)), top]
        Pr.thread(f"up{i}", pts, Pr.COLD, radius=0.009, collection="threads_up", head_size=0.028)
        Pr.thread(f"down{i}", list(reversed(pts)), (1.0, 0.6, 0.3), radius=0.009, collection="threads_up",
                  head_size=0.028)
        ups.append(i)
        Pr.anchor(f"up{i}_start", s)
    REG["ups"] = ups


# ---------------------------------------------------------------- build

def build(res=1.0, samples=48):
    global P_KIDCAM
    bpy.ops.wm.read_factory_settings(use_empty=True)
    random.seed(3)
    M = home.make_materials()
    home.walls(M)
    home.living_room(M)
    home.kid_room(M)
    home.kitchen(M)
    home.laundry(M)
    home.city_backdrop()
    # The DIY speaker and, for the pain shot, a typical cloud speaker in the same spot.
    Pr.pebble_speaker("sp", SPEAKER_HOME, "living_pebble", rot_z=math.radians(30))
    Pr.generic_speaker("gen", SPEAKER_HOME + Vector((-0.02, 0.0, 0.0)), "living_generic")
    Pr.mini_pc("pc", MINIPC_HOME, "apartment", rot_z=math.radians(90))
    Pr.brain("brain", P_BRAIN, 0.16, "apartment")
    Pr.anchor("brain", P_BRAIN)
    # Cameras: on the kitchen wall corner, and clipped to the desk lamp.
    Pr.security_camera("kitcam", P_KITCAM, STOVE, "apartment", scale=1.0)
    P_KIDCAM = REG["desk_cam_pos"]
    Pr.security_camera("kidcam", P_KIDCAM, DESK + Vector((-0.05, -0.12, 0)), "apartment", scale=0.6, white=False)
    Pr.flame("flame", STOVE + Vector((0, 0, 0.022)), 0.05)
    Pr.steam("steam", STOVE + Vector((0, 0, 0.12)), 0.75, 0.16)
    tex = ROOT / "build" / "textures" / "worksheet.png"
    if tex.exists():
        Pr.worksheet("worksheet", DESK + Vector((-0.08, -0.08, 0.0012)), (0.21, 0.297), tex,
                     rot_z=math.radians(-6))
        Pr.anchor("worksheet", DESK + Vector((-0.08, -0.08, 0.0)))
        # Corners of problem 3 and its picture, from the texture layout (u right, v down).
        import json as _json
        lay = _json.loads((ROOT / "build" / "textures" / "worksheet.json").read_text())
        ctr, rz = DESK + Vector((-0.08, -0.08, 0.0015)), math.radians(-6)
        for key in ("p3", "apples"):
            u0, v0, u1, v1 = lay[key]
            for tag, (u, v) in {"tl": (u0, v0), "tr": (u1, v0), "bl": (u0, v1), "br": (u1, v1)}.items():
                lx, ly = (u - 0.5) * 0.21, (0.5 - v) * 0.297
                Pr.anchor(f"ws_{key}_{tag}", ctr + Vector((lx * math.cos(rz) - ly * math.sin(rz),
                                                           lx * math.sin(rz) + ly * math.cos(rz), 0)))
    from kit import box
    box("pencil", (0.006, 0.16, 0.006), DESK + Vector((0.07, -0.14, 0.004)), M["toy"][2], bev=0.002,
        rot=(0, 0, math.radians(25)))
    box("eraser", (0.04, 0.022, 0.012), DESK + Vector((0.1, 0.02, 0.006)), M["white_plastic"], bev=0.003,
        rot=(0, 0, 0.4))
    home_threads()
    diorama_threads()
    Pr.dome("dome", DORM_CENTER, (11.0, 7.0, 5.5))
    Pr.cloud("cloud", (0.5, 4.0, 10.2), (34, 26, 3.2))
    Pr.server_lights("servers", (0.5, 4.0, 9.0), 46, 30, 0.55)
    studio.build()
    world_setup()
    render_setup(res, samples)
    shadow_budget()
    camera()
    # Lamp shades and bulbs glow; they must not trap their own light.
    for ob in bpy.data.objects:
        if ob.type == "MESH" and any(m and m.name in REG.get("glow_mats", ()) for m in ob.data.materials):
            ob.visible_shadow = False
    return M
