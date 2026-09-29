# 小爱音箱 + Xiaozhi + Hermes + DeepSeek 个人 AI 助理测试方案

## 1. 目标

在现有“小爱音箱 + Open-XiaoAI + Xiaozhi + DeepSeek”语音聊天方案基础上，引入 Hermes Agent，验证是否可以在尽量不牺牲语音响应速度的前提下，获得：

- 长期记忆
- Skills
- Function Calling / Tool Calling
- Web Search / 新闻查询
- Home Assistant 智能家居控制
- MCP
- 定时任务
- 更复杂的多步骤 Agent 能力

第一阶段以 POC 为主，不重构当前已经稳定的语音链路。

---

## 2. 当前架构

现有架构：

```text
小爱音箱 OH2P
    ↓
Open-XiaoAI
    ↓
Xiaozhi
    ├─ 唤醒
    ├─ VAD
    ├─ ASR
    ├─ 连续对话
    ├─ 中途打断
    └─ TTS / 小爱原生音色
    ↓
DeepSeek API
    ↓
普通聊天
```

现有方案已经解决了最重要的语音交互问题，因此第一阶段不修改 Open-XiaoAI 的音频链路。

---

## 3. 目标架构

第一阶段推荐架构：

```text
小爱音箱 OH2P
    ↓
Open-XiaoAI
    ↓
Xiaozhi
  ASR / VAD / 会话 / TTS
    ↓
OpenAI Compatible API
    ↓
Hermes Agent
    ↓
DeepSeek Flash
    │
    ├─ 普通聊天
    ├─ Memory
    ├─ Skills
    ├─ Web Search
    ├─ Home Assistant
    ├─ MCP
    ├─ Cron
    └─ 其他 Tools
```

核心思想：

> Xiaozhi 继续负责“耳朵和嘴巴”，Hermes 负责“大脑和行动”，DeepSeek Flash 负责底层推理。

---

## 4. 为什么使用 Hermes

Hermes 放在 Xiaozhi 与 DeepSeek 之间的主要价值不是单纯“再套一层 LLM”，而是提供 Agent Runtime。

它负责：

```text
用户语音
   ↓
Xiaozhi 转文字
   ↓
Hermes
   ↓
DeepSeek 判断用户意图
   ↓
决定：
├─ 直接回答
├─ 查询记忆
├─ Web Search
├─ Home Assistant
├─ MCP
├─ Skill
└─ 多步骤 Agent
```

因此用户不需要自己说：

> “调用 Home Assistant 工具。”

只需要说：

> “小七，把客厅灯关掉。”

Hermes + DeepSeek 自动判断应该调用智能家居 Tool。

---

## 5. 典型使用场景

### 5.1 普通聊天

用户：

> 小七，为什么猫喜欢钻纸箱？

执行：

```text
Xiaozhi
    ↓
Hermes
    ↓
DeepSeek Flash
    ↓
回答
```

这种请求不需要使用 Tool。

---

### 5.2 智能家居

用户：

> 小七，把客厅灯关掉。

执行：

```text
Hermes
   ↓
DeepSeek 判断需要 Home Assistant
   ↓
查询 / 定位设备
   ↓
调用 Home Assistant Service
   ↓
灯关闭
   ↓
“小七：好了。”
```

后续可以继续支持：

- 开灯 / 关灯
- 调节亮度
- 调节色温
- 控制空调
- 控制风扇
- 控制窗帘
- 查询温湿度
- 执行 HA Scene / Automation

---

### 5.3 新闻 / 联网查询

用户：

> 小七，今天 AI 圈有什么重要新闻？

执行：

```text
Hermes
   ↓
Web Search
   ↓
读取搜索结果
   ↓
DeepSeek 总结
   ↓
语音回答
```

---

### 5.4 记忆

用户：

> 小七，记住我晚上睡觉喜欢空调开 25 度。

执行：

```text
Hermes
   ↓
Memory
   ↓
写入长期偏好
```

之后用户说：

> 小七，我准备睡觉了。

系统可以结合 Memory：

```text
关闭卧室灯
↓
空调设置 25℃
↓
执行睡眠相关 Skill
```

---

### 5.5 Skills

Memory 更适合记住：

> “什么信息”。

Skills 更适合记住：

> “以后遇到这类事情应该怎么做”。

例如建立：

```text
Skill：睡觉模式

1. 关闭客厅灯
2. 关闭书房灯
3. 卧室空调设为 25℃
4. 检查门窗状态
5. 查询第二天天气
6. 给用户一句简短反馈
```

