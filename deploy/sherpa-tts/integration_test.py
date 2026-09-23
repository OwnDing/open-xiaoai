import asyncio
import os
import queue

from config.config_loader import load_config
from core.utils.modules_initialize import initialize_tts


config = asyncio.run(load_config())
tts = initialize_tts(config)
asyncio.run(tts.text_to_speak("你好小七，本地语音合成测试成功。", True))

first = 0
middle = 0
last = 0
opus_bytes = 0
while True:
    try:
        item = tts.tts_audio_queue.get_nowait()
    except queue.Empty:
        break
    sentence_type, audio = item[0], item[1]
    name = sentence_type.name
    first += name == "FIRST"
    middle += name == "MIDDLE"
    last += name == "LAST"
    if isinstance(audio, bytes):
        opus_bytes += len(audio)

print(
    {
        "provider": type(tts).__module__,
        "first_messages": first,
        "opus_frames": middle,
        "last_messages": last,
        "opus_bytes": opus_bytes,
    }
)

mode = os.getenv("XIAOZHI_TTS_OUTPUT_MODE", "sherpa")
if mode == "native_xiaomi":
    if first != 1 or middle != 0 or last != 1 or opus_bytes != 0:
        raise RuntimeError("native_xiaomi did not produce text-only TTS events")
else:
    if first != 1 or middle == 0 or last != 1 or opus_bytes == 0:
        raise RuntimeError("sherpa did not produce the expected Opus stream")
