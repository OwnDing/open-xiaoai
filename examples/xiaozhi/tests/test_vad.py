import unittest
from unittest.mock import Mock, patch

from xiaozhi.services.audio.vad import _VAD, frame_sample_count


class VADDurationTests(unittest.TestCase):
    def setUp(self):
        self.vad = _VAD()
        self.vad.pause = Mock()
        self.frame = bytes(512 * 2)

    def test_frame_count_uses_s16_samples(self):
        self.assertEqual(frame_sample_count(self.frame), 512)

    def test_minimum_speech_duration_is_not_halved(self):
        self.vad.target = "speech"
        with patch("xiaozhi.services.audio.vad.EventManager.on_speech") as on_speech:
            for _ in range(7):
                self.vad._handle_speech_frame(self.frame)
            on_speech.assert_not_called()

            self.vad._handle_speech_frame(self.frame)
            on_speech.assert_called_once()

    def test_minimum_silence_duration_is_not_halved(self):
        self.vad.target = "silence"
        with patch("xiaozhi.services.audio.vad.EventManager.on_silence") as on_silence:
            for _ in range(15):
                self.vad._handle_silence_frame(self.frame)
            on_silence.assert_not_called()

            self.vad._handle_silence_frame(self.frame)
            on_silence.assert_called_once()


if __name__ == "__main__":
    unittest.main()
