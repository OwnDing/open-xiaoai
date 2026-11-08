# person-watch：摄像头有人记录

客厅和连廊两台海康摄像头只要拍到人，就记录一次"有人"事件，并保存抓拍图。全天运行。2026-11-04 开始试运行，到 11-08 记录了 65 次有人事件（客厅 49 次、连廊 16 次），阈值用的是默认值，识别率很高。

```text
子码流 RTSP（768×432 / 704×576 H.265）
  └─ 每秒取 2 帧 → 96 px 缩略图做画面变动检测（OSD 文字区域不算）
       └─ 画面在动（最多每秒 1 次）/ 有人时每 5 秒 / 平时每 60 秒
            └─ Intel person-detection-0202（OpenVINO，1 个 CPU 线程）
                 └─ 10 秒内命中 2 次 → 事件开始；60 秒没再看到人 → 事件结束
                      ├─ 抓拍：取主码流下一个关键帧（1080p，0–2 秒内），再检测一遍并画框
                      ├─ SQLite + JPEG（命名卷 person-watch-data，保留 30 天）
                      ├─ 网页 http://192.168.5.15:18110
                      ├─ QQ：连廊事件开始时推送抓拍图（QQ_NOTIFY_CAMS）
                      └─ HA webhook → 模板传感器 binary_sensor.person_keting / person_lianlang
```

