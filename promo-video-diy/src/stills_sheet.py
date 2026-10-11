"""Tile compositor stills into a labelled sheet: stills_sheet.py DIR OUT [cols]."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

src, out = Path(sys.argv[1]), Path(sys.argv[2])
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 3
fs = sorted(src.glob("f*.jpg"))
tw, th = 640, 360
rows = (len(fs) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 24)), (30, 30, 30))
d = ImageDraw.Draw(sheet)
font = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 18)
for i, f in enumerate(fs):
    x, y = (i % cols) * tw, (i // cols) * (th + 24)
    sheet.paste(Image.open(f).resize((tw, th)), (x, y + 24))
    d.text((x + 6, y + 2), f.stem, font=font, fill=(220, 220, 220))
sheet.save(out, quality=88)
print(out, len(fs))
