# 小爱音箱 + Xiaozhi + Hermes + DeepSeek：接入与延迟测试报告

测试日期：2026-09-29  
对应方案：[xiaoai-xiaozhi-hermes-deepseek-agent-poc.md](./xiaoai-xiaozhi-hermes-deepseek-agent-poc.md)  
部署与复现：[deploy/hermes/README.md](../deploy/hermes/README.md)

---

## 0. 结论

1. **Hermes 对普通聊天几乎不增加延迟。** 从“用户说完”到音箱开始出声，直连 DeepSeek 约 2.2 秒，接入 Hermes 后约 2.3 秒，只多了 **0.06 ~ 0.1 秒**。方案第 13 节担心的“3~5 秒”没有出现，**第一阶段不需要做 Fast Path Router**。
2. **Agent 能力全部跑通。**
   - 智能家居：“把客厅灯关掉”，灯在用户说完后约 2.0 秒熄灭，约 2.7 秒听到“好了，客厅灯关了”。
   - 新闻：约 2 秒先说“我查一下”，约 4.6 秒开始播报新闻内容。
   - 记忆：跨会话能记住“睡觉空调二十五度”，也能记住聊天里讲过的故事细节。
   - 睡觉模式 Skill：一次完成关两盏灯、设空调、检查窗户。
   - 直连 DeepSeek 时这些全部做不到：它会口头说“好的这就关灯”但什么都没做，查新闻只说“稍等一下”就没有下文，跨会话记不住偏好。
3. **瓶颈不在 Hermes，而在 VAD 和 ASR。**
   - 一次回答里，VAD 尾音等待 0.5 秒，ASR 0.77 ~ 1.08 秒，两者加起来占了一半以上。
   - 长句的 ASR 会更慢：一段约 1 分钟的讲述，ASR 用了 15.7 秒。
   - 想让普通聊天达到方案 T2 ≤ 1.5~2 秒的目标，应优化 VAD 和 ASR，而不是绕开 Hermes。
4. **已经接入并运行在你的音箱上。**
   - 当前 xiaozhi-server 已切到 Hermes，可以一条命令切回直连 DeepSeek（见第 7 节）。
   - Home Assistant 目前是演示用的虚拟 HA，接真实设备需要替换 HASS_URL/TOKEN，并更新设备表。

---

## 1. 测试环境

| 项目 | 内容 |
|---|---|
| 音箱 | 小爱 OH2P，Open-XiaoAI，原生小爱 TTS（`native_xiaomi` 模式） |
| Mini PC | Windows 11 + Docker Desktop，4 核，Docker VM 7.6 GB |
| xiaozhi-esp32-server | 0.9.6（本地镜像 `smooth-audio`），ASR：FunASR SenseVoiceSmall（CPU），VAD：Silero |
| 大模型 | DeepSeek `deepseek-flash`，关闭思考模式 |
| Hermes Agent | v0.21.5（镜像 revision `749220e`），OpenAI 兼容 API Server，端口 8642 |
| Web Search | Tavily（DuckDuckGo、Brave 在本网络不可达） |
| Home Assistant | 2026.9.3 演示实例，虚拟设备：客厅灯、书房灯、卧室灯、卧室空调、温湿度传感器、窗户传感器 |

Hermes 的 `xiaoqi-home` 配置：

- 只开放 `memory`、`session_search`、`skills`、`web`、`homeassistant`、`cronjob`。终端、文件、浏览器、代码执行、子代理全部关闭。
- `reasoning_effort: none`：Hermes 对 `deepseek-flash` 默认会开启思考模式，必须显式关掉。
- 不加载自带的 58 个 Skills，只保留自建的“睡觉模式”。
- 人设（SOUL.md）要求：
  - 只说中文，不用 Markdown。
  - 联网搜索前先说“我查一下”。
  - 控制设备前不说话，做完再说结果。
- SOUL.md 附带设备实体表，省掉一轮“先列设备”的推理。

---

## 2. 测试方法与计时口径

### 2.1 计时起点 T0

