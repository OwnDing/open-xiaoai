"""Tile look-dev stills into one labelled sheet: contact_sheet.py DIR OUT "P01:1,6" ..."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

src, out = Path(sys.argv[1]), Path(sys.argv[2])
files = []
for spec in sys.argv[3:]:
    p, times = spec.split(":")
    for t in times.split(","):
        f = src / f"{p}_{float(t):05.2f}.jpg"
        if f.exists():
            files.append((f"{p} {float(t):.2f}s", f))
cols = 3 if len(files) > 4 else 2
tw = 640
ims = [Image.open(f) for _, f in files]
th = int(tw * ims[0].height / ims[0].width) if ims else 100
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 28)), (20, 20, 20))
d = ImageDraw.Draw(sheet)
font = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 20)
for i, ((label, _), im) in enumerate(zip(files, ims)):
    x, y = (i % cols) * tw, (i // cols) * (th + 28)
    sheet.paste(im.resize((tw, th)), (x, y + 28))
    d.text((x + 8, y + 2), label, font=font, fill=(230, 230, 230))
sheet.save(out, quality=88)
print(out, len(files), "stills")
