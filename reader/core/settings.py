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
_settings_write_lock = threading.RLock()

# Default model path = <repo_root>/model_backup/OmniVoice
_DEFAULT_MODEL_PATH = str(_REPO_ROOT / 'model_backup' / 'OmniVoice')
_DEFAULT_HIGGS_MODEL_PATH = str(_REPO_ROOT / 'model_backup' / 'Higgs-TTS-3-4B')
LEGACY_NARRATOR_INSTRUCT = 'female, middle-aged, moderate pitch, american accent'
# Foreign accents in the voice description pull Hungarian stress and vowels
# towards English, so the default narrator carries no accent.
PREVIOUS_NARRATOR_INSTRUCT = 'male, elderly, low pitch, british accent'
DEFAULT_NARRATOR_INSTRUCT = 'male, middle-aged, low pitch'
TTS_EXPRESSION_POLICY_VERSION = 2
TTS_SEGMENT_BOUNDARY_POLICY_VERSION = 2

DEFAULTS: dict = {
    # Active TTS engine. Each engine keeps an independent model configuration.
    'tts_engine': 'omnivoice',          # 'omnivoice' | 'higgs'

    # OmniVoice model
    'model_source': 'local',           # 'local' | 'download'
    'model_path': _DEFAULT_MODEL_PATH,
    'model_repo': 'k2-fsa/OmniVoice',
    'hf_endpoint': '',                 # e.g. https://hf-mirror.com for restricted networks

    # Higgs TTS 3 (Transformers-compatible port used for direct local inference)
    'higgs_model_source': 'download',  # 'local' | 'download' (HF cache)
    'higgs_model_path': _DEFAULT_HIGGS_MODEL_PATH,
    'higgs_model_repo': 'multimodalart/higgs-audio-v3-tts-4b-transformers',
    'higgs_temperature': 0.8,
    'higgs_top_p': 0.95,
    'higgs_top_k': 50,
    # ~25 audio frames per second: 2048 leaves room for a 500-character
    # segment read slowly (1024 could cut off after ~41 s).
    'higgs_max_new_tokens': 2048,
    'higgs_seed': -1,
    # raw = match the reference Gradio app (plain text, no automatic controls)
    # expressive = apply Auris normalization, scene speed and expression tags
    'higgs_prompt_mode': 'raw',
    'higgs_default_emotion': 'none',
    'higgs_default_style': 'none',
    'higgs_default_expressive': 'none',

    # Narrator
    'narrator_instruct': DEFAULT_NARRATOR_INSTRUCT,
    'single_narrator_mode': False,

    # Character and dialogue-speaker detection. "llm" can use either a local
    # OpenAI-compatible server (LM Studio, Ollama, llama.cpp) or OpenAI's API;
    # "legacy" keeps the original English spaCy/regex detector.
    'character_detection_mode': 'legacy',
    'llm_provider': 'local',           # 'local' | 'openai'
    'llm_base_url': 'http://127.0.0.1:1234/v1',
    'llm_api_key': '',
    'llm_model': '',
    'openai_api_key': '',
    'openai_model': '',
    'llm_timeout_sec': 600,
    'llm_max_output_tokens': 8192,
    'llm_max_characters': 60,
    # Keep both prompt and compact per-dialogue JSON comfortably inside the
    # output budget. A normal novel is therefore analyzed one chapter/request.
    'llm_batch_chars': 10000,

    # Playback defaults
    'default_speed': 1.0,

    # TTS text processing
    # Expand numbers/dates/currency into spoken form before synthesis.
    # EN/ZH prefer WeTextProcessing (optional); other languages use num2words.
    'normalize_text': True,

    # Internal migration marker. Version 2 stops treating OmniVoice's literal
    # "oh/ah" non-verbal tags as silent punctuation/prosody controls.
    'tts_expression_policy_version': TTS_EXPRESSION_POLICY_VERSION,
    # Version 1 disables proportional waveform splitting of coalesced lines.
    'tts_segment_boundary_policy_version': TTS_SEGMENT_BOUNDARY_POLICY_VERSION,

    # How many segments to synthesize in one OmniVoice.generate() call.
    # 0 = auto from free VRAM (recommended). Larger values keep the GPU busier.
    # On OOM the engine automatically halves the batch and retries.
    'tts_batch_size': 0,

    # Exact sentence audio boundaries take priority over unsafe waveform
    # splitting. GPU batching still combines independent synthesis requests.
    'tts_coalesce_chars': 0,

    # OmniVoice iterative decoding steps for playback and export.
    # Higher = better quality but slower. 16 is a good default; 32 is max quality.
    'tts_num_step': 16,

    # Inference acceleration: off | auto | eager | cuda_graph | triton | hybrid
    # Auto: NVIDIA CUDA Graph; ROCm/MPS/CPU portable scoring optimization.
    # cuda_graph = pure PyTorch; speed depends on workload and shape reuse.
    # triton/hybrid need the Triton compiler (triton or triton-windows); the kernels are vendored.
    'tts_accel': 'auto',

    # Parallel model replicas for export: 0 = auto, 1 = off, 2 = dual worker.
    # Auto enables two replicas on CUDA cards with at least 20GB VRAM.
    'tts_export_workers': 0,

    # Export defaults
    'audio_format': 'wav',
    'subtitle_format': 'ass',
    # Conservative FFmpeg EQ/compression + two-pass chapter loudness matching.
    'audio_mastering': True,
    # Render voice descriptions once into an anchor clip, then clone it.
    'voice_design_anchor': True,
    # Export: trim model silence at sentence edges; optional ACX room tone
    'trim_segment_silence': True,
    'export_room_tone': False,
    # Publishing: credits and Audiobookshelf server
    'narrator_credit': '',
    'export_intro_template': '{title}. Írta: {author}. Felolvassa: {narrator}.',
    'export_outro_template': 'Vége. {title}. Írta: {author}.',
    'abs_url': '',
    'abs_api_token': '',
    'abs_library_id': '',
    'abs_folder_id': '',
    # Optional bearer token for the OpenAI-compatible /v1 speech API
    'api_token': '',
    # Quality control (core/qa.py): character error rate thresholds
    'qa_cer_warn': 0.08,
    'qa_cer_fail': 0.15,
    'qa_max_takes': 3,
    'asr_model': '',
    # auto: Whisper on a CUDA GPU, Parakeet + Whisper confirmation on CPU.
    'asr_backend': 'auto',
    'asr_keep_loaded': False,
    # ONNX engines (Supertonic, Parakeet): auto uses DirectML
    # on Windows when onnxruntime-directml is installed, cpu forces the CPU.
    'onnx_device': 'auto',
    # Additional engines (core/local_engines.py)
    'piper_voice': 'anna',
    'supertonic_voice': 'F1',
    'supertonic_steps': 10,
    'moss_seed': 1234,
    'moss_temperature': 1.7,
    'moss_top_p': 0.8,
    'moss_top_k': 25,

    # UI
    'theme': 'night',
    'font_size': 18,
    'font_family': 'serif',
    'line_height': 1.9,
}


