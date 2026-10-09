# 语音终端（电脑音频设备接入小智后端）

把接在电脑上的麦克风和音箱（蓝牙、USB 或内置）变成一台独立的小智设备：本地唤醒 → 上传语音 → 后端识别和回答 → 回答只在这台设备上播放。小爱音箱继续走原来的桥接，互不影响。

方案和测试记录：

- [跨平台多终端语音接入方案](../../docs/cross-platform-voice-terminal-plan.md)
- [P0.5 硬件测试记录](../../docs/voice-terminal-p05-hardware-tests.md)
- [P1 功能测试记录](../../docs/voice-terminal-p1-tests.md)

## 工作方式

```text
麦克风（设备原生采样率）
  → 重采样到 16 kHz → 高通 / WebRTC 降噪 / 自动增益
  → 待机：唤醒词（与小爱桥接同一个 sherpa-onnx 模型，可几路错开同时检测）
  → 唤醒后：Silero VAD 判断开口和说完，带 0.8 s 预录音
  → Opus 16 kHz / 60 ms 上传（listen start/stop，manual 模式）
小智后端：ASR → Hermes → TTS（Sherpa），音频只发回这条连接
  → Opus 解码到 48 kHz → 重采样到音箱采样率 → 播放
  → 播完 + 余音保护后继续听；空闲 20 s 回到待机
```

- 每个终端一个进程、一份配置、一个 `device_id`；要接多个设备就启动多个进程。
- 轮流听说：播放时不收音（P0.5 测得这台蓝牙音箱没有回声消除）。播完后还有一段余音保护（`[session] tts_end_guard_ms`，默认 700 ms）：蓝牙音箱自己的回声约 210 ms 后才进麦克风，房间里还要再响约 500 ms；保护期间听到的声音不做开口判断，但会留作预录，抢着说话不会丢开头。
- 播放端有自适应抖动缓冲（`[audio] playback_buffer_ms`，默认 240 ms）：服务端按实时节奏发音频，句间停顿之后每一包都是踩着点到的；缓冲播空后先攒够 240 ms 再播，避免一秒断十几次的“哧哧”声。`/status` 里的 `playback_underruns` 是播空次数。
- 对话中只说“拜拜”“没事了”之类的话（前后可带“好的”“谢谢”或唤醒词，如“你好小七，拜拜”）时马上结束：通知后端中止、不播它对这句的回答、播告别提示音后回到待机，不用等空闲超时。词表在 `[session] exit_words`（`[]` 关闭），判断规则和小爱桥接相同，“关灯，拜拜”这样带请求的话照常交给后端。不要加“晚安”这类会触发场景的话，否则只会结束对话。
- 断线自动重连（后端空闲约 3 分钟会主动断开）；麦克风停止出数据时自动重开设备（蓝牙断开、重连）。
- 麦克风只送纯静音（全是 0）时也会处理：真实麦克风总有底噪，连续 `[audio] silent_reopen_s` 秒（默认 10）全是 0 就重开设备；重开后还是 0，就运行 `silent_recover_command` 再重开，之后每 5 分钟重试一次，直到有声音。示例配置用 [restart-audio-device.ps1](scripts/restart-audio-device.ps1) 重启麦克风的驱动（蓝牙音箱是它的免提音频），需要管理员权限，计划任务以 SYSTEM 运行正好满足。`/status` 的 `mic_silent_s` 是当前连续静音的秒数。2026-10-09 这台蓝牙音箱就出现过：连接一直在，麦克风却送了大半天的 0，终端没发现，怎么喊都不醒，重连音箱后才恢复。

## 后端：按设备配置

线上后端是 `native_xiaomi` 模式（只发文字给小爱）。每台设备的差异写在后端 `data/.config.yaml` 的 `voice_devices` 里，以连接时的 `Device-Id` 为键；代码里不写任何具体设备或房间：

```yaml
voice_devices:
  "02:76:74:00:00:01":        # 设备 ID 要加引号
    output: server_audio      # 收服务端合成的音频；不写就是只收文字（小爱原生合成）
    tts: EdgeTTS              # 可选：TTS 下的任意模块名，不写用 selected_module.TTS
    room: 书房                # 可选：Home Assistant 区域名
    reply_style: sentence     # 可选：sentence = 至少一句完整的话；也可以直接写一句要求
    send_interval_ms: 50      # 可选：服务端音频包（每包 60 ms）的发送间隔，见下
```

流式 Edge（推荐给电脑终端）：在 `TTS` 下加一个模块，设备里写 `tts: EdgeStreamTTS`：

```yaml
TTS:
  EdgeStreamTTS:
    type: edge_stream         # deploy/sherpa-tts/xiaozhi-server-overrides/edge_stream.py
    voice: zh-CN-XiaoxiaoNeural
    output_dir: tmp/
```

