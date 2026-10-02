"""Synthesize every line in lines.json with Edge neural voices.

Writes build/audio/voice/<id>.wav (48 kHz mono, silence trimmed) and
build/audio/voice/meta.json with each line's duration, word timings and a
per-frame loudness envelope that drives the speaker's light ring.
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "audio" / "voice"
FPS = 30
SR = 48000


async def synth(text, voice, rate, pitch, mp3_path):
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "t": chunk["offset"] / 1e7,
                    "d": chunk["duration"] / 1e7,
                    "text": chunk["text"],
                })
    return words


def decode(mp3_path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp3_path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def main(only=None):
    cfg = json.loads((ROOT / "src" / "lines.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for lid, line in cfg["lines"].items():
        if only and lid not in only:
            continue
        v = cfg["voices"][line["role"]]
        text = line.get("tts", line["text"])
        mp3 = OUT / f"{lid}.mp3"
        words = asyncio.run(synth(text, v["voice"], v["rate"], v["pitch"], mp3))
        x = decode(mp3)
        # Trim leading/trailing silence, keeping a short natural tail.
        loud = np.flatnonzero(np.abs(x) > 0.01)
        a = max(0, loud[0] - int(0.02 * SR))
        b = min(len(x), loud[-1] + int(0.12 * SR))
        x = x[a:b]
        shift = a / SR
        for w in words:
            w["t"] = round(w["t"] - shift, 3)
            w["d"] = round(w["d"], 3)
        peak = np.max(np.abs(x))
        x = x / peak * 0.89
        wavfile.write(OUT / f"{lid}.wav", SR, (x * 32767).astype(np.int16))
        # RMS per video frame, normalised to 0..1 for the ring animation.
        hop = SR // FPS
        n = int(np.ceil(len(x) / hop))
        pad = np.pad(x, (0, n * hop - len(x)))
        rms = np.sqrt(np.mean(pad.reshape(n, hop) ** 2, axis=1))
        env = np.clip(rms / (np.percentile(rms, 95) + 1e-6), 0, 1)
        meta[lid] = {
            "role": line["role"],
            "text": line["text"],
            "dur": round(len(x) / SR, 3),
            "words": words,
            "env": [round(float(e), 3) for e in env],
        }
        mp3.unlink()
        print(f"{lid} {meta[lid]['dur']:.2f}s  {line['text']}")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
