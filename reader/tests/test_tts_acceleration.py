import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import torch

from core import tts_accel as accel


class AccelerationTest(unittest.TestCase):
    def test_variable_length_audio_does_not_enable_cudnn_exhaustive_search(self):
        from core.tts_engine import _enable_cuda_fast_paths
        previous = torch.backends.cudnn.benchmark
        try:
            with patch.object(torch.cuda, 'is_available', return_value=True):
                torch.backends.cudnn.benchmark = True
                _enable_cuda_fast_paths()
            self.assertFalse(torch.backends.cudnn.benchmark)
        finally:
            torch.backends.cudnn.benchmark = previous

    def test_backend_distinguishes_rocm_from_nvidia(self):
        with patch.object(torch.cuda, 'is_available', return_value=True), \
             patch.object(torch.version, 'hip', '7.2'), \
             patch.object(torch.cuda, 'get_device_name', return_value='AMD Radeon'):
            probe = accel.probe_accel()
        self.assertEqual(probe['backend'], 'rocm')
        self.assertEqual(probe['recommended'], 'eager')

    def test_status_reports_runtime_graph_fallback(self):
        from core.tts_engine import TTSEngine
        engine = TTSEngine()
        engine._ready = True
        engine.model = SimpleNamespace(_auris_cuda_graph=SimpleNamespace(disabled_reason='capture failed'))
        engine._accel_status = {'effective': 'cuda_graph', 'cuda_graph': True, 'scoring_opt': True}
        status = engine.status()['accel']
        self.assertEqual(status['effective'], 'eager')
        self.assertFalse(status['cuda_graph'])
        self.assertIn('capture failed', status['message'])

    def test_rocm_does_not_enable_nvidia_tf32_flags(self):
        from core.tts_engine import _enable_cuda_fast_paths
        with patch.object(torch.cuda, 'is_available', return_value=True), \
             patch.object(torch.version, 'hip', '7.2'), \
             patch.object(torch, 'set_float32_matmul_precision') as precision:
            _enable_cuda_fast_paths()
        precision.assert_not_called()

    def test_mps_gets_portable_optimization(self):
        with patch.object(torch.cuda, 'is_available', return_value=False), \
             patch.object(torch.backends.mps, 'is_available', return_value=True):
            probe = accel.probe_accel()
        self.assertEqual(probe['backend'], 'mps')
        self.assertEqual(probe['recommended'], 'eager')

    def test_optional_import_failure_is_not_fatal(self):
        with patch.dict('sys.modules', {'triton': None}):
            self.assertFalse(accel.triton_available())

    def test_explicit_gpu_mode_falls_back_to_eager_on_rocm(self):
        with patch.object(accel, 'probe_accel', return_value={
            'backend': 'rocm', 'cuda': True, 'recommended': 'eager',
            'triton': True, 'omnivoice_triton': True,
        }):
            self.assertEqual(accel.resolve_accel_mode('hybrid'), 'eager')

    def test_graph_key_includes_optional_tensor_metadata(self):
        ids = torch.zeros(2, 3, 4, dtype=torch.long)
        mask = torch.zeros(2, 4, dtype=torch.bool)
        key = accel.CUDAGraphForward._shape_key
        self.assertNotEqual(key(ids, mask), key(ids, mask, torch.ones(2, 1, 4, 4)))
        self.assertNotEqual(key(ids, mask), key(ids, mask.float()))

    def test_failed_capture_falls_back_and_does_not_retry(self):
        original = Mock(return_value='eager output')
        wrapper = accel.CUDAGraphForward(SimpleNamespace(forward=original, training=False))
        ids = torch.zeros(2, 3, 4, dtype=torch.long)
        mask = torch.zeros(2, 4, dtype=torch.bool)
        with patch.object(wrapper, '_capture', side_effect=RuntimeError('capture unsupported')) as capture:
            self.assertEqual(wrapper(ids, mask), 'eager output')
            self.assertEqual(wrapper(ids, mask), 'eager output')
        self.assertEqual(capture.call_count, 1)
        self.assertIn('capture unsupported', wrapper.disabled_reason)

    def test_eager_installs_scoring_without_graph(self):
        model = SimpleNamespace(_predict_tokens_with_scoring=Mock())
        status = accel.apply_acceleration(model, 'eager')
        self.assertEqual(status['effective'], 'eager')
        self.assertTrue(status['scoring_opt'])
        self.assertFalse(status['cuda_graph'])

    def test_scoring_matches_existing_fast_path_including_ties(self):
        import torch.nn.functional as F
        torch.manual_seed(42)
        model = SimpleNamespace(config=SimpleNamespace(audio_mask_id=16))
        for guidance in (0.0, 2.0):
            for zeros in (False, True):
                c = torch.zeros(2, 3, 5, 17) if zeros else torch.randn(2, 3, 5, 17)
                u = torch.randn_like(c)
                g = SimpleNamespace(guidance_scale=guidance, class_temperature=0.0)
                p = F.log_softmax(c + guidance * (c-u) if guidance else c, dim=-1)
                p[..., 16] = -float('inf')
                tokens, scores = accel._fast_predict_tokens_with_scoring(model, c, u, g)
                self.assertTrue(torch.equal(tokens, p.argmax(dim=-1)))
                self.assertTrue(torch.equal(scores, p.max(dim=-1).values))


if __name__ == '__main__':
    unittest.main()