它和自带的 `EdgeTTS` 相比：连接预先建好、多句复用（省掉每句约 0.6 s 的建连），MP3 边收边用 ffmpeg 解码边发送，第一段在第一个标点处切出，并把 Edge 每句头尾约 0.75 s 的静音裁到约 0.3 s。实测说完到开始出声的中位数：自带 EdgeTTS 2.14 s，流式 1.17 s（Sherpa 约 1.36 s）。还没出声就失败的句子会自动改用自带 EdgeTTS 重试。

`send_interval_ms`：这台 mini PC 上 Docker 虚拟机的时钟比真实时间慢约 7.7%，服务端按“每 60 ms 一包”发送，实际变成每 65 ms 一包，比音箱播放慢，长回答每隔约 3 s 就会播空一次（听起来是句中停顿）。给终端配 50，让服务端提前一点发，终端的缓冲会兜住。

- `room`：后端在系统提示词的上下文里加一行“Device room: 书房（……没说房间的指令指的就是书房）”。问“这个房间的灯开着吗”就查书房灯。
- `reply_style: sentence`：避免只回一个字（Sherpa 合成单字很难听清）。
- 没有条目的设备（比如小爱）行为完全不变。小爱也可以加一条 `room`，但不能写 `output: server_audio`，因为桥接走小爱原生合成。
- 改完后重启后端容器，设备重连后生效。
- 兼容旧做法：环境变量 `XIAOZHI_SERVER_AUDIO_DEVICES`（逗号分隔的设备 ID）同样能让设备收服务端音频。

实现：[voice_devices.py](../../deploy/sherpa-tts/xiaozhi-server-overrides/voice_devices.py)，加上 [patch_server.py](../../deploy/sherpa-tts/xiaozhi-server-overrides/patch_server.py) 里的三处挂钩：创建 TTS、只发文字的判断、提示词上下文。Hermes provider 在精简提示词时会保留 `Device room` 和 `Reply style` 两行。

开发期间用一个并行的后端容器，线上后端（18000）不动：

1. 把 `deploy/sherpa-tts/xiaozhi-server-overrides/` 复制到部署目录 `xiaozhi-server\xiaozhi-server-overrides-vt\`。
2. 复制 `data` 为 `data-vt`，把 `server.websocket` 的端口改成 18100，加上 `voice_devices`。
3. 把本分支的 `deploy/hermes/xiaozhi-provider/hermes.py` 复制到 `xiaozhi-server\hermes-provider-vt\hermes.py`。
4. 把 [backend.compose.yml](../../deploy/voice-terminal/backend.compose.yml) 复制为 `docker-compose.voice-terminal.yml`，执行 `docker compose -f docker-compose.voice-terminal.yml up -d --build`。

它加入现有的 `xiaozhi-server_default` 网络，共用 sherpa-tts 和 Hermes，端口 18100 / 18103。

### 切换到单一后端（稳定后）

2026-10-07 已在 mini PC 上完成：小爱和书房蓝牙音箱共用生产后端（18000），并行后端已停掉。

1. 备份：`docker tag local/xiaozhi-esp32-server:smooth-audio local/xiaozhi-esp32-server:smooth-audio-backup`，
   部署目录里的 `data/.config.yaml`、`docker-compose.yml` 和 `xiaozhi-server-overrides` 各留一份 `*.before-single-backend`。
2. 合并到 `main`。线上 Hermes provider 挂的是 mini PC 上 open-xiaoai 目录里的 `deploy/hermes/xiaozhi-provider/hermes.py`，确认它和 `main` 一致。
3. 用 `deploy/sherpa-tts/xiaozhi-server-overrides`（和 `xiaozhi-server-overrides-vt` 相同）替换部署目录里的 `xiaozhi-server-overrides`；
   把 `data-vt/.config.yaml` 里的 `EdgeStreamTTS` 和 `voice_devices` 两段原样加进 `data/.config.yaml`（端口保持 18000）；
   执行 `docker compose up -d --build xiaozhi-esp32-server`。
4. 终端配置的 `websocket_url` 改成 18000 端口（原文件留了 `terminal.toml.before-single-backend`），重启计划任务；
   停掉并行后端：`docker compose -f docker-compose.voice-terminal.yml down`。

回滚：把 `*.before-single-backend` 改回原名，`smooth-audio-backup` 重新打回 `smooth-audio` 标签后
`docker compose up -d xiaozhi-esp32-server`；需要并行后端时再 `docker compose -f docker-compose.voice-terminal.yml up -d`，终端改回 18100。

## 安装（Windows）

在接音频设备的电脑上，用 [uv](https://docs.astral.sh/uv/) 安装依赖：

```powershell
cd voice-terminal          # 本目录的副本
uv sync --python 3.12     # 默认源是阿里云镜像（pyproject.toml），uv.lock 按它解析
powershell -ExecutionPolicy Bypass -File scripts\fetch-assets.ps1
copy terminal.example.toml terminal.toml
```

`fetch-assets.ps1` 从小爱桥接容器复制唤醒和 VAD 模型到 `models\`，并把“我在。”“我没听清，再说一遍？”“有需要再叫我。”三段提示音合成到 `prompts\`。默认用 Edge 晓晓生成 MP3，和 `EdgeStreamTTS` 的回答同一个音色；终端用 Sherpa 回答时加 `-PromptEngine sherpa` 生成 WAV，并把配置里的 `*_prompt` 改成 `.wav`。终端加载提示音时会自动裁掉头尾静音（Edge 的“我在”原本 1.2 s，裁后 0.6 s）。

查看设备名，填进 `terminal.toml` 的 `[audio]`：

```powershell
.venv\Scripts\python.exe -X utf8 -m voice_terminal devices --host-api WASAPI
```

配置项说明见 [terminal.example.toml](terminal.example.toml)。`device_id` 每个终端唯一，并且要写进后端的 `XIAOZHI_SERVER_AUDIO_DEVICES`。

## 运行

```powershell
.venv\Scripts\python.exe -X utf8 -m voice_terminal run --config terminal.toml
```

开机自启（系统启动时以 SYSTEM 运行，不需要登录或远程桌面；进程退出 1 分钟后自动重启）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Config terminal.toml
powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Config terminal.toml -Remove
```