T0 定义为 **bridge 的 VAD 判定用户说完、向 xiaozhi-server 发送 `listen stop` 的时刻**。

真实的“用户最后一个字”比 T0 早约 **0.5 秒**，这是 `min_silence_duration = 500ms`，即 VAD 的尾音等待。下文如果写“用户说完后 X 秒”，都已经把这 0.5 秒加进去了。

### 2.2 四种测量方式

| 方式 | 说明 | 样本 |
|---|---|---|
| A. API 级交错 A/B | 在 mini PC 上用同样的问题，交替请求 DeepSeek 直连和 Hermes，测首字（TTFT）和第一句 | 各 20 次 |
| B. 模拟设备语音链路 | 伪装成 bridge 连接 xiaozhi-server，按实时速度发送合成的语音（Opus），走真实的 ASR、LLM 和分句 | 9 类问题 × 3~6 轮 |
| C. 真人语音日志 | 用 `docker logs -t` 对齐 server 的 `listen stop` 和 bridge 的“识别文本 / 第一句 / 原生 TTS 已生成” | 直连 486 轮（过去 6 天），Hermes 27 轮（今晚实测） |
| D. 设备动作时刻 | 对比 HA 实体的 `last_changed` 与 T0 的时间差 | 13 次（1 次异常，已剔除） |

### 2.3 T1 / T2 的组成

- **T1**（用户说完 → LLM 第一个 token）= 0.5 秒 VAD + ASR + LLM 首字
- **T2**（用户说完 → 音箱开始播放）= 0.5 秒 VAD + ASR + LLM 第一句 + 原生 TTS 生成（中位 0.31 秒）+ miplayer 起播

miplayer 起播时间无法从日志测得，估计在 0.1 ~ 0.2 秒，A/B 两边相同，所以下文的 T2 **没有**计入这一项。

---

## 3. 当前基线：直连 DeepSeek

### 3.1 模拟设备（方式 B，27 次聊天）

| 阶段（从 T0 起算） | 中位 | p90 |
|---|---|---|
| ASR 完成 | 0.77 s | 1.06 s |
| 第一句文本到达 | 1.37 s | 1.71 s |
| 其中 LLM 部分 | 0.55 s | 0.78 s |

### 3.2 真人语音（方式 C，过去 6 天 486 轮）

| 阶段（从 T0 起算） | 中位 | p90 |
|---|---|---|
| ASR 文本到达 bridge | 1.08 s | 1.65 s |
| 第一句到达 bridge | 1.87 s | 2.62 s |
| 第一段原生 TTS 生成完成 | 2.20 s | 3.04 s |

**换算：真人使用时 T2 ≈ 0.5 + 2.20 ≈ 2.7 秒。**

真人数据比模拟数据慢约 0.5 秒，原因有两个：真人说话更长，ASR 更慢；多轮对话的历史更长，LLM 也更慢。

### 3.3 基线的功能缺陷（本次接入要解决的问题）

| 用户说 | 直连 DeepSeek 的回答 | 问题 |
|---|---|---|
| 把客厅灯关掉 | “好的，这就把客厅灯关掉” | 什么都没做，是在说谎 |
| 今天 AI 圈有什么重要新闻？ | “我这就帮你看看……稍等一下” | 之后没有任何内容 |
| （新会话）我睡觉的时候空调应该开多少度？ | “二十六度上下最稳妥” | 没有记住用户说过的 25 度 |

---

## 4. 接入 Hermes 后

### 4.1 普通聊天

| 测量 | 直连 DeepSeek | 经过 Hermes | 差值 |
|---|---|---|---|
| API 首字 TTFT，中位（方式 A，n=20） | 0.47 s | 0.58 s | +0.11 s |
| API 第一句，中位 | 0.53 s | 0.64 s | +0.11 s |
| 语音链路：T0 → 第一句，中位（方式 B） | 1.37 s | 1.45 s | +0.08 s |
| 语音链路：T0 → 第一句，p90 | 1.71 s | 1.61 s | 在波动范围内 |
| 真人：LLM 部分（第一句 − ASR），中位（方式 C） | 0.78 s | 0.84 s | +0.06 s |
| 真人：LLM 部分，p90 | 1.10 s | 1.23 s | +0.14 s |
| 真人：T0 → 首段 TTS 生成，中位 | 2.20 s | 2.35 s | +0.15 s（问题不同，仅供参考） |

