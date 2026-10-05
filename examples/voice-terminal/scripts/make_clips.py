"""Synthesize test clips or terminal prompts with the deployed sherpa-tts or Edge TTS.

Run inside a container on the backend's Docker network, e.g.
  docker cp scripts/make_clips.py xiaozhi-esp32-server:/tmp/
  docker exec xiaozhi-esp32-server python /tmp/make_clips.py /tmp/p05-clips
  docker exec xiaozhi-esp32-server python /tmp/make_clips.py /tmp/prompts prompts --engine edge

sherpa writes WAV; edge (edge_tts, already in the xiaozhi-server image) writes
MP3 in --voice, which should match the voice the backend answers in.
"""

import argparse
import asyncio
import json
import urllib.request
import wave
from pathlib import Path

TTS_URL = "http://sherpa-tts:11996/tts"
CLIPS = {
    "stereo": "测试，这是立体声输出。请数一数，后面有几声嘀。",
    "handsfree": "测试，这是免提输出。请数一数，后面有几声嘀。",
    "answer": "今天晴，最高气温二十六度，最低十八度，傍晚有微风，适合出门散步。",
    "take_start": "开始录音，请读第一句。",
    "take_end": "录音结束。",
}
# Voice-terminal prompts (examples/voice-terminal, [session] *_prompt).
PROMPTS = {
    "wake": "我在。",
    "no_reply": "我没听清，再说一遍？",
    "goodbye": "有需要再叫我。",
}
# Spoken input for the end-to-end test (tests/e2e.toml).
E2E = {
    "wake_phrase": "你好小七。",
    "q_math": "一加一等于几？",
    "q_time": "现在几点了？",
}
SETS = {"p05": CLIPS, "prompts": PROMPTS, "e2e": E2E}


def synthesize(text):
    request = urllib.request.Request(
        TTS_URL,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rate = int(response.headers.get("X-Audio-Sample-Rate", "24000"))
        return response.read(), rate


async def synthesize_edge(text, voice, path):
    import edge_tts

    await edge_tts.Communicate(text, voice).save(str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", nargs="?", default="p05-clips")
    parser.add_argument("set", nargs="?", default="p05", choices=sorted(SETS))
    parser.add_argument("--engine", choices=("sherpa", "edge"), default="sherpa")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural", help="Edge voice")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in SETS[args.set].items():
        if args.engine == "edge":
            path = out / f"{name}.mp3"
            asyncio.run(synthesize_edge(text, args.voice, path))
            print(f"{path.name} {path.stat().st_size} bytes ({args.voice})")
            continue
        pcm, rate = synthesize(text)
        with wave.open(str(out / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        print(f"{name}.wav {len(pcm) / 2 / rate:.2f} s @ {rate} Hz")


if __name__ == "__main__":
    main()
