"""Wake-word detection with the 小爱 bridge's sherpa-onnx keyword spotter."""

import logging
import re
from pathlib import Path

import numpy as np

from .config import WakeConfig

log = logging.getLogger(__name__)
RATE = 16000
CHUNK = RATE // 10  # decode every 100 ms


def build_keywords_file(model_dir: Path, keywords: list[str]) -> Path:
    """Encode keywords for the cjkchar+bpe model, like the bridge's keywords.py."""
    from sherpa_onnx import text2token

    output = model_dir / "keywords.generated.txt"
    encoded = text2token(
        [k.upper() for k in keywords],
        tokens=str(model_dir / "tokens.txt"),
        tokens_type="cjkchar+bpe",
        bpe_model=str(model_dir / "bpe.model"),
    )
    lines = []
    for tokens in encoded:
        line = "".join(tokens)
        if re.match(r"^[▁A-Z\s]+$", line):
            lines.append(" ".join(tokens))
        else:
            lines.append(" ".join(tokens) + f" @{line}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


class WakeWordDetector:
    def __init__(self, config: WakeConfig, model_dir: Path):
        import sherpa_onnx

        keywords_file = build_keywords_file(model_dir, config.keywords)
        self._spotter = sherpa_onnx.KeywordSpotter(
            provider="cpu",
            num_threads=1,
            max_active_paths=8,
            keywords_score=config.score,
            keywords_threshold=config.threshold,
            num_trailing_blanks=0,
            keywords_file=str(keywords_file),
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.onnx"),
        )
        self._stream = self._spotter.create_stream()
        self._pending = np.zeros(0, dtype=np.float32)
        log.info("wake words: %s", ", ".join(config.keywords))

    def reset(self):
        self._spotter.reset_stream(self._stream)
        self._pending = np.zeros(0, dtype=np.float32)

    def accept(self, samples: np.ndarray) -> str | None:
        self._pending = np.concatenate([self._pending, samples])
        if len(self._pending) < CHUNK:
            return None
        chunk, self._pending = self._pending, np.zeros(0, dtype=np.float32)
        self._stream.accept_waveform(RATE, chunk)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            result = self._spotter.get_result(self._stream)
            if result:
                self._spotter.reset_stream(self._stream)
                return result
        return None
