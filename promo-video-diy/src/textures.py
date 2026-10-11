"""Bitmaps used inside the 3D scene: the kid's maths worksheet.

Writes build/textures/worksheet.png (A4 portrait, 1240 x 1754). Problem 3 is
left blank; problems 1 and 2 have pencil answers. Its layout (problem 3's box,
in 0..1 page coordinates) is written to build/textures/worksheet.json for the
compositor's detection frame.
"""
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "textures"
PINGFANG = ("/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
            "86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc")
W, H = 1240, 1754


def font(size, weight="Regular"):
    idx = {"Regular": 3, "Medium": 7, "Semibold": 11, "Light": 15}[weight]
    return ImageFont.truetype(PINGFANG, size, index=idx)


def apple(d, cx, cy, r, rnd, color=(206, 46, 40)):
    d.ellipse([cx - r, cy - r * 0.92, cx + r, cy + r * 0.95], fill=color, outline=(120, 25, 20), width=3)
    d.ellipse([cx - r * 0.55, cy - r * 0.6, cx - r * 0.2, cy - r * 0.25], fill=(240, 120, 110))
    d.line([cx, cy - r * 0.85, cx + r * 0.1, cy - r * 1.3], fill=(90, 60, 30), width=5)
    d.ellipse([cx + r * 0.1, cy - r * 1.35, cx + r * 0.6, cy - r * 1.1], fill=(70, 150, 60), outline=(40, 90, 35),
              width=2)


def pencil_text(img, xy, s, size, rnd):
    """Child's pencil writing: grey, slightly wobbly, soft."""
    layer = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(layer)
    x, y = xy
    f = font(size, "Regular")
    for ch in s:
        d.text((x + rnd.uniform(-2, 2), y + rnd.uniform(-3, 3)), ch, font=f, fill=200)
        x += f.getlength(ch) * rnd.uniform(0.95, 1.08)
    layer = layer.filter(ImageFilter.GaussianBlur(0.8))
    grey = Image.new("RGB", img.size, (70, 70, 78))
    img.paste(grey, (0, 0), layer)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(2)
    img = Image.new("RGB", (W, H), (250, 248, 242))
    d = ImageDraw.Draw(img)
    # Paper tooth.
    for _ in range(9000):
        x, y = rnd.randrange(W), rnd.randrange(H)
        g = rnd.randint(232, 246)
        d.point((x, y), fill=(g, g - 2, g - 8))
    # Header band.
    d.rectangle([70, 70, W - 70, 210], fill=(226, 238, 248))
    d.text((110, 92), "一年级数学 · 看图列算式", font=font(58, "Semibold"), fill=(40, 60, 95))
    d.text((W - 470, 112), "姓名：", font=font(38), fill=(60, 70, 90))
    d.line([W - 360, 158, W - 110, 158], fill=(120, 130, 150), width=3)
    pencil_text(img, (W - 340, 102), "小宇", 46, rnd)

    def problem_title(n, y, s):
        d.ellipse([90, y, 150, y + 60], fill=(40, 60, 95))
        d.text((108, y + 4), str(n), font=font(42, "Semibold"), fill=(255, 255, 255))
        d.text((175, y + 2), s, font=font(42, "Medium"), fill=(35, 40, 50))

    def answer_boxes(y, filled=None):
        x = 200
        f = font(60, "Regular")
        for k, sym in enumerate(["", "+", "", "=", ""]):
            if sym:
                d.text((x + 10, y + 8), sym, font=f, fill=(35, 40, 50))
                x += 80
            else:
                d.rectangle([x, y, x + 110, y + 100], outline=(70, 80, 100), width=4)
                if filled:
                    pencil_text(img, (x + 32, y + 10), filled[k // 2], 66, rnd)
                x += 140

    # Problem 1: 2 + 3 apples.
    y = 270
    problem_title(1, y, "一共有几个苹果？")
    for k in range(2):
        apple(d, 260 + k * 110, y + 190, 42, rnd)
    d.text((500, y + 150), "+", font=font(70), fill=(35, 40, 50))
    for k in range(3):
        apple(d, 640 + k * 110, y + 190, 42, rnd)
    answer_boxes(y + 290, ["2", "3", "5"])
    # Problem 2: pears.
    y = 720
    problem_title(2, y, "盘子里一共有几个梨？")
    for k in range(4):
        cx, cy = 260 + k * 100, y + 190
        d.ellipse([cx - 32, cy - 20, cx + 32, cy + 48], fill=(232, 200, 70), outline=(150, 120, 30), width=3)
        d.ellipse([cx - 22, cy - 55, cx + 22, cy + 5], fill=(232, 200, 70), outline=(150, 120, 30), width=3)
    d.text((690, y + 150), "+", font=font(70), fill=(35, 40, 50))
    for k in range(2):
        cx, cy = 820 + k * 100, y + 190
        d.ellipse([cx - 32, cy - 20, cx + 32, cy + 48], fill=(232, 200, 70), outline=(150, 120, 30), width=3)
        d.ellipse([cx - 22, cy - 55, cx + 22, cy + 5], fill=(232, 200, 70), outline=(150, 120, 30), width=3)
    answer_boxes(y + 290, ["4", "2", "6"])
    # Problem 3: apples on the tree and on the grass -- blank, with an erased attempt.
    y = 1170
    p3_top = y - 20
    problem_title(3, y, "树上有 4 个苹果，地上有 3 个，一共有几个？")
    d.ellipse([200, y + 80, 620, y + 300], fill=(120, 175, 95), outline=(70, 120, 60), width=4)
    d.rectangle([390, y + 290, 430, y + 400], fill=(130, 90, 55))
    for k, (ax, ay) in enumerate([(290, y + 170), (380, y + 130), (470, y + 190), (540, y + 150)]):
        apple(d, ax, ay, 32, rnd)
    d.line([160, y + 400, 1080, y + 400], fill=(110, 160, 80), width=5)
    for k in range(3):
        apple(d, 700 + k * 100, y + 365, 32, rnd)
    answer_boxes(y + 430)
    # Faint erased scribble in the first box.
    smudge = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(smudge)
    sd.text((230, y + 438), "4", font=font(66), fill=60)
    smudge = smudge.filter(ImageFilter.GaussianBlur(3))
    img.paste(Image.new("RGB", img.size, (150, 150, 160)), (0, 0), smudge)
    p3_bottom = y + 560
    img.save(OUT / "worksheet.png")
    (OUT / "worksheet.json").write_text(json.dumps({
        "p3": [70 / W, p3_top / H, (W - 70) / W, p3_bottom / H],
        "apples": [170 / W, (y + 90) / H, 1090 / W, (y + 410) / H],
    }))
    print("worksheet ->", OUT / "worksheet.png")


if __name__ == "__main__":
    main()
