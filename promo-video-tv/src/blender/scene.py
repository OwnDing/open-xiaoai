"""Assemble the whole set: the living room with its TV, the speakers, the mini PC,
the remote, the voice threads, the studio sets, and the render settings
(2.39:1 plate, 24 fps, bloom + anamorphic streaks).
"""
import math
import random
from pathlib import Path

import bpy
from mathutils import Vector

import props as Pr
import room
import studio
import tvset
from kit import REG, light, node
from room import MINIPC, REMOTE, SPEAKER, TV_CENTER, TV_H, TV_W

ROOT = Path(__file__).resolve().parents[2]
PLATE_W, PLATE_H = 1920, 800

P_SPEAKER = SPEAKER + Vector((0, 0, 0.085))
P_GENERIC = SPEAKER + Vector((0, 0, 0.19))
P_PC = MINIPC + Vector((0.0, 0.0, 0.05))
P_BRAIN = MINIPC + Vector((0.0, 0.0, 0.3))
P_TV = TV_CENTER + Vector((0, -0.01, 0))
P_LED = TV_CENTER + Vector((0, -0.003, -TV_H / 2 - 0.004))
AMBER, ROSE, VIOLET = Pr.AMBER, Pr.ROSE, Pr.VIOLET
IR = (1.0, 0.12, 0.08)


# ---------------------------------------------------------------- world

def world_setup():
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.004, 0.006, 0.012, 1)
    bg.inputs["Strength"].default_value = 1.0
    REG["world"] = bg


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
    ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
    ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    sc.compositing_node_group = ng
    rl = ng.nodes.new("CompositorNodeRLayers")
    bl = ng.nodes.new("CompositorNodeGlare")
    bl.inputs["Type"].default_value = "Bloom"
    bl.inputs["Quality"].default_value = "High"
    bl.inputs["Threshold"].default_value = 1.0
    bl.inputs["Strength"].default_value = 0.45
    bl.inputs["Size"].default_value = 0.8
    st = ng.nodes.new("CompositorNodeGlare")
    st.inputs["Type"].default_value = "Streaks"
    st.inputs["Quality"].default_value = "High"
    st.inputs["Threshold"].default_value = 3.0
    st.inputs["Streaks"].default_value = 2
    st.inputs["Streaks Angle"].default_value = 0.0
    st.inputs["Fade"].default_value = 0.93
    st.inputs["Strength"].default_value = 0.3
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
NO_SHADOW = ("ringlight", "barlight", "_hl", "console_light", "slat_light", "tlamp")


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


# ---------------------------------------------------------------- threads in the room

def room_threads():
    c = "threads_room"
    Pr.thread("t_sp_pc", [P_SPEAKER, P_SPEAKER + Vector((0.02, 0.12, 0.45)), Vector((0.55, 4.0, 1.25)),
                          P_PC + Vector((-0.05, -0.25, 0.4)), P_PC], AMBER, radius=0.004, collection=c, head_light=0.5)
    Pr.thread("t_pc_tv", [P_PC, P_PC + Vector((-0.05, -0.12, 0.3)), Vector((0.5, 5.25, 1.25)),
                          P_TV + Vector((0.25, -0.12, 0.05)), P_TV], VIOLET, radius=0.004, collection=c, head_light=0.4)
    Pr.thread("t_ir", [P_SPEAKER + Vector((0, 0.02, 0.0)), P_SPEAKER.lerp(P_LED, 0.5) + Vector((0, 0, 0.12)), P_LED],
              IR, radius=0.0022, collection=c, head_light=0.25)
    Pr.thread("t_gen_ir", [P_GENERIC + Vector((0, 0.02, 0.0)), P_GENERIC.lerp(P_LED, 0.5) + Vector((0, 0, 0.1)), P_LED],
              IR, radius=0.0022, collection=c, head_light=0.25)


# ---------------------------------------------------------------- build

def build(res=1.0, samples=48):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    random.seed(3)
    M = room.make_materials()
    room.build(M)
    tvset.tv("tv", TV_CENTER, TV_W, TV_H, "room")
    tvset.remote("rm", REMOTE, "room", rot=(0, 0, math.radians(-28)))
    Pr.pebble_speaker("sp", SPEAKER, "living_pebble", rot_z=math.radians(30))
    Pr.generic_speaker("gen", SPEAKER, "living_generic")
    Pr.mini_pc("pc", MINIPC, "room", rot_z=0.0)
    Pr.brain("brain", P_BRAIN, 0.13, "room")
    from kit import anchor
    anchor("brain", P_BRAIN)
    room_threads()
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
