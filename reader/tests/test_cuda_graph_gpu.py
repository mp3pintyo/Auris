"""Opt-in real GPU parity check: AURIS_TEST_CUDA_GRAPH=1."""
import os
import unittest

import torch

from core.tts_accel import CUDAGraphForward


@unittest.skipUnless(os.environ.get('AURIS_TEST_CUDA_GRAPH') == '1' and torch.cuda.is_available(),
                     'Set AURIS_TEST_CUDA_GRAPH=1 on an NVIDIA test machine')
class GraphParityTest(unittest.TestCase):
    def test_alternating_shapes_masks_and_evictions(self):
        class Model:
            training = False

            def forward(self, input_ids, audio_mask, labels=None,
                        attention_mask=None, document_ids=None, position_ids=None):
                result = input_ids.float().sum(dim=1) + audio_mask.float()
                if attention_mask is not None:
                    result = result + attention_mask.float()
                return result * 2

        model = Model()
        wrapper = CUDAGraphForward(model)
        with torch.inference_mode():
            for size, masked in [(4, False), (7, True), (4, True), (4, False),
                                 (6, True), (8, False), (9, True), (7, True), (4, False)]:
                ids = torch.randint(0, 50, (2, 3, size), device='cuda')
                mask = torch.ones((2, size), device='cuda', dtype=torch.bool)
                attn = torch.rand((2, size), device='cuda') if masked else None
                expected = model.forward(ids, mask, attention_mask=attn)
                actual = wrapper(ids, mask, attention_mask=attn)
                torch.cuda.synchronize()
                self.assertTrue(torch.equal(actual, expected))
                self.assertLessEqual(len(wrapper._graphs), 4)
                self.assertFalse(wrapper.disabled_reason, 'Must test graph replay, not fallback')
        wrapper.clear()


if __name__ == '__main__':
    unittest.main()
