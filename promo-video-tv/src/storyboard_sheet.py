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
    "S01": "序 · 黑暗中的遥控器", "S02": "一句话，电视醒了", "S03": "片名 · 遥控器退休了", "S04": "痛点 01 · 只会开关",
    "S05": "痛点 02 · 按了 37 下", "S06": "痛点 03 · 各说各话", "S07": "三道坎", "S08": "转折 · 电视交给小七",
    "S09": "三样东西", "S10": "小七的眼睛", "S11": "小七的手", "S12": "链路 · 局域网",
    "S13": "慢放那一句", "S14": "播放中随时说", "S15": "音乐 App · 一步步点", "S16": "浏览器 · 一次输完",
    "S17": "关电视", "S18": "遥控器退休", "S19": "片尾",
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
