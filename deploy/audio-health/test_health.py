"""Run against either Python sink: AUDIO_HEALTH_MODULE=/path/health.py python test_health.py."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

module_path = os.environ.get('AUDIO_HEALTH_MODULE')
if not module_path:
    module_path = Path(__file__).resolve().parents[2] / 'examples/xiaozhi/xiaozhi/services/audio/health.py'
module_path = Path(module_path)
spec = importlib.util.spec_from_file_location('health_under_test', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HealthTests(unittest.TestCase):
    def make(self, path='unused'):
        return module.HealthLog('test', 'device', path, interval=0.02)

    def test_sequence_loss_and_restart(self):
        h = self.make()
        data = np.zeros(160, dtype=np.float32)
        for seq in [1, 3, 2, 4]:
            h.pcm(data, {'capture_id': 'a', 'seq': seq, 'sample_start': (seq-1)*160})
        first = h.snapshot()
        self.assertEqual(first['totals']['sequence_gaps'], 1)
        self.assertEqual(first['totals']['missing_samples'], 160)
        self.assertEqual(first['totals']['sequence_reorders'], 1)
        h.pcm(data, {'capture_id': 'b', 'seq': 1, 'sample_start': 0})
        last = h.snapshot()
        self.assertEqual(last['totals']['sequence_gaps'], 1)
        self.assertEqual(last['seq'], 1)
        self.assertEqual(h.capture_id, 'b')

    def test_signal_processing_and_no_input_window(self):
        h = self.make()
        with patch.object(module.time, 'monotonic', return_value=100):
            h._last_report = 90
            h.pcm(np.array([0, 1, -1, 0], dtype=np.float32))
            h.kws(4, 'active', duration=0.001, hit=True)
            h.kws(4, 'speaking')
            first = h.snapshot()
        self.assertEqual(first['input_rate_hz'], 0.4)
        self.assertEqual(first['zero_ratio'], 0.5)
        self.assertEqual(first['clip_ratio'], 0.5)
        self.assertEqual(first['window']['wake_hits'], 1)
        self.assertEqual(first['window']['skipped_samples'], 4)
        with patch.object(module.time, 'monotonic', return_value=110):
            second = h.snapshot()
        self.assertEqual(second['input_rate_hz'], 0)
        self.assertEqual(second['input_age_ms'], 10000)
        self.assertEqual(second['level_samples'], 0)

    def test_status_does_not_consume_window(self):
        h = self.make()
        h.pcm(np.zeros(160))
        h.peek(); h.peek()
        self.assertEqual(h.snapshot()['window']['input_samples'], 160)

    def test_bounded_writer_failure_does_not_stop_capture(self):
        h = self.make()
        for _ in range(200):
            h.emit('event')
        self.assertEqual(h._queue.qsize(), 128)
        self.assertEqual(h.log_dropped, 72)
        with tempfile.TemporaryDirectory() as d:
            file = Path(d)/'is-a-file'
            file.write_text('')
            h = self.make(file/'unwritable.jsonl')
            h.start()
            h.pcm(np.zeros(160))
            deadline = time.monotonic()+1
            while not h.log_errors and time.monotonic()<deadline:
                time.sleep(0.005)
            h.close()
            self.assertGreater(h.log_errors, 0)
            self.assertEqual(h.peek()['totals']['input_samples'], 160)

    def test_periodic_summary_and_rotation_are_metadata_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'health.jsonl'
            h = self.make(path)
            h.start()
            h.pcm(np.zeros(160))
            time.sleep(0.065)
            for _ in range(15):
                h.emit('test_rotation', padding='x'*90000)
            h.close()
            self.assertTrue(Path(str(path)+'.1').exists())
            records = []
            for p in Path(d).glob('health.jsonl*'):
                records.extend(json.loads(line) for line in p.read_text().splitlines())
            summaries = [r for r in records if r['event']=='summary']
            self.assertGreaterEqual(len(summaries), 2)
            self.assertTrue(any(r['input_rate_hz']==0 for r in summaries))
            self.assertTrue(all('audio' not in r and 'transcript' not in r for r in records))


if __name__ == '__main__':
    unittest.main()
