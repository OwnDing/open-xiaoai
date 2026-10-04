"""Offline comparison of audio front-end settings on the P0.5 corpus.

Each take is an 8 kHz mic WAV of the 20 lines in corpus.txt read in order.
For every take this builds 16 kHz variants (raw, WebRTC APM high-pass /
noise suppression / gain, stationary spectral gating), then runs

  - Silero VAD + SenseVoice (the backend's ASR model) -> character error rate
  - the bridge's sherpa-onnx wake-word model          -> wake-word hits

Example (Windows venv):
  python frontend_eval.py --corpus corpus.txt --takes corpus\\take*.wav ^
    --asr-dir C:\\...\\sherpa-onnx-sense-voice --kws-dir models\\kws ^
    --vad models\\silero_vad.onnx --out corpus\\eval
"""

import argparse
import glob
import json
import re
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx
import soxr

RATE = 16000
WAKE = "你好小七"
WAKE_FUZZY = re.compile("你好小[七期奇琪齐起其棋旗气器柒]")
# The start cue ("开始录音，请读第一句") is played into the open mic.
CUE_WORDS = ("录音", "第一句")
CUE_SECONDS = 6.0


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0, rate


def write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def apm(x, ns=False, hpf=False, agc=False):
    """Stream x through WebRTC APM in 10 ms frames, like the terminal would."""
    from livekit import rtc

    module = rtc.AudioProcessingModule(
        echo_cancellation=False, noise_suppression=ns, high_pass_filter=hpf, auto_gain_control=agc
    )
    n = RATE // 100
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)[: len(x) // n * n]
    out = np.empty_like(pcm)
    for i in range(0, len(pcm), n):
        frame = rtc.AudioFrame(pcm[i:i + n].tobytes(), RATE, 1, n)
        module.process_stream(frame)
        out[i:i + n] = np.frombuffer(frame.data, dtype=np.int16)
    return out.astype(np.float32) / 32768.0


def spectral(x, prop):
    """Stationary spectral gating; offline only (noise profile from the take)."""
    import noisereduce

    return noisereduce.reduce_noise(y=x, sr=RATE, stationary=True, prop_decrease=prop).astype(np.float32)


VARIANTS = {
    "raw": lambda x: x,
    "hpf": lambda x: apm(x, hpf=True),
    "webrtc_ns": lambda x: apm(x, ns=True, hpf=True),
    "webrtc_ns_agc": lambda x: apm(x, ns=True, hpf=True, agc=True),
    "spectral_0.6": lambda x: spectral(x, 0.6),
    "spectral_0.95": lambda x: spectral(x, 0.95),
}


def normalize(text):
    return "".join(ch for ch in text if ch.isalnum())


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def level_profile(x):
    """(floor, speech) dBFS from 100 ms RMS percentiles."""
    n = RATE // 10
    rms = np.sqrt(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    return float(np.percentile(db, 20)), float(np.percentile(db, 95))


class Evaluator:
    def __init__(self, args):
        asr = Path(args.asr_dir)
        self.asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(asr / "model.int8.onnx"),
            tokens=str(asr / "tokens.txt"),
            num_threads=args.threads,
            use_itn=False,
            language="zh",
        )
        kws = Path(args.kws_dir)
        self.kws = sherpa_onnx.KeywordSpotter(
            provider="cpu",
            num_threads=1,
            max_active_paths=8,
            keywords_score=args.kws_score,
            keywords_threshold=args.kws_threshold,
            num_trailing_blanks=0,
            keywords_file=str(kws / "keywords.txt"),
            tokens=str(kws / "tokens.txt"),
            encoder=str(kws / "encoder.onnx"),
            decoder=str(kws / "decoder.onnx"),
            joiner=str(kws / "joiner.onnx"),
        )
        self.vad_model = args.vad

    def segments(self, x):
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = self.vad_model
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_silence_duration = 0.5
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.max_speech_duration = 8
        config.sample_rate = RATE
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=200)
        window = config.silero_vad.window_size
        found = []

        def collect():
            while not vad.empty():
                found.append((vad.front.start / RATE, np.array(vad.front.samples, dtype=np.float32)))
                vad.pop()

        for i in range(0, len(x) - window + 1, window):
            vad.accept_waveform(x[i:i + window])
            collect()
        vad.flush()
        collect()
        return found

    def recognize(self, samples):
        stream = self.asr.create_stream()
        stream.accept_waveform(RATE, samples)
        self.asr.decode_stream(stream)
        return stream.result.text

    def wake_hits(self, x):
        stream = self.kws.create_stream()
        hits = []
        chunk = RATE // 10
        for i in range(0, len(x), chunk):
            stream.accept_waveform(RATE, x[i:i + chunk])
            while self.kws.is_ready(stream):
                self.kws.decode_stream(stream)
                result = self.kws.get_result(stream)
                if result:
                    hits.append((round(i / RATE, 1), result))
                    self.kws.reset_stream(stream)
        return hits

    def run(self, x, reference):
        lines = []
        for start, samples in self.segments(x):
            text = self.recognize(samples)
            if start < CUE_SECONDS and any(word in text for word in CUE_WORDS):
                continue
            lines.append({"start": round(start, 2), "text": text})
        hyp = normalize("".join(line["text"] for line in lines))
        ref = normalize("".join(reference))
        hits = self.wake_hits(x)
        floor, speech = level_profile(x)
        return {
            "segments": len(lines),
            "cer": edit_distance(ref, hyp) / len(ref),
            "wake_asr": hyp.count(WAKE),
            "wake_asr_fuzzy": len(WAKE_FUZZY.findall(hyp)),
            "wake_kws": sum(1 for _, word in hits if WAKE in word),
            "kws_other": [h for h in hits if WAKE not in h[1]],
            "floor_db": round(floor, 1),
            "speech_db": round(speech, 1),
            "lines": lines,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--takes", nargs="+", required=True)
    parser.add_argument("--asr-dir", required=True)
    parser.add_argument("--kws-dir", required=True)
    parser.add_argument("--vad", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--threads", type=int, default=2)
    # Bridge defaults: keywords_score 2.0, keywords_threshold 0.2.
    parser.add_argument("--kws-score", type=float, default=2.0)
    parser.add_argument("--kws-threshold", type=float, default=0.2)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS))
    args = parser.parse_args()

    reference = [line.strip() for line in Path(args.corpus).read_text(encoding="utf-8").splitlines() if line.strip()]
    wakes = sum(1 for line in reference if line == WAKE)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    evaluator = Evaluator(args)
    takes = sorted(p for pattern in args.takes for p in glob.glob(pattern))
    results = {}

    print(f"reference: {len(reference)} lines, {wakes} x {WAKE}")
    print(f"{'take':<16} {'variant':<14} {'floor':>6} {'speech':>6} {'segs':>4} {'CER':>6} {'wakeASR':>7} {'wakeKWS':>7}  other-KWS")
    for take in takes:
        x8, rate = read_wav(take)
        x = soxr.resample(x8, rate, RATE, quality="HQ").astype(np.float32)
        name = Path(take).stem
        for variant in args.variants:
            y = VARIANTS[variant](x)
            write_wav(out / f"{name}.{variant}.wav", y)
            result = evaluator.run(y, reference)
            results[f"{name}/{variant}"] = result
            print(
                f"{name:<16} {variant:<14} {result['floor_db']:6.1f} {result['speech_db']:6.1f} "
                f"{result['segments']:4d} {result['cer']:6.1%} {result['wake_asr']:>3}/{wakes:<3} "
                f"{result['wake_kws']:>3}/{wakes:<3}  {result['kws_other'] or ''}",
                flush=True,
            )

    print(f"\n{'variant':<14} {'mean CER':>8} {'wakeASR':>8} {'wakeKWS':>8}")
    for variant in args.variants:
        rows = [r for key, r in results.items() if key.endswith("/" + variant)]
        print(
            f"{variant:<14} {np.mean([r['cer'] for r in rows]):8.1%} "
            f"{sum(r['wake_asr'] for r in rows):>4}/{wakes * len(rows):<3} "
            f"{sum(r['wake_kws'] for r in rows):>4}/{wakes * len(rows):<3}"
        )
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