- 模型：[person-detection-0202](https://docs.openvino.ai/2023.3/omz_models_model_person_detection_0202.html)（Intel Open Model Zoo，Apache-2.0，1.8 M 参数，3.6 MB）。它只认人，在构建镜像时下载。输入尺寸会按每台摄像头的画面比例调整：客厅 576×320，连廊 480×384。
- 抓拍时机：
  - 事件开始时抓一张；
  - 人数比之前多时再抓一张（两张至少间隔 10 秒）；
  - 人一直在的话，每 10 分钟抓一张。

  抓拍优先用 1080p 关键帧。关键帧里没认出人（人只露一部分，或者刚好走开）时，就把子码流检测到的框画在 1080p 图上。拿不到主码流时退回子码流图。
- 资源（N100 上实测）：
  - 两路子码流一直解码，约 0.05 核。
  - 每次检测约 85 ms（单线程，连续运行 4 天多的平均）。客厅有人走动时每秒检测一次，整个容器约 0.1–0.2 核。
  - 内存约 155 MB。
  - 磁盘：5 天的事件记录和抓拍图约 15 MB。

  容器设置了 `cpus: 1.0` 和 `cpu_shares: 256`，进程 `nice 10`，CPU 紧张时优先让给唤醒词容器。

## 摄像头用 RTSP 接入 Home Assistant

摄像头用 HA 自带的 **Generic Camera** 集成接入。接入后可以在 HA 里看实时画面，person-watch 的摄像头地址也从这份配置生成。

在 HA 网页的"设置 → 设备与服务 → 添加集成 → Generic Camera"里，每台摄像头添加一次。两台海康摄像头当前的配置：

| 配置项 | 填写 |
| --- | --- |
| 视频流地址 | `rtsp://<摄像头 IP>:554/Streaming/Channels/101`（101 主码流，102 子码流） |
| 静态图片地址 | 留空。海康 ISAPI 抓图实测要 1.5–9 秒，连廊那台还返回 503 |
| RTSP 传输协议 | TCP |
| 认证方式 | basic |
| 用户名、密码 | 摄像头的账号密码，单独填，不写进地址 |
| 帧率 | 2 |

检测不经过 HA：person-watch 直接连摄像头拉流，HA 只负责看画面和接收检测结果。

`cams_from_ha.py` 按集成条目的名称找摄像头（名称由 IP 生成，比如 `192_168_254_200`），并把地址里的 101 换成 102 作为子码流。换了摄像头要改脚本里的 `NAMES`。

其他品牌的摄像头（还没实测）可以手写 `cams.env`，子码流和主码流用 `|` 隔开：

```text
CAMS=keting=rtsp://用户:密码@IP/子码流|rtsp://用户:密码@IP/主码流;lianlang=...
```

## 部署（mini PC）

```powershell
cd C:\Users\djcmy\Documents\develop\ai\open-xiaoai\deploy\person-watch
# 摄像头地址（含密码）从 HA 的 generic 摄像头配置生成，只留在 mini PC 上，不进 git
docker exec -i homeassistant python3 - < cams_from_ha.py > cams.env
# .env：网页登录 WEB_USER=... / WEB_PASSWORD=...（可选）
docker compose up -d --build
```

HA 端（只需做一次）：

1. 把 `ha_templates.yaml` 拷成 HA 的 `/config/templates.yaml`。
2. 在 `configuration.yaml` 里加一行 `template: !include templates.yaml`。
3. 重启 HA。

完成后会多出两个带 unique_id 的模板二元传感器，由 webhook `person-watch-<摄像头>` 更新（只接受局域网访问）。它们可以分配区域；当前分在"客厅"和"室外连廊"。

如果不用 webhook（删掉 compose 里的 `HA_WEBHOOK`），person-watch 会改用 `.env` 里的 `HA_TOKEN`，直接写 `/api/states`。这样写出来的实体没有 unique_id，只能在"开发者工具 → 状态"里看到。HA 网页 → 左下角用户 → 安全 → 长期访问令牌，可以创建令牌；`create_ha_token.py` 也能用现有的管理员令牌创建。

## 查看记录

- 网页：`http://192.168.5.15:18110`，按天、按摄像头列出事件和抓拍。可选设置 `WEB_USER` / `WEB_PASSWORD` 加 Basic 认证。不设的话，局域网里谁都能打开。
- 接口：`/api/events?date=2026-11-04&cam=keting` 返回 JSON；`/health` 返回每台摄像头是否在线、检测次数、累计推理耗时。
- HA：
  - `binary_sensor.person_keting`（客厅摄像头有人）
  - `binary_sensor.person_lianlang`（连廊摄像头有人）

  有人时状态为 `on`，摄像头断流超过 60 秒变成 `unavailable`。属性里有 `max_persons`、`event_start` 和 `last_snapshot`（抓拍网址）。HA 自己保留 30 天历史。

  person-watch 每分钟重发一次当前状态；模板传感器在 HA 重启后也会恢复之前的状态。

## QQ 推送

`QQ_NOTIFY_CAMS`（compose 里设成 `lianlang`）列出的摄像头，每次事件开始时，用 QQ 官方机器人接口把那张抓拍图发到你的 QQ 私聊。图上带一行说明：哪台摄像头、时间、几个人，以及记录网页链接。

- 凭据和接收人写在 `.env`：`QQ_APP_ID`、`QQ_CLIENT_SECRET`、`QQ_OPENID`。它们和 Hermes 的 QQ 机器人是同一套（见 `deploy/hermes/README.md` 的 QQ 一节）。
- 同一台摄像头 `QQ_COOLDOWN_S`（120 秒）内最多推送一次。
- 图片发不出去时，改发纯文字。

这一路直接调用 QQ 接口，不经过 Hermes，因为 Hermes 的 webhook 推送只能发文字。

其他告警（漏水、电量低、摄像头监控中断）走 HA 自动化 → Hermes → QQ，见 `deploy/homeassistant/qq_alerts.yaml`。

person-watch 每分钟还会调用一次 webhook `person-watch-heartbeat`，更新 `sensor.person_watch_heartbeat`（"person-watch 最后上报"）。HA 用它判断服务是否停了：状态没变时 HA 不会刷新传感器的上报时间，所以不能用 `binary_sensor` 来判断。

## 调参

在 `docker-compose.yml` 的 `environment` 里设置：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `THRESH` | 0.5 | 置信度阈值 |
| `MIN_BOX_H` | 0.08 | 人框最小高度（占画面比例），更小的框不算 |
| `OSD_MASKS` | 时间、名字、Wi-Fi 三块 | `x1,y1,x2,y2;...`（0–1）。这些区域不参与画面变动检测，框有一半以上落在里面的也不算人 |
| `START_HITS` / `END_AFTER_S` | 2 / 60 | 开始事件需要的命中次数 / 多久没看到人算结束 |
| `KEEPALIVE_S` / `IDLE_CHECK_S` | 5 / 60 | 有人时 / 没人时的定期检测间隔 |
| `PERIODIC_SNAPSHOT_S` | 600 | 人一直在时的抓拍间隔 |
| `KEEP_DAYS` | 30 | 保留天数 |
| `DEBUG_DETS` | 1（试运行期） | 把每次检测的原始结果写进 `/data/debug/dets-日期.jsonl`，用于调阈值 |

## 测速

`bench.py` 直接拉子码流跑检测，打印延迟和 CPU 占用，并保存画了框的帧：

```powershell
docker run --rm --env-file cams.env -e DURATION=60 -v %CD%\bench-out:/out local/person-watch:1.0 python bench.py
```
