import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('auris_installer', Path(__file__).parents[1] / 'setup.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class TorchInstallTests(unittest.TestCase):
    def test_new_nvidia_smi_umd_version_is_detected(self):
        from types import SimpleNamespace
        result = SimpleNamespace(returncode=0, stdout='CUDA UMD Version: 13.4')
        with patch.object(installer.subprocess, 'run', return_value=result):
            self.assertEqual(installer.detect_cuda_version(), '13.4')

    def test_rocm_install_preserves_verified_vendor_runtime(self):
        with patch.object(installer, 'rocm_runtime_works', return_value=True), \
             patch.object(installer, 'verify_torch') as verify, \
             patch.object(installer, 'pip_install') as pip, \
             patch.object(installer, 'run') as run:
            installer.install_torch('rocm')
        verify.assert_called_once_with('rocm')
        pip.assert_not_called()
        run.assert_not_called()

    def test_rocm_install_pins_amd_build_with_device_extra(self):
        with patch.object(installer, 'rocm_runtime_works', return_value=False), \
             patch.object(installer, 'amd_gpu_names', return_value=['AMD Radeon RX 6600']), \
             patch.object(installer, 'verify_torch'), \
             patch.object(installer, 'run') as run:
            installer.install_torch('rocm')
        cmd = run.call_args.args[0]
        self.assertIn(installer.ROCM_INDEX_URL, cmd)
        self.assertIn(f'torch[device-gfx1032]=={installer.ROCM_TORCH_VERSION}', cmd)
        self.assertIn(f'torchaudio=={installer.ROCM_TORCH_VERSION}', cmd)

    def test_failed_rocm_install_falls_back_to_cpu_torch(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if any('rocm' in str(arg) for arg in cmd):
                raise installer.subprocess.CalledProcessError(1, cmd)

        with patch.object(installer, 'rocm_runtime_works', return_value=False), \
             patch.object(installer, 'amd_gpu_names', return_value=['AMD Radeon RX 6600']), \
             patch.object(installer, 'run', side_effect=fake_run), \
             patch.object(installer, 'pip_install') as pip:
            self.assertEqual(installer.install_torch('rocm'), 'cpu')
        self.assertTrue(any('uninstall' in cmd for cmd in calls), 'Remove a half-installed ROCm torch')
        pip.assert_called_once_with(installer.TORCH_SPEC, installer.TORCHAUDIO_SPEC)

    def test_amd_detection_is_skipped_on_macos(self):
        with patch.object(installer.platform, 'system', return_value='Darwin'), \
             patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.amd_gpu_names(), [])
        run.assert_not_called()

    def test_strict_offline_amd_install_uses_cpu_torch(self):
        with patch.object(installer, 'STRICT_OFFLINE', True), \
             patch.object(installer, 'rocm_runtime_works', return_value=False), \
             patch.object(installer, 'install_rocm_torch') as rocm, \
             patch.object(installer, 'pip_install'):
            self.assertEqual(installer.install_torch('rocm'), 'cpu')
        rocm.assert_not_called()

    def test_amd_gpu_is_detected_when_no_nvidia_gpu_exists(self):
        with patch.dict(installer.os.environ, {'AURIS_TORCH_VARIANT': '', 'AURIS_ROCM_GFX': ''}), \
             patch.object(installer, 'is_apple_silicon', return_value=False), \
             patch.object(installer, 'rocm_runtime_works', return_value=False), \
             patch.object(installer, 'detect_cuda_version', return_value=None), \
             patch.object(installer, 'amd_gpu_names', return_value=['AMD Radeon RX 6600']):
            self.assertEqual(installer.detect_hardware(), 'rocm')

    def test_rocm_validation_requires_hip(self):
        with patch.object(installer, 'run') as run:
            installer.verify_torch('rocm')
        self.assertIn('torch.version.hip', run.call_args.args[0][-1])

    def test_cuda_wheels_are_selected_without_pypi_and_installed_as_exact_files(self):
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            if 'download' in cmd:
                dest = Path(cmd[cmd.index('--dest') + 1])
                for name in ('torch', 'torchaudio'):
                    (dest / f'{name}-2.11.0+cu128-cp311-cp311-win_amd64.whl').touch()

        with patch.object(installer, 'offline_wheels_available', return_value=False), \
             patch.object(installer, 'run', side_effect=fake_run):
            installer.install_torch('cu128')
        downloads = [cmd for cmd in commands if 'download' in cmd]
        self.assertEqual(len(downloads), 1, 'Select binaries only from the CUDA index')
        self.assertIn('--no-deps', downloads[0])
        self.assertNotIn('--extra-index-url', downloads[0])
        self.assertIn('https://download.pytorch.org/whl/cu128', downloads[0])
        installs = [cmd for cmd in commands if 'install' in cmd and any(str(arg).endswith('.whl') for arg in cmd)]
        self.assertEqual(len(installs), 1)
        self.assertEqual(sum(str(arg).endswith('.whl') for arg in installs[0]), 2)
        self.assertFalse(any('uninstall' in cmd for cmd in commands), 'Keep old packages until downloads succeed')

    def test_runtime_validation_checks_native_audio_and_cuda(self):
        with patch.object(installer, 'run') as run:
            installer.verify_torch('cu128')
        code = run.call_args.args[0][-1]
        self.assertIn('import torchaudio', code)
        self.assertIn('torch.cuda.is_available()', code)


if __name__ == '__main__':
    unittest.main()
