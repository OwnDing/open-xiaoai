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
    """sherpa-onnx keyword spotter over one or more streams started a little apart.

    The encoder works in fixed chunks, and where the keyword falls inside a chunk
    changes whether it is found; streams offset by a fraction of a chunk miss
    different utterances, and any of them may wake (as in the 小爱 bridge).
    """

    def __init__(self, config: WakeConfig, model_dir: Path, spotter=None):
        if spotter is None:
            import sherpa_onnx

            keywords_file = build_keywords_file(model_dir, config.keywords)
            spotter = sherpa_onnx.KeywordSpotter(
                provider="cpu",
                num_threads=1,
                max_active_paths=config.max_active_paths,
                keywords_score=config.score,
                keywords_threshold=config.threshold,
                num_trailing_blanks=0,
                keywords_file=str(keywords_file),
                tokens=str(model_dir / "tokens.txt"),
                encoder=str(model_dir / "encoder.onnx"),
                decoder=str(model_dir / "decoder.onnx"),
                joiner=str(model_dir / "joiner.onnx"),
            )
        self._spotter = spotter
        self._offsets = [ms * RATE // 1000 for ms in config.stream_offsets_ms]
        self.reset()
        log.info("wake words: %s (%d paths, streams at %s ms)", ", ".join(config.keywords),
                 config.max_active_paths, "/".join(str(ms) for ms in config.stream_offsets_ms))

    def reset(self):
        # Fresh streams (the loaded model is reused): the audio before a pause
        # must not run into what comes after it.
        self._streams = [self._spotter.create_stream() for _ in self._offsets]
        self._skip = list(self._offsets)  # samples each stream still drops to stay offset
        self._pending = np.zeros(0, dtype=np.float32)

    def accept(self, samples: np.ndarray) -> str | None:
        self._pending = np.concatenate([self._pending, samples])
        if len(self._pending) < CHUNK:
            return None
        chunk, self._pending = self._pending, np.zeros(0, dtype=np.float32)
        for i, stream in enumerate(self._streams):
            skip = min(self._skip[i], len(chunk))
            self._skip[i] -= skip
            if skip < len(chunk):
                stream.accept_waveform(RATE, chunk[skip:])
        for stream in self._streams:
            # One stream per call: this model export only takes a batch of 1.
            while self._spotter.is_ready(stream):
                self._spotter.decode_stream(stream)
                result = self._spotter.get_result(stream)
                if result:
                    # One utterance wakes once, not once per stream.
                    for s in self._streams:
                        self._spotter.reset_stream(s)
                    return result
        return None
