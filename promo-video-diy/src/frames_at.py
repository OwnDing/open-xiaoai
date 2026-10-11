"""Print global frame numbers for "SHOT:mark+offset" specs (for compositor stills)."""
import json
import sys
from pathlib import Path

tl = json.loads((Path(__file__).resolve().parents[1] / "build" / "timeline.json").read_text())
shots = {s["id"]: s for s in tl["shots"]}
out = []
for spec in sys.argv[1:]:
    sid, rest = spec.split(":")
    sign = "+" if "+" in rest else ("-" if "-" in rest else None)
    mark, off = (rest.split(sign) if sign else (rest, "0"))
    off = float(off) * (-1 if sign == "-" else 1)
    s = shots[sid]
    t = (s["marks"][mark] if mark not in ("", "start") else 0.0) + off
    out.append(str(s["start"] + round(t * tl["fps"])))
print(",".join(out))
