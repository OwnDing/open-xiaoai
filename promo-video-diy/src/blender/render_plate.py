"""Render one plate (or look-dev stills) with Blender in the background.

  blender -b --factory-startup -P src/blender/render_plate.py -- P06
  blender -b --factory-startup -P src/blender/render_plate.py -- P06 --still 2.5 --still 9 --res 0.5

Frames go to build/plates/<plate>/####.jpg (existing frames are skipped, so an
interrupted render resumes). The screen positions of named 3D anchors, plus
per-frame flags set by the plate (e.g. "pov"), go to anchors.json for the
compositor's labels.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import plates as P  # noqa: E402
import scene as S  # noqa: E402
from kit import REG  # noqa: E402


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("plate")
    ap.add_argument("--still", type=float, action="append")
    ap.add_argument("--res", type=float)
    ap.add_argument("--samples", type=int)
    ap.add_argument("--out")
    ap.add_argument("--no-anchors", action="store_true")
    ap.add_argument("--anchors-only", action="store_true")
    ap.add_argument("--frames", nargs=2, type=int, help="render only this inclusive frame range")
    ap.add_argument("--step", type=int, default=1, help="render every Nth frame (proxies)")
    ap.add_argument("--blur", type=int, choices=(0, 1), help="force motion blur off/on")
    a = ap.parse_args(argv)

    tl = json.loads((ROOT / "build" / "timeline.json").read_text())
    meta = json.loads((ROOT / "build" / "audio" / "voice" / "meta.json").read_text())
    fps, handle = tl["fps"], tl["handle"]
    plate = tl["plates"][a.plate]
    res = a.res or (0.5 if a.plate in P.HALF_RES else 1.0)
    samples = a.samples or (24 if a.plate in P.HALF_RES else 48)

    S.build(res=res, samples=samples)
    ctx = P.Ctx(plate, meta, fps, handle)
    update = P.PLATES[a.plate](ctx)
    sc = bpy.context.scene
    sc.frame_start = 1
    sc.frame_end = plate["frames"] + 2 * handle
    blur = a.plate in P.MOTION_BLUR if a.blur is None else bool(a.blur)
    sc.render.use_motion_blur = blur
    sc.eevee.motion_blur_steps = 1

    def frame_time(f):
        return (f - 1 - handle) / fps

    def on_frame(scene, depsgraph=None):
        update(frame_time(scene.frame_current + scene.frame_subframe))

    bpy.app.handlers.frame_change_pre.append(on_frame)

    if a.still:
        out = Path(a.out) if a.out else ROOT / "build" / "lookdev"
        out.mkdir(parents=True, exist_ok=True)
        for t in a.still:
            f = t * fps + 1 + handle
            sc.frame_set(int(f), subframe=f - int(f))
            sc.render.filepath = str(out / f"{a.plate}_{t:05.2f}.jpg")
            bpy.ops.render.render(write_still=True)
        return

    out = Path(a.out) if a.out else ROOT / "build" / "plates" / a.plate
    out.mkdir(parents=True, exist_ok=True)
    if not a.no_anchors:
        cam = REG["cam"]
        anchors = {}
        for f in range(sc.frame_start, sc.frame_end + 1):
            sc.frame_set(f)
            bpy.context.view_layer.update()
            row = {}
            for name, co in REG["anchors"].items():
                v = world_to_camera_view(sc, cam, co)
                row[name] = [round(v.x, 4), round(1 - v.y, 4), round(v.z, 3)]
            row["_lens"] = round(cam.data.lens, 2)
            if REG.get("flags"):
                row["_flags"] = dict(REG["flags"])
            anchors[f] = row
        (out / "anchors.json").write_text(json.dumps(anchors))
        if a.anchors_only:
            return
    if a.frames:
        sc.frame_start, sc.frame_end = a.frames
    sc.frame_step = a.step
    sc.render.filepath = str(out / "####")
    sc.render.use_overwrite = False
    sc.render.use_placeholder = True
    bpy.ops.render.render(animation=True)


main()
