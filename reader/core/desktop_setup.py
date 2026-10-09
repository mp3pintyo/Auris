"""First-run model downloads and optional private NVIDIA runtime."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

TORCH_VERSION = '2.11.0'


def setup_complete(root: Path) -> bool:
    try:
        return bool(json.loads((root / 'data' / 'settings.json').read_text(encoding='utf-8')).get('desktop_setup_complete'))
    except (OSError, ValueError):
        return False


def hardware() -> dict:
    result = {'nvidia': '', 'cuda': '', 'gpu_supported': False}
    try:
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        # nvidia-smi prints GPU process paths in the ANSI code page; an accented
        # path would otherwise fail UTF-8 decoding and leave stdout as None.
        flags['errors'] = 'replace'
        info = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=10, **flags)
        match = re.search(r'CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)', info.stdout)
        name = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                              capture_output=True, text=True, timeout=10, **flags)
        if info.returncode == 0 and match:
            result.update(nvidia=name.stdout.strip().split('\n')[0], cuda='.'.join(match.groups()),
                          gpu_supported=tuple(map(int, match.groups())) >= (12, 8))
    except (OSError, subprocess.SubprocessError):
        pass
    return result


class SetupController:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()
        self._state = {'state': 'idle', 'progress': 0, 'message': 'Válassz beszédmotort az első induláshoz.',
                       'file_bytes': 0, 'file_total': 0, 'restart_required': False}
        self._hardware = None

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def machine(self) -> dict:
        if self._hardware is None:
            self._hardware = hardware()
        return dict(self._hardware)

    def start(self, engine: str, gpu: bool) -> None:
        if engine not in ('supertonic', 'omnivoice'):
            raise ValueError('Ismeretlen beszédmotor.')
        if gpu and engine != 'omnivoice':
            raise ValueError('A Supertonichoz nem kell GPU-telepítés: a videokártyát DirectML-lel külön letöltés nélkül is használja.')
        if gpu and not self.machine()['gpu_supported']:
            raise ValueError('Ehhez az NVIDIA-gyorsításhoz CUDA 12.8-at támogató vagy újabb NVIDIA-illesztőprogram szükséges. CPU-val is elindíthatod.')
        with self._lock:
            if self._state['state'] == 'running':
                raise ValueError('A kezdeti beállítás már folyamatban van.')
            self._state.update(state='running', progress=0, message='A letöltés előkészítése…',
                               file_bytes=0, file_total=0, restart_required=False)
        threading.Thread(target=self._run, args=(engine, gpu), daemon=True).start()

    def _run(self, engine: str, gpu: bool):
        try:
            if gpu:
                self._install_gpu()
            self._download_model(engine)
            from core import settings
            from core.paths import omnivoice_model
            values = {'tts_engine': engine, 'desktop_setup_complete': True,
                      'onboarding_complete': True}
            if engine == 'omnivoice':
                values.update(model_path=str(omnivoice_model()), model_source='local')
            settings.save(values)
            self._update(state='done', progress=100, message='Az Auris használatra kész.', restart_required=gpu)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception('Desktop setup failed')
            self._update(state='error', message=f'A beállítás nem fejeződött be: {exc}. Ellenőrizd az internetkapcsolatot és a szabad tárhelyet, majd próbáld újra.')

    def _install_gpu(self):
        from core.desktop_support import write_json, python_command
        runtime = self.root / 'runtime'
        target = runtime / 'gpu'
        if (target / 'ready.json').is_file():
            return
        stage = runtime / ('gpu-download-' + uuid.uuid4().hex)
        stage.mkdir(parents=True)
        self._update(message='NVIDIA-gyorsítás letöltése és telepítése. Több GB, néhány percet igényelhet…', progress=1)
        try:
            log_path = self.root / 'logs' / 'gpu-install.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            with log_path.open('w', encoding='utf-8') as output:
                subprocess.run([*python_command(), '-m', 'pip', 'install', '--disable-pip-version-check',
                                '--no-warn-script-location', '--no-deps', '--target', str(stage),
                                f'torch=={TORCH_VERSION}+cu128', f'torchaudio=={TORCH_VERSION}+cu128',
                                '--index-url', 'https://download.pytorch.org/whl/cu128'],
                               stdout=output, stderr=subprocess.STDOUT, check=True, **flags)
                probe = 'import sys;sys.path.insert(0,sys.argv[1]);import torch,torchaudio;assert torch.cuda.is_available();print(torch.cuda.get_device_name(0))'
                subprocess.run([*python_command(), '-c', probe, str(stage)], stdout=output,
                               stderr=subprocess.STDOUT, check=True, **flags)
            write_json(stage / 'ready.json', {'torch': TORCH_VERSION, 'variant': 'cu128'})
            # No running process ever imports an incomplete GPU installation.
            if target.exists():
                raise RuntimeError('A GPU-mappa már létezik; az eltérő telepítést a napló alapján javítani kell.')
            stage.rename(target)
        finally:
            if stage.exists() and stage.resolve().parent == runtime.resolve():
                shutil.rmtree(stage)

    def _download_model(self, engine: str):
        from huggingface_hub import hf_hub_download, list_repo_files
        from tqdm.auto import tqdm
        from core.local_engines import SUPERTONIC_REPO, SUPERTONIC_REVISION
        from core.paths import omnivoice_model

        if engine == 'supertonic':
            repo, revision = SUPERTONIC_REPO, SUPERTONIC_REVISION
            dest = self.root / 'models' / 'supertonic-3'
            patterns = ['onnx/*', 'voice_styles/*', 'LICENSE*', 'README*']
        else:
            repo, revision = 'k2-fsa/OmniVoice', None
            dest = omnivoice_model()
            patterns = ['*']
        files = [name for name in list_repo_files(repo, revision=revision)
                 if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)]
        if not files:
            raise RuntimeError('A modelltároló nem tartalmaz letölthető fájlokat.')
        owner = self
        index = 0

        class DownloadProgress(tqdm):
            def __init__(self, *args, **kwargs):
                kwargs['disable'] = False
                super().__init__(*args, **kwargs)

            def update(self, n=1):
                value = super().update(n)
                total = self.total or 0
                fraction = min(1, self.n / total) if total else 0
                owner._update(progress=10 + int(85 * (index + fraction) / len(files)),
                              file_bytes=self.n, file_total=total)
                return value

            def display(self, *args, **kwargs):
                return None

        for index, name in enumerate(files):
            self._update(message=f'Modell letöltése: {name} ({index + 1}/{len(files)})',
                         progress=10 + int(85 * index / len(files)), file_bytes=0, file_total=0)
            hf_hub_download(repo_id=repo, filename=name, revision=revision,
                            local_dir=str(dest), tqdm_class=DownloadProgress)
        # Load the selected model before reporting a successful setup.
        self._update(message='A letöltött modell ellenőrzése…', progress=96)
        if engine == 'supertonic':
            from core.local_engines import SupertonicEngine
            model = SupertonicEngine()
            model._load_model()
            model._release()
        else:
            if not (dest / 'config.json').is_file() or not list(dest.glob('*.safetensors')):
                raise RuntimeError('A letöltött OmniVoice-modell hiányos.')


def register(app, controller: SetupController, restart):
    from flask import Blueprint, jsonify, render_template, request
    bp = Blueprint('desktop', __name__)

    @bp.get('/desktop/setup')
    def setup_page():
        return render_template('desktop_setup.html', hardware=controller.machine(),
                               data_dir=str(controller.root), complete=setup_complete(controller.root))

    @bp.get('/api/desktop/status')
    def status():
        return jsonify(controller.status())

    @bp.post('/api/desktop/setup')
    def begin():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or not isinstance(body.get('gpu', False), bool):
            return jsonify(error='Érvénytelen beállítás.'), 400
        try:
            controller.start(body.get('engine', 'supertonic'), body.get('gpu', False))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True), 202

    @bp.post('/api/desktop/restart')
    def restart_route():
        if controller.status()['state'] == 'running':
            return jsonify(error='Várd meg a folyamatban lévő beállítást.'), 409
        restart()
        return jsonify(ok=True)

    app.register_blueprint(bp)
