# 《遥控器退休了》：让小七，接管你家的电视

Open-XiaoAI 的第三部宣传片，约 2 分 41 秒。讲清楚三件事：今天的智能家居对不同品牌的电视只能开机、关机，剩下的还得靠遥控器一下下按；
小七在电视上多了一个开源的电视助手，它是小七的“眼睛”（不到 0.3 秒读完整块屏幕）和“手”（打字、点击、按键、播放控制）；
于是开机、找片、选集、播放控制、音乐 App、浏览器，电视上的每一步都交给一句话。

| 文件 | 内容 |
|---|---|
| [`storyboard.md`](storyboard.md) | 大纲与分镜：创意、痛点与亮点、视听风格、结构、逐镜头分镜表 |
| `output/remote-retires.mp4` | 成片（1920×1080 · 24fps · 2.39:1 遮幅 · H.264 + AAC） |
| `output/storyboard_frames.jpg` | 从成片截取的每个镜头的代表帧 |
| `output/cover_16x9.jpg`、`output/cover_4x3.jpg` | B 站封面（16:9 主封面与 4:3 版），由 `src/cover/` 生成 |
| `src/` | 全部源码：配音、时间线、电视界面、Blender 场景、合成器、配乐与音效 |
| `scripts/` | 渲染与成片脚本 |

所有画面、配乐、音效都由本目录的代码生成，没有使用外部素材。片中剧集《雾港》、歌曲《晚风慢慢》和其他片名都是虚构的。

## 制作流程

```text
src/lines.json ──src/tts.py──▶ build/audio/voice/*.wav + meta.json（时长、逐字时间、音量包络）
                                   │
                                   ▼
                           src/timeline.py ──▶ build/timeline.json（镜头起止帧、台词入点、动作标记、37 次按键）
                                   │
       ┌───────────────────────────┼──────────────────────────────┬─────────────────────────────┐
       ▼                           ▼                              ▼                             ▼
src/tvui/                    src/blender/                   src/audio/                    src/compositor/
  tv.js  电视里的一切：桌面、   room.py   以电视墙为中心的客厅   synth.py 合成器与音效          comp.js  字幕、设备标签、痛点卡片、
         视频 App、首字母键盘、 tvset.py  电视、遥控器、展柜     score.py 原创配乐                       小七的“眼睛”线框和点击光纹、
         选集、播放器、音乐     studio.py 三台电视、三件套、展厅  mix.py   配音 + 音效 + 电视里的         步骤清单、链路图、片名片尾
         App、浏览器、别家电视  props.py  音箱、mini PC、光丝             声音 + 配乐（人声闪避）   render.mjs 无头 Edge 逐帧截图 → ffmpeg
  render_screens.mjs         plates.py 每段底片的机位与灯光
  → build/screens/Pxx/<屏>/   → build/plates/Pxx/*.jpg       → build/audio/mix.wav         → build/video.mp4
    ####.jpg + eyes.json        + anchors.json（3D 锚点的屏幕坐标：电视四角、设备）
  screen_light.py
  → light.json（每帧屏幕平均色）       │
                                       ▼
                         scripts/make_video.sh ──▶ output/remote-retires.mp4
```

- **时间由配音驱动**：先合成配音，再按真实时长排时间线；电视界面、3D 动作、图形、字幕、音效和配乐都读同一份 `timeline.json`。
- **电视屏幕是真贴图**：`src/tvui` 用 HTML 逐帧画出电视此刻显示的内容（雾港夜景和雨夜长街用 canvas 程序绘制），渲成图片序列，
  在 Blender 里作为屏幕的自发光贴图；`screen_light.py` 算出每帧的平均色，驱动屏幕前的面光源，所以屏幕的颜色和明暗会实时打在墙上和沙发上。
- **小七的眼睛和手**：电视界面在渲染时记下小七“读到”的文字框和“点下”的按钮（`eyes.json`，屏幕像素坐标）；
  Blender 导出电视四角的屏幕坐标，合成器用透视映射把线框和光纹准确贴到 3D 电视的屏幕上。
