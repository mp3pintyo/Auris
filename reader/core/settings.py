"""
Persistent settings — stored in data/settings.json.
All path defaults are resolved relative to the repo root at runtime,
so the app works on Windows, Linux, and macOS without modification.
"""

import json
import os
import sys
import threading
from pathlib import Path

# reader/ directory
_APP_DIR   = Path(__file__).resolve().parent.parent
# E:\Ebook-Reader\ (or equivalent on other platforms)
_REPO_ROOT = _APP_DIR.parent

SETTINGS_FILE = _APP_DIR / 'data' / 'settings.json'

# Default model path = <repo_root>/model_backup/OmniVoice
_DEFAULT_MODEL_PATH = str(_REPO_ROOT / 'model_backup' / 'OmniVoice')
LEGACY_NARRATOR_INSTRUCT = 'female, middle-aged, moderate pitch, american accent'
DEFAULT_NARRATOR_INSTRUCT = 'male, elderly, low pitch, british accent'

DEFAULTS: dict = {
    # Model
    'model_source': 'local',           # 'local' | 'download'
    'model_path': _DEFAULT_MODEL_PATH,
    'model_repo': 'k2-fsa/OmniVoice',
    'hf_endpoint': '',                 # e.g. https://hf-mirror.com for restricted networks

    # Narrator
    'narrator_instruct': DEFAULT_NARRATOR_INSTRUCT,
    'single_narrator_mode': False,

    # Playback defaults
    'default_speed': 1.0,

    # Export defaults
    'audio_format': 'wav',
    'subtitle_format': 'ass',

    # UI
    'theme': 'night',
    'font_size': 18,
    'font_family': 'serif',
    'line_height': 1.9,
}


def load() -> dict:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
            merged = {**DEFAULTS, **saved}
            narrator_instruct = str(merged.get('narrator_instruct') or '').strip().lower()
            if narrator_instruct in {'', LEGACY_NARRATOR_INSTRUCT.lower()}:
                merged['narrator_instruct'] = DEFAULT_NARRATOR_INSTRUCT
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save(updates: dict) -> dict:
    current = load()
    current.update(updates)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, indent=2)
    return current


def get(key: str, default=None):
    return load().get(key, default)


# ── spaCy status ──────────────────────────────────────────────────────────────

def spacy_status() -> dict:
    """Returns {'installed': bool, 'model_installed': bool, 'model': str}"""
    try:
        import spacy
        spacy_ok = True
    except ImportError:
        return {'installed': False, 'model_installed': False, 'model': 'en_core_web_sm'}

    try:
        spacy.load('en_core_web_sm')
        model_ok = True
    except OSError:
        model_ok = False

    return {'installed': spacy_ok, 'model_installed': model_ok, 'model': 'en_core_web_sm'}


def install_spacy_model() -> dict:
    """Run 'python -m spacy download en_core_web_sm' as a subprocess."""
    import subprocess
    python = sys.executable
    result = subprocess.run(
        [python, '-m', 'spacy', 'download', 'en_core_web_sm'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return {'ok': True, 'message': 'en_core_web_sm installed successfully.'}
    return {'ok': False, 'message': result.stderr or result.stdout}


# ── HuggingFace model download ────────────────────────────────────────────────

_dl_state: dict = {'status': 'idle', 'pct': 0, 'message': '', 'dest': ''}
_dl_lock = threading.Lock()


def download_state() -> dict:
    with _dl_lock:
        return dict(_dl_state)


def _set_dl(status, pct, message, dest=''):
    with _dl_lock:
        _dl_state.update({'status': status, 'pct': pct, 'message': message, 'dest': dest})


def start_model_download(repo_id: str, dest_dir: str, hf_endpoint: str = '') -> None:
    """Kick off a background download of a HuggingFace model."""
    if _dl_state['status'] == 'downloading':
        return
    t = threading.Thread(
        target=_do_download, args=(repo_id, dest_dir, hf_endpoint), daemon=True
    )
    t.start()


def _do_download(repo_id: str, dest_dir: str, hf_endpoint: str):
    _set_dl('downloading', 0, f'Connecting to HuggingFace for {repo_id}…', dest_dir)
    try:
        if hf_endpoint:
            os.environ['HF_ENDPOINT'] = hf_endpoint

        from huggingface_hub import list_repo_files, hf_hub_download
        import huggingface_hub

        _set_dl('downloading', 2, 'Listing repository files…', dest_dir)

        files = list(list_repo_files(repo_id))
        total = len(files)
        if total == 0:
            _set_dl('error', 0, 'No files found in repository.', dest_dir)
            return

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        for i, filename in enumerate(files):
            pct = int((i / total) * 95)
            _set_dl('downloading', pct, f'Downloading {filename} ({i+1}/{total})…', dest_dir)
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(dest),
            )

        _set_dl('done', 100, f'Download complete → {dest_dir}', dest_dir)

        # Persist the new model path in settings
        save({'model_path': dest_dir, 'model_source': 'local'})

    except Exception as e:
        _set_dl('error', 0, str(e), dest_dir)
