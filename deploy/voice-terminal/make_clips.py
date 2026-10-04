"""Synthesize the P0.5 announcement clips with the deployed sherpa-tts.

Run inside a container on the backend's Docker network, e.g.
  docker cp make_clips.py xiaozhi-esp32-server:/tmp/
  docker exec xiaozhi-esp32-server python /tmp/make_clips.py /tmp/p05-clips
"""

import json
import sys
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


def synthesize(text):
    request = urllib.request.Request(
        TTS_URL,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rate = int(response.headers.get("X-Audio-Sample-Rate", "24000"))
        return response.read(), rate


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "p05-clips")
    out.mkdir(parents=True, exist_ok=True)
    for name, text in CLIPS.items():
        pcm, rate = synthesize(text)
        with wave.open(str(out / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        print(f"{name}.wav {len(pcm) / 2 / rate:.2f} s @ {rate} Hz")


if __name__ == "__main__":
    main()
