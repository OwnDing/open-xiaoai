"""Local Sherpa-ONNX SenseVoiceSmall ASR (int8 ONNX, no PyTorch)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import threading
import time

import numpy as np

log = logging.getLogger("voice-gateway.asr")


class SenseVoiceASR:
    """Thread-safe SenseVoiceSmall offline recognizer backed by sherpa-onnx."""

    def __init__(
        self,
        model_dir: str | Path,
        num_threads: int = 2,
        language: str = "auto",
        use_itn: bool = True,
        max_audio_s: float = 30.0,
    ):
        import sherpa_onnx

        root = Path(model_dir)
        model_file = root / "model.int8.onnx"
        if not model_file.is_file():
            model_file = root / "model.onnx"
        tokens_file = root / "tokens.txt"
        if not model_file.is_file() or not tokens_file.is_file():
            raise FileNotFoundError(
                f"SenseVoice model files not found in {root} (need model.int8.onnx/model.onnx and tokens.txt)"
            )

        started = time.perf_counter()
        self.model_path = model_file
        self.max_audio_s = max(1.0, float(max_audio_s))
        self._lock = threading.Lock()
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens_file),
            num_threads=max(1, int(num_threads)),
            use_itn=use_itn,
            language=language,
            debug=False,
        )
        self.utterances = 0
        self.total_infer_s = 0.0
        # Warm up ONNX Runtime threadpool so the very first user utterance is fast.
        warm = self._recognizer.create_stream()
        warm.accept_waveform(16000, np.zeros(3200, dtype=np.float32))
        self._recognizer.decode_stream(warm)
        log.info(
            "SenseVoice ASR ready: %s (threads=%d, max_audio=%.0fs) in %.2fs",
            model_file.name,
            num_threads,
            self.max_audio_s,
            time.perf_counter() - started,
        )

    def transcribe_pcm16_sync(self, pcm: bytes, sample_rate: int = 16000) -> tuple[str, float]:
        """Recognize 16-bit mono little-endian PCM; returns (text, elapsed_s)."""
        if not pcm:
            return "", 0.0
        usable = len(pcm) // 2 * 2
        samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32) / 32768.0
        # Cap input length so onnxruntime's memory arena cannot grow unboundedly
        # if ambient noise keeps a terminal recording for minutes.
        max_samples = int(self.max_audio_s * sample_rate)
        if len(samples) > max_samples:
            log.warning("ASR audio truncated from %.1fs to %.1fs", len(samples) / sample_rate, self.max_audio_s)
            samples = samples[:max_samples]
        if len(samples) < int(sample_rate * 0.1):
            return "", 0.0

        started = time.perf_counter()
        with self._lock:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(sample_rate, samples)
            self._recognizer.decode_stream(stream)
            text = (stream.result.text or "").strip()
        elapsed = time.perf_counter() - started
        self.utterances += 1
        self.total_infer_s += elapsed
        return text, elapsed

    async def transcribe_pcm16(self, pcm: bytes, sample_rate: int = 16000) -> tuple[str, float]:
        return await asyncio.to_thread(self.transcribe_pcm16_sync, pcm, sample_rate)
