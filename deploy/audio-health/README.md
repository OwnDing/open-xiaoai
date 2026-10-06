# 语音采集健康日志

每 10 秒写一条 JSONL 汇总，另记开始/停止、连接变化、断流、ALSA 错误、唤醒、KWS 暂停和异常。所有时间为 Unix UTC 毫秒 `ts_ms`；速率、间隔和耗时用单调时钟计算。日志只保存计数和信号统计，不保存音频、识别文本或访问令牌。添加日志不更改模型、阈值或收音重启策略。

| 位置 | 日志 | 保留范围 |
| --- | --- | --- |
| 小爱音箱 | `/data/open-xiaoai/logs/audio-health.jsonl` | 当前 512 KiB，加 `.1`、`.2` |
| 小爱桥接服务 `open-xiaoai-xiaozhi` | `/app/logs/audio-health.jsonl`，Compose 持久卷 | 当前 1 MiB，加 `.1`～`.3` |
| Windows 语音终端 | 配置文件所在目录的 `logs/audio-health.jsonl` | 当前 1 MiB，加 `.1`～`.3` |
| 语音终端后端 `xiaozhi-esp32-server-vt` | `/opt/xiaozhi-esp32-server/data/audio-health.jsonl`，现有 data 挂载 | 当前 1 MiB，加 `.1`～`.3` |

桥接服务不依赖 Docker 标准输出：即使 `docker logs` 没有更新，仍能查看独立健康日志。音箱可用环境变量 `OPEN_XIAOAI_HEALTH_LOG` 改路径；桥接服务使用同名变量。日志通过有界队列交给独立写盘线程；队列满或文件不可写时计入 `log_dropped_total`/`log_errors_total`，采集继续运行。

## 对照方法

小爱音箱每个录音进程有一个 `capture_id`，传输每批 PCM 的 `seq`、`sample_start`、`samples`、`sample_rate`、`ts_ms`。桥接服务保留同一 ID 和最后收到的序号。不同设备时钟可能有偏差，先匹配 ID/序号，再比较同一时间附近的窗口。窗口起点不完全一致，约 10 秒的速率应接近，不要求每条计数完全相同。

1. 音箱 `capture_rate_hz` 和 `send_rate_hz` 应接近 16000。`input_age_ms` 持续上升或 `capture_read_timeout` 表示读取中断；`xruns_total`/`alsa_errors_total` 增长表示 ALSA 异常。累计计数用于比较不同窗口。新客户端（见“连接卡住与重连”）的 `send_*` 指放入发送队列，不再等网络，`send_pending_ms` 应始终接近 0；网络跟不上时 `queue_dropped_packets_total` 增长，桥接端相应出现 `sequence_gaps`。
2. 桥接端 `input_rate_hz` 应接近 16000。`recording_rpc.ok` 只表示 RPC 是否收到回复，不能单独证明麦克风有数据，应同时看音频速率和新鲜度。`sequence_gaps`/`missing_samples` 增长表示序号或采样范围不连续；`sequence_reorders` 表示重复或乱序；旧客户端没有元数据时记 `metadata_missing_packets`。换采集 ID 不算丢包。
3. `window.kws_samples` 是模型处理的采样数，`skipped_samples` 及 `mode_*_samples` 是因监听、播音或其他模式跳过的采样数。待命且音频正常时，KWS 应持续处理；`kws_thread_alive=false`、`kws_errors` 增长、缓冲积压或 `kws_rtf` 接近/超过 1，可指向程序/算力问题。KWS 为流式分批模型，单帧耗时偶尔波动，以整个窗口的 RTF 为主。
4. `rms`/`peak`/`zero_ratio`/`clip_ratio` 反映送给模型的信号；`level_samples=0` 时该窗口没有信号统计，不把 RMS=0 解读成静音。非零音量不能证明有人说了唤醒词，健康日志也不能单独计算真实唤醒率。
5. Windows 终端另记设备原生 `mic_rate_hz`、输入回调和工作线程累计采样、溢出/丢样、回调间隔及处理队列延迟。`mic_*` 最大值自本次打开设备累计，重开时通过 `capture_start`/`capture_stop` 区分；KWS 输入统一为 16 kHz。`GET http://127.0.0.1:18110/status` 的 `audio_health` 不会重置汇总窗口。
6. 终端每 10 秒向后端镜像一条 `audio_health` 消息，后端只保留白名单统计，并附加当前连接收到的 Opus 包/字节累计数。待命时 Opus 包数为零属于正常状态，连续环境音留在本机唤醒模型。诊断消息不触发会话、ASR、LLM，也不更新会话空闲计时器。镜像失败记 `health_mirror_errors`，本机日志继续写入。

