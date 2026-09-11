"""Local daily/weekly backups while Auris is running; durable scheduling state."""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from core.database import get_db_path

_lock = threading.RLock()
_running = False
_started = False
INTERVALS = {'daily': 86400, 'weekly': 7 * 86400}
NAME = re.compile(r'auris-auto-\d+-[0-9a-f]{32}\.zip')


def folder():
    return Path(get_db_path()).parent / 'backups' / 'scheduled'


def _state_path():
    return Path(get_db_path()).parent / 'backup-schedule.json'


def _read():
    state = {'frequency': 'off', 'keep': 7, 'next_due': None, 'last_success': None,
             'last_error': '', 'retry_after': 0}
    if _state_path().is_file():
        state.update(json.loads(_state_path().read_text(encoding='utf-8')))
    return state


def _write(state):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def status():
    with _lock:
        state = _read()
        files = sorted((p for p in folder().glob('*.zip') if NAME.fullmatch(p.name)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return {**state, 'running': _running, 'directory': str(folder()),
                'files': [{'name': p.name, 'bytes': p.stat().st_size,
                           'download': '/api/backup/schedule/files/' + p.name} for p in files]}


def configure(values, now=None):
    now = time.time() if now is None else now
    frequency = values.get('frequency', 'off')
    keep = values.get('keep', 7)
    if frequency not in {'off', *INTERVALS} or type(keep) is not int or not 1 <= keep <= 100:
        raise ValueError('Válassz napi/heti mentést vagy kikapcsolást, és 1–100 megőrzött mentést.')
    with _lock:
        state = _read()
        if frequency != state['frequency']:
            state['next_due'] = now + INTERVALS[frequency] if frequency in INTERVALS else None
        state.update(frequency=frequency, keep=keep, retry_after=0)
        _write(state)
    return status()


def run_backup(*, force=False, now=None):
    global _running
    now = time.time() if now is None else now
    with _lock:
        state = _read()
        if _running:
            return False
        if not force and (state['frequency'] == 'off' or not state['next_due']
                          or now < state['next_due'] or now < state['retry_after']):
            return False
        _running = True
    temporary = None
    try:
        # Same gate as manual restore/import/deletion. Never snapshot midway
        # through a destructive library replacement or active generation.
        import app as application
        from core.experience_api import _assert_idle
        from core.library_backup import create_backup
        with application._work_dispatch_lock:
            _assert_idle()
            target = folder() / f'auris-auto-{int(now)}-{uuid.uuid4().hex}.zip'
            temporary = target.with_suffix('.partial')
            create_backup(temporary, include_audio=False)
            os.replace(temporary, target)
        with _lock:
            state = _read()
            state.update(last_success=now, last_error='', retry_after=0,
                         next_due=now + INTERVALS[state['frequency']] if state['frequency'] in INTERVALS else None)
            _write(state)
            files = sorted((p for p in folder().glob('*.zip') if NAME.fullmatch(p.name)),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[state['keep']:]:
                old.unlink()
        return True
    except Exception as exc:
        with _lock:
            state = _read()
            state.update(last_error=str(exc), retry_after=now + 300)
            _write(state)
        return False
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
        with _lock:
            _running = False


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def worker():
        while True:
            try:
                run_backup()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Scheduled backup check failed')
            time.sleep(30)
    threading.Thread(target=worker, daemon=True, name='auris-backup').start()
