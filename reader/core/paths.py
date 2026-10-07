"""Writable application paths; source installations keep their existing layout."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def storage_root() -> Path:
    override = os.environ.get('AURIS_DATA_DIR', '').strip()
    return Path(override).expanduser().resolve() if override else APP_DIR


def user_path(*parts: str) -> Path:
    return storage_root().joinpath(*parts)


def omnivoice_model() -> Path:
    if os.environ.get('AURIS_DATA_DIR', '').strip():
        return user_path('models', 'OmniVoice')
    return APP_DIR.parent / 'model_backup' / 'OmniVoice'


def higgs_model() -> Path:
    if os.environ.get('AURIS_DATA_DIR', '').strip():
        return user_path('models', 'Higgs-TTS-3-4B')
    return APP_DIR.parent / 'model_backup' / 'Higgs-TTS-3-4B'


def speaker_model_dir() -> Path:
    if os.environ.get('AURIS_DATA_DIR', '').strip():
        return user_path('models', 'speaker-embedding')
    return APP_DIR.parent / 'model_backup' / 'speaker-embedding'
