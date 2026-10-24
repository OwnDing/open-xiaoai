"""Mean linear colour of every rendered screen frame: the light each TV throws into the room.

Writes build/screens/<plate>/<screen>/light.json: one [r, g, b, on] per frame (on = the screen is not black).
  screen_light.py [P01 P05 ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def main(plates):
    base = ROOT / "build" / "screens"
    for pdir in sorted(base.iterdir()):
        if plates and pdir.name not in plates:
            continue
        for sdir in sorted(d for d in pdir.iterdir() if d.is_dir()):
            out = []
            for f in sorted(sdir.glob("*.jpg")):
                im = Image.open(f)
                im.draft("RGB", (240, 135))
                a = linear(np.asarray(im.convert("RGB"), np.float32) / 255.0)
                m = a.reshape(-1, 3).mean(axis=0)
                out.append([round(float(x), 5) for x in m] + [1 if float(m.max()) > 0.002 else 0])
            (sdir / "light.json").write_text(json.dumps(out))
            print(f"{pdir.name}/{sdir.name}: {len(out)} frames")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
