> [!NOTE]
> **维护状态：活跃更新中。** 本 Fork 每天在真实家庭中使用：客厅的小爱音箱、书房的蓝牙音箱，共用小智服务端、Hermes Agent 和 Home Assistant。Fork 自 [idootop/open-xiaoai](https://github.com/idootop/open-xiaoai)（原项目已归档）。

# Open-XiaoAI · 小七

**把小爱音箱变成真正的 AI 智能管家：听得懂，会做事，能学会你家的规矩，还会主动开口。**

![](./docs/images/cover.jpg)

## 真正的智能，现在开始

2017 年，当全球首款千万级销量的智能音箱诞生时，我们以为触摸到了未来。但很快发现，这些设备被困在「指令-响应」的牢笼里：它能执行命令，却不会主动思考；它有千万用户，却只有一套思维。

**真正的智能不应被预设的代码逻辑所束缚，而应像生命体般在交互中进化。**

现在，这句话开始成真。Open-XiaoAI 接管小爱音箱的“耳朵”和“嘴巴”，接入小智服务端和 [Hermes Agent](https://github.com/NousResearch/hermes-agent)，再通过 Home Assistant 连上家里的设备：不只米家，海尔智家等其他品牌的设备也一样。住在音箱里的“小七”：

- **会做事**：说一句话，设备真的开关；查状态先去看，不凭印象回答。
- **会安排**：“两个小时后关鱼缸灯”，到点自己执行，做完说一声。
- **能学会**：“以后我说‘我回来了’，就开客厅灯”，教一次就记住；“洗衣机洗完了提醒我”，它自己去盯。
- **会开口**：家里有事主动播报；夜里不打扰，漏水这种大事照样叫醒你。

**不用打开 App，不用写自动化，也没有预设的场景。** 每家的规矩不一样，全部由你用语音教会它。

## 小七能做什么

| 你这样说 | 小七会 |
| --- | --- |
| “把客厅灯关掉” | 通过 Home Assistant 真正关灯，再说“好了”；没执行成功，不会说做了 |
| “冰箱冷冻室现在几度？” | 现查设备状态再回答 |
| “今天有什么新闻？” | 先说“我查一下”，联网搜索后播报摘要 |
| “两个小时后关鱼缸灯”“晚上十点关空调” | 建一个定时任务，到点自动执行，再在小爱上说一声 |
| “半小时后提醒我关火” | 到点在小爱上提醒你 |
| “以后我说‘我回来了’，就开客厅灯，空调调到 26 度” | 复述一遍，你说“好”才保存成场景；以后说这句话就执行 |
| “洗衣机洗完了提醒我” | 建一个一次性联动：洗完时提醒你，提醒过后自动失效 |
| “主卧开关双击的时候，把书房灯关掉” | 建一个长期联动，由 Home Assistant 自己运行 |
| “阳台漏水了马上告诉我，半夜也要说” | 建一个紧急联动：一漏水就播报，勿扰时段也照样响 |
| “现在有哪些联动？”“把洗衣机那个删掉” | 查看、修改、删除、试运行教过的场景和联动 |
| “我睡觉了” | 一次完成关灯、按记忆里的偏好设置空调、检查窗户 |
| “记住我睡觉时空调开 26 度” | 写进长期记忆，以后自动参考 |
| 在书房问“这个房间的灯开着吗” | 书房的音箱知道自己在书房，去查书房灯 |

### 不只米家：一个小七管全屋

小七不直接对接某个品牌，而是通过 [Home Assistant](https://www.home-assistant.io/) 控制设备，所以不同品牌的设备能放在一起说、一起联动。比如“洗衣机洗完了提醒我”，洗衣机是海尔的，播报用的是小米的小爱音箱。

作者家里的 15 台设备、300 多个可控制和查询的项目，已经全部接入小七，日常在用：

| 品牌 / 接入方式 | 设备 |
| --- | --- |
| **米家**：小米官方 [Xiaomi Home](https://github.com/XiaoMi/ha_xiaomi_home) 集成，11 台 | 五个房间的灯、Aqara 墙壁开关（单击 / 双击 / 长按）、鱼缸插座、电风扇、红外遥控的电视、水浸传感器、小爱音箱 |
| **海尔智家**：通过 HACS 安装的 [Haier](https://github.com/banto6/haier) 集成，4 台 | 冰箱（冷藏 / 冷冻温度、门状态）、滚筒洗衣机（洗涤阶段、剩余时间）、干衣机、净水机 |

其他 Home Assistant 能接入的品牌和平台，接进来后也可以交给小七，作者实测过的是米家和海尔。新设备接入后，在 Home Assistant 的“设置 → 语音助手”里把它设为公开，再重新生成一次设备表，小七就认识它了。👉 [Home Assistant 接入米家与海尔](deploy/homeassistant/README.md)

### 不需要人操作

- **用说的就能建规则**：小七把你的话翻译成 Home Assistant 的场景（脚本）和联动（自动化）。保存前会检查用到的设备、动作和状态值都真实存在，不对就问你。
- **规则由 Home Assistant 自己运行**：联动不依赖大模型在线，触发又快又稳。在 Home Assistant 界面里也能看到、修改、删除它们。
- **定时任务到点自动执行**：由 Hermes 的定时任务负责，执行完主动播报结果。
- **场景口令跨对话有效**：教过的“我回来了”，换一次对话、过几天再说，照样执行。

### 主动开口，但懂分寸

- 联动、提醒、定时任务都通过客厅的小爱主动播报，用的是小爱原生音色。
- 勿扰时段跟随小爱自己的设置（米家 App 里改），这段时间普通消息自动静音。
- 漏水、烟雾、燃气这类安全报警例外，半夜也会响。

### 安全边界

- 门锁、燃气、热水器、取暖器这类高风险设备，不允许放进场景或联动，需要时当面直接说。
- 空调、窗帘、电视放进联动时，必须同时播报一声，让你知道它动了。
- 场景和长期联动先复述、你同意才保存；一次性提醒直接建好，用完即止。
- 只查看和修改自己创建的规则，不动你在 Home Assistant 里原有的自动化。
- 家里人之间说话也会被听到：刚安排完定时，又听到一句含糊的“现在关”，小七会先问清楚，不会贸然动设备。

## 真实对话

以下摘自实际测试记录：

```text
你：以后阳台漏水了马上告诉我，半夜也要说
小七：我打算这样建：阳台水浸传感器一旦检测到漏水，马上在客厅小爱音箱大声提醒你，半夜也会响。要我保存吗？
你：好
小七：好，以后阳台一漏水，我马上在客厅小爱音箱喊你，半夜也不会静音。

你：以后我说“我出门了”，就把书房灯关掉
小七：好，以后你说“我出门了”，我就把书房灯关掉。要我保存吗？
你：好
（换一个新对话）
你：我出门了
小七：好，书房灯关掉了，出门注意安全。

你：记得今天 11 点钟关闭鱼缸灯
小七：好，今天上午十一点整关鱼缸插座，关好我会说一声。
（11:01，鱼缸灯自动关闭，客厅小爱：“鱼缸插座关好了。”）
```

## 它是怎么工作的

```text
客厅：小爱音箱 ⇄ Open-XiaoAI 桥接 ───────┐
书房：蓝牙音箱 ⇄ 电脑语音终端 ─────────────┼⇄ 小智服务端 ⇄ Hermes Agent ⇄ DeepSeek
其他房间：USB 麦克风 / ESP32 小智硬件 ─────┘  唤醒·识别·合成    │
                                                              ├─ 长期记忆 / Skills / 联网搜索
                                                              ├─ 定时任务
                                                              └─ Home Assistant ── 米家、海尔智家……
                                                                  ├─ 设备控制与状态查询
                                                                  ├─ 场景（脚本）与联动（自动化）
                                                                  └─ 小七播报 → 客厅小爱
```

- **小智服务端**负责“耳朵和嘴”：唤醒、语音识别、语音合成。**Hermes** 负责“想和做”：理解意图、调用工具、记住偏好。
- **场景与联动**由一个小型 MCP 服务（`home_rules`）提供给 Hermes：校验、风险分级，再写入 Home Assistant。
- **每台设备独立**：小爱用原生音色，电脑终端可选 Edge 流式或离线 Sherpa 语音。房间、音色、回答方式写在服务端配置里，不写死在程序中。

## 稳定性与体验

小七要每天用，稳定比炫技重要。本 Fork 在真实环境里逐项实测、修正：

- **唤醒更准**：给“你好小七”单独设阈值，扩大解码搜索，两路错开检测。离线测试 23 遍平均认出 22.6 遍，20 分钟电视声音里零误唤醒。👉 [唤醒率测试](docs/xiaoai-wake-rate-test.md)
- **追问不漏**：每轮开始听之前重置说话检测模型。以前它运行久了，会把回答之后的追问当成静音。
- **网络抖动不失聪**：心跳和发送卡住检测，断线快速重连；音频改用二进制帧，流量从约 92 KB/s 降到 37 KB/s。断网 30 秒，网络恢复后 1 秒内连回。👉 [音频健康日志与连接恢复](deploy/audio-health/README.md)
- **响应快**：接入 Hermes 只比直连大模型多约 0.1 秒；从说完话到灯灭约 2 秒。👉 [接入与延迟测试报告](docs/xiaoai-xiaozhi-hermes-latency-report.md)
- **小爱原生音色**：回答文字交给音箱自带的语音合成，听起来就是小爱本身；也可切回服务端流式 Sherpa 语音。👉 [TTS 输出模式](deploy/sherpa-tts/README.md)
- **长期运行可排查**：音箱、桥接、终端、后端各自记录音频健康日志，出问题能对照到每 10 秒。

## 不用小爱音箱也行

一台带麦克风的普通蓝牙音箱（或 USB 麦克风 + 音箱），接在家里常开的电脑上，就是一个独立的语音终端：说“你好小七”唤醒，能力和小爱一样，不需要刷机。它和小爱共用同一套后端，谁听到的问题就由谁回答，多台同时提问互不串话；终端在 Windows 上开机自启，断线和蓝牙断开后自动恢复。

目前在 Windows 11 mini PC + 京鱼座蓝牙小黑胶上验收。这台音箱的麦克风只有 8 kHz 通话音质，近距离可用，远场一般；换 USB 会议麦克风效果更好。👉 [电脑语音终端](examples/voice-terminal/README.md) · [多终端方案与测试记录](docs/cross-platform-voice-terminal-plan.md)

## 演示视频

👉 [小爱音箱 + Hermes Agent，让真正的 AI 管家进入你家](https://www.bilibili.com/video/BV1hhao6cEfq)

[![](./promo-video/output/cover.jpg)](https://www.bilibili.com/video/BV1hhao6cEfq)

这支宣传片从分镜、3D 场景、配音、配乐到剪辑，全部由 AI（Claude Opus 5.5）编写代码完成。制作过程、原始提示词和可复用的方法见 👉 [用 AI 制作精美的产品宣传片](docs/ai-promo-video-guide.md)，分镜与源码见 [`promo-video/`](promo-video/README.md)。

👉 [小爱音箱接入 DeepSeek！这才是真正的 AI 智能管家！（手把手教你用 AI 完成小爱音箱刷机）](https://www.bilibili.com/video/BV1Lph86ZEfd)

[![](./docs/images/flash-ai.jpg)](https://www.bilibili.com/video/BV1Lph86ZEfd)

👉 [小爱音箱接入小智 AI 演示视频](https://www.bilibili.com/video/BV1TxJhzvEhz)

[![](./docs/images/xiaozhi.jpg)](https://www.bilibili.com/video/BV1TxJhzvEhz)

👉 [小爱音箱自定义唤醒词演示视频](https://www.bilibili.com/video/BV1YfVUz5EMj)

[![](./docs/images/kws.jpg)](https://www.bilibili.com/video/BV1YfVUz5EMj)

👉 [小爱音箱接入 MiGPT 演示视频](https://www.bilibili.com/video/BV1N1421y7qn)

[![](./docs/images/migpt.jpg)](https://www.bilibili.com/video/BV1N1421y7qn)

## 快速开始

> [!IMPORTANT]
> 刷机教程仅适用于 **小爱音箱 Pro（LX06）** 和 **Xiaomi 智能音箱 Pro（OH2P）** 这两款机型，**其他型号**的小爱音箱请勿直接使用！🚨
> 没有这两款音箱？用电脑上的普通蓝牙 / USB 音箱也可以，见下方“不刷机”。

**小爱音箱**

1. 刷机更新小爱音箱补丁固件，开启并 SSH 连接到小爱音箱 👉 [教程](docs/flash.md) · [视频：用 AI 帮你刷机](https://www.bilibili.com/video/BV1Lph86ZEfd)
2. 在小爱音箱上安装 Client 端补丁程序，使用本仓库 [Releases](https://github.com/OwnDing/open-xiaoai/releases) 里 `client-` 开头的版本 👉 [教程](packages/client-rust/README.md)
3. 部署小爱桥接和小智服务端 👉 [小爱音箱接入小智 AI](examples/xiaozhi/README.md) · [TTS 输出模式](deploy/sherpa-tts/README.md)
4. 部署 Home Assistant 并接入米家、海尔等设备，再部署 Hermes。定时任务、场景与联动、主动播报随 Hermes 配置一起安装，装好就能用语音教 👉 [Home Assistant](deploy/homeassistant/README.md) · [Hermes 部署](deploy/hermes/README.md)

**不刷机：普通蓝牙 / USB 音箱**

1. 在常开的电脑上部署小智服务端、Hermes 和 Home Assistant 👉 [Sherpa / 小智服务端](deploy/sherpa-tts/README.md) · [Hermes](deploy/hermes/README.md) · [Home Assistant](deploy/homeassistant/README.md)
2. 把带麦克风的蓝牙音箱（或 USB 麦克风 + 音箱）接到电脑上，安装并运行语音终端 👉 [电脑语音终端](examples/voice-terminal/README.md)

**更多玩法**：[自定义唤醒词](examples/kws/README.md) · [接入 MiGPT（完美版）](examples/migpt/README.md) · [接入 Gemini Live API](examples/gemini/README.md) · [多台音箱组立体声](examples/stereo/README.md)

以上皆为抛砖引玉，你也可以亲手编写自己想要的功能，未来由你定义！

## 文档

| 文档 | 内容 |
| --- | --- |
| [Home Assistant 接入](deploy/homeassistant/README.md) | 米家官方集成、HACS 与海尔智家集成、让小七认识新设备 |
| [Hermes 部署说明](deploy/hermes/README.md) | 接入方式、定时任务、语音教的场景与联动、主动播报、工具调用防护 |
| [电脑语音终端](examples/voice-terminal/README.md) | 安装、配置、开机自启、多设备共用一个后端 |
| [TTS 输出模式](deploy/sherpa-tts/README.md) | 小爱原生音色与 Sherpa 流式语音的切换和调优 |
| [音频健康日志](deploy/audio-health/README.md) | 各环节的采集统计、连接卡住与重连的实测 |
| [唤醒率测试](docs/xiaoai-wake-rate-test.md) | “你好小七”漏唤醒的原因、调参过程和结果 |
| [接入与延迟测试报告](docs/xiaoai-xiaozhi-hermes-latency-report.md) | Hermes 对各类请求的延迟影响 |
| [多终端语音接入方案](docs/cross-platform-voice-terminal-plan.md) | 不用小爱音箱的语音终端方案与各阶段测试 |

## 相关项目

> [!TIP]
> 技术的意义在于分享与共创。如果你打算或正在使用本项目做些有趣的事情，欢迎提交 PR 或 issue 分享你的项目和创意。✨

如果你不想刷机，或者不是小爱音箱 Pro，下面的项目或许对你有用：

- https://github.com/idootop/mi-gpt
- https://github.com/idootop/migpt-next
- https://github.com/yihong0618/xiaogpt
- https://github.com/hanxi/xiaomusic

## 参考链接

如果你想要了解更多技术细节，下面的链接可能对你有用：

- https://github.com/yihong0618/gitblog/issues/258
- https://github.com/jialeicui/open-lx01
- https://github.com/duhow/xiaoai-patch
- https://javabin.cn/2021/xiaoai_fm.html
- https://xuanxuanblingbling.github.io/iot/2022/09/16/mi/

## 免责声明

1. **适用范围**
   本项目为开源非营利项目，仅供学术研究或个人测试用途。严禁用于商业服务、网络攻击、数据窃取、系统破坏等违反《网络安全法》及使用者所在地司法管辖区的法律规定的场景。
2. **非官方声明**
   本项目由第三方开发者独立开发，与小米集团及其关联方（下称"权利方"）无任何隶属/合作关系，亦未获其官方授权/认可或技术支持。项目中涉及的商标、固件、云服务的所有权利归属小米集团。若权利方主张权益，使用者应立即主动停止使用并删除本项目。

继续下载或运行本项目，即表示您已完整阅读并同意[用户协议](agreement.md)，否则请立即终止使用并彻底删除本项目。

## License

MIT License © 2024-PRESENT [Del Wang](https://del.wang)
