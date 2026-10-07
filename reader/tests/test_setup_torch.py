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
        with patch.object(installer, 'verify_torch') as verify, \
             patch.object(installer, 'pip_install') as pip, \
             patch.object(installer, 'run'):
            installer.install_torch('rocm')
        verify.assert_called_once_with('rocm')
        pip.assert_not_called()

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