- **37 次按键**：`timeline.py` 生成一份按键表（方向键、确认键和时间）；电视界面按它一格格跳焦点，遥控器模型按它一下下按下按钮，
  音效按它发出按键声，计数也是按它数的。
- 全片 2.39:1 遮幅，底片直接按 1920×800 渲染，字幕放在下方黑边里。

## 环境

- Blender 5.2（EEVEE）、ffmpeg、Node.js、Microsoft Edge（或 Chrome，设置 `CHROME=` 路径）
- Python 3.9+：`python3 -m venv .venv && .venv/bin/pip install numpy scipy pillow edge-tts`
- 合成器依赖：`cd src/compositor && npm install`

配音使用微软 Edge 在线神经网络语音（`edge-tts`，需要联网）：旁白 云健、用户 云希、小七 晓晓、普通音箱 晓伊。

## 构建

```sh
.venv/bin/python src/tts.py                 # 配音（修改台词后重跑）
.venv/bin/python src/timeline.py            # 时间线
.venv/bin/python src/textures.py            # 展柜铭牌贴图
node src/tvui/render_screens.mjs            # 电视屏幕图片序列（约 4 分钟）
.venv/bin/python src/screen_light.py        # 每帧屏幕平均色
./scripts/render_plates.sh                  # 渲染全部 3D 底片（M5 上约 2 小时，可中断续渲）
./scripts/make_video.sh                     # 混音 + 合成 + 编码，输出 output/
```

B 站封面：先用 Blender 渲一张不带遮幅的全幅背景（展柜里的遥控器），再用 HTML 叠字截图：

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
$B -b --factory-startup -P src/cover/render_bg.py -- --w 1920 --h 1080 --t 11 --lens 50 --shift -0.22 --out build/cover/bg_16x9.png
$B -b --factory-startup -P src/cover/render_bg.py -- --w 1440 --h 1080 --t 11 --lens 50 --shift -0.16 --out build/cover/bg_4x3.png
node src/cover/render_cover.mjs             # 文案在 src/cover/cover.html
```

调试用：

```sh
# 电视界面单帧（底片:屏幕:时间），输出到 build/screen_stills/
node src/tvui/render_screens.mjs --stills P01:main:9.2,12.4 P06:c:16
# 某几段底片在指定时刻的半分辨率测试帧，拼成联系表 build/lookdev_sheet.jpg
./scripts/lookdev.sh "P01:1,9.6" "P13:5"
# 合成器单帧截图（全局帧号）；src/frames_at.py 把 "S13:k6+0.5" 换算成帧号
cd src/compositor && node render.mjs --stills $(../../.venv/bin/python ../frames_at.py S13:k6+0.5 S16:type+0.8)
```

## 修改指引

- **改台词**：编辑 `src/lines.json`，重跑 `tts.py`、`timeline.py`、`render_screens.mjs`、`screen_light.py`，再重渲受影响的底片。
- **改电视界面**：`src/tvui/tv.js` 的页面（`build*`）和每段底片的屏幕流程（`SCREENS`），重跑 `render_screens.mjs`、`screen_light.py`，
  再重渲对应底片（屏幕是贴图）。
- **改画面文字、标签、线框**：`src/compositor/comp.js` 中各镜头的 `SHOTS.Sxx`，只需重跑 `make_video.sh`。
- **改配乐与音效**：`src/audio/score.py`、`src/audio/mix.py`（电视里的声音在 `tv_audio()`）。

## 说明

- 片中能力都是本项目已上线的功能：开机走小爱音箱的红外（红外码是开关切换，电视关着才发），关机让电视待机；
  奇异果里找片、选集并读屏核对集数；播放控制；没有专门工具的操作读屏后一步步点；浏览器里一次输入整句。
  详见根目录 README 的“看电视”一节和 [`deploy/tv-helper`](../deploy/tv-helper/README.md)。
- 目前在 TCL 雷鸟（Android 11）上验收，适用于开启 ADB 调试的安卓电视；“品牌 A / B / C”为泛指。
- 开源项目，与 TCL、爱奇艺（银河奇异果）、网易云音乐等公司无隶属或合作关系，各名称为其所有者的商标。
