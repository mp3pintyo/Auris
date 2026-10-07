import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import onnx_device


def fake_ort(*providers):
    return SimpleNamespace(get_available_providers=lambda: list(providers))


class OnnxDeviceTests(unittest.TestCase):
    def test_auto_prefers_directml_when_the_build_exposes_it(self):
        with patch.object(onnx_device, 'onnx_device_setting', return_value='auto'), \
             patch.dict('sys.modules', {'onnxruntime': fake_ort('DmlExecutionProvider', 'CPUExecutionProvider')}):
            self.assertEqual(onnx_device.onnx_providers(), ['DmlExecutionProvider', 'CPUExecutionProvider'])

    def test_auto_falls_back_to_cpu_without_directml(self):
        with patch.object(onnx_device, 'onnx_device_setting', return_value='auto'), \
             patch.dict('sys.modules', {'onnxruntime': fake_ort('CPUExecutionProvider')}):
            self.assertEqual(onnx_device.onnx_providers(), ['CPUExecutionProvider'])

    def test_cpu_setting_ignores_directml(self):
        with patch.object(onnx_device, 'onnx_device_setting', return_value='cpu'), \
             patch.dict('sys.modules', {'onnxruntime': fake_ort('DmlExecutionProvider', 'CPUExecutionProvider')}):
            self.assertEqual(onnx_device.onnx_providers(), ['CPUExecutionProvider'])

    def test_label_names_the_device(self):
        self.assertEqual(onnx_device.onnx_device_label(['DmlExecutionProvider', 'CPUExecutionProvider']),
                         'GPU · DirectML')
        self.assertEqual(onnx_device.onnx_device_label(['CPUExecutionProvider']), 'CPU · ONNX Runtime')

    def test_directml_failure_falls_back_to_cpu(self):
        attempts = []

        def load(providers):
            attempts.append(providers)
            if 'DmlExecutionProvider' in providers:
                raise RuntimeError('D3D12 device lost')
            return 'model'

        result, used = onnx_device.load_with_cpu_fallback(load, ['DmlExecutionProvider', 'CPUExecutionProvider'])
        self.assertEqual((result, used), ('model', ['CPUExecutionProvider']))
        self.assertEqual(len(attempts), 2)

    def test_cpu_failure_is_not_retried(self):
        def load(providers):
            raise RuntimeError('missing model file')

        with self.assertRaises(RuntimeError):
            onnx_device.load_with_cpu_fallback(load, ['CPUExecutionProvider'])


if __name__ == '__main__':
    unittest.main()
