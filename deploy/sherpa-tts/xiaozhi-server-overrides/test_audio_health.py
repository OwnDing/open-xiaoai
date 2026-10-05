import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('audio_health',Path(__file__).with_name('audio_health.py'))
health=importlib.util.module_from_spec(spec);spec.loader.exec_module(health)
spec=importlib.util.spec_from_file_location('patch_health',Path(__file__).with_name('patch_audio_health.py'))
patcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(patcher)

class BackendHealthTests(unittest.TestCase):
    def test_filter_removes_sensitive_fields(self):
        result=health.sanitize({'capture_id':'test','audio':'pcm','transcript':'speech','access_token':'secret',
                               'totals':{'input_samples':160,'speech':'words'},'mic':'device'})
        self.assertEqual(result, {'capture_id':'test','totals':{'input_samples':160}})

    def test_diagnostics_bypass_conversation(self):
        conn=SimpleNamespace(device_id='test',session_id='s')
        health.count_audio(conn,b'abc')
        with patch.object(health,'_start_writer'):
            self.assertTrue(health.handle_health(conn,'{"type":"audio_health","health":{"capture_id":"c"}}'))
            record=health._QUEUE.get_nowait()
            self.assertEqual(record['received_opus_bytes_total'],3)
            self.assertEqual(record['capture_id'],'c')
            self.assertFalse(health.handle_health(conn,'{"type":"listen","text":"audio_health"}'))
        self.assertFalse(hasattr(conn,'last_activity_time'))

    def test_patch_is_idempotent_and_refuses_changed_upstream(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'core').mkdir();p=root/'core/connection.py'
            source='class Test:\n    async def route(self,message):\n        if isinstance(message, str):\n            await handleTextMessage(self, message)\n        elif isinstance(message, bytes):\n            pass\n'
            p.write_text(source);patcher.patch(root);first=p.read_text();patcher.patch(root)
            self.assertEqual(p.read_text(),first)
            p.write_text('changed');self.assertRaises(RuntimeError,patcher.patch,root)
            self.assertEqual(p.read_text(),'changed')

if __name__=='__main__': unittest.main()
