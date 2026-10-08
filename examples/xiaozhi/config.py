import asyncio


async def before_wakeup(speaker, text, source):
    """
    处理收到的用户消息，并决定是否唤醒小智 AI

    - source: 唤醒来源
        - 'kws': 关键字唤醒
        - 'xiaoai': 小爱同学收到用户指令
    """
    if source == "kws":
        # 播放唤醒提示语
        await speaker.play(text="你好主人，请问有什么吩咐？")
        # 返回 True 唤醒小智 AI
        return True

    if source == "xiaoai" and text == "召唤小智":
        # 打断原来的小爱同学
        await speaker.abort_xiaoai()
        # 等待 2 秒，让小爱 TTS 恢复可用
        await asyncio.sleep(2)
        # 播放唤醒提示语（如果你不使用自带的小爱 TTS，可以去掉上面的延时）
        await speaker.play(text="小智来了，主人有什么吩咐？")
        # 唤醒小智 AI
        return True


async def after_wakeup(speaker):
    """
    退出唤醒状态
    """
    await speaker.play(text="主人再见，拜拜")


APP_CONFIG = {
    "wakeup": {
        # 自定义唤醒词列表（英文字母要全小写）
        "keywords": [
            "天猫精灵",
            "小度小度",
            "豆包豆包",
            "你好小智",
            "你好小爱",
            "hi siri",
            "hey siri",
        ],
        # 单独调整某个唤醒词的检测阈值（0-1，越小越容易唤醒，也越容易误唤醒），
        # 例如 {"你好小智": 0.1}；没列出的词使用默认值 0.2。
        "keyword_thresholds": {},
        # 唤醒检测保留的候选数，越大越不容易漏，也越耗 CPU（默认 8）。
        "max_active_paths": 16,
        # 同时运行几路唤醒检测，各路起点错开多少毫秒；任一路认出即唤醒。
        # 模型按 320 ms 一块处理音频，错开半块的两路漏掉的不是同一批；[0] 只用一路。
        "stream_offsets_ms": [0, 160],
        # 静音多久后自动退出唤醒（秒）
        "timeout": 20,
        # 退出播报后的余音保护时间（ms），结束后清理唤醒识别状态。
        "exit_guard_ms": 300,
        # 语音识别结果回调
        "before_wakeup": before_wakeup,
        # 退出唤醒时的提示语（设置为空可关闭）
        "after_wakeup": after_wakeup,
    },
    "vad": {
        # 语音检测阈值（0-1，越小越灵敏）
        "threshold": 0.10,
        # 最小语音时长（ms）
        "min_speech_duration": 250,
        # 最小静默时长（ms）
        "min_silence_duration": 500,
        # 只说了很短一句（如“啊”“嗯”）时，多等一会儿再判定说完，
        # 这样“啊……国庆不是八天”不会被截成“啊”。
        "short_utterance_duration": 800,
        "short_utterance_silence": 1000,
        # 小七说完后只留这段时间避开余音，然后马上开始听（ms）
        "tts_end_guard_ms": 300,
        # 说完后服务端多久没有识别结果，就提示重说并重新开始听（秒）
        "no_reply_timeout": 5,
        "no_reply_prompt": "我没听清，再说一遍？",
    },
    "barge_in": {
        # 小七说话时喊唤醒词可以打断她，然后直接说新的问题（需要 echo_reference）。
        "enabled": True,
        # 让音箱同时发回它正在播放的声音，桥接据此消除回声。需要本仓库的音箱客户端；
        # 旧客户端会忽略这个请求，照旧发送单声道录音（此时不能打断）。
        "echo_reference": True,
        # 打断后播放的提示音（音箱上的文件，留空则不播放）
        "prompt_tone": "/usr/share/common_sound/wakeup.opus",
        # 一口气说“你好小七，明天天气怎么样”时，唤醒词认出时已经过去一小段，
        # 从认出的位置往回多取这么多毫秒接着听，不丢开头。
        "keyword_tail_ms": 100,
        # 刚放过声音的那一小段（播放中、停播后 echo_vad_hangover_ms 内），消除后剩下的小七的声音
        # 仍可能被当成说话；这段时间里说话检测用这个更高的阈值（真人说话约 1.0）。
        "echo_vad_threshold": 0.7,
        "echo_vad_hangover_ms": 300,
        # 打断时比较“回声消除后剩下的声音”和“消掉的回声”（dB）。设成数字（如 -17）后，
        # 低于它的唤醒当作小七自己的声音忽略；None 只记录在健康日志里。
        "near_end_min_db": None,
        # 音箱录音：一个麦克风 + 播放回采声道（OH2P 的 hw:0,3 第 4 声道）
        "capture": {
            "pcm": "Capture",
            "channels": 4,
            "sample_rate": 48000,
            "mic_channel": 0,
            "ref_channel": 3,
            "mic_shift": 14,
            "ref_shift": 16,
        },
        "echo_canceller": {
            # 回声尾巴长度（帧，每帧 16 ms）；8 帧在 3 米、音量 75 时也能认出唤醒词
            "taps": 8,
            # 回声路径的平均时长（秒）
            "tau_s": 3.0,
            # 消除后放大多少倍，回到原来单声道录音的音量
            "output_gain": 64,
        },
    },
    "tts_output": {
        # 可选："sherpa"（服务端音频流）或 "native_xiaomi"（音箱原生音色）
        # Docker 部署可通过 XIAOZHI_TTS_OUTPUT_MODE 环境变量覆盖。
        "mode": "native_xiaomi",
        "native_xiaomi": {
            # 第一段立即播放；后续文本按目标长度或短暂等待进行合并。
            "target_chars": 80,
            "max_chars": 120,
            "flush_delay_ms": 250,
            # 已合成但尚未播放的最大段数。
            "prefetch_segments": 2,
            "generate_timeout_ms": 5000,
            "play_timeout_ms": 10 * 60 * 1000,
            # miplayer 偶发不退出时，按音频时长动态终止播放。
            "play_min_timeout_ms": 15000,
            "play_timeout_grace_ms": 8000,
            "max_file_bytes": 8 * 1024 * 1024,
            "max_total_bytes": 8 * 1024 * 1024,
        },
    },
    "xiaozhi": {
        "OTA_URL": "https://api.tenclass.net/xiaozhi/ota/",
        "WEBSOCKET_URL": "wss://api.tenclass.net/xiaozhi/v1/",
        "WEBSOCKET_ACCESS_TOKEN": "", #（可选）一般用不到这个值
        "VERIFICATION_CODE": "", # 首次对话时，验证码会在这里更新
        "DEVICE_ID": "", # 如果没有提示绑定设备，则将 DEVICE_ID 清空后，重启应用再次尝试
    },
}
