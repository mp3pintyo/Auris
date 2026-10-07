"""Desktop isolation, startup ownership, and setup input regressions."""
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DesktopPathsTests(unittest.TestCase):
    def test_cpu_bundle_keeps_torch_dependencies_when_replacing_gpu_binaries(self):
        import importlib.util
        script = Path(__file__).resolve().parents[2] / 'scripts' / 'windows' / 'build.py'
        spec = importlib.util.spec_from_file_location('desktop_build_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dependencies = module.dependency_closure()
        self.assertIn('sympy', dependencies)
        self.assertIn('networkx', dependencies)
        self.assertIn('mpmath', dependencies)
        self.assertNotIn('torch', dependencies)

    def test_bundle_takes_the_installed_onnxruntime_build(self):
        import importlib.metadata as metadata
        import importlib.util
        script = Path(__file__).resolve().parents[2] / 'scripts' / 'windows' / 'build.py'
        spec = importlib.util.spec_from_file_location('desktop_build_ort_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real = metadata.distribution

        def only(installed):
            def distribution(name):
                if name in ('onnxruntime', 'onnxruntime-directml') and name != installed:
                    raise metadata.PackageNotFoundError(name)
                return real(name) if name not in ('onnxruntime', 'onnxruntime-directml') else object()
            return distribution

        for installed in ('onnxruntime-directml', 'onnxruntime'):
            with patch.object(module.metadata, 'distribution', side_effect=only(installed)):
                self.assertEqual(module.onnxruntime_distribution(), installed)

    def test_default_paths_preserve_source_installation(self):
        from core import paths
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.storage_root(), paths.APP_DIR)
            self.assertEqual(paths.omnivoice_model(), paths.APP_DIR.parent / 'model_backup' / 'OmniVoice')

    def test_desktop_storage_is_separate_from_program_files(self):
        from core import paths
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'AURIS_DATA_DIR': folder}):
            self.assertEqual(paths.user_path('data', 'reader.db'), Path(folder) / 'data' / 'reader.db')
            self.assertEqual(paths.omnivoice_model(), Path(folder) / 'models' / 'OmniVoice')


class DesktopLifecycleTests(unittest.TestCase):
    def test_desktop_workers_disable_user_site_packages_and_use_utf8(self):
        from core.desktop_support import python_command
        with patch.dict(os.environ, {'AURIS_DESKTOP': '1'}):
            self.assertEqual(python_command('bundled-python'), ['bundled-python', '-s', '-X', 'utf8'])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(python_command('source-python'), ['source-python'])

    def test_second_process_cannot_own_the_same_library(self):
        from core.desktop_support import InstanceLock
        with tempfile.TemporaryDirectory() as folder:
            first, second = InstanceLock(Path(folder)), InstanceLock(Path(folder))
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.close()
                second.close()
            third = InstanceLock(Path(folder))
            self.assertTrue(third.acquire())
            third.close()

    def test_worker_runtime_is_selected_before_library_imports(self):
        from core.desktop_support import activate_gpu_runtime
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'AURIS_DATA_DIR': folder}):
            runtime = Path(folder) / 'runtime' / 'gpu'
            runtime.mkdir(parents=True)
            (runtime / 'ready.json').write_text('{}')
            with patch('sys.path', []):
                activate_gpu_runtime()
                import sys
                self.assertEqual(sys.path[0], str(runtime))


class DesktopSetupTests(unittest.TestCase):
    def setUp(self):
        from core import desktop_setup
        self.setup = desktop_setup
        self.controller = desktop_setup.SetupController(Path(tempfile.gettempdir()) / 'auris-unit-test')

    def test_modern_nvidia_smi_umd_header_is_recognised(self):
        import subprocess
        outputs = [subprocess.CompletedProcess([], 0, 'CUDA UMD Version: 13.4', ''),
                   subprocess.CompletedProcess([], 0, 'NVIDIA GeForce RTX 3090\n', '')]
        with patch('core.desktop_setup.subprocess.run', side_effect=outputs):
            info = self.setup.hardware()
        self.assertTrue(info['gpu_supported'])
        self.assertEqual(info['nvidia'], 'NVIDIA GeForce RTX 3090')

    def test_unknown_engine_is_rejected_before_network_work(self):
        with self.assertRaises(ValueError):
            self.controller.start('arbitrary-engine', False)

    def test_gpu_is_rejected_for_the_cpu_engine(self):
        with self.assertRaises(ValueError):
            self.controller.start('supertonic', True)

    def test_finished_setup_does_not_replace_existing_user_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'data' / 'settings.json'
            target.parent.mkdir()
            target.write_text('{"theme":"paper","desktop_setup_complete":true,"tts_engine":"omnivoice"}')
            self.assertTrue(self.setup.setup_complete(Path(folder)))
            self.assertEqual(target.read_text(), '{"theme":"paper","desktop_setup_complete":true,"tts_engine":"omnivoice"}')


if __name__ == '__main__':
    unittest.main()