_load_cache: dict[str, tuple[tuple[int, int], dict]] = {}
_load_cache_lock = threading.Lock()


def _normalize_loaded(saved: dict) -> dict:
    merged = {**DEFAULTS, **saved}
    narrator_instruct = str(merged.get('narrator_instruct') or '').strip().lower()
    if narrator_instruct in {
        '', LEGACY_NARRATOR_INSTRUCT.lower(), PREVIOUS_NARRATOR_INSTRUCT.lower(),
    }:
        merged['narrator_instruct'] = DEFAULT_NARRATOR_INSTRUCT
    return merged


def load() -> dict:
    """Return settings, cached by file identity.

    A transient read failure (for example while ``save`` replaces the file on
    Windows) must never silently switch the app to defaults: that would flip
    the active TTS engine mid-session. The last good copy is used instead.
    """
    path = SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    cache_key = str(path)
    last_error = None
    for attempt in range(4):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return dict(DEFAULTS)
        except OSError as exc:
            last_error = exc
        else:
            identity = (st.st_mtime_ns, st.st_size)
            with _load_cache_lock:
                cached = _load_cache.get(cache_key)
            if cached and cached[0] == identity:
                return dict(cached[1])
            try:
                with open(path, encoding='utf-8') as f:
                    saved = json.load(f)
                if not isinstance(saved, dict):
                    raise ValueError('settings.json must contain an object')
                merged = _normalize_loaded(saved)
                with _load_cache_lock:
                    _load_cache[cache_key] = (identity, merged)
                return dict(merged)
            except (OSError, ValueError) as exc:
                last_error = exc
        if attempt < 3:
            import time
            time.sleep(0.02 * (attempt + 1))
    with _load_cache_lock:
        cached = _load_cache.get(cache_key)
    if cached:
        return dict(cached[1])
    import logging
    logging.getLogger(__name__).warning('Unable to read settings (%s); using defaults.', last_error)
    return dict(DEFAULTS)


