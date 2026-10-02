# Open-XiaoAI 宣传片

《小爱，换个大脑》——约 2 分 11 秒的宣传片，讲清楚三件事：原生小爱哪里不够用；
接入自定义大模型（Hermes Agent）后，对话变聪明、有了记忆；通过 Home Assistant
统一控制米家和其他品牌设备，而原来的小爱功能全部保留。

| 文件 | 内容 |
|---|---|
| [`storyboard.md`](storyboard.md) | 分镜脚本：创意、视听风格、结构、逐镜头分镜表、台词总表 |
| `output/open-xiaoai-promo.mp4` | 成片（1920×1080 · 30fps · H.264 + AAC，-15 LUFS） |
| `output/storyboard_frames.jpg` | 从成片截取的每个镜头的代表帧 |
| `output/cover.jpg` | 封面 |
| [`../docs/ai-promo-video-guide.md`](../docs/ai-promo-video-guide.md) | 制作全记录：原始提示词、AI 的制作流程、可复用的方法 |
| `src/` | 全部源码：配音、时间线、Blender 场景、合成器、配乐与音效 |
| `scripts/` | 渲染与成片脚本 |

所有画面、配乐、音效都由本目录的代码生成，没有使用外部素材。代码由 Claude Opus 5.5 在 Claude Code 中编写。

## 制作流程

```text
src/lines.json ──src/tts.py──▶ build/audio/voice/*.wav + meta.json（时长、逐字时间、音量包络）
                                   │
                                   ▼
                           src/timeline.py ──▶ build/timeline.json（镜头起止帧、台词入点、动作标记）
                                   │
      ┌────────────────────────────┼─────────────────────────────┐
      ▼                            ▼                             ▼
src/blender/                 src/audio/                     src/compositor/
  scene.py   三居室剖面屋、     synth.py  合成器与音效          comp.js   字幕、对话气泡、设备胶囊、
             音箱、摄影棚       score.py  原创配乐                        架构图、遮幅、调色、转场
  plates.py  每个镜头的机位、   mix.py    配音 + 音效 + 配乐      render.mjs 无头 Edge 逐帧截图 → ffmpeg
             灯光和光环动画               （人声闪避）
  → build/plates/Pxx/*.jpg     → build/audio/mix.wav          → build/video.mp4
      + anchors.json（3D 锚点的屏幕坐标，给标签定位）
                                   │
                                   ▼
                     scripts/make_video.sh ──▶ output/open-xiaoai-promo.mp4
```

- **时间由配音驱动**：先合成配音，再用真实时长排时间线；3D 动画、字幕逐字出现、
  光环随声音起伏、音效和配乐的重拍都读同一份 `timeline.json`，因此天然对齐。
- **音箱光环**是全片的视觉主线：原生小爱为冷白色，AI「小七」为琥珀→紫色流动渐变，
  听、想、说三种状态分别对应常亮、加速旋转和随音量起伏。
- **设备标签跟随 3D 物体**：渲染时导出锚点投影坐标，合成器据此放置胶囊和引线。

## 环境

- Blender 5.2（EEVEE）、ffmpeg、Node.js、Microsoft Edge（或 Chrome，设置 `CHROME=` 路径）
- Python 3.9+：`python3 -m venv .venv && .venv/bin/pip install numpy scipy pillow edge-tts`
- 合成器依赖：`cd src/compositor && npm install`

配音使用微软 Edge 在线神经网络语音（`edge-tts`，需要联网）：旁白 云健、用户 云希、音箱 晓晓。

## 构建

```sh
.venv/bin/python src/tts.py          # 配音（修改台词后重跑）
.venv/bin/python src/timeline.py     # 时间线
./scripts/render_plates.sh           # 渲染全部 3D 底片（M5 上约 3.5 小时，可中断续渲）
./scripts/make_video.sh              # 配乐混音 + 合成 + 编码，输出 output/
```

调试用：

```sh
# 某个镜头的外观测试帧（秒为该底片内的时间）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
  -P src/blender/render_plate.py -- P09 --still 6.0 --res 0.5
# 低分辨率代理底片，用于在正式底片渲完前调合成
./scripts/render_proxies.sh
./scripts/make_video.sh --proxy
# 合成器单帧截图（全局帧号）
cd src/compositor && node render.mjs --stills 300,1500,3000
```

## 修改指引

- **改台词 / 唤醒词**：编辑 `src/lines.json`（例如把「你好小七」改成实际配置的唤醒词），
  重跑 `tts.py`、`timeline.py`。台词时长变化会改变镜头长度，需要重渲对应底片。
- **改画面文字**：`src/compositor/comp.js` 中各镜头的 `SHOTS.Sxx`，只需重跑 `make_video.sh`。
- **改配乐**：`src/audio/score.py`；音效位置在 `src/audio/mix.py`。

## 说明

片中的「品牌 A/B/C」为泛指的其他智能家居品牌；片尾注明本项目为开源项目，与小米集团无隶属或合作关系。
