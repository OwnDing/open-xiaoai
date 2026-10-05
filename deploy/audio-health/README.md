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

1. 音箱 `capture_rate_hz` 和 `send_rate_hz` 应接近 16000。`input_age_ms` 持续上升或 `capture_read_timeout` 表示读取中断；`xruns_total`/`alsa_errors_total` 增长表示 ALSA 异常；`send_pending_ms` 持续上升说明发送等待。累计计数用于比较不同窗口。
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
docker compose -f deploy/xiaozhi/docker-compose.yml up -d
```

部署前备份音箱 `/data/open-xiaoai/client`，停止旧客户端后替换 `temp/audio-health-client/client`，按原 `server.txt` 地址启动。现有 `/data/init.sh` 开机入口和小爱原生 AI 不需要改动。升级终端的 `voice_terminal/{audio,terminal,health}.py`，重启对应 Windows 计划任务。后端覆盖层 Dockerfile 已包含诊断路由，旧镜像也可单独复制 `audio_health.py` 到 `core/utils/`，运行 `patch_audio_health.py` 后构建为独立新镜像；不要直接覆盖运行容器中的文件作为永久部署。

本次 Windows 主机的离线构建目录为 `C:\Users\djcmy\audio-health-build-20261005`，保留 `Dockerfile.audio-health-offline`、vendored crates 和 ARM 标准库，避免依赖容器联网。原程序和 Compose 备份在 `C:\Users\djcmy\audio-health-backup-20261005`；音箱备份为 `/data/open-xiaoai/client.before-audio-health`。

桥接模型配置是现有 `config.py` 挂载，升级时保留现场配置。回退时恢复原镜像标签及客户端备份；新日志无需删除。

## 测试

`test_health.py` 通过 `AUDIO_HEALTH_MODULE` 指定任一 Python 日志实现，测试断流窗口、序号缺失/乱序/重启、信号统计、状态读取不影响窗口、队列满/写盘失败及轮转。另运行两个语音程序的原有回归测试和后端 `test_audio_health.py`；音箱 Rust 库测试及目标架构构建验证 PCM 转换和录音逻辑兼容。
