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
        # 静音多久后自动退出唤醒（秒）
        "timeout": 20,
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
