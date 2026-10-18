# 小七放本地音乐

小七用音箱播放电脑里的音乐（离线，不涉及在线曲库和会员）。代码在
`examples/xiaozhi/xiaozhi/services/music/`，provider 的入口在 `deploy/hermes/xiaozhi-provider/hermes.py`
（`MusicShortcut`），Hermes 工具在 `deploy/hermes/profile/mcp/xiaoqi_music/`。

## 怎么工作

```
"你好小七，播放梁静茹的勇气"
  → 桥接：唤醒词一出现，正在放的音乐先变小（xqmusicvol −20 dB）
  → xiaozhi-esp32-server → hermes.py：像“播放…/暂停/下一首”这样的话先 POST 桥接 /music/command
        桥接接了：小七说一句短回答（“好的，梁静茹的勇气。”），回答完对话结束，音乐恢复音量
        桥接不接（不是点歌，或曲库里没有且话里没提歌）：照常交给 Hermes
  → 桥接在音箱上运行 /tmp/xq-music/xqmusic -f http://<桥接>:4400/music/track/<id>.mp3
```

- **播放器**：音箱自带的 `miplayer`（libxiaomimediaplayerlite，基于 VLC），从桥接的 HTTP 拉文件。复制成
  `/tmp/xq-music/xqmusic` 运行：原生 TTS 停播时执行 `busybox killall miplayer`，它按可执行文件匹配，
  符号链接也会被杀掉，复制出来的不会。
- **单独的音乐音量**：`xqmusic` 用自己的 ALSA 配置（`ALSA_CONFIG_PATH=/tmp/xq-music/alsa.conf`，
  只对这个进程生效），把 `default` 换成 softvol `xqmusicvol` → `Playback`（主音量 `mysoftvol`）→ dmix。
  “你好小七”只调 `xqmusicvol`，小七的回答（`aplay`/`miplayer` 走原来的 `default`）音量不变。
  回采声道 ch3 在 dmix 之后，回声消除照样覆盖音乐，放歌时唤醒词也能用。
- **曲库**：读 ID3v2/ID3v1、FLAC Vorbis 注释、WAV 长度（自己解析，不装 mutagen）；GBK 标签和被转成
  Latin-1 字符的 GBK（`Áº¾²Èã` → 梁静茹）都能还原。没标签时用“歌手/专辑/文件名”，文件名
  `A - B` 中哪边是歌手按已知歌手名判断。同一首歌（标题+歌手的拼音相同）只留一个，按 `formats`
  的顺序挑格式（mp3 优先）。比较名字时还比不带声调的拼音：同音字、繁体都能找到。索引缓存在
  `/app/logs/music-index.json`，每 10 分钟重读一次目录（只给新文件读标签）。
- **队列**：点一首歌后接着放同一位歌手的其他歌（随机），点歌手放他的歌，“放首歌”放全部；放完从头。
  开头 3 秒内就结束的算放不了，跳过；连续 3 首放不了就停。mp3 记录停下的位置，“继续播放”时从那里接着放
  （发那一秒之后的帧，播放器自己找帧头）；flac 从头放。
- **问曲库**：“曲库有多少首歌”“有哪些歌手”“有没有周杰伦的歌”“陈奕迅有几首歌”“这首歌是哪张专辑的”由桥接直接
  从曲库回答（不经过大模型，回答完接着听）；更开放的问题由 Hermes 用 `xiaoqi_music` 工具查。
- **桥接的地址**：默认用音箱连桥接时的地址（音箱上 `netstat` 里 4399 的对端），可用 `music.base_url` 指定。

## 实测（2026-10-18，OH2P，mini PC 双网卡：音箱侧 192.168.5.10）

- 格式：mp3（歌曲）、flac、wav 能放；wma 报 `EncounteredError`（不收进曲库）。一个 2015 年的单声道
  64 kbps 播客 mp3 让播放器的解码线程崩溃（`vlc-decoder: unhandled alignment fault`），所以默认排除
  `Podcasts`，其余放不了的会被跳过。
- `ALSA_CONFIG_PATH` 对 `miplayer` 生效（新的 softvol 控件被创建）；复制出来的 `xqmusic` 在
  `busybox killall miplayer` 后仍在播放，按 PID 能停。
- 真实曲库：663 个音频文件 → 去重后 338 首（mp3 302、flac 35、wav 1），首次扫描 13.7 s（Docker Desktop
  挂载 Windows 目录），有缓存后 2.5 s。点歌示例：“梁静如”→ 梁静茹 16 首；“一千个伤心的理由”→ 张学友
  《一千個傷心的理由》；“梁静茹的勇气”→ 曲库没有《勇气》，放梁静茹的歌；“布兰妮”需要在 `aliases` 里配。

## 测试

- 桥接：`tests/test_music_library.py`（标签、曲库、意图）、`tests/test_music_player.py`（播放器对着假音箱、
  HTTP、唤醒和对话结束时的音量）。需要 Python 3.12 和 pypinyin，在桥接镜像的临时容器里跑：
  `python -m unittest tests.test_music_library tests.test_music_player`。
- provider：`cd deploy/hermes/xiaozhi-provider && python3 -m unittest test_hermes`。
- Hermes 工具：`cd deploy/hermes/profile/mcp && python3 -m unittest test_xiaoqi_music`。

## 现场试听清单

1. “你好小七，播放梁静茹的歌” → 小七说“好的，播放梁静茹的歌。”，对话结束，音乐正常音量。
2. 放歌时“你好小七” → 音乐立刻变小，提示语音量正常；问一句别的（“现在几点”）→ 回答音量正常；
   对话结束（说“拜拜”或等 20 秒）→ 音乐恢复。
3. “你好小七，暂停” → 音乐马上停，小七不说话，对话结束。
4. “你好小七，继续播放” → 从停下的地方接着放（mp3）。
5. “下一首”“上一首”“这是什么歌”“单曲循环”。
6. 一首放完 → 自动放下一首。
7. “小爱同学”在放歌时仍能用（音乐不变小，小爱自己的回声消除处理）。
8. “曲库有多少首歌”“有哪些歌手”“有没有周杰伦的歌”。

## 上线后修的问题（2026-10-18 晚）

- `XiaoAI.run_shell` 返回客户端的 JSON 字符串，播放器当成对象读 `.stdout`，第一次点歌 500，provider 交给了
  Hermes，它去调 HA `media_player.play_media` 失败。加了 `shell_results`，测试里的假音箱也改成返回 JSON。
- “这是首什么歌”“暂停，拜拜”没认出来（只认“这是什么歌”，结尾的“拜拜”没去掉），被 Hermes 接走后它说“好，先暂停”
  其实没停。
- 正在放歌时说“播放”会换一首随机歌；改为接着放当前这首。随便放时说出放的是哪首。
- 桥接重启后不记得正在放的歌：单说“暂停”时先看音箱上还有没有 xqmusic 在放。
- 问曲库（总数、歌手、有没有某首、专辑）加到桥接；Hermes 的 `xiaoqi_music` 工具上线后，“曲库里都有谁”这类说法
  由 Hermes 查工具回答，“暂请播放”（暂停听错）也由它调 `music_control` 停掉。
- Hermes 用 `music_play("周杰伦 青花瓷")` 这类写法点歌时找不到（只认“周杰伦的青花瓷”），它就说曲库没有。
  现在歌手和歌名之间用空格、横线、括号或什么都不加、顺序反过来都能找到（歌手名也按拼音比，“梁静如偶阵雨”）。
