import numpy as np
import pytest
from voice_terminal.health import HealthLog
from voice_terminal.terminal import FrameRouter, Mode

class Wake:
    def reset(self): pass
    def accept(self, frame): return ''

class BrokenWake(Wake):
    def accept(self, frame): raise RuntimeError('model error')


def test_router_counts_active_skipped_and_disabled_frames(tmp_path):
    h = HealthLog('test','device',tmp_path/'health.jsonl')
    router = FrameRouter(Wake(),None,None,800,lambda *_: None,h)
    router.set_mode(Mode.WAKE)
    router.on_frame(np.zeros(160,dtype=np.float32))
    router.set_mode(Mode.OFF)
    router.on_frame(np.zeros(160,dtype=np.float32))
    result = h.snapshot()
    assert result['window']['input_samples'] == 320
    assert result['window']['kws_samples'] == 160
    assert result['window']['skipped_samples'] == 160
    router._wake = None
    router.set_mode(Mode.WAKE)
    router.on_frame(np.zeros(160,dtype=np.float32))
    assert h.peek()['kws_mode'] == 'disabled'


def test_router_reports_model_error_without_hiding_exception(tmp_path):
    h=HealthLog('test','device',tmp_path/'health.jsonl')
    router=FrameRouter(BrokenWake(),None,None,800,lambda *_:None,h)
    router.set_mode(Mode.WAKE)
    with pytest.raises(RuntimeError):
        router.on_frame(np.zeros(160,dtype=np.float32))
    assert h.peek()['totals']['kws_errors'] == 1
