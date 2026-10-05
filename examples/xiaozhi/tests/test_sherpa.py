import unittest
from unittest.mock import patch

import numpy as np

from xiaozhi.services.audio.kws import sherpa


class FakeStream:
    def __init__(self):
        self.samples = 0  # accepted
        self.decoded = 0
        self.resets = 0

    def accept_waveform(self, rate, samples):
        self.samples += len(samples)


class FakeSpotter:
    """Ready per 960 samples; reports a hit when a stream has decoded `hit_at` samples."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.hit_at = {}  # stream index -> decoded samples that produce a hit
        self.streams = []

    def create_stream(self):
        self.streams.append(FakeStream())
        return self.streams[-1]

    def is_ready(self, stream):
        return stream.samples - stream.decoded >= 960

    def decode_streams(self, streams):
        for stream in streams:
            stream.decoded += 960

    def get_result(self, stream):
        index = self.streams.index(stream)
        return "你好小七" if self.hit_at.get(index) == stream.decoded else ""

    def reset_stream(self, stream):
        stream.resets += 1


def frame():
    return np.zeros(960, dtype=np.int16).tobytes()


class SherpaStreamsTests(unittest.TestCase):
    def start(self, wakeup):
        model = sherpa._SherpaOnnx()
        with patch.object(sherpa.sherpa_onnx, "KeywordSpotter", FakeSpotter), \
                patch.dict(sherpa.APP_CONFIG, {"wakeup": wakeup}):
            model.start()
        return model

    def test_defaults_keep_one_stream_and_eight_paths(self):
        model = self.start({})
        self.assertEqual(model.keyword_spotter.kwargs["max_active_paths"], 8)
        self.assertEqual(len(model.streams), 1)

    def test_offset_stream_starts_later(self):
        model = self.start({"max_active_paths": 16, "stream_offsets_ms": [160, 0]})
        self.assertEqual(model.keyword_spotter.kwargs["max_active_paths"], 16)
        for _ in range(4):
            model.kws(frame())
        first, second = model.streams
        self.assertEqual(first.samples, 4 * 960)
        self.assertEqual(second.samples, 4 * 960 - 2560)

    def test_hit_in_one_stream_resets_all_and_wakes_once(self):
        model = self.start({"stream_offsets_ms": [0, 160]})
        model.keyword_spotter.hit_at = {1: 960}
        results = [model.kws(frame()) for _ in range(5)]
        self.assertEqual([r for r in results if r], ["你好小七"])
        self.assertEqual([s.resets for s in model.streams], [1, 1])

    def test_reset_restores_the_offsets(self):
        model = self.start({"stream_offsets_ms": [0, 160]})
        model.kws(frame())
        model.reset()
        model.kws(frame())
        self.assertEqual([s.samples for s in model.streams], [960, 0])


if __name__ == "__main__":
    unittest.main()
