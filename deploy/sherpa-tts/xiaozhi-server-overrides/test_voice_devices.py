"""python -m unittest test_voice_devices (no xiaozhi-server needed)."""

import os
import unittest
from unittest import mock

import voice_devices

CONFIG = {
    "selected_module": {"TTS": "SherpaOnnxTTS", "ASR": "SherpaASR"},
    "TTS": {"SherpaOnnxTTS": {"type": "index_stream"}, "EdgeTTS": {"type": "edge"}},
    "voice_devices": {
        "02:76:74:00:00:01": {"output": "server_audio", "room": "书房", "reply_style": "sentence"},
        "02:76:74:00:00:02": {"output": "server_audio", "tts": "EdgeTTS"},
        "AA:BB:CC:DD:EE:FF": {"room": "客厅", "reply_style": "回答控制在两句话以内。"},
        "02:76:74:00:00:03": {"tts": "NoSuchTTS"},
    },
}
PROMPT = "intro\n<context>\n- Current time: {{current_time}}\n- Device location: 宁波\n\n</context>\nend"


class VoiceDevicesTest(unittest.TestCase):
    def test_lookup_ignores_case_and_spaces(self):
        self.assertEqual(voice_devices.settings(CONFIG, " aa:bb:cc:dd:ee:ff ")["room"], "客厅")
        self.assertEqual(voice_devices.settings(CONFIG, "12:70:81:a8:4e:75"), {})
        self.assertEqual(voice_devices.settings(CONFIG, None), {})
        self.assertEqual(voice_devices.settings({}, "02:76:74:00:00:01"), {})

    @mock.patch.dict(os.environ, {"XIAOZHI_SERVER_AUDIO_DEVICES": ""})
    def test_server_audio_from_config(self):
        self.assertTrue(voice_devices.wants_server_audio(CONFIG, "02:76:74:00:00:01"))
        self.assertFalse(voice_devices.wants_server_audio(CONFIG, "aa:bb:cc:dd:ee:ff"))
        self.assertFalse(voice_devices.wants_server_audio(CONFIG, "12:70:81:a8:4e:75"))

    @mock.patch.dict(os.environ, {"XIAOZHI_SERVER_AUDIO_DEVICES": "12:70:81:A8:4E:75, x"})
    def test_server_audio_from_environment(self):
        self.assertTrue(voice_devices.wants_server_audio(CONFIG, "12:70:81:a8:4e:75"))

    def test_tts_override_only_for_known_modules(self):
        edge = voice_devices.tts_config(CONFIG, "02:76:74:00:00:02")
        self.assertEqual(edge["selected_module"], {"TTS": "EdgeTTS", "ASR": "SherpaASR"})
        self.assertEqual(CONFIG["selected_module"]["TTS"], "SherpaOnnxTTS")  # not mutated
        self.assertIs(voice_devices.tts_config(CONFIG, "02:76:74:00:00:01"), CONFIG)
        with self.assertLogs(voice_devices.log, "WARNING"):
            self.assertIs(voice_devices.tts_config(CONFIG, "02:76:74:00:00:03"), CONFIG)

    def test_context_lines_are_added_inside_the_context_block(self):
        prompt = voice_devices.add_context(PROMPT, CONFIG, "02:76:74:00:00:01")
        body = prompt.split("<context>")[1].split("</context>")[0]
        self.assertIn("- Device room: 书房（", body)
        self.assertIn("指的就是书房", body)
        self.assertIn("- Reply style: 用完整的一句话回答", body)
        self.assertTrue(prompt.endswith("</context>\nend"))

    def test_free_text_reply_style(self):
        prompt = voice_devices.add_context(PROMPT, CONFIG, "aa:bb:cc:dd:ee:ff")
        self.assertIn("- Reply style: 回答控制在两句话以内。", prompt)

    def test_prompt_unchanged_without_settings_or_context(self):
        self.assertEqual(voice_devices.add_context(PROMPT, CONFIG, "12:70:81:a8:4e:75"), PROMPT)
        self.assertEqual(voice_devices.add_context("no context", CONFIG, "02:76:74:00:00:01"), "no context")
        self.assertIsNone(voice_devices.add_context(None, CONFIG, "02:76:74:00:00:01"))


if __name__ == "__main__":
    unittest.main()
