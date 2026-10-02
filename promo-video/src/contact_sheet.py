"""Tile images into a labelled contact sheet: contact_sheet.py out.jpg cols width img..."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out, cols, w = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
files = sys.argv[4:]
h = w * 9 // 16
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * (h + 22)), (20, 20, 20))
font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB").resize((w, h))
    x, y = (i % cols) * w, (i // cols) * (h + 22)
    sheet.paste(im, (x, y + 22))
    d.text((x + 4, y + 3), Path(f).stem, fill=(230, 230, 230), font=font)
sheet.save(out, quality=88)
