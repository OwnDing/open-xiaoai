"""Opus codec helpers (16 kHz uplink decode, continuous 24 kHz downlink encode)."""

from __future__ import annotations

import io
import logging
import wave

log = logging.getLogger("voice-gateway.opus")

UPLINK_RATE = 16000
DOWNLINK_RATE = 24000
FRAME_MS = 60
UPLINK_FRAME_SAMPLES = UPLINK_RATE * FRAME_MS // 1000      # 960 samples
DOWNLINK_FRAME_SAMPLES = DOWNLINK_RATE * FRAME_MS // 1000  # 1440 samples
DOWNLINK_FRAME_BYTES = DOWNLINK_FRAME_SAMPLES * 2          # 2880 bytes (int16 mono)


def _import_opus():
    try:
        import opuslib_next as opuslib
        return opuslib
    except ImportError:
        import opuslib  # type: ignore[no-redef]
        return opuslib


class OpusDecoder16k:
    """Decode incoming 16 kHz mono Opus packets to s16le PCM bytes."""

    def __init__(self, sample_rate: int = UPLINK_RATE, frame_ms: int = FRAME_MS):
        opuslib = _import_opus()
        self.sample_rate = sample_rate
        self.frame_samples = sample_rate * frame_ms // 1000
        self._decoder = opuslib.Decoder(sample_rate, 1)

    def decode_frames(self, frames: list[bytes], max_samples: int = 0) -> bytes:
        """Decode a list of Opus packets into contiguous 16-bit mono PCM."""
        out = bytearray()
        max_bytes = max_samples * 2 if max_samples > 0 else 0
        for packet in frames:
            if not packet:
                continue
            try:
                pcm = self._decoder.decode(packet, self.frame_samples)
            except Exception as exc:
                log.debug("opus decode skipped bad frame (%d bytes): %s", len(packet), exc)
                continue
            out.extend(pcm)
            if max_bytes and len(out) >= max_bytes:
                del out[max_bytes:]
                break
        return bytes(out)


class ContinuousOpusEncoder24k:
    """Continuous 24 kHz / 60 ms mono Opus encoder across sentence boundaries.

    Carries partial PCM bytes across sentences so consecutive sentences play
    smoothly with zero clicks or silence gaps; call flush() once after the
    final sentence of an answer.
    """

    def __init__(self, sample_rate: int = DOWNLINK_RATE, frame_ms: int = FRAME_MS):
        self._opuslib = _import_opus()
        self.sample_rate = sample_rate
        self.frame_samples = sample_rate * frame_ms // 1000
        self.frame_bytes = self.frame_samples * 2
        self._encoder = self._opuslib.Encoder(sample_rate, 1, self._opuslib.APPLICATION_AUDIO)
        self._buf = bytearray()

    def reset(self) -> None:
        self._buf.clear()
        self._encoder = self._opuslib.Encoder(
            self.sample_rate, 1, self._opuslib.APPLICATION_AUDIO
        )

    def encode(self, pcm: bytes) -> list[bytes]:
        if not pcm:
            return []
        self._buf.extend(pcm)
        packets: list[bytes] = []
        offset = 0
        limit = len(self._buf) - self.frame_bytes
        while offset <= limit:
            frame = bytes(self._buf[offset : offset + self.frame_bytes])
            packets.append(self._encoder.encode(frame, self.frame_samples))
            offset += self.frame_bytes
        if offset:
            del self._buf[:offset]
        return packets

    def flush(self) -> list[bytes]:
        if not self._buf:
            return []
        pad = self.frame_bytes - len(self._buf)
        frame = bytes(self._buf) + (b"\x00" * pad)
        self._buf.clear()
        return [self._encoder.encode(frame, self.frame_samples)]


def pcm16_to_wav(pcm: bytes, sample_rate: int = UPLINK_RATE) -> bytes:
    """Wrap raw 16-bit mono little-endian PCM bytes in a WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()
