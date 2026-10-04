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
  → 待机：唤醒词（与小爱桥接同一个 sherpa-onnx 模型）
  → 唤醒后：Silero VAD 判断开口和说完，带 0.8 s 预录音
  → Opus 16 kHz / 60 ms 上传（listen start/stop，manual 模式）
小智后端：ASR → Hermes → TTS（Sherpa），音频只发回这条连接
  → Opus 解码到 48 kHz → 重采样到音箱采样率 → 播放
  → 播完 + 余音保护后继续听；空闲 20 s 回到待机
```

- 每个终端一个进程、一份配置、一个 `device_id`；要接多个设备就启动多个进程。
- 轮流听说：播放时不收音（P0.5 测得这台蓝牙音箱没有回声消除）。
- 断线自动重连（后端空闲约 3 分钟会主动断开）；麦克风停止出数据时自动重开设备（蓝牙断开、重连）。

## 后端：按设备发送音频

线上后端是 `native_xiaomi` 模式（只发文字给小爱）。终端需要服务端音频，所以后端补丁增加了设备名单：

```text
XIAOZHI_TTS_OUTPUT_MODE=native_xiaomi
XIAOZHI_SERVER_AUDIO_DEVICES=02:76:74:00:00:01,02:76:74:00:00:02
```

名单里的设备收 Sherpa 音频，其余设备（小爱）行为不变。补丁见 [patch_index_stream.py](../../deploy/sherpa-tts/xiaozhi-server-overrides/patch_index_stream.py)。

开发期间用一个并行的后端容器，线上后端（18000）不动：

1. 把 `deploy/sherpa-tts/xiaozhi-server-overrides/` 复制到部署目录 `xiaozhi-server\xiaozhi-server-overrides-vt\`。
2. 复制 `data` 为 `data-vt`，把 `server.websocket` 的端口改成 18100。
3. 把 [backend.compose.yml](../../deploy/voice-terminal/backend.compose.yml) 复制为 `docker-compose.voice-terminal.yml`，执行 `docker compose -f docker-compose.voice-terminal.yml up -d --build`。

它加入现有的 `xiaozhi-server_default` 网络，共用 sherpa-tts 和 Hermes，端口 18100 / 18103。

## 安装（Windows）

在接音频设备的电脑上，用 [uv](https://docs.astral.sh/uv/) 安装依赖：

```powershell
cd voice-terminal          # 本目录的副本
uv sync --python 3.12     # 默认源是阿里云镜像（pyproject.toml），uv.lock 按它解析
powershell -ExecutionPolicy Bypass -File scripts\fetch-assets.ps1
copy terminal.example.toml terminal.toml
```

`fetch-assets.ps1` 从小爱桥接容器复制唤醒和 VAD 模型到 `models\`，用已部署的 sherpa-tts 合成“我在。”等提示音到 `prompts\`。

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

日志：`logs\terminal.log`（1 MB 滚动，保留 5 个）。

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

# 后端路由：名单内设备收音频、名单外只收文字、两台同时提问各自返回
$env:VT_BACKEND_URL = 'ws://127.0.0.1:18100/xiaozhi/v1/'
.venv\Scripts\python.exe -X utf8 -m pytest -m backend -v

# 端到端：WAV 当麦克风、WAV 当音箱，走真实唤醒、VAD、后端识别和回答
.venv\Scripts\python.exe -X utf8 -m voice_terminal run --config tests\e2e.toml `
  --input-file 2@logs\e2e\wake_phrase.wav --input-file 6@logs\e2e\q_math.wav `
  --output-file logs\e2e\out.wav --duration 30
```

端到端的输入语音用 `docker exec ... python /tmp/make_clips.py /tmp/vt-e2e e2e` 生成（见 [make_clips.py](scripts/make_clips.py)）。

## 已知问题

- **京鱼座蓝牙小黑胶的麦克风只有 8 kHz 窄带**，打开麦克风后播放也降为通话音质。指令识别可用，唤醒在安静环境 1 米内单独说可以触发，远场和噪声下不稳定。换 USB 麦克风或支持宽带语音的音箱可以改善。
- **只有一个字的回答听不清**：Sherpa TTS 合成单字（如“二”）只有 0.3 s 左右的声音，再过窄带更难辨认；长回答正常。
- 房间上下文还没做：Hermes provider 只保留系统提示词里的时间、日期、位置，需要后端模板和 provider 一起改。
- Windows 11 的 `System32\onnxruntime.dll` 是旧版（1.17）。`sherpa-onnx-core` 必须安装（pyproject 已显式声明），否则 sherpa-onnx 会加载系统里的旧版并在创建模型时崩溃。
- 在 PowerShell 5.1 里，`.ps1` 脚本要么全用 ASCII，要么存成带 BOM 的 UTF-8。