以后只需要说：

> 小七，我睡觉了。

---

## 6. Hermes Profile 建议

不要直接把 Hermes 所有能力全部开放给智能音箱。

建议创建一个独立 Profile：

```text
xiaoqi-home
```

第一阶段只开放：

```text
memory
session_search
skills

web_search
web_extract

homeassistant

cron
```

后续需要时再开放：

```text
MCP
weather
calendar
reminder
music
```

第一阶段建议关闭：

```text
terminal
filesystem
code_execution
computer_use
browser automation
delegation
```

原因：

1. 减少 Tool Schema
2. 减少 System Prompt
3. 提高 DeepSeek Tool 选择速度
4. 降低误调用概率
5. 减少家庭环境中的安全风险

---

## 7. 第一阶段 POC 原则

### 不修改

暂时不要修改：

- 小爱音箱固件
- Open-XiaoAI Client
- 唤醒词
- VAD
- ASR
- 打断逻辑
- 小爱原生 TTS
- 已经优化好的首段播放逻辑

### 只修改

把 Xiaozhi 当前：

```text
Xiaozhi
   ↓
DeepSeek API
```

替换为：

```text
Xiaozhi
   ↓
Hermes OpenAI Compatible API
   ↓
DeepSeek Flash
```

这是整个测试中最重要的原则：

> **尽可能只替换“AI 大脑”，不动语音链路。**

---

## 8. Hermes API

Hermes 可以作为 OpenAI Compatible API Server 对外提供服务。

预期形式：

```text
http://MINI_PC_IP:8642/v1/chat/completions
```

Xiaozhi 将 Hermes 当作普通 OpenAI API 使用。

示意配置：

```text
base_url:
http://127.0.0.1:8642/v1

model:
hermes-agent
```

Hermes 内部再配置：

```text
Provider:
DeepSeek

Model:
DeepSeek Flash
```

因此调用链为：

```text
Xiaozhi
    ↓
OpenAI API
    ↓
Hermes
    ↓
DeepSeek Flash
```

---

## 9. 为什么优先选择 DeepSeek Flash

智能音箱最大的体验指标不是模型 benchmark，而是：

> 从用户说完话，到音箱开始回答，需要多久？

DeepSeek Flash 的高速度非常适合 Agent Voice 场景。

普通聊天时：

```text
ASR
↓
Hermes
↓
DeepSeek Flash
↓
Streaming Response
↓
TTS
```

复杂任务时：

```text
DeepSeek
↓
Tool
↓
DeepSeek
↓
最终回答
```

Agent 模式一定会比纯聊天多一些延迟，因此底层模型必须尽可能快。

---

## 10. 第一阶段测试项目

建议只测试 4 类场景。

### Case 1：普通聊天

例如：

> 为什么天空是蓝色？

目的：

验证加入 Hermes 后，对普通聊天首字延迟增加多少。

---

### Case 2：Home Assistant

例如：

> 把客厅灯关掉。

目的：

验证：

- Tool 判断速度
- Home Assistant 执行速度
- Agent 是否会多做不必要推理

---

### Case 3：Web Search

例如：

> 今天 AI 圈有什么重要新闻？

目的：

验证：

- Hermes 能否自动判断需要联网
- Search 能力
- 搜索后的总结能力

---

### Case 4：Memory

第一轮：

> 记住我晚上睡觉喜欢空调开 25 度。

第二轮：

> 我睡觉的时候空调应该开多少度？

第三轮可以跨 Session 测试。

目的：

验证长期记忆是否真正生效。

---

## 11. 延迟测试指标

不要只记录“总耗时”。

重点记录：

### T1

```text
用户说完
↓
收到 LLM 第一个 Token
```

### T2

```text
用户说完
↓
小爱音箱开始播第一句话
```

对于智能音箱，T2 比 T1 更重要。

建议目标：

### 普通聊天

```text
T2 <= 1.5 ~ 2 秒
```

体验非常好。

### 简单 Tool

例如：

> 关闭客厅灯。

设备最好：

```text
1 秒左右开始执行
```

TTS 可以稍晚。

因为灯本身的变化就是用户反馈。

---

## 12. 第一阶段不要过度设计 Router

最初建议：

```text
所有用户请求
      ↓
Hermes
      ↓
DeepSeek Flash
```

让 Hermes 自己判断：

```text
聊天
控制
搜索
记忆
Skill
```

先测真实性能。

不要第一天就开发：

```text
Intent Router
↓
Chat Route
Agent Route
HA Route
```

否则很容易过度设计。

---

