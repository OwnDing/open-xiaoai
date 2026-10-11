"""Render a full-frame cover background (no letterbox) from the vision plate.

  blender -b --factory-startup -P src/cover/render_bg.py -- --w 1920 --h 1080 --t 8.6 --out build/cover/bg_16x9.png
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "blender"))

import plates as P  # noqa: E402
import scene as S  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
ap = argparse.ArgumentParser()
ap.add_argument("--w", type=int, default=1920)
ap.add_argument("--h", type=int, default=1080)
ap.add_argument("--t", type=float, default=8.6)
ap.add_argument("--plate", default="P19")
ap.add_argument("--shift", type=float, default=0.0, help="horizontal lens shift (moves the subject sideways)")
ap.add_argument("--lens", type=float, default=0.0, help="override the focal length (0 = keep)")
ap.add_argument("--shift_y", type=float, default=0.0)
ap.add_argument("--out", required=True)
a = ap.parse_args(argv)

tl = json.loads((ROOT / "build" / "timeline.json").read_text())
meta = json.loads((ROOT / "build" / "audio" / "voice" / "meta.json").read_text())
S.build(res=1.0, samples=96)
update = P.PLATES[a.plate](P.Ctx(tl["plates"][a.plate], meta, tl["fps"], tl["handle"]))
update(a.t)
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y = a.w, a.h
sc.render.image_settings.file_format = "PNG"
cam = sc.camera.data
cam.shift_x = a.shift
cam.shift_y = a.shift_y
if a.lens:
    cam.lens = a.lens
sc.render.filepath = str(ROOT / a.out)
bpy.ops.render.render(write_still=True)