## 查看/导出

音箱（按原 SSH 方式登录）：

```sh
tail -n 12 /data/open-xiaoai/logs/audio-health.jsonl
```

Windows PowerShell：

```powershell
Get-Content C:\Users\djcmy\voice-terminal\app\logs\audio-health.jsonl -Tail 12
docker exec open-xiaoai-xiaozhi tail -n 12 /app/logs/audio-health.jsonl
docker exec xiaozhi-esp32-server-vt tail -n 12 /opt/xiaozhi-esp32-server/data/audio-health.jsonl
docker cp open-xiaoai-xiaozhi:/app/logs ./bridge-health
docker cp xiaozhi-esp32-server-vt:/opt/xiaozhi-esp32-server/data/audio-health.jsonl ./terminal-server-health.jsonl
```

将导出的文件放在一起，可用不依赖额外库的汇总工具查看各采集 ID、速率范围、最后序号和异常计数：

```sh
python deploy/audio-health/compare.py speaker-health.jsonl bridge-health/audio-health.jsonl terminal-health.jsonl terminal-server-health.jsonl
```

也可把 `.1`～`.3` 作为额外输入；工具容忍导出时末尾不完整的行并报告 `invalid_lines`。速率范围包含启动/停止窗口，判断持续异常时应回看对应原始记录。

导出时同时保留轮转文件，并记下失败唤醒的大致时间、设备和距离。长期保留范围取决于事件频率；高频错误会更快覆盖旧记录。

## 构建和部署

在已有 `local/open-xiaoai-xiaozhi:smooth-audio` 镜像的 Linux Docker 主机，从仓库根目录运行（编译限为 2 个并发任务）：

```sh
docker build --target runtime -f deploy/audio-health/Dockerfile -t local/open-xiaoai-xiaozhi:audio-health .
docker build --target client-artifact -f deploy/audio-health/Dockerfile --output type=local,dest=temp/audio-health-client .
docker build --network none -f deploy/audio-health/Dockerfile.wake-lifecycle -t local/open-xiaoai-xiaozhi:wake-lifecycle .
docker compose -f deploy/xiaozhi/docker-compose.yml up -d
```

部署前备份音箱 `/data/open-xiaoai/client`，停止旧客户端后替换 `temp/audio-health-client/client`，按原 `server.txt` 地址启动。现有 `/data/init.sh` 开机入口和小爱原生 AI 不需要改动。升级终端的 `voice_terminal/{audio,terminal,health}.py`，重启对应 Windows 计划任务。后端覆盖层 Dockerfile 已包含诊断路由，旧镜像也可单独复制 `audio_health.py` 到 `core/utils/`，运行 `patch_audio_health.py` 后构建为独立新镜像；不要直接覆盖运行容器中的文件作为永久部署。

本次 Windows 主机的离线构建目录为 `C:\Users\djcmy\audio-health-build-20261005`，保留 `Dockerfile.audio-health-offline`、vendored crates 和 ARM 标准库，避免依赖容器联网。原程序和 Compose 备份在 `C:\Users\djcmy\audio-health-backup-20261005`；音箱备份为 `/data/open-xiaoai/client.before-audio-health`。