**换算后的 T1 / T2（普通聊天）：**

| | 直连 DeepSeek | 经过 Hermes |
|---|---|---|
| T1（模拟） | 0.5 + 0.77 + 0.47 ≈ **1.7 s** | ≈ **1.9 s** |
| T2（模拟） | 0.5 + 1.37 + 0.31 ≈ **2.2 s** | 0.5 + 1.45 + 0.31 ≈ **2.3 s** |
| T2（真人） | ≈ **2.7 s** | ≈ **2.85 s** |

**冷启动：**

- Hermes 重启后的第一次请求会慢一些：API 首字 1.6 秒，语音链路第一句约 4.1 秒。
- 之后恢复正常。

### 4.2 Home Assistant：“把客厅灯关掉”

| 方案 | 灯实际熄灭（T0 起） | 听到“好了” | 用户说完 → 灯灭 |
|---|---|---|---|
| Hermes，先列设备再调用 | 2.16 s（n=5） | 2.75 s | ≈ 2.7 s |
| **Hermes + SOUL 设备表（当前配置）** | **1.49 s**（n=7，1.36 ~ 1.73） | **2.17 s** | **≈ 2.0 s** |
| 真人实测（当前配置） | 1.48 s | 2.08 s（第一句文本） | ≈ 2.0 s |

- 工具调用都是有效的：有设备表时只调用 1 次 `ha_call_service`；没有设备表时先 `ha_list_entities`，再 `ha_call_service`。
- 方案里“1 秒左右开始执行”的目标**没有达到**。耗时构成大约是：VAD 0.5 秒 + ASR 0.7 秒 + 一轮 LLM 决策约 0.7 秒 + HA 调用 < 0.05 秒。

另有 1 次异常样本：灯在 T0 之前就已经熄灭。原因未查明，因为演示 HA 没有开启历史记录。这个样本已从统计中剔除。

### 4.3 联网搜索：“今天 AI 圈有什么重要新闻？”

| 阶段（从 T0 起算） | 中位 |
|---|---|
| 播放“我查一下” | 1.43 s |
| 新闻内容第一句 | 4.14 s（4.01 ~ 4.58） |
| 用户听到“我查一下”（含 VAD 和 TTS） | ≈ 2.2 s |
| 用户听到新闻内容（含 VAD 和 TTS） | ≈ 4.9 s |

- 每次新闻查询大约调用 2 次 `web_search`（按 API 级测试观察）。
- 摘要质量良好：三条要闻，口语化，最后会问“想细听哪条？”。
- 如果没有“我查一下”这句垫话，用户会先静音等待约 4.5 秒。

### 4.4 记忆

| 用户说 | T0 → 第一句 | 结果 |
|---|---|---|
| 记住我晚上睡觉喜欢空调开二十五度 | 2.62 s（写入工具要多一轮） | 3/3 写入 `USER.md` |
| （新会话）我睡觉的时候空调应该开多少度？ | 1.54 s（记忆已在系统提示里，不需要调用工具） | 8/9 正确回答“二十五度”，1 次先答错后自我纠正（见 5.2） |

真人会话里，Hermes 在没有收到指令的情况下，**自动记住了**：

- 用户睡觉空调 26 度；
- 小猫“小超超”的故事、老板周超、黄妈妈。

之后在全新会话里问“小超超是谁？”，它能正确复述。这正好解决了基线里用户抱怨的“你咋就只有两秒钟的记忆”。

### 4.5 Skills：“我睡觉了，晚安”

- **执行过程：** 加载 `sleep-mode` Skill，读取记忆里的温度偏好，然后在 HA 里：
  - 关闭客厅灯和书房灯；
  - 把卧室空调设为 25 度；
  - 检查卧室窗户状态。
- **回答：** “灯关好了，卧室空调调到二十五度，窗户也关着，晚安。”
- **耗时：** API 级第一句 2.07 秒，所有工具在 1.74 秒内完成。

