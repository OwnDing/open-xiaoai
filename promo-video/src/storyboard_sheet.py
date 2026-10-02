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
    "S01": "开场 · 夜晚客厅", "S02": "它，真的懂你吗？", "S03": "痛点 01 · 听不懂", "S04": "痛点 02 · 没记忆",
    "S05": "痛点 03 · 设备割裂", "S06": "痛点汇总 · 塌缩", "S07": "转折 · 换一颗 AI 大脑", "S08": "原小爱保留 + 唤醒小七",
    "S09": "原理 · 链路架构", "S10": "同一句话，它听懂了", "S11": "一句话跨品牌控制", "S12": "三天前 · 记住偏好",
    "S13": "今晚 · 睡觉模式", "S14": "能力蒙太奇", "S15": "收尾 · 懂你的家", "S16": "片尾",
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