桥接模型配置是现有 `config.py` 挂载，升级时保留现场配置。回退时恢复原镜像标签及客户端备份；新日志无需删除。

## 测试

`test_health.py` 通过 `AUDIO_HEALTH_MODULE` 指定任一 Python 日志实现，测试断流窗口、序号缺失/乱序/重启、信号统计、状态读取不影响窗口、队列满/写盘失败及轮转。另运行两个语音程序的原有回归测试和后端 `test_audio_health.py`；音箱 Rust 库测试及目标架构构建验证 PCM 转换和录音逻辑兼容。

## 对话超时后的再次唤醒

20 秒没有收到语音时，桥接服务结束对话、停用 VAD 和对话音频流。告别播报及随后默认 300 ms 的余音保护期间暂停 KWS；`wakeup.exit_guard_ms` 可以调整这个保护时间。播报完成、失败或退出被取消时都会释放本次暂停；重叠的唤醒提示仍保留自己的暂停。

恢复时，KWS 检测线程清理旧的输入缓冲并创建新的识别流，复用已经加载的 ONNX 模型。LISTENING/SPEAKING 后重新进入检测也执行同样的清理，避免把不连续的音频接到旧流上。解码期间收到暂停以及排队后已过期的命中都不会触发新会话。模型、关键词、阈值使用现有现场配置。

健康日志记录以下阶段：`session_exit_start` → `session_exit_prompt_start` → `session_exit_prompt_end` → `session_exit_guard_end` → `session_exit_end` → `kws_reset`。禁用告别回调时跳过播报和余音保护；播报失败记 `session_exit_prompt_error`，取消记 `session_exit_cancelled`。`session_exit_end` 表示暂停已释放；实际清理完成以 `kws_reset.reason=session_exit` 为准，状态汇总中的 `kws_reset_pending` 用于检查是否仍有请求等待处理。

`kws_reset.discarded_samples` 与 `window.mode_reset_samples` 表示恢复时丢弃的旧缓冲采样，属于有意清理；`kws_stale_hit` 表示过期命中被拦截；`kws_reset_error` 表示清理异常。现场验收应对照这些阶段，再测试“回答结束 → 20 秒无语音自动退出 → 再次说你好小七”。自动测试通过不能替代实际距离、音量和背景噪声下的唤醒验证。

针对本次修补，运行 `examples/xiaozhi/tests/test_session_exit.py` 和 `test_kws_lifecycle.py`，并运行同目录的原有会话、VAD、TTS、重连测试。已有健康日志镜像可直接用 `Dockerfile.wake-lifecycle` 构建升级镜像，无需重新编译客户端或桥接 Rust 库；替换挂载的 Python 文件及 Compose 后，仅更新 `open-xiaoai-xiaozhi` 服务。

## 连接卡住与重连

音箱和桥接服务之间是一条 WebSocket（TCP）长连接。Wi-Fi 时通时断时，TCP 连接不会断开，只会把重传等待一次次翻倍（单次最长 2 分钟），十几到三十分钟后才放弃；连接没断，客户端也就不会重连，小七因此可能连续几分钟收不到声音。2026-10-06 实测：60 秒内每 5 秒只通 0.5 秒，桥接只收到约 10 秒音频，最长 37 秒完全没有声音。

现在两端共用的 `MessageManager` 这样处理：

- **心跳和超时**：每 5 秒发一次 WebSocket ping，对方会自动回 pong。15 秒内什么都没收到，或者一帧 10 秒还没写出去，就判定这条连接已死，`process_messages()` 返回原因，调用方按断线处理。
- **发送队列**：由一个单独的写任务负责发送。控制消息（请求、回复、事件、ping）最先发，其次是不能丢的流（如播放音频），最后是实时音频。实时音频最多排约 1 秒（12 帧），再多就丢掉最旧的，因为迟到的声音比丢掉的声音更糟。录音线程只往队列里放，不等网络，麦克风不会再因为网络卡住而溢出、重启。
- **二进制音频帧**：格式为 `OXS1` + 头长度（u32 LE）+ JSON 头（id、tag、data）+ 原始字节。旧格式是整条 JSON、字节写成数字数组，大小约为原始数据的 3 倍（实测每秒约 92 KB，原始音频约 32 KB）。解码同时兼容旧格式，所以先升级桥接再升级音箱，中间不会断。

