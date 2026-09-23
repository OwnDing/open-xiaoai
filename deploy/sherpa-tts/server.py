import logging
import os
import threading
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import soxr
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("sherpa-tts")

MODEL_DIR = Path(
    os.getenv(
        "SHERPA_MODEL_DIR", "/models/vits-piper-zh_CN-xiao_ya-medium"
    )
)
MODEL_PATH = MODEL_DIR / "zh_CN-xiao_ya-medium.onnx"
LEXICON_PATH = MODEL_DIR / "lexicon.txt"
TOKENS_PATH = MODEL_DIR / "tokens.txt"
RULE_FSTS = ",".join(
    str(MODEL_DIR / filename)
    for filename in ("phone.fst", "date.fst", "number.fst")
)
OUTPUT_SAMPLE_RATE = 24000
FRAME_DURATION_MS = 60
FRAME_BYTES = OUTPUT_SAMPLE_RATE * 2 * FRAME_DURATION_MS // 1000
NUM_THREADS = max(1, int(os.getenv("SHERPA_NUM_THREADS", "3")))
DEFAULT_SPEED = float(os.getenv("SHERPA_SPEED", "1.0"))
DEFAULT_SILENCE_SCALE = float(os.getenv("SHERPA_SILENCE_SCALE", "0.2"))
EDGE_FADE_MS = max(0, int(os.getenv("SHERPA_EDGE_FADE_MS", "5")))


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    character: str | None = None
    speed: float | None = Field(default=None, gt=0.25, le=3.0)
    sid: int = Field(default=0, ge=0)


def build_tts() -> sherpa_onnx.OfflineTts:
    required = (MODEL_PATH, LEXICON_PATH, TOKENS_PATH)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing Sherpa-ONNX model files: {missing}")

    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(MODEL_PATH),
                lexicon=str(LEXICON_PATH),
                tokens=str(TOKENS_PATH),
            ),
            num_threads=NUM_THREADS,
            provider="cpu",
            debug=False,
        ),
        rule_fsts=RULE_FSTS,
        max_num_sentences=1,
    )
    if not config.validate():
        raise RuntimeError("Invalid Sherpa-ONNX TTS configuration")
    return sherpa_onnx.OfflineTts(config)


def float_audio_to_pcm24k(samples: np.ndarray, sample_rate: int) -> bytes:
    audio = np.asarray(samples, dtype=np.float32)
    if sample_rate != OUTPUT_SAMPLE_RATE:
        audio = soxr.resample(audio, sample_rate, OUTPUT_SAMPLE_RATE, quality="HQ")
    else:
        audio = audio.copy()

    # Smooth independently generated segments to avoid an abrupt waveform edge.
    fade_samples = min(
        len(audio) // 2,
        OUTPUT_SAMPLE_RATE * EDGE_FADE_MS // 1000,
    )
    if fade_samples > 0:
        fade_in = np.linspace(0.0, 1.0, fade_samples, endpoint=False, dtype=np.float32)
        audio[:fade_samples] *= fade_in
        audio[-fade_samples:] *= fade_in[::-1]

    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767.0).astype("<i2").tobytes()


tts = build_tts()
warmup_started = time.perf_counter()
warmup_audio = tts.generate(text="你好，我是小七。", sid=0, speed=DEFAULT_SPEED)
logger.info(
    "warmup complete elapsed=%.3fs samples=%d",
    time.perf_counter() - warmup_started,
    len(warmup_audio.samples),
)
tts_lock = threading.Lock()
app = FastAPI(title="Sherpa-ONNX streaming TTS", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL_DIR.name,
        "model_sample_rate": tts.sample_rate,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "num_speakers": tts.num_speakers,
        "threads": NUM_THREADS,
        "silence_scale": DEFAULT_SILENCE_SCALE,
        "edge_fade_ms": EDGE_FADE_MS,
    }


@app.post("/tts")
def synthesize(request: TTSRequest) -> StreamingResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be blank")

    started = time.perf_counter()
    speed = request.speed or DEFAULT_SPEED
    generation_config = sherpa_onnx.GenerationConfig()
    generation_config.sid = request.sid
    generation_config.speed = speed
    generation_config.silence_scale = DEFAULT_SILENCE_SCALE
    with tts_lock:
        audio = tts.generate(text, generation_config)
    if len(audio.samples) == 0:
        raise HTTPException(status_code=500, detail="TTS returned no audio")

    pcm = float_audio_to_pcm24k(audio.samples, audio.sample_rate)
    elapsed = time.perf_counter() - started
    duration = len(pcm) / (OUTPUT_SAMPLE_RATE * 2)
    rtf = elapsed / duration if duration else 0.0
    logger.info(
        "synthesized chars=%d elapsed=%.3fs audio=%.3fs rtf=%.3f",
        len(text),
        elapsed,
        duration,
        rtf,
    )

    def pcm_chunks():
        for offset in range(0, len(pcm), FRAME_BYTES):
            chunk = pcm[offset : offset + FRAME_BYTES]
            yield chunk

    return StreamingResponse(
        pcm_chunks(),
        media_type="application/octet-stream",
        headers={
            "X-Audio-Sample-Rate": str(OUTPUT_SAMPLE_RATE),
            "X-Audio-Format": "pcm_s16le",
            "X-TTS-Elapsed-Ms": str(round(elapsed * 1000)),
            "X-TTS-RTF": f"{rtf:.3f}",
        },
    )
