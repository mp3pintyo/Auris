"""
OmniVoice TTS engine wrapper.

Loads the model lazily from the configured model directory.
Caches generated audio by segment hash.
Stabilizes short voice-design generations by reusing a longer
instruction-conditioned reference clip for each instruct string.
Caches VoiceClonePrompt tokens for character / narrator reference audio.
"""

import hashlib
import gc
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from core.cancellation import GenerationAborted, SiblingAborted
from core.hungarian_numbers import looks_hungarian, normalize_hungarian

log = logging.getLogger(__name__)

from core.paths import user_path, omnivoice_model

AUDIO_CACHE_DIR = str(user_path('audio_cache'))
VOICE_REF_DIR = os.path.join(AUDIO_CACHE_DIR, "voice_refs")
VOICE_PROMPT_DIR = os.path.join(AUDIO_CACHE_DIR, "voice_prompts")
SAMPLE_RATE = 24_000
VOICE_DESIGN_REF_TEXT = (
    "Hello. This is a stable voice sample for conditioning. "
    "The room is quiet, the day is calm, and every word should sound clear, "
    "natural, and easy to understand."
)
# Hungarian anchor sentence: a voice description (voice design) is rendered
# once into this clip, then every segment clones it, so the timbre stays the
# same across a book instead of drifting segment by segment.
VOICE_DESIGN_REF_TEXT_HU = (
    "Jó napot kívánok. Ez egy nyugodt, tiszta hangminta. Minden szó érthetően, "
    "természetes hangsúllyal szól, a mondatok végén pedig rövid szünetet tartok."
)
VOICE_DESIGN_ANCHOR_VERSION = 1
VOICE_REF_MIN_ZCR = 0.015
VOICE_REF_GEN_ATTEMPTS = 4
VOICE_GENDERS = {"male", "female"}
VOICE_AGES = {"child", "teenager", "young adult", "middle-aged", "elderly"}
VOICE_PITCHES = {
    "very low pitch",
    "low pitch",
    "moderate pitch",
    "high pitch",
    "very high pitch",
}
VOICE_STYLES = {"whisper"}
_VOICE_CLONE_PROMPT_FORMAT_VERSION = 1
_BRACKET_TAG_RE = re.compile(r"\[[^\[\]]*\]")
# 0 = auto-size from free VRAM (recommended). Small fixed values under-utilize GPU.
DEFAULT_TTS_BATCH_SIZE = 0
DEFAULT_TTS_NUM_STEP = 16
ALLOWED_TTS_NUM_STEPS = (8, 16, 24, 32)
# OmniVoice decoding fields Auris may override (OmniVoiceGenerationConfig).
SAMPLING_FIELDS = {
    "guidance_scale": (0.0, 10.0),
    "t_shift": (0.01, 1.0),
    "position_temperature": (0.0, 20.0),
    "class_temperature": (0.0, 5.0),
    "layer_penalty_factor": (0.0, 20.0),
}


def sampling_kwargs(sampling: dict | None) -> dict:
    """Validated OmniVoice decoding overrides; unknown or None fields are dropped."""
    out = {}
    for key, value in (sampling or {}).items():
        if key not in SAMPLING_FIELDS or value is None:
            continue
        low, high = SAMPLING_FIELDS[key]
        out[key] = min(high, max(low, float(value)))
    return out

MAX_TTS_BATCH_SIZE = 48
# Soft char budget; scaled up with batch size so packs actually fill on long cards.
DEFAULT_TTS_BATCH_MAX_CHARS = 12000
# Merge consecutive same-voice short lines before synth so each GPU call does
# real work. OmniVoice is ~0.6B params — tiny per-line batches never fill a 24GB card.
# 0 disables coalescing. ~600–900 chars ≈ several sentences / ~15–25s speech.
DEFAULT_TTS_COALESCE_CHARS = 0
AUDIO_CACHE_FORMAT_VERSION = 2


def _audio_duration(path: str) -> float:
    """Duration from the WAV header; cache hits must not decode the audio."""
    info = sf.info(path)
    return float(info.frames) / float(info.samplerate)


