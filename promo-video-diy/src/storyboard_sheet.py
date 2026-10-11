"""One frame per shot from the finished film, tiled with the shot descriptions."""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
video, out = sys.argv[1], sys.argv[2]
tl = json.loads((ROOT / "build" / "timeline.json").read_text())
fps = tl["fps"]
TITLES = {
    "S01": "序 · 黑暗中的耳朵", "S02": "一句话点亮全屋", "S03": "片名 · 家的大脑", "S04": "痛点 01 · 不够聪明",
    "S05": "痛点 02 · 各自为政", "S06": "痛点 03 · 没有秘密", "S07": "三道坎", "S08": "转折 · 大脑住在家里",
    "S09": "DIY · 两样东西", "S10": "① 带麦克风的音箱", "S11": "② 常开的 mini PC", "S12": "开源软件栈",
    "S13": "声音不出家门", "S14": "听得懂意思", "S15": "不同品牌一起联动", "S16": "一句话教会规矩",
    "S17": "扩展 · 看见危险", "S18": "扩展 · 陪写作业", "S19": "愿景", "S20": "片尾",
}
W, H, cols = 480, 270, 4
font = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 20)
shots = tl["shots"]
rows = (len(shots) + cols - 1) // cols
sheet = Image.new("RGB", (cols * W, rows * (H + 34)), (14, 14, 18))
d = ImageDraw.Draw(sheet)
for i, s in enumerate(shots):
    mid = (s["start"] + s["frames"] * 0.6) / fps
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{mid:.3f}", "-i", video, "-frames:v", "1",
                          "-vf", f"scale={W}:{H}", "-f", "image2pipe", "-c:v", "png", "-"],
                         check=True, capture_output=True).stdout
    from io import BytesIO
    im = Image.open(BytesIO(png)).convert("RGB")
    x, y = (i % cols) * W, (i // cols) * (H + 34)
    sheet.paste(im, (x, y + 34))
    d.text((x + 8, y + 6), f"{s['id']}  {s['start'] / fps:5.1f}s  {TITLES.get(s['id'], '')}", fill=(235, 235, 235), font=font)
sheet.save(out, quality=90)
print("->", out)