日志：`logs\terminal.log`（1 MB 滚动，保留 5 个）。采集与唤醒健康统计另写 `logs\audio-health.jsonl`，每 10 秒汇总，后端同步留档；查看字段、两端对照及导出方法见 [语音采集健康日志](../../deploy/audio-health/README.md)。

## 本地控制接口

默认只监听 `127.0.0.1:18110`：

| 请求 | 作用 |
| --- | --- |
| `GET /status` | 状态、最近一句识别和回答、各阶段耗时 |
| `POST /wake` | 不用唤醒词直接开始听 |
| `POST /ask`，`{"text": "..."}` | 用文字代替说话，回答在这台设备上播放 |
| `POST /stop` | 停止播放和对话，回到待机 |

```powershell
curl.exe -s http://127.0.0.1:18110/status
curl.exe -s -X POST http://127.0.0.1:18110/ask -d "{\"text\":\"现在几点了\"}"
```

## 测试

```powershell
# 单元测试（不需要设备和后端）
.venv\Scripts\python.exe -X utf8 -m pytest -q

# 后端（6 项）：配置的设备收音频、未配置的只收文字、两台同时提问各自返回、
# 房间上下文、未配置设备没有房间、完整句子回答。
# 需要 02:76:74:00:00:02 配成 server_audio + room 卧室 + reply_style sentence（可用 VT_* 环境变量改）
$env:VT_BACKEND_URL = 'ws://127.0.0.1:18100/xiaozhi/v1/'
.venv\Scripts\python.exe -X utf8 -m pytest -m backend -v

# 端到端：WAV 当麦克风、WAV 当音箱，走真实唤醒、VAD、后端识别和回答
.venv\Scripts\python.exe -X utf8 -m voice_terminal run --config tests\e2e.toml `
  --input-file 2@logs\e2e\wake_phrase.wav --input-file 6@logs\e2e\q_math.wav `
  --output-file logs\e2e\out.wav --duration 30
```

端到端的输入语音用 `docker exec ... python /tmp/make_clips.py /tmp/vt-e2e e2e` 生成（见 [make_clips.py](scripts/make_clips.py)）。

## 已知问题

- **京鱼座蓝牙小黑胶的麦克风只有 8 kHz 窄带**，打开麦克风后播放也降为通话音质。指令识别可用，唤醒和开口判断都比较勉强，示例配置为它放宽了设置（16 条候选、4 路错开的唤醒，VAD 阈值 0.3），测试见 [唤醒与静音麦克风测试](../../docs/voice-terminal-wake-silence-test.md)。远场和噪声下仍不稳定，换 USB 麦克风或支持宽带语音的音箱可以改善。
- **远程桌面连着时，本机蓝牙音箱没声音**：所有程序都一样，包括以 SYSTEM 运行的终端；断开远程桌面就恢复。远程桌面客户端的“远程音频”要设成“在远程计算机上播放”（mstsc：本地资源 → 远程音频 → 设置；Mac 的 Windows App / Microsoft Remote Desktop：Play sound → On the remote PC）。
- Sherpa TTS 合成单字（如“二”）只有约 0.3 s 声音，很难听清；给设备配置 `reply_style: sentence` 后，回答会变成“一加一等于二”这样的完整句子。
- Edge TTS 需要联网；断网时配了 Edge 的设备没有语音回答（流式 Edge 会先退回自带 EdgeTTS 重试，同样要联网），目前没有自动退回 Sherpa。
- Docker 虚拟机时钟偏慢（见上面的 `send_interval_ms`）。在虚拟机里把时钟源从 `tsc` 换成 `hyperv_clocksource_tsc_page` 或 `acpi_pm` 都没有改善，已改回 `tsc`。
- Windows 11 的 `System32\onnxruntime.dll` 是旧版（1.17）。`sherpa-onnx-core` 必须安装（pyproject 已显式声明），否则 sherpa-onnx 会加载系统里的旧版并在创建模型时崩溃。
- 在 PowerShell 5.1 里，`.ps1` 脚本要么全用 ASCII，要么存成带 BOM 的 UTF-8。