### 4.6 成本

| | 每次 LLM 调用的输入 token |
|---|---|
| 直连 DeepSeek（只有 xiaozhi 的提示词） | 32 |
| 经过 Hermes（系统提示 + 工具 schema + 记忆 + Skill 索引） | 约 7,600 |

- 带工具调用的回合会调用 LLM 2 ~ 3 次。
- 这部分是固定前缀，适合 DeepSeek 的上下文缓存，但输入 token 用量仍会明显上升。
- Tavily 免费额度是每月 1000 次，按每次新闻查询约 2 次搜索来估算用量。

---

## 5. 测试中发现的问题

| # | 问题 | 影响 | 处理 |
|---|---|---|---|
| 1 | 调用工具前，模型输出了英文“I'll turn off the living room light.”，会被音箱念出来 | 1 次 / 3 轮 | 在 SOUL.md 中规定“只说中文、控制设备前不说话”。之后 64 轮模拟对话和 27 轮真人对话中没有再出现 |
| 2 | 记忆写入后约 10 秒内新开会话，读到的记忆是空的，模型先答“二十六度”，又自我纠正，并把“用户自己的偏好我记一下吧”念了出来 | 1/9 | Hermes 写记忆时的竞态。真实使用中间隔通常更长，暂时接受 |
| 3 | Hermes 默认对 `deepseek-flash` 开启思考模式 | 首字会明显变慢 | 已配置 `reasoning_effort: none` |
| 4 | Hermes 不允许为命名 profile 单独启动 gateway | 部署方式要调整 | 使用专用容器和专用数据卷，容器内的默认 profile 就是 xiaoqi-home |
| 5 | 通过 SSH 执行 `docker pull` 失败（Windows 凭据助手） | 无法直接拉取镜像 | 在 Mac 上用 `crane` 拉取后，通过 `ssh … docker load` 导入 |
| 6 | DuckDuckGo、Brave 不可达 | 无法零配置联网 | 改用 Tavily |
| 7 | 流式输出以 `\n\n` 开头 | 无影响，bridge 显示正常 | 无需处理 |
| 8 | 仍被自动加载 1 个内置 Skill（`hermes-agent`） | Skill 索引略大 | 可忽略 |
| 9 | Hermes 重启后第一次请求慢 | 首句最多约 4 秒 | 建议重启后发一次预热请求 |
| 10 | 实体表写在 SOUL.md 里 | 新增设备时要手动更新 | 见第 6 节建议 |
| 11 | 演示阶段 Hermes API 曾对局域网开放 | 安全风险 | 已改为只绑定 `127.0.0.1:8642`，xiaozhi 通过 Docker 内网访问 |

---

## 6. 验收清单（对照方案第 16 节）

### 基础

| 项目 | 状态 | 说明 |
|---|---|---|
| Xiaozhi 可以正常连接 Hermes OpenAI API | ✅ | |
| Hermes 可以正常调用 DeepSeek Flash | ✅ | |
| 普通聊天正常 | ✅ | 真人连续聊了 27 轮 |
| Streaming 正常 | ✅ | |
| 小爱原生 TTS 正常 | ✅ | |
| 中途打断正常 | ⚠️ 未实测 | 真人测试时没有做打断。打断逻辑在 bridge 和 server，本次没有改动；Hermes 在客户端断开后是否会停止运行也未验证 |

### Agent

| 项目 | 状态 | 说明 |
|---|---|---|
| Web Search 成功 | ✅ | |
| Home Assistant 成功 | ✅ | 演示 HA |
| Memory 成功 | ✅ | 1 次竞态，见 5.2 |
| Skills 可以使用 | ✅ | |
| Tool Calling 稳定 | ✅ | 没有观察到多余的工具调用 |
| Cron | ❌ 未测试 | 见第 7 节 |

### 性能

