import json
import time
import urllib.request


for text in (
    "你好，我是小七。",
    "两个角色？",
    "今天天气不错，适合出去散步。",
    "现在使用本地语音合成，为你提供更加流畅的语音服务。",
):
    payload = json.dumps(
        {"text": text, "speed": 1.0}, ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(
        "http://sherpa-tts:11996/tts",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=60) as response:
        first = response.read(2880)
        first_packet = time.perf_counter() - started
        body = first + response.read()
        total = time.perf_counter() - started
        headers = {key.lower(): value for key, value in response.headers.items()}

    audio_seconds = len(body) / (24000 * 2)
    print(
        json.dumps(
            {
                "text": text,
                "bytes": len(body),
                "audio_seconds": round(audio_seconds, 3),
                "first_packet_seconds": round(first_packet, 3),
                "total_seconds": round(total, 3),
                "server_rtf": headers.get("x-tts-rtf"),
                "sample_rate": headers.get("x-audio-sample-rate"),
                "format": headers.get("x-audio-format"),
            },
            ensure_ascii=False,
        )
    )