def save(updates: dict) -> dict:
    with _settings_write_lock:
        current = load()
        current.update(updates)
        temporary = SETTINGS_FILE.with_suffix('.json.tmp')
        try:
            with open(temporary, 'w', encoding='utf-8') as f:
                json.dump(current, f, indent=2, ensure_ascii=False)
            for attempt in range(5):
                try:
                    os.replace(temporary, SETTINGS_FILE)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    import time
                    time.sleep(0.05 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)
        try:
            st = os.stat(SETTINGS_FILE)
            with _load_cache_lock:
                _load_cache[str(SETTINGS_FILE)] = (
                    (st.st_mtime_ns, st.st_size), _normalize_loaded(current)
                )
        except OSError:
            pass
        return current


def migrate_tts_expression_policy_version() -> bool:
    """Record the expression policy and report whether segment prompts are stale."""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
        else:
            saved = {}
        previous = int(saved.get('tts_expression_policy_version', 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        previous = 0

    if previous == TTS_EXPRESSION_POLICY_VERSION:
        return False

    save({'tts_expression_policy_version': TTS_EXPRESSION_POLICY_VERSION})
    return True


def migrate_tts_segment_boundary_policy_version() -> bool:
    """Disable unsafe line coalescing once and mark cached segments stale."""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
        else:
            saved = {}
        previous = int(saved.get('tts_segment_boundary_policy_version', 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        previous = 0

    if previous == TTS_SEGMENT_BOUNDARY_POLICY_VERSION:
        return False

    save({
        'tts_segment_boundary_policy_version':
            TTS_SEGMENT_BOUNDARY_POLICY_VERSION,
        'tts_coalesce_chars': 0,
    })
    return True


# Bumped when a release changes how existing segment audio must be rendered
# (voice anchoring, Hungarian normalization). Clone voices re-hit the WAV
# cache; only audio whose identity changed is synthesized again.
TTS_RENDER_POLICY_VERSION = 1


def current_tts_render_policy() -> str:
    from core import hungarian_numbers
    from core.tts_engine import VOICE_DESIGN_ANCHOR_VERSION

    return (
        f"r{TTS_RENDER_POLICY_VERSION}"
        f"-n{getattr(hungarian_numbers, 'NORMALIZER_VERSION', 1)}"
        f"-a{VOICE_DESIGN_ANCHOR_VERSION}"
    )


def migrate_tts_render_policy_version() -> bool:
    """Record the render policy; True when segment rows must be rebuilt."""
    policy = current_tts_render_policy()
    if str(load().get('tts_render_policy', '')) == policy:
        return False
    save({'tts_render_policy': policy})
    return True


def get(key: str, default=None):
    return load().get(key, default)


# ── spaCy status ──────────────────────────────────────────────────────────────

HUNGARIAN_SPACY_MODEL = 'hu_core_news_md'
HUNGARIAN_SPACY_VERSION = '3.8.1'
HUNGARIAN_SPACY_URL = (
    'https://huggingface.co/huspacy/hu_core_news_md/resolve/main/'
    'hu_core_news_md-any-py3-none-any.whl'
)


def _spacy_package_installed(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def spacy_status() -> dict:
    """Returns spaCy availability for English and Hungarian (HuSpaCy) models."""
    try:
        import spacy  # noqa: F401
        spacy_ok = True
    except ImportError:
        return {
            'installed': False, 'model_installed': False, 'model': 'en_core_web_sm',
            'hu_model_installed': False, 'hu_model': HUNGARIAN_SPACY_MODEL,
        }
    hu_installed = next(
        (m for m in ('hu_core_news_lg', 'hu_core_news_md', 'hu_core_news_trf')
         if _spacy_package_installed(m)),
        None,
    )
    return {
        'installed': spacy_ok,
        'model_installed': _spacy_package_installed('en_core_web_sm'),
        'model': 'en_core_web_sm',
        'hu_model_installed': bool(hu_installed),
        'hu_model': hu_installed or HUNGARIAN_SPACY_MODEL,
    }


def install_spacy_model(language: str = 'en') -> dict:
    """Install the English spaCy model or the Hungarian HuSpaCy model."""
    import subprocess
    import tempfile
    import urllib.request

    python = sys.executable
    if language != 'hu':
        result = subprocess.run(
            [python, '-m', 'spacy', 'download', 'en_core_web_sm'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return {'ok': True, 'message': 'en_core_web_sm installed successfully.'}
        return {'ok': False, 'message': result.stderr or result.stdout}
    # HuSpaCy publishes a wheel whose file name lacks a version; current pip
    # rejects it, so download it under a valid PEP 427 name first.
    with tempfile.TemporaryDirectory(prefix='auris-huspacy-') as folder:
        wheel = Path(folder) / (
            f'{HUNGARIAN_SPACY_MODEL}-{HUNGARIAN_SPACY_VERSION}-py3-none-any.whl'
        )
        try:
            urllib.request.urlretrieve(HUNGARIAN_SPACY_URL, wheel)
        except Exception as exc:
            return {'ok': False, 'message': f'A HuSpaCy letöltése nem sikerült: {exc}'}
        result = subprocess.run(
            [python, '-m', 'pip', 'install', str(wheel)],
            capture_output=True, text=True,
        )
    if result.returncode == 0:
        return {'ok': True, 'message': f'{HUNGARIAN_SPACY_MODEL} telepítve.'}
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
    _set_dl('downloading', 0, f'Kapcsolódás a HuggingFace-hez ({repo_id})…', dest_dir)
    try:
        if hf_endpoint:
            os.environ['HF_ENDPOINT'] = hf_endpoint

        from huggingface_hub import list_repo_files, hf_hub_download
        import huggingface_hub

        _set_dl('downloading', 2, 'A tároló fájljainak listázása…', dest_dir)

        files = list(list_repo_files(repo_id))
        total = len(files)
        if total == 0:
            _set_dl('error', 0, 'A tárolóban nincs letölthető fájl.', dest_dir)
            return

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        for i, filename in enumerate(files):
            pct = int((i / total) * 95)
            _set_dl('downloading', pct, f'Letöltés: {filename} ({i+1}/{total})…', dest_dir)
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(dest),
            )

        _set_dl('done', 100, f'A letöltés kész → {dest_dir}', dest_dir)

        # Persist the new model path in settings
        save({'model_path': dest_dir, 'model_source': 'local'})

    except Exception as e:
        _set_dl('error', 0, str(e), dest_dir)
