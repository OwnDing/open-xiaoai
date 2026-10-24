"""Tile images into one labelled sheet: sheet.py OUT [cols] FILES..."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out, cols = Path(sys.argv[1]), int(sys.argv[2])
files = [Path(f) for f in sys.argv[3:]]
tw = 640
ims = [Image.open(f).convert("RGB") for f in files]
th = int(tw * ims[0].height / ims[0].width)
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 26)), (40, 40, 40))
d = ImageDraw.Draw(sheet)
font = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 18)
for i, (f, im) in enumerate(zip(files, ims)):
    x, y = (i % cols) * tw, (i // cols) * (th + 26)
    sheet.paste(im.resize((tw, th)), (x, y + 26))
    d.text((x + 6, y + 3), f.stem, font=font, fill=(230, 230, 230))
sheet.save(out, quality=88)
print(out, len(ims))
