import numpy as np
import sherpa_onnx

from config import APP_CONFIG
from xiaozhi.utils.file import get_model_file_path

SAMPLE_RATE = 16000


class _SherpaOnnx:
    def start(self):
        wakeup = APP_CONFIG["wakeup"]
        self.keyword_spotter = sherpa_onnx.KeywordSpotter(
            provider="cpu",
            num_threads=1,
            max_active_paths=int(wakeup.get("max_active_paths", 8)),
            keywords_score=2.0,
            keywords_threshold=0.2,
            num_trailing_blanks=0,
            keywords_file=get_model_file_path("keywords.txt"),
            tokens=get_model_file_path("tokens.txt"),
            encoder=get_model_file_path("encoder.onnx"),
            decoder=get_model_file_path("decoder.onnx"),
            joiner=get_model_file_path("joiner.onnx"),
        )
        # The encoder works in fixed chunks, and where a keyword falls inside a
        # chunk changes whether it is found. Streams started a fraction of a
        # chunk apart miss different utterances; any of them may wake.
        offsets = sorted({max(0, int(ms)) for ms in wakeup.get("stream_offsets_ms", [0])}) or [0]
        self.offsets = [ms * SAMPLE_RATE // 1000 for ms in offsets]
        self.reset()

    def reset(self):
        # Reuse the loaded model but discard features as well as decoder state:
        # paused audio creates a discontinuity in this stream.
        self.streams = [self.keyword_spotter.create_stream() for _ in self.offsets]
        self.skip = list(self.offsets)  # samples each stream still drops to stay offset

    def kws(self, frames):
        samples = np.frombuffer(frames, dtype=np.int16)
        samples = samples.astype(np.float32) / 32768.0
        for i, stream in enumerate(self.streams):
            skip = min(self.skip[i], len(samples))
            self.skip[i] -= skip
            if skip < len(samples):
                stream.accept_waveform(SAMPLE_RATE, samples[skip:])
        while True:
            ready = [s for s in self.streams if self.keyword_spotter.is_ready(s)]
            if not ready:
                return None
            self.keyword_spotter.decode_streams(ready)
            for stream in ready:
                result = self.keyword_spotter.get_result(stream)
                if result:
                    # One utterance wakes once, not once per stream.
                    for s in self.streams:
                        self.keyword_spotter.reset_stream(s)
                    return result.lower()


SherpaOnnx = _SherpaOnnx()
