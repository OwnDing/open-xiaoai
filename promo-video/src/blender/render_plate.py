"""Render one plate (or a look-dev still) with Blender in the background.

  blender -b --factory-startup -P src/blender/render_plate.py -- P03
  blender -b --factory-startup -P src/blender/render_plate.py -- P03 --still 2.5 --res 0.5

Frames go to build/plates/<plate>/####.jpg (existing frames are skipped, so an
interrupted render resumes), and the screen positions of named 3D anchors to
build/plates/<plate>/anchors.json for the compositor's labels.
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

    def frame_time(f):
        return (f - 1 - handle) / fps

    def on_frame(scene, depsgraph=None):
        update(frame_time(scene.frame_current + scene.frame_subframe))

    if a.still:
        out = Path(a.out) if a.out else ROOT / "build" / "lookdev"
        out.mkdir(parents=True, exist_ok=True)
        for t in a.still:
            update(t)
            sc.render.filepath = str(out / f"{a.plate}_{t:05.2f}.jpg")
            bpy.ops.render.render(write_still=True)
        return

    out = Path(a.out) if a.out else ROOT / "build" / "plates" / a.plate
    out.mkdir(parents=True, exist_ok=True)
    if not a.no_anchors:
        cam = S.REG["cam"]
        anchors = {}
        for f in range(sc.frame_start, sc.frame_end + 1):
            update(frame_time(f))
            bpy.context.view_layer.update()
            row = {}
            for name, co in S.REG["anchors"].items():
                v = world_to_camera_view(sc, cam, co)
                row[name] = [round(v.x, 4), round(1 - v.y, 4), round(v.z, 3)]
            row["_lens"] = round(cam.data.lens, 2)
            anchors[f] = row
        (out / "anchors.json").write_text(json.dumps(anchors))
        if a.anchors_only:
            return
    if a.frames:
        sc.frame_start, sc.frame_end = a.frames
    sc.frame_step = a.step
    bpy.app.handlers.frame_change_pre.append(on_frame)
    sc.render.filepath = str(out / "####")
    sc.render.use_overwrite = False
    sc.render.use_placeholder = True
    bpy.ops.render.render(animation=True)


main()
