"""Silero VAD and the start / end-of-utterance logic used by the 小爱 bridge."""

import numpy as np

from .config import VadConfig

RATE = 16000
WINDOW = 512  # Silero at 16 kHz
CONTEXT = 64


class Silero:
    """Streaming Silero VAD (onnxruntime), one speech probability per 512 samples."""

    def __init__(self, model_path: str):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)

    def __call__(self, window: np.ndarray) -> float:
        x = np.concatenate([self._context, window.reshape(1, -1).astype(np.float32)], axis=1)
        out, self._state = self._session.run(
            None, {"input": x, "state": self._state, "sr": np.array(RATE, dtype="int64")}
        )
        self._context = x[:, -CONTEXT:]
        return float(out.item())


class SpeechDetector:
    """Feed 16 kHz float32 audio; returns "start" / "end" events.

    waiting: "start" after min_speech_ms of continuous speech.
    in_utterance: "end" after enough continuous silence (longer when the
    utterance so far is very short), or when max_utterance_s is reached.
    """

    def __init__(self, config: VadConfig, model=None):
        self.config = config
        self.model = model if model is not None else Silero(config.model)
        self._pending = np.zeros(0, dtype=np.float32)
        self.reset(in_utterance=False)

    def reset(self, in_utterance: bool):
        self.in_utterance = in_utterance
        self._speech = 0  # continuous speech samples
        self._silence = 0  # continuous silence samples
        self._voiced = 0  # speech samples inside the current utterance
        self._length = 0  # samples since the utterance started
        self.max_prob = 0.0  # diagnostics: highest speech probability since reset

    def _required_silence(self) -> float:
        voiced_ms = self.config.min_speech_ms + self._voiced * 1000 / RATE
        if voiced_ms < self.config.short_utterance_ms:
            return max(self.config.min_silence_ms, self.config.short_utterance_silence_ms)
        return self.config.min_silence_ms

    def accept(self, samples: np.ndarray) -> list[str]:
        self._pending = np.concatenate([self._pending, samples])
        events = []
        while len(self._pending) >= WINDOW:
            window, self._pending = self._pending[:WINDOW], self._pending[WINDOW:]
            prob = self.model(window)
            self.max_prob = max(self.max_prob, prob)
            speech = prob >= self.config.threshold
            if speech:
                self._speech += WINDOW
                self._silence = 0
            else:
                self._silence += WINDOW
                self._speech = 0
            if not self.in_utterance:
                if self._speech >= self.config.min_speech_ms * RATE / 1000:
                    self.reset(in_utterance=True)
                    events.append("start")
                continue
            self._length += WINDOW
            if speech:
                self._voiced += WINDOW
            if (
                self._silence >= self._required_silence() * RATE / 1000
                or self._length >= self.config.max_utterance_s * RATE
            ):
                self.reset(in_utterance=False)
                events.append("end")
        return events
