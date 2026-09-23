import asyncio

from config.config_loader import load_config
from core.utils.modules_initialize import initialize_tts


async def main():
    config = await load_config()
    tts = initialize_tts(config)

    await tts.text_to_speak("你好，我是小七。", False)
    pending_after_first = len(tts.pcm_buffer)

    await tts.text_to_speak("这是连续音频的第二句。", True)
    pending_after_last = len(tts.pcm_buffer)

    result = {
        "provider": type(tts).__module__,
        "pending_pcm_after_first": pending_after_first,
        "pending_pcm_after_last": pending_after_last,
    }
    print(result)

    if pending_after_first == 0:
        raise RuntimeError("The first sentence was padded or flushed independently")
    if pending_after_last != 0:
        raise RuntimeError("The final answer did not flush the remaining PCM")


asyncio.run(main())
