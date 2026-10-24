"""Bitmaps used inside the 3D scene: the museum plaque for the retired remote.

Writes build/textures/plaque.png (white = engraved letters, black = polished brass).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "textures"
PINGFANG = ("/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
            "86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc")
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"


def font(size, weight="Regular"):
    try:
        idx = {"Regular": 3, "Medium": 7, "Semibold": 11, "Light": 15}[weight]
        return ImageFont.truetype(PINGFANG, size, index=idx)
    except OSError:
        return ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", size)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    W, H = 1500, 600
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, W - 24, H - 24], outline=255, width=6)
    d.rectangle([44, 44, W - 44, H - 44], outline=160, width=2)

    def centered(y, s, f, fill=255):
        w = d.textlength(s, font=f)
        d.text(((W - w) / 2, y), s, font=f, fill=fill)
    centered(92, "电视遥控器", font(150, "Semibold"))
    centered(300, "服役  1956 — 2026", font(80, "Medium"))
    centered(430, "光荣退休  ·  由小七接班", font(64, "Regular"), fill=210)
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    img.save(OUT / "plaque.png")
    print("plaque ->", OUT / "plaque.png")


if __name__ == "__main__":
    main()
