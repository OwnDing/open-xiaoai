# 《家的大脑》：如何 DIY 一个全网最智能的 AI 家庭管家

约 2 分 49 秒的宣传片。讲清楚四件事：现在的智能家居为什么总差一口气（不够聪明、品牌各自为政、隐私都交给了云端）；
DIY 只需要一台带麦克风的音箱和一台常开的 mini PC；唤醒和语音识别在家里完成，声音不出家门，交给大模型的只有一行文字；
它听得懂意思、能跨品牌联动、一句话就能教会家里的规矩，还能扩展摄像头去看见危险、陪孩子写作业。

| 文件 | 内容 |
|---|---|
| [`storyboard.md`](storyboard.md) | 创意、视听风格、结构、逐镜头分镜表 |
| `output/home-brain.mp4` | 成片（1920×1080 · 24fps · 2.39:1 遮幅 · H.264 + AAC） |
| `output/storyboard_frames.jpg` | 从成片截取的每个镜头的代表帧 |
| `src/` | 全部源码：配音、时间线、Blender 场景、合成器、配乐与音效 |
| `scripts/` | 渲染与成片脚本 |

所有画面、配乐、音效都由本目录的代码生成，没有使用外部素材。

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
  kit.py     几何体、材质、灯光组  synth.py  合成器与音效          comp.js   字幕、设备标签、App 孤岛、话语碎片、
  home.py    三个房间的家         score.py  原创配乐                       链路图、规则卡、摄像头取景框、片名片尾
  props.py   音箱、mini PC、星点大脑、mix.py  配音 + 音效 + 配乐     render.mjs 无头 Edge 逐帧截图 → ffmpeg
             声音光丝、光罩、云层、       （人声闪避）
             摄像头、灶火、蒸汽
  studio.py  黑色产品摄影棚、软件层
  plates.py  每段底片的机位、灯光、光丝
  → build/plates/Pxx/*.jpg     → build/audio/mix.wav          → build/video.mp4
      + anchors.json（3D 锚点的屏幕坐标和每帧标记，给标签定位）
                                   │
                                   ▼
                     scripts/make_video.sh ──▶ output/home-brain.mp4
```

- **时间由配音驱动**：先合成配音，再按真实时长排时间线；3D 动作、标签、字幕、音效和配乐都读同一份 `timeline.json`。
- **声音之光**是全片的视觉主线：说话时一束琥珀→玫瑰→紫色的光丝从音箱飞向 mini PC；思考时 mini PC 上方浮现星点“大脑”；
  执行时光丝射向各个设备。光丝是沿路径建的发光管，材质里一个“脉冲头”参数控制它走到哪。
- **家的边界**：痛点段里墙壁变成玻璃、话语飞向云端；转折时一切倒流，一层光罩把家罩住。
- **一镜到底的开场**：微距音箱 → 跟着光丝到 mini PC → 拉开看全屋亮灯 → 升起成悬浮的微缩剖面模型，是同一段底片。
- 全片 2.39:1 遮幅，底片直接按 1920×800 渲染，字幕放在下方黑边里。

## 环境

- Blender 5.2（EEVEE）、ffmpeg、Node.js、Microsoft Edge（或 Chrome，设置 `CHROME=` 路径）
- Python 3.9+：`python3 -m venv .venv && .venv/bin/pip install numpy scipy pillow edge-tts`
- 合成器依赖：`cd src/compositor && npm install`

配音使用微软 Edge 在线神经网络语音（`edge-tts`，需要联网）：旁白 云健、用户 云希、小七 晓晓、孩子 云夏、普通音箱 晓伊。

## 构建

```sh
.venv/bin/python src/tts.py          # 配音（修改台词后重跑）
.venv/bin/python src/textures.py     # 作业纸贴图
.venv/bin/python src/timeline.py     # 时间线
./scripts/render_plates.sh           # 渲染全部 3D 底片（M5 上约 2.5 小时，可中断续渲）
./scripts/make_video.sh              # 配乐混音 + 合成 + 编码，输出 output/
```

调试用：

```sh
# 某几段底片在指定时刻的半分辨率测试帧，拼成联系表 build/lookdev_sheet.jpg
./scripts/lookdev.sh "P01:1,6.6,12" "P06:7,20"
# 只重新导出某段底片的 3D 锚点（改了标签位置时用，不重渲画面）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P src/blender/render_plate.py -- P13 --anchors-only
# 合成器单帧截图（全局帧号）；src/frames_at.py 可以把 "S13:send+0.5" 换算成帧号
cd src/compositor && node render.mjs --stills $(../../.venv/bin/python ../frames_at.py S13:send+0.5 S16:rule+0.6)
```

## 修改指引

- **改台词**：编辑 `src/lines.json`，重跑 `tts.py`、`timeline.py`。台词时长变化会改变镜头长度，需要重渲对应底片。
- **改画面文字、标签、链路图**：`src/compositor/comp.js` 中各镜头的 `SHOTS.Sxx`，只需重跑 `make_video.sh`。
- **改配乐**：`src/audio/score.py`；音效在 `src/audio/mix.py`。

## 说明

- 片中的设备品牌标注（米家、海尔等）用来说明“不同品牌统一接入”，与作者家里实际接入的品牌一致；“品牌 X / 品牌 Y”为泛指。
- 摄像头识别危险、陪孩子写作业是**扩展方向**，片中已标注“扩展”，不是本项目现有功能。
- 开源项目，与小米、海尔等公司无隶属或合作关系。