音箱客户端：

- 连接的每一步都有 5 秒超时（解析地址、TCP 连接、WebSocket 握手），内核发送缓冲设为 16 KiB（约 1 秒音频）。
- 断开后 1 秒重连。连接失败时，从这次尝试开始算起，依次隔 1、2、5 秒再试，之后每 5 秒一次，不会退出；超时的尝试本身已经等过，所以接着就试下一次。`connect_error` 记下 `attempt` 和 `retry_in_ms`，`disconnected` 记下 `reason`。

桥接服务：

- 每个新连接单独接受，握手限 10 秒。音箱发起新连接时，说明它已放弃旧连接（或重启了），所以直接关掉旧连接，不让音箱等到这边超时。
- 只在启动后第一次连上、或距上次断开已超过 60 秒时才播“已连接”，避免网络抖动重连时反复出声。`disconnected` 记下 `reason`。

注意：短于判定阈值（10–15 秒）的网络抖动不会触发重连，由 TCP 自己恢复；更长才重连。网络真正中断时重连也连不上，但网络一恢复，几秒内就能连上，不用等 TCP 的退避。

2026-10-06 在音箱上用 iptables 丢弃发往 192.168.5.10:4399 的包做对比（桥接与音箱都换成新版本前后各测一次）：

| 故障 | 旧版本 | 新版本 |
| --- | --- | --- |
| 完全断 30 秒 | 约 25 秒后 Windows 端先放弃连接；恢复后约 8 秒连上 | 10 秒判定发送卡住并断开，每约 5 秒重试；恢复后 1 秒连上，再 1 秒录音恢复 |
| 60 秒内每 5 秒只通 0.5 秒 | 连接不断，46 KB 积压 47 秒发不出去；桥接共收到约 10 秒音频，最长 37 秒无声 | 积压限 1 秒、每次通时先发最新音频；第 25–47 秒判定卡住并重连，结束后 1–2 秒恢复 |
| 正常 | mini PC 每秒收约 92 KB | 每秒约 37 KB，排队耗时约 0.2 ms，无丢帧 |

时通时断时两个版本都无法保证听清，网络本身太差；新版本的作用是不再被旧数据和 TCP 退避拖住，网络一好马上恢复。

构建（在已有 `local/open-xiaoai-xiaozhi:wake-lifecycle` 镜像的 Linux Docker 主机，从仓库根目录运行；会先跑 `packages/client-rust` 的测试）：

```sh
docker build --target runtime -f deploy/audio-health/Dockerfile.link-resilience -t local/open-xiaoai-xiaozhi:link-resilience .
docker build --target client-artifact -f deploy/audio-health/Dockerfile.link-resilience --output type=local,dest=temp/link-client .
```

先把 `deploy/xiaozhi/docker-compose.yml` 的镜像换成 `link-resilience` 并重建桥接容器，确认旧客户端的音频仍正常；再备份音箱 `/data/open-xiaoai/client`，换上 `temp/link-client/client` 并重启客户端。回退时恢复原镜像标签和客户端备份即可，两边的新旧版本可以任意组合，唯一例外是 sherpa 播放模式下新桥接发给旧客户端的播放音频旧客户端解不开。

本次 mini PC 上的离线构建目录为 `C:\Users\djcmy\link-build-20261006`（`Dockerfile.link` 与上面的 Dockerfile 相同，只是改用 audio-health 构建保留的 vendored crates 和 ARM 标准库）。Compose 备份为 `deploy\xiaozhi\docker-compose.yml.before-link-resilience`（原镜像 `wake-lifecycle`），音箱旧客户端备份为 `/data/open-xiaoai/client.before-link-resilience`。