## 13. 如果 Hermes 导致普通聊天变慢

如果测试结果：

```text
直接 DeepSeek：
T2 = 1 秒

经过 Hermes：
T2 = 3~5 秒
```

说明 Hermes 对普通聊天路径过重。

第二阶段再增加 Fast Path：

```text
               ┌── DeepSeek Flash
               │   普通聊天
Xiaozhi → Router
               │
               └── Hermes
                   Agent 请求
```

例如：

```text
“讲个笑话”
    ↓
DeepSeek Flash

“把客厅灯关掉”
    ↓
Hermes

“查今天 AI 新闻”
    ↓
Hermes

“我昨天说了什么”
    ↓
Hermes
```

---

## 14. 未来完整架构

如果 POC 成功，可以逐步演进：

```text
                  ┌──────────────────┐
                  │  Xiaomi Speaker  │
                  │      OH2P        │
                  └────────┬─────────┘
                           │
                         Audio
                           │
                           ▼
                  ┌──────────────────┐
                  │   Open-XiaoAI    │
                  │ Wake / VAD / TTS │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │     Xiaozhi      │
                  │   Voice Layer    │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  Xiao7 Gateway   │
                  │   Optional       │
                  └──────┬─────┬─────┘
                         │     │
                 Chat    │     │ Agent
                         │     │
                         ▼     ▼
                  DeepSeek   Hermes
                  Flash       Agent
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
       Memory               Skills              Web

          │                    │                    │
          └───────────┬────────┴─────────┬──────────┘
                      │                  │
                      ▼                  ▼
               Home Assistant          MCP
                      │
                      ▼
               智能家居设备
```

---

## 15. 后续可实现能力

当第一阶段跑通后，可以逐步增加：

### 家庭能力

- 智能灯
- 空调
- 温湿度传感器
- 窗帘
- 门锁状态
- 人体传感器
- 摄像头事件
- 家庭场景

### Personal Agent

- 长期记忆
- 用户偏好
- 家庭成员偏好
- 日程
- 提醒
- 定时任务
- 新闻摘要
- 天气提醒

### Skills

例如：

```text
起床模式
睡觉模式
离家模式
回家模式
观影模式
工作模式
```

### MCP

以后可以让“小七”访问：

```text
Home Assistant
NAS
个人知识库
日历
邮件
文件
其他自建系统
```

---

## 16. 第一阶段验收条件

### 基础

- [ ] Xiaozhi 可以正常连接 Hermes OpenAI API
- [ ] Hermes 可以正常调用 DeepSeek Flash
- [ ] 普通聊天正常
- [ ] Streaming 正常
- [ ] 小爱原生 TTS 正常
- [ ] 中途打断正常

### Agent

- [ ] Web Search 成功
- [ ] Home Assistant 成功
- [ ] Memory 成功
- [ ] Skills 可以使用
- [ ] Tool Calling 稳定

### 性能

- [ ] 普通聊天延迟增加可接受
- [ ] 简单智能家居命令执行足够快
- [ ] Agent 搜索期间无明显卡死
- [ ] Tool 不出现大量无效调用

---

## 17. 当前推荐实施顺序

### Step 1

部署 Hermes。

### Step 2

Hermes 配置 DeepSeek Flash。

### Step 3

启动 Hermes OpenAI Compatible API。

### Step 4

使用 curl / Postman 单独验证：

```text
Hermes → DeepSeek
```

### Step 5

验证 Hermes Memory。

### Step 6

接入 Home Assistant。

### Step 7

验证：

```text
把客厅灯关掉
```

### Step 8

把 Xiaozhi 的 LLM Base URL 改成 Hermes。

### Step 9

进行四类 A/B 测试：

```text
聊天
HA
Web
Memory
```

### Step 10

记录 T1 / T2。

### Step 11

根据延迟决定是否增加 Fast Path Router。

---

# 18. 最终判断

当前最值得测试的结构是：

```text
小爱音箱
    ↓
Open-XiaoAI
    ↓
Xiaozhi
    ↓
Hermes
    ↓
DeepSeek Flash
```

不要首先重构整个系统，也不要先开发复杂 Router。

第一阶段的核心问题只有一个：

> **Hermes 能否在保持足够快语音响应的同时，为 Xiaozhi 增加 Memory、Skills、Web、Home Assistant 和 MCP 等 Agent 能力。**

如果答案是“可以”，那么当前的小爱音箱就可以从：

```text
AI 聊天音箱
```

升级成：

```text
长期在线的家庭个人 AI Agent
```

这将是整个方案最大的价值。