def _write_audio_atomic(path: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write a cache WAV without exposing a partial file to another worker."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp.wav"
    try:
        sf.write(tmp, audio, sample_rate)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _model_path_from_settings() -> str:
    try:
        from core.settings import get

        return get("model_path") or ""
    except Exception:
        return str(omnivoice_model())


def _normalize_text_enabled() -> bool:
    try:
        from core.settings import get

        return bool(get("normalize_text", True))
    except Exception:
        return True


def _auto_batch_size_from_vram(voice_clone: bool = False) -> int:
    """Pick a throughput-oriented batch size from GPU memory.

    OmniVoice is a small backbone: on a 24GB card a batch of ~8–12 often only
    uses ~8GB and leaves the GPU idle between diffusion steps. Size primarily
    by **total** VRAM (card class), then shave if free memory is tight.
    Real OOM still lowers a session cap.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return 2
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        free_gb = free_bytes / (1024**3)
        total_gb = total_bytes / (1024**3)

        # OmniVoice doubles the effective batch for classifier-free guidance,
        # then pads every item to the longest sequence. Voice cloning also adds
        # the reference tokens to every item. On a 24GB RTX 3090, measured
        # length-bucketed batches of 8 are both faster and about half the peak
        # VRAM of a batch of 24.
        if total_gb >= 20:  # 24GB class
            size = 8 if voice_clone else 16
        elif total_gb >= 14:  # 16GB
            size = 6 if voice_clone else 12
        elif total_gb >= 10:  # 12GB
            size = 4 if voice_clone else 8
        elif total_gb >= 7:  # 8GB
            size = 3 if voice_clone else 6
        else:
            size = 2 if voice_clone else 4

        # Only shrink if the card is actually nearly full already.
        if free_gb < 2.0:
            size = min(size, 4)
        elif free_gb < 3.5:
            size = min(size, 8)
        elif free_gb < 5.0:
            size = min(size, 12)

        size = max(1, min(size, MAX_TTS_BATCH_SIZE))
        log.info(
            "Auto TTS batch size=%d (voice_clone=%s, free %.1f / total %.1f GB)",
            size,
            voice_clone,
            free_gb,
            total_gb,
        )
        return size
    except Exception as exc:
        log.debug("VRAM auto batch probe failed: %s", exc)
        return 12 if voice_clone else 16


def _tts_batch_size_from_settings(voice_clone: bool = False) -> int:
    try:
        from core.settings import get

        raw = get("tts_batch_size", DEFAULT_TTS_BATCH_SIZE)
        if raw is None or raw == "":
            value = DEFAULT_TTS_BATCH_SIZE
        else:
            value = int(raw)
    except Exception:
        value = DEFAULT_TTS_BATCH_SIZE
    # 0 (or negative) => auto
    if value <= 0:
        return _auto_batch_size_from_vram(voice_clone=voice_clone)
    return max(1, min(value, MAX_TTS_BATCH_SIZE))


def _tts_batch_max_chars_from_settings(batch_size: int | None = None) -> int:
    try:
        from core.settings import get

        value = int(get("tts_batch_max_chars", DEFAULT_TTS_BATCH_MAX_CHARS) or DEFAULT_TTS_BATCH_MAX_CHARS)
    except Exception:
        value = DEFAULT_TTS_BATCH_MAX_CHARS
    # Ensure a full batch of ~400-char lines still fits the budget.
    if batch_size:
        value = max(value, int(batch_size) * 400)
    return max(500, min(value, 40000))


def _cuda_mem_gb() -> tuple[float | None, float | None]:
    try:
        import torch

        if not torch.cuda.is_available():
            return None, None
        alloc = torch.cuda.memory_allocated() / (1024**3)
        reserved = torch.cuda.memory_reserved() / (1024**3)
        return alloc, reserved
    except Exception:
        return None, None


def _cuda_peak_gb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return torch.cuda.max_memory_allocated() / (1024**3)
    except Exception:
        return None


def _tts_num_step_from_settings() -> int:
    try:
        from core.settings import get

        value = int(get("tts_num_step", DEFAULT_TTS_NUM_STEP) or DEFAULT_TTS_NUM_STEP)
    except Exception:
        value = DEFAULT_TTS_NUM_STEP
    if value in ALLOWED_TTS_NUM_STEPS:
        return value
    # Snap to nearest allowed step count.
    return min(ALLOWED_TTS_NUM_STEPS, key=lambda s: abs(s - value))


def _is_cuda_oom(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in {"OutOfMemoryError", "CUDAOutOfMemoryError"}:
        return True
    msg = str(exc).lower()
    return "out of memory" in msg or "cuda error: out of memory" in msg


def _enable_cuda_fast_paths() -> None:
    """Throughput knobs that do not change generation quality (num_step, sampling)."""
    try:
        import torch

        if not torch.cuda.is_available():
            return
        if getattr(torch.version, 'hip', None):
            # ROCm counterpart of disabling cuDNN search below: MIOpen's default
            # find mode searches convolution solvers for every new codec shape,
            # i.e. almost every sentence (RX 6600: 80.6s vs 49.9s for ten
            # sentences of different lengths, identical CER). FAST uses its
            # immediate-mode choice. Read when MIOpen starts; an explicit
            # MIOPEN_FIND_MODE in the environment wins.
            os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
            return
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        # Speech waveforms have changing lengths. Exhaustive cuDNN convolution
        # search repeats for new codec shapes (measured 27s vs 2.4s first pack
        # on RTX 3090), with no material warm-throughput benefit.
        torch.backends.cudnn.benchmark = False
        try:
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass
        # Prefer flash / mem-efficient SDPA when available.
        try:
            torch.backends.cuda.enable_flash_sdp(True)
            torch.backends.cuda.enable_mem_efficient_sdp(True)
            torch.backends.cuda.enable_math_sdp(True)
        except Exception:
            pass
    except Exception as exc:
        log.debug("CUDA fast-path setup skipped: %s", exc)


def _pack_items_for_batch(
    items: list[dict],
    max_items: int,
    max_chars: int,
) -> list[list[dict]]:
    """Pack length-sorted items into full GPU batches.

    Items should already be sorted by text length so neighbours are similar
    (less padding). Always try to fill ``max_items`` — on large-VRAM cards
    under-filled packs are the main reason for ~10% GPU util.
    """
    if not items:
        return []
    max_items = max(1, int(max_items))
    max_chars = max(1, int(max_chars))
    batches: list[list[dict]] = []
    current: list[dict] = []
    chars = 0
    for it in items:
        length = len(it.get("text") or "")
        if current and (
            len(current) >= max_items or (chars + length > max_chars)
        ):
            batches.append(current)
            current = []
            chars = 0
        current.append(it)
        chars += length
    if current:
        batches.append(current)
    return batches


def _parse_instruct(instruct: str) -> dict:
    parsed = {
        "gender": None,
        "age": None,
        "pitch": None,
        "accent": None,
        "styles": [],
        "extras": [],
    }

    for raw in str(instruct or "").split(","):
        item = raw.strip().lower()
        if not item:
            continue
        if item in VOICE_GENDERS:
            parsed["gender"] = item
        elif item in VOICE_AGES:
            parsed["age"] = item
        elif item in VOICE_PITCHES:
            parsed["pitch"] = item
        elif item in VOICE_STYLES:
            parsed["styles"].append(item)
        elif item.endswith("accent"):
            parsed["accent"] = item
        else:
            parsed["extras"].append(item)

    return parsed


def _format_instruct(parts: dict) -> str | None:
    items = []
    for key in ("gender", "age", "pitch", "accent"):
        if parts.get(key):
            items.append(parts[key])
    items.extend(parts.get("styles", []))
    items.extend(parts.get("extras", []))
    return ", ".join(items) if items else None


def _stabilize_voice_design_instruct(instruct: str | None) -> str | None:
    if not instruct:
        return instruct

    parts = _parse_instruct(instruct)
    gender = parts["gender"]
    age = parts["age"]
    pitch = parts["pitch"]
    original = _format_instruct(parts)

    # OmniVoice docs note that some attribute combinations do not work well.
    # Empirically, male teenage/child prompts often collapse into squeals or
    # repeated junk. Simplifying them to a nearby stable voice is much more
    # reliable than passing the raw prompt through.
    if gender == "male" and age in {"teenager", "child"}:
        parts["age"] = None
        if pitch in {None, "moderate pitch", "very high pitch"}:
            parts["pitch"] = "high pitch"
        elif pitch == "very low pitch":
            parts["pitch"] = "low pitch"
    elif gender == "female" and age in {"teenager", "child"}:
        if pitch == "very low pitch":
            parts["pitch"] = "moderate pitch"
        elif age == "teenager" and pitch == "low pitch":
            parts["pitch"] = "moderate pitch"

    effective = _format_instruct(parts)
    if effective != original:
        log.info("Stabilized voice instruct: '%s' -> '%s'", original, effective)
    return effective


def _audio_zcr(audio: np.ndarray) -> float:
    mono = np.asarray(audio, dtype=float).reshape(-1)
    if mono.size < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(np.signbit(mono)))))


def _map_tn_lang(language: str | None, text: str) -> str:
    """Map book language to a TN language code (en/zh/ja/other)."""
    code = (language or "").strip().lower()
    if code in {"en", "english"}:
        return "en"
    if code in {"zh", "zh-cn", "zh-tw", "chinese", "mandarin"}:
        return "zh"
    if code in {"ja", "japanese"}:
        return "ja"
    if code and code not in {"none", "auto"}:
        return code
    # Script-based auto-detect when language is missing.
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    return "en"


def _apply_with_bracket_protection(text: str, fn) -> str:
    """Run ``fn`` on text while leaving ``[...]`` control spans untouched."""
    parts: list[str] = []
    last = 0
    for m in _BRACKET_TAG_RE.finditer(text):
        if m.start() > last:
            parts.append(fn(text[last:m.start()]))
        parts.append(m.group())
        last = m.end()
    if last < len(text):
        parts.append(fn(text[last:]))
    return "".join(parts) if parts else fn(text)


def _num2words_fallback(text: str, language: str | None) -> str:
    """Best-effort integer expansion when full TN is unavailable."""
    if looks_hungarian(language, text):
        return _apply_with_bracket_protection(text, normalize_hungarian)

    try:
        from num2words import num2words
    except ImportError:
        return text

    lang = _map_tn_lang(language, text)
    if lang in {"en", "zh", "ja"}:
        n2w_lang = "en" if lang != "zh" else "zh"
    else:
        n2w_lang = lang

    def _repl(match: re.Match) -> str:
        try:
            return num2words(int(match.group()), lang=n2w_lang)
        except Exception:
            try:
                return num2words(int(match.group()), lang="en")
            except Exception:
                return match.group()

    return _apply_with_bracket_protection(text, lambda s: re.sub(r"\d+", _repl, s))


_WETEXT_CACHE: dict[str, object] = {}


def _wetext_normalize(text: str, language: str | None) -> str | None:
    """Windows-friendly WeText runtime (no pynini). Returns None if unavailable."""
    if _WETEXT_CACHE.get("unavailable"):
        return None
    try:
        from wetext import Normalizer
    except ImportError:
        return None
    except Exception as exc:
        # wetext loads its FST files on import; kaldifst cannot open them
        # from a non-ASCII path on Windows (e.g. an accented user name in
        # the desktop install folder). Remember it and use the fallback.
        _WETEXT_CACHE["unavailable"] = True
        log.warning("wetext could not load (%s); using the num2words fallback.", exc)
        return None

    lang = _map_tn_lang(language, text)
    if lang not in {"en", "zh", "ja"}:
        return None

    try:
        normalizer = _WETEXT_CACHE.get(lang)
        if normalizer is None:
            normalizer = Normalizer(lang=lang, operator="tn")
            _WETEXT_CACHE[lang] = normalizer
        return _apply_with_bracket_protection(text, normalizer.normalize)
    except Exception as exc:
        log.warning("wetext normalization failed (%s); trying next fallback.", type(exc).__name__)
        return None


def apply_text_normalization(text: str, language: str | None = None) -> str:
    """Normalize numbers/dates for TTS.

    Order:
    1. OmniVoice ``normalize_text`` (WeTextProcessing + pynini) when installed
    2. ``wetext`` pure-Python runtime (recommended on Windows; no pynini)
    3. ``num2words`` integer fallback
    """
    if not text or not text.strip():
        return text

    # Hungarian needs language-specific cardinal, ordinal, date and suffix
    # handling. Generic normalizers do not preserve these forms reliably.
    if looks_hungarian(language, text):
        return _apply_with_bracket_protection(text, normalize_hungarian)

    # 1) Upstream OmniVoice TN (needs WeTextProcessing → pynini).
    try:
        from omnivoice.utils.text import normalize_text as ov_normalize

        return ov_normalize(text, language)
    except ImportError:
        pass
    except Exception as exc:
        log.warning(
            "OmniVoice text normalization failed (%s); trying fallbacks.",
            type(exc).__name__,
        )

    # 2) wetext (pynini-free; works on Windows pip).
    wetext_out = _wetext_normalize(text, language)
    if wetext_out is not None:
        return wetext_out

    # 3) Integer-only fallback.
    return _num2words_fallback(text, language)


def hungarian_normalizer_key(text: str, language: str | None, normalize_text: bool) -> str:
    """Cache-key suffix that changes when Hungarian normalization changes.

    Without it, a normalizer fix would never reach already cached audio.
    Other languages keep their historical keys.
    """
    if not normalize_text:
        return ""
    lang = str(language or "").lower()[:2]
    if lang == "hu" or (not lang and looks_hungarian(text)):
        from core import hungarian_numbers

        return f"|hn={getattr(hungarian_numbers, 'NORMALIZER_VERSION', 1)}"
    return ""


def take_variant(variant: str, take: int) -> str:
    """Cache-key variant of an alternative take; take 0 keeps the old key."""
    take = int(take or 0)
    if take <= 0:
        return variant
    return f"{variant}|take{take}" if variant else f"take{take}"


def seed_for_take(take: int) -> int:
    """Seed the samplers so each take is a different, repeatable version."""
    seed = (int(take) * 7919 + 17) % (2**31 - 1)
    try:
        import random

        import torch

        random.seed(seed)
        np.random.seed(seed % (2**32 - 1))
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass
    return seed


def _voice_design_anchor_enabled() -> bool:
    try:
        from core import settings as app_settings

        return bool(app_settings.get("voice_design_anchor", True))
    except Exception:
        return True


def _prompt_cache_key(ref_audio: str, ref_text: str | None) -> str:
    try:
        st = os.stat(ref_audio)
        identity = f"{os.path.abspath(ref_audio)}|{st.st_mtime_ns}|{st.st_size}|{ref_text or ''}"
    except OSError:
        identity = f"{ref_audio}|{ref_text or ''}"
    return hashlib.md5(identity.encode("utf-8")).hexdigest()


class TTSEngine:
    def __init__(self, model_path: str = "", worker_label: str = "primary"):
        self.model_path = model_path
        self.model = None
        self.worker_label = worker_label
        self._lock = threading.Lock()
        self._loading = False
        self._ready = False
        self._cancel_load = threading.Event()
        self._load_start_lock = threading.Lock()
        self._load_mutex = threading.Lock()
        self._anchor_lock = threading.Lock()
        self._error: str | None = None
        self._prompt_mem: dict[str, object] = {}
        # After CUDA OOM, never retry larger packs in this process (avoids
        # 100% spike → OOM → half VRAM forever-churn on every subsequent batch).
        self._batch_size_cap: int | None = None
        self._accel_status: dict = {"effective": "off", "message": ""}
        self._generation_stream = None
        # Device and dtype actually used for the loaded model, as a short tag
        # that feeds the audio cache key. Empty until the model is loaded.
        self._render_variant = ""
        os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
        os.makedirs(VOICE_REF_DIR, exist_ok=True)
        os.makedirs(VOICE_PROMPT_DIR, exist_ok=True)

    @property
    def render_variant(self) -> str:
        """Device/dtype tag of the loaded model, empty before it loads."""
        return self._render_variant

    def status(self) -> dict:
        resolved_path = self.model_path or _model_path_from_settings()
        if self._error:
            return {"state": "error", "message": self._error}
        if self._ready:
            accel = dict(self._accel_status)
            wrapper = getattr(self.model, '_auris_cuda_graph', None)
            if wrapper is not None and wrapper.disabled_reason:
                accel.update(
                    cuda_graph=False,
                    effective='triton' if accel.get('triton') else 'eager',
                    message='CUDA Graph kikapcsolva: ' + wrapper.disabled_reason,
                )
            return {
                "state": "ready",
                "accel": accel,
            }
        if self._loading:
            return {"state": "loading"}
        return {
            "state": "not_loaded",
            "model_path": resolved_path,
            "model_exists": os.path.isdir(resolved_path),
        }

    def load_async(self) -> None:
        # Check-and-set atomically: concurrent status polls must not start two
        # loads (a second Higgs worker would orphan several GB of VRAM).
        with self._load_start_lock:
            if self._ready or self._loading:
                return
            self._loading = True
            self._cancel_load.clear()
        threading.Thread(target=self._load, daemon=True).start()

    def load_sync(self) -> None:
        """Load the model in the current thread or raise its load error."""
        self._cancel_load.clear()
        self._load()
        if not self._ready:
            raise RuntimeError(self._error or "TTS model failed to load")

    def set_dedicated_cuda_stream(self, enabled: bool) -> None:
        """Route this engine's generation through its own CUDA stream."""
        if not enabled:
            self._generation_stream = None
            return
        import torch

        if torch.cuda.is_available():
            self._generation_stream = torch.cuda.Stream()

    def unload(self) -> None:
        """Release a replica model and its graph/cache allocations."""
        self._cancel_load.set()
        if self.model is not None:
            wrapper = getattr(self.model, "_auris_cuda_graph", None)
            if wrapper is not None:
                try:
                    wrapper.clear()
                except Exception:
                    pass
        self._generation_stream = None
        self._prompt_mem.clear()
        self.model = None
        self._ready = False
        # A concurrent from_pretrained() cannot be interrupted safely. Keep
        # _loading true until it returns and observes _cancel_load.
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def reload(self):
        if self.model is not None:
            wrapper = getattr(self.model, "_auris_cuda_graph", None)
            if wrapper is not None:
                try:
                    wrapper.clear()
                except Exception:
                    pass
        self._ready = False
        self._error = None
        self.model = None
        self._prompt_mem.clear()
        self._batch_size_cap = None
        self._accel_status = {"effective": "off", "message": ""}
        self.load_async()

    def _note_batch_oom(self, failed_size: int) -> int:
        """Record OOM and return the new session batch-size cap."""
        new_cap = max(1, int(failed_size) // 2)
        prev = self._batch_size_cap
        if prev is None or new_cap < prev:
            self._batch_size_cap = new_cap
            log.warning(
                "CUDA OOM at batch=%d → session batch cap now %d "
                "(will not retry larger packs until model reload)",
                failed_size,
                new_cap,
            )
        return self._batch_size_cap or new_cap

    def _effective_batch_size(self, requested: int, voice_clone: bool = False) -> int:
        """Apply architecture and session safety caps to a requested batch."""
        size = max(1, min(int(requested), MAX_TTS_BATCH_SIZE))
        # A clone batch is doubled for CFG and carries repeated reference
        # context. Above 8, padding and scoring overhead outweigh parallelism
        # on the currently supported consumer-GPU path.
        if voice_clone:
            size = min(size, 8)
        if self._batch_size_cap is not None:
            size = min(size, self._batch_size_cap)
        return max(1, size)

    def _load(self) -> None:
        with self._load_mutex:
            self._load_locked()

    def _load_locked(self) -> None:
        with self._lock:
            if self._ready:
                self._loading = False
                return
            self._loading = True
            self._error = None

        try:
            if not self.model_path:
                self.model_path = _model_path_from_settings()

            if not os.path.isdir(self.model_path):
                raise FileNotFoundError(
                    f"Model not found at: {self.model_path}\n"
                    "Go to Settings to set the correct path or download the model."
                )

            import torch
            from omnivoice import OmniVoice

            if self._cuda_available():
                device = "cuda"
            elif self._mps_available():
                device = "mps"
            else:
                device = "cpu"
            if device == "cuda":
                _enable_cuda_fast_paths()
                # bf16 is faster on Ampere+ and avoids some fp16 underflow issues.
                bf16_ok = bool(getattr(torch.cuda, "is_bf16_supported", lambda: False)())
                dtype = torch.bfloat16 if bf16_ok else torch.float16
            elif device == "mps":
                # Apple Silicon (Metal). float32 by default: bfloat16 audibly
                # clips sentence onsets on MPS (verified on M-series hardware).
                # Set AURIS_MPS_DTYPE=bf16 to trade quality for speed.
                dtype = (
                    torch.bfloat16
                    if os.environ.get("AURIS_MPS_DTYPE", "").lower() in {"bf16", "bfloat16"}
                    else torch.float32
                )
            else:
                dtype = torch.float32
            # Renders from different devices or dtypes are not interchangeable,
            # so the cache key has to tell them apart.
            self._render_variant = f"{device}/{dtype}"
            log.info(
                "Loading OmniVoice from %s on %s (%s) ...",
                self.model_path,
                device,
                dtype,
            )
            load_kwargs = {
                "device_map": device,
                "dtype": dtype,
                "local_files_only": True,
            }
            # Prefer SDPA (flash/mem-efficient kernels when available).
            try:
                self.model = OmniVoice.from_pretrained(
                    self.model_path,
                    attn_implementation="sdpa",
                    **load_kwargs,
                )
            except TypeError:
                self.model = OmniVoice.from_pretrained(self.model_path, **load_kwargs)
            except Exception as attn_exc:
                log.warning(
                    "SDPA load failed (%s); retrying default attention.",
                    attn_exc,
                )
                self.model = OmniVoice.from_pretrained(self.model_path, **load_kwargs)

            if self._cancel_load.is_set():
                log.info("OmniVoice load cancelled for import-time LLM analysis.")
                self.model = None
                self._ready = False
                return

            # Optional CUDA Graph / Triton acceleration (settings: tts_accel).
            self._accel_status = {"effective": "off", "message": "not applied"}
            if device in ("cuda", "mps", "cpu"):
                try:
                    from core.settings import get as _settings_get
                    from core.tts_accel import apply_acceleration

                    accel_mode = _settings_get("tts_accel", "auto")
                    self._accel_status = apply_acceleration(self.model, accel_mode)
                    self._accel_status.update(device=device, dtype=str(dtype))
                except Exception as accel_exc:
                    log.warning("TTS acceleration skipped: %s", accel_exc)
                    self._accel_status = {
                        "effective": "off",
                        "message": f"accel error: {accel_exc}",
                    }

            if self._cancel_load.is_set():
                log.info("OmniVoice load cancelled after acceleration setup.")
                self.model = None
                self._ready = False
                return
            self._ready = True
            if device == "cuda":
                self._warm_up()
            if device == "cuda":
                try:
                    free_b, total_b = torch.cuda.mem_get_info()
                    log.info(
                        "OmniVoice ready on CUDA — VRAM free %.1f / %.1f GB, "
                        "auto batch≈%d, accel=%s",
                        free_b / (1024**3),
                        total_b / (1024**3),
                        _auto_batch_size_from_vram(),
                        self._accel_status.get("effective", "off"),
                    )
                except Exception:
                    log.info("OmniVoice model ready.")
            else:
                log.info("OmniVoice model ready (%s).", device.upper())
        except Exception as exc:
            self._error = str(exc)
            log.error("Failed to load OmniVoice: %s", exc)
        finally:
            self._loading = False

    def _warm_up(self) -> None:
        """Run one short Hungarian sentence so the first real request does
        not pay for kernel selection, CUDA graph capture and codec setup."""
        try:
            from core import settings as app_settings

            if not app_settings.get("tts_warmup", True):
                return
        except Exception:
            pass
        started = time.time()
        try:
            self._synthesize_batch(
                texts=["Jó napot kívánok."],
                instruct="male, middle-aged",
                speeds=[1.0],
                num_step=_tts_num_step_from_settings(),
                language="hu",
                normalize_text=False,
            )
            log.info("OmniVoice warm-up finished in %.2fs", time.time() - started)
        except Exception as exc:
            log.warning("OmniVoice warm-up skipped: %s", exc)

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    @staticmethod
    def _mps_available() -> bool:
        """Apple Silicon Metal backend (macOS)."""
        try:
            import torch

            mps = getattr(torch.backends, "mps", None)
            return bool(mps is not None and mps.is_available())
        except ImportError:
            return False

    @staticmethod
    def cache_key(
        text: str,
        instruct: str | None,
        ref_audio: str | None,
        speed: float,
        ref_text: str | None = None,
        language: str | None = None,
        normalize_text: bool = False,
        num_step: int = DEFAULT_TTS_NUM_STEP,
        variant: str = "",
    ) -> str:
        payload = (
            f"{text}|{instruct}|{ref_audio}|{ref_text}|{speed:.2f}|"
            f"{language or ''}|nt={int(bool(normalize_text))}|ns={int(num_step)}|"
            f"audio-cache-v={AUDIO_CACHE_FORMAT_VERSION}"
        )
        # Appended only when supplied, so a caller that passes no variant keeps
        # the historical key and existing cache entries stay valid.
        if variant:
            payload += f"|rv={variant}"
        payload += hungarian_normalizer_key(text, language, normalize_text)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def cache_path(key: str) -> str:
        return os.path.join(AUDIO_CACHE_DIR, f"{key}.wav")

    @staticmethod
    def _voice_ref_key(instruct: str) -> str:
        return hashlib.md5(instruct.encode("utf-8")).hexdigest()

    def _voice_ref_path(self, instruct: str, language: str | None = None) -> str:
        if language is None:
            return os.path.join(VOICE_REF_DIR, f"{self._voice_ref_key(instruct)}.wav")
        key = self._voice_ref_key(
            f"{instruct}|{str(language).lower()[:2]}|anchor-v{VOICE_DESIGN_ANCHOR_VERSION}"
        )
        return os.path.join(VOICE_REF_DIR, f"anchor_{key}.wav")

    def _prompt_path(self, key: str) -> str:
        return os.path.join(VOICE_PROMPT_DIR, f"{key}.pt")

    def _load_voice_clone_prompt(self, path: str):
        from omnivoice import VoiceClonePrompt

        if hasattr(VoiceClonePrompt, "load"):
            return VoiceClonePrompt.load(path)
        import torch

        data = torch.load(path, map_location="cpu", weights_only=True)
        version = data.get("format_version")
        if version not in (None, _VOICE_CLONE_PROMPT_FORMAT_VERSION):
            raise ValueError(f"Unsupported VoiceClonePrompt format version: {version}")
        return VoiceClonePrompt(
            ref_audio_tokens=data["ref_audio_tokens"],
            ref_text=data["ref_text"],
            ref_rms=data["ref_rms"],
        )

    def _save_voice_clone_prompt(self, prompt, path: str) -> None:
        if hasattr(prompt, "save"):
            prompt.save(path)
            return
        import torch

        torch.save(
            {
                "format_version": _VOICE_CLONE_PROMPT_FORMAT_VERSION,
                "ref_audio_tokens": prompt.ref_audio_tokens.detach().cpu(),
                "ref_text": prompt.ref_text,
                "ref_rms": float(prompt.ref_rms),
            },
            path,
        )

    def _get_voice_clone_prompt(self, ref_audio: str, ref_text: str | None):
        """Return a cached VoiceClonePrompt for the reference clip, creating if needed."""
        if not self._ready or self.model is None:
            raise RuntimeError("Model is not loaded yet. " + (self._error or "Call load_async() first."))
        if not ref_audio or not os.path.exists(ref_audio):
            raise FileNotFoundError(f"Reference audio not found: {ref_audio}")

        key = _prompt_cache_key(ref_audio, ref_text)
        if key in self._prompt_mem:
            return self._prompt_mem[key]

        path = self._prompt_path(key)
        if os.path.exists(path):
            try:
                prompt = self._load_voice_clone_prompt(path)
                self._prompt_mem[key] = prompt
                log.debug("VoiceClonePrompt cache hit: %s", key[:12])
                return prompt
            except Exception as exc:
                log.warning("Discarding bad VoiceClonePrompt cache %s: %s", path, exc)

        log.info("Encoding VoiceClonePrompt for %s", os.path.basename(ref_audio))
        prompt = self.model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        try:
            self._save_voice_clone_prompt(prompt, path)
        except Exception as exc:
            log.warning("Could not persist VoiceClonePrompt: %s", exc)
        self._prompt_mem[key] = prompt
        return prompt

    def invalidate_voice_prompt(self, ref_audio: str | None = None, ref_text: str | None = None) -> None:
        """Drop cached prompts. If ref_audio is None, clear all prompt caches.

        Memory cache is always fully cleared for a path-targeted invalidation so
        stale in-memory prompts cannot survive a WAV overwrite with a new mtime.
        """
        if ref_audio is None:
            self._prompt_mem.clear()
            try:
                for name in os.listdir(VOICE_PROMPT_DIR):
                    if name.endswith(".pt"):
                        try:
                            os.remove(os.path.join(VOICE_PROMPT_DIR, name))
                        except OSError:
                            pass
            except OSError:
                pass
            return

        key = _prompt_cache_key(ref_audio, ref_text)
        path = self._prompt_path(key)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        # Path identity is part of the key via mtime/size; after overwrite those
        # change, so also drop any in-memory entries for safety.
        self._prompt_mem.clear()

    @staticmethod
    def _coerce_audio_array(audio) -> np.ndarray:
        if not isinstance(audio, np.ndarray):
            audio = np.array(audio)
        if audio.ndim > 1:
            audio = audio.mean(axis=0)
        return audio

    def _build_generate_kwargs(
        self,
        texts: list[str],
        instruct: str | None,
        ref_audio: str | None,
        ref_text: str | None,
        speeds: list[float],
        num_step: int,
        language: str | None,
        normalize_text: bool,
        sampling: dict | None = None,
    ) -> dict:
        """Build OmniVoice.generate kwargs for one or many texts (same voice)."""
        synth_texts = [
            apply_text_normalization(t, language) if normalize_text else t
            for t in texts
        ]
        multi = len(synth_texts) > 1
        kwargs = {
            "text": synth_texts if multi else synth_texts[0],
            "speed": speeds if multi else speeds[0],
            "num_step": num_step,
            "language": language,
            **sampling_kwargs(sampling),
        }

        if ref_audio:
            # OmniVoice's clone and design conditioning are mutually exclusive.
            # A supplied reference always selects clone mode, even when the UI
            # also holds a previously saved design instruction.
            try:
                kwargs["voice_clone_prompt"] = self._get_voice_clone_prompt(
                    ref_audio, ref_text
                )
            except Exception as exc:
                log.warning(
                    "VoiceClonePrompt cache failed (%s); falling back to raw ref_audio.",
                    exc,
                )
                kwargs["ref_audio"] = ref_audio
                kwargs["ref_text"] = ref_text
        elif instruct:
            kwargs["instruct"] = instruct
        return kwargs

    def _synthesize_batch(
        self,
        texts: list[str],
        instruct: str | None = None,
        ref_audio: str | None = None,
        ref_text: str | None = None,
        speeds: list[float] | None = None,
        num_step: int = 32,
        language: str | None = None,
        normalize_text: bool = False,
        sampling: dict | None = None,
    ) -> list[np.ndarray]:
        """Synthesize multiple texts that share the same voice conditioning.

        ``sampling`` optionally overrides OmniVoice decoding fields (see
        ``SAMPLING_FIELDS``); omitted fields keep the upstream defaults.
        """
        if not texts:
            return []
        if not self._ready:
            raise RuntimeError("Model is not loaded yet. " + (self._error or "Call load_async() first."))

        speeds = list(speeds) if speeds is not None else [1.0] * len(texts)
        if len(speeds) != len(texts):
            raise ValueError("speeds must match texts length")

        def _run(chunk_texts: list[str], chunk_speeds: list[float]) -> list[np.ndarray]:
            kwargs = self._build_generate_kwargs(
                texts=chunk_texts,
                instruct=instruct,
                ref_audio=ref_audio,
                ref_text=ref_text,
                speeds=chunk_speeds,
                num_step=num_step,
                language=language,
                normalize_text=normalize_text,
                sampling=sampling,
            )
            text_arg = kwargs.get("text")
            b_eff = len(text_arg) if isinstance(text_arg, list) else 1
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.reset_peak_memory_stats()
            except Exception:
                pass
            t0 = __import__("time").perf_counter()
            with self._lock:
                if self._generation_stream is not None:
                    import torch

                    with torch.cuda.stream(self._generation_stream):
                        audio_arrays = self.model.generate(**kwargs)
                    self._generation_stream.synchronize()
                else:
                    audio_arrays = self.model.generate(**kwargs)
            elapsed = __import__("time").perf_counter() - t0
            peak = _cuda_peak_gb()
            alloc, reserved = _cuda_mem_gb()
            # Force visibility even if a parent logger filters: export debugging.
            msg = (
                "GPU generate done: worker=%s batch=%d num_step=%d elapsed=%.2fs "
                "peak_alloc=%.2fGB now_alloc=%.2fGB reserved=%.2fGB "
                "text_type=%s clone=%s"
                % (
                    self.worker_label,
                    b_eff,
                    num_step,
                    elapsed,
                    peak if peak is not None else -1.0,
                    alloc if alloc is not None else -1.0,
                    reserved if reserved is not None else -1.0,
                    type(text_arg).__name__,
                    bool(ref_audio or kwargs.get("voice_clone_prompt") is not None),
                )
            )
            log.info(msg)
            print(msg, flush=True)
            if not isinstance(audio_arrays, list):
                audio_arrays = [audio_arrays]
            if len(audio_arrays) != len(chunk_texts):
                raise RuntimeError(
                    f"Model returned {len(audio_arrays)} audios for {len(chunk_texts)} texts"
                )
            return [self._coerce_audio_array(a) for a in audio_arrays]

        try:
            return _run(texts, speeds)
        except Exception as exc:
            if not _is_cuda_oom(exc) or len(texts) == 1:
                raise
            # Persist a lower cap so the next packs do not re-OOM every time.
            new_cap = self._note_batch_oom(len(texts))
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            # Re-pack this request into cap-sized chunks instead of a single mid split.
            out: list[np.ndarray] = []
            step = max(1, new_cap)
            for start in range(0, len(texts), step):
                out.extend(
                    self._synthesize_batch(
                        texts[start : start + step],
                        instruct=instruct,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        speeds=speeds[start : start + step],
                        num_step=num_step,
                        language=language,
                        normalize_text=normalize_text,
                        sampling=sampling,
                    )
                )
            return out

    def _synthesize_audio(
        self,
        text: str,
        instruct: str | None = None,
        ref_audio: str | None = None,
        ref_text: str | None = None,
        speed: float = 1.0,
        num_step: int = 32,
        language: str | None = None,
        normalize_text: bool = False,
    ) -> np.ndarray:
        return self._synthesize_batch(
            texts=[text],
            instruct=instruct,
            ref_audio=ref_audio,
            ref_text=ref_text,
            speeds=[speed],
            num_step=num_step,
            language=language,
            normalize_text=normalize_text,
        )[0]

    def _ensure_voice_design_reference(
        self, instruct: str, language: str | None = None
    ) -> tuple[str, str]:
        hungarian = str(language or "").lower().startswith("hu")
        ref_text = VOICE_DESIGN_REF_TEXT_HU if hungarian else VOICE_DESIGN_REF_TEXT
        ref_path = self._voice_ref_path(instruct, language if language is not None else None)
        if os.path.exists(ref_path):
            cached_audio, _ = sf.read(ref_path)
            if _audio_zcr(cached_audio) >= VOICE_REF_MIN_ZCR:
                return ref_path, ref_text
            log.warning("Discarding unstable cached voice reference for '%s'", instruct)

        best_audio = None
        best_zcr = -1.0
        seed = int(self._voice_ref_key(instruct)[:8], 16)

        for attempt in range(VOICE_REF_GEN_ATTEMPTS):
            try:
                import torch

                torch.manual_seed(seed + attempt)
            except Exception:
                pass
            audio = self._synthesize_audio(
                text=ref_text,
                instruct=instruct,
                speed=1.0,
                num_step=24,
                language=language or None,
                normalize_text=False,
            )
            zcr = _audio_zcr(audio)
            if zcr > best_zcr:
                best_audio = audio
                best_zcr = zcr
            if zcr >= VOICE_REF_MIN_ZCR:
                break
            log.warning(
                "Retrying unstable voice reference for '%s' (attempt %d/%d, zcr=%.4f)",
                instruct,
                attempt + 1,
                VOICE_REF_GEN_ATTEMPTS,
                zcr,
            )

        os.makedirs(os.path.dirname(ref_path), exist_ok=True)
        _write_audio_atomic(ref_path, best_audio, SAMPLE_RATE)
        if best_zcr < VOICE_REF_MIN_ZCR:
            log.warning(
                "Using best-effort voice reference for '%s' despite low zcr=%.4f",
                instruct,
                best_zcr,
            )
        return ref_path, ref_text

    def _resolve_voice(
        self,
        instruct: str | None,
        ref_audio: str | None,
        ref_text: str | None,
        language: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Return the (instruct, ref_audio, ref_text) actually synthesized.

        Reference audio always wins (pure clone). A voice description is
        anchored to a generated reference clip when the setting allows it.
        """
        if ref_audio:
            return None, ref_audio, ref_text
        stabilized = _stabilize_voice_design_instruct(instruct)
        if not stabilized or not _voice_design_anchor_enabled():
            return stabilized, None, ref_text
        with self._anchor_lock:
            path, text = self._ensure_voice_design_reference(stabilized, language or "")
        return None, path, text

    def anchor_items(self, items: list[dict]) -> list[dict]:
        """Resolve design voices to anchor clips before work is split."""
        resolved = []
        for item in items:
            instruct, ref_audio, ref_text = self._resolve_voice(
                item.get("instruct"), item.get("ref_audio"), item.get("ref_text"),
                item.get("language"),
            )
            resolved.append(
                {**item, "instruct": instruct, "ref_audio": ref_audio, "ref_text": ref_text}
            )
        return resolved

    def generate(
        self,
        text: str,
        instruct: str | None = None,
        ref_audio: str | None = None,
        ref_text: str | None = None,
        speed: float = 1.0,
        num_step: int | None = None,
        language: str | None = None,
        normalize_text: bool | None = None,
        take: int = 0,
    ) -> dict:
        """
        ``take`` > 0 renders an alternative version of the same sentence
        (a different random seed) under its own cache key; 0 is the default.

        Returns:
            {
                audio_path: str,
                duration_sec: float,
                cache_hit: bool,
                cache_key: str,
            }
        """
        if normalize_text is None:
            normalize_text = _normalize_text_enabled()
        normalize_text = bool(normalize_text)
        if num_step is None:
            num_step = _tts_num_step_from_settings()
        num_step = int(num_step)

        # OmniVoice supports either voice cloning or voice design for a
        # generation. Reference audio takes precedence over any saved style
        # instruction so a narrator/character clone stays a pure clone.
        effective_instruct, effective_ref_audio, effective_ref_text = self._resolve_voice(
            instruct, ref_audio, ref_text, language
        )

        key = self.cache_key(
            text,
            effective_instruct,
            effective_ref_audio,
            speed,
            ref_text=effective_ref_text,
            language=language,
            normalize_text=normalize_text,
            num_step=num_step,
            variant=take_variant(self._render_variant, take),
        )
        path = self.cache_path(key)

        if os.path.exists(path):
            duration = _audio_duration(path)
            return {
                "audio_path": path,
                "duration_sec": duration,
                "cache_hit": True,
                "cache_key": key,
            }

        if take:
            seed_for_take(take)
        audio = self._synthesize_audio(
            text=text,
            instruct=effective_instruct,
            ref_audio=effective_ref_audio,
            ref_text=effective_ref_text,
            speed=speed,
            num_step=num_step,
            language=language,
            normalize_text=normalize_text,
        )
        _write_audio_atomic(path, audio, SAMPLE_RATE)

        return {
            "audio_path": path,
            "duration_sec": len(audio) / SAMPLE_RATE,
            "cache_hit": False,
            "cache_key": key,
        }

    def generate_many(
        self,
        items: list[dict],
        num_step: int | None = None,
        batch_size: int | None = None,
        on_item=None,
        on_status=None,
    ) -> list[dict]:
        """Synthesize many segments, batching same-voice items for GPU throughput.

        Each item is a dict with keys:
          text, instruct, ref_audio, ref_text, speed, language, normalize_text?

        Returns one result dict per input item (same shape as :meth:`generate`).
        Cache hits are resolved without calling the model. Pending work is grouped
        by voice conditioning and synthesized in batches of ``batch_size`` (default
        from settings ``tts_batch_size``). ``num_step`` defaults to settings
        ``tts_num_step`` and is part of the audio cache key.

        ``on_item(index, result)`` is called as soon as each item finishes
        (cache hit or synth), so export UIs can update progress mid-batch.
        ``on_status(message)`` is called when a GPU pack starts (long silence otherwise).
        """
        if not items:
            return []

        # Detect voice-clone early so auto batch accounts for ref-token VRAM.
        any_voice_clone = any(bool(it.get("ref_audio")) for it in items)
        if batch_size is None:
            batch_size = _tts_batch_size_from_settings(voice_clone=any_voice_clone)
        batch_size = self._effective_batch_size(batch_size, voice_clone=any_voice_clone)
        max_chars = _tts_batch_max_chars_from_settings(batch_size)
        if num_step is None:
            num_step = _tts_num_step_from_settings()
        num_step = int(num_step)
        log.info(
            "generate_many: %d items, batch_size=%d (oom_cap=%s), max_chars=%d, "
            "num_step=%d, voice_clone=%s",
            len(items),
            batch_size,
            self._batch_size_cap,
            max_chars,
            num_step,
            any_voice_clone,
        )

        results: list[dict | None] = [None] * len(items)
        # pending: list of (index, prepared fields for synthesis)
        pending: list[dict] = []

        def _emit(idx: int, result: dict) -> None:
            results[idx] = result
            if on_item is not None:
                try:
                    on_item(idx, result)
                except GenerationAborted:
                    raise
                except Exception as exc:
                    log.warning("generate_many on_item callback failed: %s", exc)

        for idx, raw in enumerate(items):
            text = raw["text"]
            instruct = raw.get("instruct")
            ref_audio = raw.get("ref_audio")
            ref_text = raw.get("ref_text")
            speed = float(raw.get("speed") or 1.0)
            language = raw.get("language")
            if "normalize_text" in raw and raw["normalize_text"] is not None:
                normalize_text = bool(raw["normalize_text"])
            else:
                normalize_text = _normalize_text_enabled()

            # Keep cache identity and batch grouping aligned with the actual
            # OmniVoice mode: a reference selects cloning, never design.
            effective_instruct, effective_ref_audio, effective_ref_text = self._resolve_voice(
                instruct, ref_audio, ref_text, language
            )

            key = self.cache_key(
                text,
                effective_instruct,
                effective_ref_audio,
                speed,
                ref_text=effective_ref_text,
                language=language,
                normalize_text=normalize_text,
                num_step=num_step,
                variant=self._render_variant,
            )
            path = self.cache_path(key)

            if os.path.exists(path):
                duration = _audio_duration(path)
                _emit(
                    idx,
                    {
                        "audio_path": path,
                        "duration_sec": duration,
                        "cache_hit": True,
                        "cache_key": key,
                    },
                )
                continue

            pending.append(
                {
                    "idx": idx,
                    "text": text,
                    "instruct": effective_instruct,
                    "ref_audio": effective_ref_audio,
                    "ref_text": effective_ref_text,
                    "speed": speed,
                    "language": language,
                    "normalize_text": normalize_text,
                    "cache_key": key,
                    "cache_path": path,
                }
            )

        if not pending:
            return results  # type: ignore[return-value]

        # Every spoken unit keeps its own waveform (exact line boundaries);
        # throughput comes from batching units, never from merging text.
        units = [{**it, "members": [it]} for it in pending]

        # Group by voice conditioning so one OmniVoice batch shares ref tokens.
        groups: dict[tuple, list[dict]] = {}
        for unit in units:
            group_key = (
                unit.get("instruct") or "",
                unit.get("ref_audio") or "",
                unit.get("ref_text") or "",
                unit.get("language") or "",
                int(bool(unit.get("normalize_text"))),
            )
            groups.setdefault(group_key, []).append(unit)

        for group_key, group_units in groups.items():
            # Similar lengths pack better (less padding in the iterative decoder).
            group_units.sort(key=lambda it: len(it.get("text") or ""))
            instruct = group_units[0].get("instruct")
            ref_audio = group_units[0].get("ref_audio")
            ref_text = group_units[0].get("ref_text")
            language = group_units[0].get("language")
            normalize_text = group_units[0].get("normalize_text")
            group_clone = bool(ref_audio)

            effective = self._effective_batch_size(batch_size, voice_clone=group_clone)
            pack_chars = _tts_batch_max_chars_from_settings(effective)
            packs = _pack_items_for_batch(group_units, effective, pack_chars)
            # Flatten to concrete GPU sub-packs (respect live OOM cap).
            all_subs: list[list[dict]] = []
            for ch in packs:
                eff = self._effective_batch_size(batch_size, voice_clone=group_clone)
                if len(ch) <= eff:
                    all_subs.append(ch)
                else:
                    all_subs.extend(ch[s : s + eff] for s in range(0, len(ch), eff))
            pack_sizes = [len(p) for p in all_subs]
            log.info(
                "Voice group %d units → %d GPU packs (target_batch=%d, sizes=%s, clone=%s)",
                len(group_units),
                len(all_subs),
                effective,
                pack_sizes[:12] + (["…"] if len(pack_sizes) > 12 else []),
                group_clone,
            )

            pack_n = len(all_subs)
            for pack_i, sub in enumerate(all_subs, start=1):
                texts = [it["text"] for it in sub]
                speeds = [float(it.get("speed") or 1.0) for it in sub]
                member_counts = [len(it.get("members") or [it]) for it in sub]
                status_msg = (
                    f"GPU pack {pack_i}/{pack_n}: {len(sub)} units / "
                    f"{sum(member_counts)} segs (this may take 30–90s)…"
                )
                log.info(
                    "GPU pack %d/%d units=%d members=%d chars=%d max_len=%d",
                    pack_i,
                    pack_n,
                    len(sub),
                    sum(member_counts),
                    sum(len(t) for t in texts),
                    max((len(t) for t in texts), default=0),
                )
                print(status_msg, flush=True)
                if on_status is not None:
                    try:
                        on_status(status_msg)
                    except Exception:
                        pass
                audios = self._synthesize_batch(
                    texts=texts,
                    instruct=instruct,
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    speeds=speeds,
                    num_step=num_step,
                    language=language,
                    normalize_text=bool(normalize_text),
                )
                for unit, audio in zip(sub, audios):
                    _write_audio_atomic(unit["cache_path"], audio, SAMPLE_RATE)
                    _emit(
                        unit["idx"],
                        {
                            "audio_path": unit["cache_path"],
                            "duration_sec": len(audio) / SAMPLE_RATE,
                            "cache_hit": False,
                            "cache_key": unit["cache_key"],
                        },
                    )

        missing = [i for i, r in enumerate(results) if r is None]
        if missing:
            raise RuntimeError(f"generate_many left {len(missing)} items unresolved")
        return results  # type: ignore[return-value]

    def generate_preview(
        self,
        instruct: str,
        sample_text: str,
        ref_audio: str | None = None,
        ref_text: str | None = None,
        language: str | None = None,
        normalize_text: bool | None = None,
    ) -> dict:
        return self.generate(
            text=sample_text,
            instruct=instruct,
            ref_audio=ref_audio,
            ref_text=ref_text,
            speed=1.0,
            num_step=24,
            language=language,
            normalize_text=normalize_text,
        )


def _partition_export_items(items: list[dict], lane_count: int) -> list[list[tuple[int, dict]]]:
    """Split items into contiguous, roughly equal sequence-cost lanes."""
    indexed = list(enumerate(items))
    if lane_count <= 1 or len(indexed) <= 1:
        return [indexed]
    if lane_count != 2:
        raise ValueError("Only one or two export lanes are supported")

    # Attention cost grows superlinearly with sequence length. Reference tokens
    # are common to both lanes, so text length squared is a useful cheap proxy.
    weights = [max(32, len(str(item.get("text") or ""))) ** 2 for item in items]
    target = sum(weights) / 2
    running = 0
    best_split = 1
    best_delta = float("inf")
    for split in range(1, len(items)):
        running += weights[split - 1]
        delta = abs(target - running)
        if delta < best_delta:
            best_delta = delta
            best_split = split
    return [indexed[:best_split], indexed[best_split:]]


class TTSExportPool:
    """One or two model replicas used only during a full export."""

    def __init__(self, primary: TTSEngine, requested_workers: int = 0):
        self.primary = primary
        self.requested_workers = max(0, min(int(requested_workers), 2))
        self.engines: list[TTSEngine] = [primary]
        self._replicas: list[TTSEngine] = []

    @property
    def worker_count(self) -> int:
        return len(self.engines)

    def start(self) -> int:
        """Load an optional second model. Auto mode uses two on 20GB+ CUDA."""
        # The local Higgs Transformers adapter exposes whole-waveform,
        # autoregressive generation and a 4B backbone. Keep one resident model;
        # the OmniVoice-only replica path below must never be selected for it.
        if getattr(self.primary, "engine_name", "omnivoice") != "omnivoice":
            log.info("Parallel export replicas are disabled for Higgs TTS.")
            return 1
        try:
            import torch

            if not torch.cuda.is_available():
                return 1
            # Dual model/stream auto tuning was measured only on NVIDIA.
            if getattr(torch.version, 'hip', None):
                return 1
            free_b, total_b = torch.cuda.mem_get_info()
            total_gb = total_b / (1024**3)
            free_gb = free_b / (1024**3)
        except Exception:
            return 1

        wanted = self.requested_workers
        if wanted == 0:
            wanted = 2 if total_gb >= 20 and free_gb >= 10 else 1
        if wanted < 2:
            return 1
        if total_gb < 16 or free_gb < 8:
            log.warning(
                "Second export worker skipped (VRAM free %.1f / total %.1f GB)",
                free_gb,
                total_gb,
            )
            return 1

        replica = TTSEngine(
            model_path=self.primary.model_path or _model_path_from_settings(),
            worker_label="lane-2",
        )
        try:
            log.info(
                "Loading second OmniVoice export worker "
                "(VRAM free %.1f / total %.1f GB)",
                free_gb,
                total_gb,
            )
            replica.load_sync()
            self.primary.worker_label = "lane-1"
            self.primary.set_dedicated_cuda_stream(True)
            replica.set_dedicated_cuda_stream(True)
            self._replicas.append(replica)
            self.engines.append(replica)
            # Two lanes + CUDA Graph capture crash on the shared CUDA RNG; two
            # eager lanes (with Triton kernels when enabled) are also faster
            # (measured: 13.2 s vs 15.6 s single-lane hybrid for 48 clones).
            from core.tts_accel import suspend_cuda_graphs

            for engine in self.engines:
                suspend_cuda_graphs(engine.model, True)
            log.info("Parallel TTS export ready: 2 model replicas / 2 CUDA streams "
                     "(CUDA Graphs paused during the export)")
        except Exception as exc:
            log.warning("Second export worker unavailable; using one: %s", exc)
            replica.unload()
        return self.worker_count

    def can_parallelize(self, items: list[dict]) -> bool:
        # Voice-design stabilization can create shared reference files. Keep
        # that path single-worker; the measured audiobook path is voice clone.
        return (
            self.worker_count >= 2
            and len(items) >= 16
            and all(bool(item.get("ref_audio")) for item in items)
        )

    def generate_many(
        self,
        items: list[dict],
        *,
        num_step: int,
        on_item=None,
        on_status=None,
    ) -> list[dict]:
        # Anchored design voices become clones, so they can use both lanes.
        if getattr(self.primary, "engine_name", "omnivoice") == "omnivoice" and hasattr(
            self.primary, "anchor_items"
        ):
            anchored = self.primary.anchor_items(items)
            if isinstance(anchored, list):
                items = anchored
        if not self.can_parallelize(items):
            return self.primary.generate_many(
                items,
                num_step=num_step,
                on_item=on_item,
                on_status=on_status,
            )

        unique_prompts = {
            (str(item["ref_audio"]), item.get("ref_text"))
            for item in items
            if item.get("ref_audio")
        }
        if on_status is not None:
            on_status("preparing 2 GPU workers…")
        # Populate/persist prompts before threads start so replicas never race
        # while writing the same .pt prompt cache file.
        for engine in self.engines:
            for ref_audio, ref_text in unique_prompts:
                engine._get_voice_clone_prompt(ref_audio, ref_text)

        lanes = _partition_export_items(items, 2)
        outputs: list[dict | None] = [None] * len(items)
        aborted = threading.Event()

        def run_lane(lane_no: int) -> None:
            engine = self.engines[lane_no]
            lane = lanes[lane_no]
            lane_items = [item for _, item in lane]

            def lane_item(local_i: int, result: dict) -> None:
                original_i = lane[local_i][0]
                outputs[original_i] = result
                if aborted.is_set():
                    raise SiblingAborted("sibling export lane aborted")
                if on_item is not None:
                    try:
                        on_item(original_i, result)
                    except GenerationAborted:
                        aborted.set()
                        raise

            def lane_status(message: str) -> None:
                if on_status is not None:
                    on_status(f"worker {lane_no + 1}/2 · {message}")

            engine.generate_many(
                lane_items,
                num_step=num_step,
                on_item=lane_item,
                on_status=lane_status,
            )

        log.info(
            "Parallel export split: lane sizes=%s chars=%s",
            [len(lane) for lane in lanes],
            [
                sum(len(str(item.get("text") or "")) for _, item in lane)
                for lane in lanes
            ],
        )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts-export") as executor:
            futures = [executor.submit(run_lane, lane_no) for lane_no in range(2)]
            first_error: BaseException | None = None
            for future in futures:
                try:
                    future.result()
                except BaseException as exc:
                    aborted.set()
                    # Prefer the real cause over the sibling lane's echo.
                    if first_error is None or (
                        isinstance(first_error, SiblingAborted)
                        and not isinstance(exc, SiblingAborted)
                    ):
                        first_error = exc
            if first_error is not None:
                raise first_error

        missing = [i for i, result in enumerate(outputs) if result is None]
        if missing:
            raise RuntimeError(
                f"Parallel export left {len(missing)} items unresolved"
            )
        return outputs  # type: ignore[return-value]

    def close(self) -> None:
        if len(self.engines) > 1:
            from core.tts_accel import suspend_cuda_graphs

            suspend_cuda_graphs(getattr(self.primary, "model", None), False)
        self.primary.set_dedicated_cuda_stream(False)
        self.primary.worker_label = "primary"
        for replica in self._replicas:
            replica.unload()
        self._replicas.clear()
        self.engines = [self.primary]
