"""Windows desktop entry point; the normal app.py web entry point is retained."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
import threading
import time


def main() -> int:
    parser = argparse.ArgumentParser(description='Auris desktop')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--headless', action='store_true', help='Run the packaged backend for QA or browser use')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--qa-exit-after', type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--check-runtime', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = (args.data_dir or Path(os.environ.get('AURIS_DATA_DIR') or
            Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Auris')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ['AURIS_DATA_DIR'] = str(root)
    os.environ['AURIS_DESKTOP'] = '1'
    os.environ['HF_HOME'] = str(root / 'models' / 'huggingface')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    install_root = Path(__file__).resolve().parents[2]
    tools = install_root / 'tools'
    if tools.is_dir():
        os.environ['PATH'] = str(tools) + os.pathsep + os.environ.get('PATH', '')
    from core.desktop_support import (InstanceLock, activate_gpu_runtime, install_pending_gpu_runtime,
                                      write_json, python_command)
    lock = InstanceLock(root)
    if not lock.acquire():
        if os.name == 'nt' and not args.headless:
            import ctypes
            window = ctypes.windll.user32.FindWindowW(None, 'Auris')
            if window:
                ctypes.windll.user32.ShowWindow(window, 9)
                ctypes.windll.user32.SetForegroundWindow(window)
        return 0
    install_pending_gpu_runtime(root)
    activate_gpu_runtime()
    logs = root / 'logs'
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / 'desktop.log', maxBytes=5_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s', force=True)
    logger = logging.getLogger('auris.desktop')
    server = None
    stop = threading.Event()
    restart_requested = threading.Event()
    window = None
    try:
        if args.check_runtime:
            import importlib.metadata as metadata
            import subprocess
            import torch
            import torchaudio
            import omnivoice
            import spacy
            import onnxruntime
            import webview
            check = subprocess.run([*python_command(), '-m', 'pip', 'check'],
                                   capture_output=True, text=True, timeout=60,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if check.returncode:
                raise RuntimeError(check.stdout + check.stderr)
            payload = {'python': sys.version.split()[0], 'prefix': sys.prefix,
                       'executable': sys.executable, 'torch': torch.__version__,
                       'cuda': torch.cuda.is_available(), 'dependencies': check.stdout.strip(),
                       'pywebview': metadata.version('pywebview'),
                       'data': str(root), 'sys_path': sys.path}
            write_json(root / 'runtime-check.json', payload)
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return 0
        import app as application
        from werkzeug.serving import make_server
        from core import backup_schedule
        from core.desktop_setup import SetupController, register, setup_complete
        controller = SetupController(root)

        def restart():
            restart_requested.set()
            if window:
                threading.Timer(0.5, window.destroy).start()
            else:
                stop.set()

        register(application.app, controller, restart)
        with application.app.app_context():
            application._startup()
        backup_schedule.start()
        server = make_server('127.0.0.1', args.port, application.app, threaded=True)
        url = f'http://127.0.0.1:{server.server_port}'
        write_json(root / 'runtime' / 'desktop-instance.json', {'pid': os.getpid(), 'url': url})
        logger.info('Auris desktop listening on %s; data=%s', url, root)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        if args.headless:
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            if args.qa_exit_after:
                threading.Timer(args.qa_exit_after, stop.set).start()
            stop.wait()
        else:
            import webview
            # pywebview cancels downloads by default; export, backup and
            # voice preset links need the native save dialog.
            webview.settings['ALLOW_DOWNLOADS'] = True
            page ='/' if setup_complete(root) else '/desktop/setup'
            window = webview.create_window('Auris', url + page, width=1280, height=860,
                                           min_size=(800, 600), background_color='#1c1a18',
                                           confirm_close=not bool(args.qa_exit_after))
            if args.qa_exit_after:
                window.events.loaded += lambda: threading.Timer(args.qa_exit_after, window.destroy).start()
            webview.start(gui='edgechromium', storage_path=str(root / 'runtime' / 'webview'),
                          private_mode=False, localization={
                              'global.quitConfirmation': 'Bezárod az Aurist? A futó háttérfeladatok leállnak.',
                              'global.ok': 'Igen', 'global.cancel': 'Mégsem',
                          })
        return 75 if restart_requested.is_set() else 0
    except Exception:
        logger.exception('Desktop startup failed')
        if os.name == 'nt' and not args.headless:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                f'Az Auris nem tudott elindulni.\n\nNapló: {logs / "desktop.log"}\n\n'
                'Ha a WebView2 hiányzik, futtasd újra az Auris telepítőjét internetkapcsolattal.',
                'Auris – indítási hiba', 0x10)
        return 1
    finally:
        if server:
            server.shutdown()
            server.server_close()
        lock.close()
        handler.close()


if __name__ == '__main__':
    raise SystemExit(main())
