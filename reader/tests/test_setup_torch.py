import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('auris_installer', Path(__file__).parents[1] / 'setup.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class TorchInstallTests(unittest.TestCase):
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
