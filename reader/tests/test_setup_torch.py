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

    def test_pip_upgrade_leaves_setuptools_to_package_requirements(self):
        with patch.object(installer, 'run') as run:
            installer.ensure_pip()
        cmd = run.call_args.args[0]
        self.assertIn('pip', cmd[3:])
        self.assertNotIn('setuptools', cmd)
        # The Windows desktop build bundles wheel; `python -m venv` lacks it.
        self.assertIn('wheel', cmd)

    def test_installed_torch_pair_is_re_required_with_exact_versions(self):
        versions = {'torch': '2.11.0+rocm10.0.0', 'torchaudio': '2.11.0+rocm10.0.0'}
        with patch('importlib.metadata.version', side_effect=versions.__getitem__), \
             patch.object(installer, 'pip_install') as pip:
            installer.ensure_torch_requirements()
        pip.assert_called_once_with('torch==2.11.0+rocm10.0.0', 'torchaudio==2.11.0+rocm10.0.0')

    def test_torch_requirement_repair_failure_does_not_stop_setup(self):
        with patch('importlib.metadata.version', return_value='2.11.0'), \
             patch.object(installer, 'pip_install',
                          side_effect=installer.subprocess.CalledProcessError(1, 'pip')):
            installer.ensure_torch_requirements()

    @staticmethod
    def installed_packages(*names):
        from importlib import metadata

        def version(name):
            if name not in names:
                raise metadata.PackageNotFoundError(name)
            return '1.24.4'
        return patch('importlib.metadata.version', side_effect=version)

    def test_plain_onnxruntime_is_removed_before_directml_on_windows(self):
        with patch.object(installer, 'directml_platform', return_value=True), \
             patch.object(installer, 'STRICT_OFFLINE', False), \
             self.installed_packages('onnxruntime'), \
             patch.object(installer, 'run') as run:
            installer.remove_plain_onnxruntime()
        cmd = run.call_args.args[0]
        self.assertIn('uninstall', cmd)
        self.assertIn('onnxruntime', cmd)
        self.assertIn('onnxruntime-directml', cmd)

    def test_installed_directml_build_is_kept_even_offline_without_wheel(self):
        import tempfile
        with tempfile.TemporaryDirectory() as empty, \
             patch.object(installer, 'directml_platform', return_value=True), \
             patch.object(installer, 'STRICT_OFFLINE', True), \
             patch.object(installer, 'WHEELS_DIR', Path(empty)), \
             self.installed_packages('onnxruntime-directml'), \
             patch.object(installer, 'run') as run:
            installer.remove_plain_onnxruntime()
        run.assert_not_called()

    def test_python_310_keeps_plain_onnxruntime(self):
        with patch.object(installer.os, 'name', 'nt'), \
             patch.object(installer.sys, 'version_info', (3, 10, 11)), \
             patch.object(installer, 'run') as run:
            installer.remove_plain_onnxruntime()
        run.assert_not_called()

    def test_strict_offline_without_directml_wheel_stops_before_uninstalling(self):
        import tempfile
        with tempfile.TemporaryDirectory() as empty, \
             patch.object(installer, 'directml_platform', return_value=True), \
             patch.object(installer, 'STRICT_OFFLINE', True), \
             patch.object(installer, 'WHEELS_DIR', Path(empty)), \
             self.installed_packages('onnxruntime'), \
             patch.object(installer, 'run') as run:
            with self.assertRaises(RuntimeError):
                installer.remove_plain_onnxruntime()
        run.assert_not_called()

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
