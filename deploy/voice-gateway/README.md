# xiaoqi-voice-gateway（轻量语音网关）

用不到 1,000 行纯 Python + ONNX 的轻量语音网关替代 `xiaozhi-esp32-server`：

- **100% 兼容小智 v1 WebSocket 协议**（`/xiaozhi/v1/`）：现有小爱桥接、电脑语音终端、压测脚本零改动直连。
- **极低资源占用**：去掉 PyTorch / FunASR / 海量云厂 SDK 与内置意图框架，直接用 `sherpa-onnx` int8 SenseVoiceSmall 做本地 ASR，PyAV 进程内流式解码 Edge TTS（零 ffmpeg 子进程），无构建期字符串补丁。
- **完整继承所有定制能力**：
  - 直接加载 `deploy/hermes/xiaozhi-provider/hermes.py`（含工具调用防幻觉护栏、场景直跑、音乐分流、`tv_control` 与可选 `voice_enroll.py`）；
  - 直接复用原有 `xiaozhi-server/data/.config.yaml`（含 `voice_devices`、`voiceprint`、`TTS` 配置，无需重复配密钥）；
  - Edge 流式 TTS 断网或异常时自动回退标准 Edge → 本地离线 `sherpa-tts`；
  - 保留 `audio_health` JSONL 日志格式，兼容 `deploy/audio-health` 排查工具；
  - 新增 `GET /health`、`GET /status`、`POST /announce`（支持向书房蓝牙音箱等在线终端主动推送播报）。

## 端口

| 端口（容器内） | 作用 |
| --- | --- |
| `8000` | 小智兼容 WebSocket（`ws://<host>:18000/xiaozhi/v1/`） |
| `8003` | HTTP 控制接口：`GET /health`、`GET /status`、`POST /announce` |

## 主动播报接口（`POST /announce`）

```bash
# 按房间播报（例如向书房蓝牙音箱播报）
curl -X POST http://127.0.0.1:18003/announce \
  -H "Content-Type: application/json" \
  -d '{"room":"书房","text":"洗衣机洗完了。"}'

# 或按 device_id 指定设备
curl -X POST http://127.0.0.1:18003/announce \
  -H "Content-Type: application/json" \
  -d '{"device_id":"02:76:74:00:00:01","text":"鱼缸灯已经关闭。"}'
```

如需鉴权，在环境变量中设置 `GATEWAY_ANNOUNCE_TOKEN`，请求头带 `Authorization: Bearer <token>`。

## 部署与灰度切换（Windows mini PC）

先在并行端口 `18100/18103` 启动验证（不影响线上 `18000`），验证通过后再停掉 `xiaozhi-esp32-server` 切到 `18000/18003`：

```powershell
cd C:\Users\djcmy\Documents\develop\ai\open-xiaoai\deploy\voice-gateway

# 1. 并行验证（18100 / 18103）
$env:GATEWAY_WS_PORT = "18100"
$env:GATEWAY_HTTP_PORT = "18103"
docker compose up -d --build
curl.exe -s http://127.0.0.1:18103/health

# 2. 切换生产端口（停掉旧 xiaozhi-esp32-server，启动 voice-gateway 接管 18000/18003）
docker stop xiaozhi-esp32-server
Remove-Item Env:GATEWAY_WS_PORT, Env:GATEWAY_HTTP_PORT
docker compose up -d
```

**一键回滚**：

```powershell
docker stop voice-gateway
docker start xiaozhi-esp32-server
```

## 运行单元测试

```bash
cd deploy/voice-gateway
python3 -m unittest discover -s tests -v
```
