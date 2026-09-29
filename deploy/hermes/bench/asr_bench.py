"""Compare local ASR options on the mini PC: latency after end of speech + CER.

Runs inside the xiaozhi-esp32-server image (funasr, torch, sherpa_onnx,
modelscope are installed). Each utterance is 16 kHz s16le PCM from
make_audio.sh plus 300 ms of trailing silence, like the bridge sends it.

  sensevoice_torch  current provider (fun_local): FunASR SenseVoiceSmall on
                    PyTorch, whole utterance after the user stops
  sensevoice_onnx   same model, sherpa-onnx int8, whole utterance
  paraformer_stream FunASR streaming Paraformer (sherpa-onnx int8): audio is
                    fed in real time; latency = end of audio -> final text
  funasr_2pass      FunASR runtime server, 2pass (streaming Paraformer +
                    SenseVoice correction at the end); latency measured the
                    same way. Needs --funasr-url.

    python asr_bench.py --methods sensevoice_torch,sensevoice_onnx --repeat 3
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import time
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHUNK_MS = 100
PUNCT = re.compile(r"[\s，。！？、,.!?：:；;“”\"'（）()<>|\-]+")
DIGITS = "零一二三四五六七八九"


def cn_number(match):
    n = int(match.group())
    if n < 10:
        return DIGITS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return ("十" if tens == 1 else DIGITS[tens] + "十") + (DIGITS[ones] if ones else "")
    return "".join(DIGITS[int(d)] for d in match.group())


def normalize(text):
    text = re.sub(r"<\|[^|]*\|>", "", text)
    text = re.sub(r"\d+", cn_number, text)
    return PUNCT.sub("", text).lower()


def cer(ref, hyp):
    ref, hyp = normalize(ref), normalize(hyp)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def load_cases(bench_dir):
    cases = []
    for line in (bench_dir / "utterances.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case_id, text = line.split("\t", 1)
        path = bench_dir / "audio" / f"{case_id}.pcm"
        if path.exists():
            cases.append((case_id, text, path.read_bytes()))
    # A longer request to show how latency scales with utterance length.
    by_id = {c[0]: c for c in cases}
    if all(k in by_id for k in ("c5", "m1", "w1")):
        silence = b"\x00\x00" * (SAMPLE_RATE // 4)
        pcm = silence.join(by_id[k][2] for k in ("c5", "m1", "w1"))
        text = "".join(by_id[k][1] for k in ("c5", "m1", "w1"))
        cases.append(("long", text, pcm))
    tail = b"\x00\x00" * (SAMPLE_RATE * 3 // 10)
    return [(case_id, text, pcm + tail) for case_id, text, pcm in cases]


def to_float(pcm):
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768


class SenseVoiceTorch:
    name = "sensevoice_torch"

    def __init__(self, args):
        from funasr import AutoModel

        self.model = AutoModel(model=args.sensevoice_dir, disable_update=True, hub="hf")

    def run(self, pcm):
        started = time.perf_counter()
        result = self.model.generate(input=pcm, cache={}, language="auto", use_itn=True, batch_size_s=60)
        return result[0]["text"], time.perf_counter() - started


class SenseVoiceOnnx:
    name = "sensevoice_onnx"

    def __init__(self, args):
        import sherpa_onnx
        from modelscope.hub.file_download import model_file_download

        model_dir = Path(args.cache) / "sherpa-sense-voice"
        for file_name in ("model.int8.onnx", "tokens.txt"):
            if not (model_dir / file_name).exists():
                model_file_download(
                    model_id="pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue",
                    file_path=file_name,
                    local_dir=str(model_dir),
                )
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_dir / "model.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=args.threads,
            use_itn=True,
        )

    def run(self, pcm):
        started = time.perf_counter()
        stream = self.recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, to_float(pcm))
        self.recognizer.decode_stream(stream)
        return stream.result.text, time.perf_counter() - started


class ParaformerStream:
    name = "paraformer_stream"

    def __init__(self, args):
        import sherpa_onnx

        model_dir = Path(args.paraformer_dir)
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=args.threads,
        )

    def run(self, pcm):
        samples = to_float(pcm)
        step = SAMPLE_RATE * CHUNK_MS // 1000
        stream = self.recognizer.create_stream()
        begin = time.perf_counter()
        for index, offset in enumerate(range(0, len(samples), step)):
            stream.accept_waveform(SAMPLE_RATE, samples[offset : offset + step])
            while self.recognizer.is_ready(stream):
                self.recognizer.decode_stream(stream)
            delay = begin + (index + 1) * CHUNK_MS / 1000 - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        ended = time.perf_counter()
        # Right context the model needs to emit the last tokens.
        stream.accept_waveform(SAMPLE_RATE, np.zeros(int(0.66 * SAMPLE_RATE), dtype=np.float32))
        stream.input_finished()
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        return self.recognizer.get_result(stream), time.perf_counter() - ended


class FunASR2Pass:
    name = "funasr_2pass"

    def __init__(self, args):
        self.url = args.funasr_url

    async def _run(self, pcm):
        import websockets

        async with websockets.connect(self.url, subprotocols=["binary"], ping_interval=None, max_size=None) as ws:
            await ws.send(json.dumps({
                "mode": "2pass", "chunk_size": [5, 10, 5], "chunk_interval": 10,
                "wav_name": "bench", "is_speaking": True, "itn": True,
            }))
            offline = []
            final = asyncio.Event()

            async def receive():
                async for raw in ws:
                    message = json.loads(raw)
                    if message.get("mode") == "2pass-offline":
                        offline.append(message.get("text", ""))
                    if message.get("is_final"):
                        final.set()
                        return

            receiver = asyncio.create_task(receive())
            step = SAMPLE_RATE * 2 * CHUNK_MS // 1000
            begin = time.perf_counter()
            for index, offset in enumerate(range(0, len(pcm), step)):
                await ws.send(pcm[offset : offset + step])
                delay = begin + (index + 1) * CHUNK_MS / 1000 - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
            ended = time.perf_counter()
            await ws.send(json.dumps({"is_speaking": False}))
            await asyncio.wait_for(final.wait(), 20)
            latency = time.perf_counter() - ended
            receiver.cancel()
            return "".join(offline), latency

    def run(self, pcm):
        return asyncio.run(self._run(pcm))


METHODS = {m.name: m for m in (SenseVoiceTorch, SenseVoiceOnnx, ParaformerStream, FunASR2Pass)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--methods", default="sensevoice_torch,sensevoice_onnx")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--bench-dir", default=".")
    parser.add_argument("--cache", default="/cache")
    parser.add_argument("--sensevoice-dir", default="/opt/xiaozhi-esp32-server/models/SenseVoiceSmall")
    parser.add_argument("--paraformer-dir", default="/cache/paraformer-stream")
    parser.add_argument("--funasr-url", default="ws://funasr:10095")
    parser.add_argument("--out", default="asr_results.jsonl")
    args = parser.parse_args()

    cases = load_cases(Path(args.bench_dir))
    with open(args.out, "a", encoding="utf-8") as out:
        for name in args.methods.split(","):
            method = METHODS[name](args)
            method.run(cases[0][2])  # warm-up
            latencies, errors = [], []
            for case_id, reference, pcm in cases:
                runs = [method.run(pcm) for _ in range(args.repeat)]
                latency = statistics.median(run[1] for run in runs)
                text = runs[-1][0]
                error = cer(reference, text)
                latencies.append(latency)
                errors.append(error)
                row = {"method": name, "threads": args.threads, "case": case_id,
                       "audio_s": round(len(pcm) / 2 / SAMPLE_RATE, 2), "latency_s": round(latency, 3),
                       "cer": round(error, 3), "text": text, "ref": reference}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{name:18} {case_id:5} {row['audio_s']:5.1f}s audio  "
                      f"latency {latency:.3f}s  cer {error:.2f}  {text}", flush=True)
            short = [l for (c, _, _), l in zip(cases, latencies) if c != "long"]
            print(f"== {name} threads={args.threads}: median latency {statistics.median(short):.3f}s "
                  f"(max {max(short):.3f}s), mean CER {statistics.mean(errors):.3f}\n", flush=True)


if __name__ == "__main__":
    main()