| 项目 | 状态 | 说明 |
|---|---|---|
| 普通聊天延迟增加可接受 | ✅ | +0.06 ~ 0.1 秒 |
| 简单智能家居命令执行足够快 | ⚠️ | 用户说完约 2 秒灯灭，未达到“1 秒左右”的目标 |
| Agent 搜索期间无明显卡死 | ✅ | 约 2.2 秒先听到“我查一下” |
| Tool 不出现大量无效调用 | ✅ | |

---

## 7. 建议与下一步

1. **保留当前架构（Xiaozhi → Hermes → DeepSeek），暂不做 Router。** Hermes 在聊天路径上的开销在 0.1 秒以内，没有必要为聊天单独走 Fast Path。
2. **要缩短整体延迟，优先处理 VAD 和 ASR。** 这部分对所有请求都有效：
   - VAD `min_silence_duration` 从 500ms 调到 300 ~ 350ms，预计每轮快 0.15 ~ 0.2 秒，需要实测误切句的比例。
   - ASR 目前是 CPU 上跑 SenseVoice，约 0.7 秒，长句会成倍增长。可以评估流式 ASR（边说边识别）或更快的推理后端。
3. **家居控制如果要做到“1 秒动作”**，才需要考虑方案第 13 节的 Fast Path：用本地规则匹配“开/关 + 设备名”，直接调用 HA，其余请求仍交给 Hermes。按目前测量，最多能省掉约 0.7 秒的 LLM 决策时间，但还剩约 1.2 秒的 VAD 和 ASR 时间。
4. **接入真实 HA：**
   - 替换 `.env` 里的 `HASS_URL` 和 `HASS_TOKEN`；
   - 更新 `profile/SOUL.md` 的设备表（或改成一个“设备表” Skill，方便维护）；
   - 重新运行 `install.sh`。
5. **定时任务（Cron）需要一个“主动播报”通道。** Hermes 的 API Server 是“一问一答”，音箱不会主动拉取，所以定时任务的结果目前无法由音箱播报。可以在 bridge 上增加一个播报接口（调用 `speaker.play(text=…)`），作为 Hermes cron 的投递目标。这属于第二阶段。
6. **补做真人测试：** 中途打断，以及退出唤醒后的跨会话记忆。
7. **其他：** 固定 Hermes 镜像版本（当前是 `poc-749220e`），升级前重跑 `bench/` 做回归。在 Hermes 重启脚本里加一次预热请求。

---

## 附录 A：原始数据

`deploy/hermes/bench/results/`：

| 文件 | 内容 |
|---|---|
| `baseline_voice.jsonl`、`baseline2_voice.jsonl` | 直连 DeepSeek，模拟设备语音链路（两次，间隔约 1 小时，用于检查漂移） |
| `hermes_voice.jsonl`、`hermes2_voice.jsonl`、`hermes-final_voice.jsonl` | Hermes 模拟设备链路：初版、加入“我查一下”、最终版 |
| `hermes_ha*.jsonl/txt`、`hermes-devmap_ha*.jsonl/txt` | 家居控制与 HA 状态时间戳：先列设备 / 使用设备表 |
| `ab_llm.jsonl` | API 级交错 A/B |
| `real_baseline.json`、`real_hermes.json` | 真人语音日志计时（已去掉对话文本） |

## 附录 B：当前部署状态（mini PC）

| 容器 | 用途 | 内存 |
|---|---|---|
| `hermes` | Hermes gateway，只在 `127.0.0.1:8642` 和 Docker 网络 `xiaozhi-server_default` 上可访问 | ≈ 300 MB |
| `homeassistant-demo` | 演示 HA，`http://192.168.5.10:8123` | ≈ 230 MB |

xiaozhi-server 当前使用 `HermesAgentLLM`。切换命令：

```powershell
cd C:\Users\djcmy\Documents\develop\ai\open-xiaoai\deploy\hermes
powershell -ExecutionPolicy Bypass -File .\switch-llm.ps1 deepseek   # 切回直连
powershell -ExecutionPolicy Bypass -File .\switch-llm.ps1 hermes     # 切到 Hermes
```

每次切换前都会备份 `xiaozhi-server\data\.config.yaml`，备份文件名为 `.config.yaml.before-llm-*`。
