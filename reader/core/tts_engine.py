"""
OmniVoice TTS engine wrapper.

Loads the model lazily from the configured model directory.
Caches generated audio by segment hash.
Stabilizes short voice-design generations by reusing a longer
instruction-conditioned reference clip for each instruct string.
"""

import hashlib
import logging
import os
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

AUDIO_CACHE_DIR = str(Path(__file__).resolve().parent.parent / "audio_cache")
VOICE_REF_DIR = os.path.join(AUDIO_CACHE_DIR, "voice_refs")
SAMPLE_RATE = 24_000
VOICE_DESIGN_REF_TEXT = (
    "Hello. This is a stable voice sample for conditioning. "
    "The room is quiet, the day is calm, and every word should sound clear, "
    "natural, and easy to understand."
)
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


def _model_path_from_settings() -> str:
    try:
        from core.settings import get

        return get("model_path") or ""
    except Exception:
        return str(Path(__file__).resolve().parent.parent.parent / "model_backup" / "OmniVoice")


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


class TTSEngine:
    def __init__(self, model_path: str = ""):
        self.model_path = model_path
        self.model = None
        self._lock = threading.Lock()
        self._loading = False
        self._ready = False
        self._error: str | None = None
        os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
        os.makedirs(VOICE_REF_DIR, exist_ok=True)

    def status(self) -> dict:
        resolved_path = self.model_path or _model_path_from_settings()
        if self._error:
            return {"state": "error", "message": self._error}
        if self._ready:
            return {"state": "ready"}
        if self._loading:
            return {"state": "loading"}
        return {
            "state": "not_loaded",
            "model_path": resolved_path,
            "model_exists": os.path.isdir(resolved_path),
        }

    def load_async(self):
        if self._ready or self._loading:
            return
        threading.Thread(target=self._load, daemon=True).start()

    def reload(self):
        self._ready = False
        self._error = None
        self.model = None
        self.load_async()

    def _load(self):
        with self._lock:
            if self._ready:
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

            device = "cuda" if self._cuda_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            log.info("Loading OmniVoice from %s on %s ...", self.model_path, device)
            self.model = OmniVoice.from_pretrained(
                self.model_path,
                device_map=device,
                dtype=dtype,
                local_files_only=True,
            )
            self._ready = True
            log.info("OmniVoice model ready.")
        except Exception as exc:
            self._error = str(exc)
            log.error("Failed to load OmniVoice: %s", exc)
        finally:
            self._loading = False

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch

            return torch.cuda.is_available()
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
    ) -> str:
        payload = f"{text}|{instruct}|{ref_audio}|{ref_text}|{speed:.2f}|{language or ''}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def cache_path(key: str) -> str:
        return os.path.join(AUDIO_CACHE_DIR, f"{key}.wav")

    @staticmethod
    def _voice_ref_key(instruct: str) -> str:
        return hashlib.md5(instruct.encode("utf-8")).hexdigest()

    def _voice_ref_path(self, instruct: str) -> str:
        return os.path.join(VOICE_REF_DIR, f"{self._voice_ref_key(instruct)}.wav")

    @staticmethod
    def _needs_voice_design_stabilization(text: str, instruct: str | None, ref_audio: str | None) -> bool:
        return bool(instruct and not ref_audio)

    def _synthesize_audio(
        self,
        text: str,
        instruct: str | None = None,
        ref_audio: str | None = None,
        ref_text: str | None = None,
        speed: float = 1.0,
        num_step: int = 32,
        language: str | None = None,
    ) -> np.ndarray:
        if not self._ready:
            raise RuntimeError("Model is not loaded yet. " + (self._error or "Call load_async() first."))

        with self._lock:
            audio_arrays = self.model.generate(
                text=text,
                instruct=instruct,
                ref_audio=ref_audio,
                ref_text=ref_text,
                speed=speed,
                num_step=num_step,
                language=language,
            )

        audio = audio_arrays[0] if isinstance(audio_arrays, list) else audio_arrays
        if not isinstance(audio, np.ndarray):
            audio = np.array(audio)
        if audio.ndim > 1:
            audio = audio.mean(axis=0)
        return audio

    def _ensure_voice_design_reference(self, instruct: str) -> tuple[str, str]:
        ref_path = self._voice_ref_path(instruct)
        if os.path.exists(ref_path):
            cached_audio, _ = sf.read(ref_path)
            if _audio_zcr(cached_audio) >= VOICE_REF_MIN_ZCR:
                return ref_path, VOICE_DESIGN_REF_TEXT
            log.warning("Discarding unstable cached voice reference for '%s'", instruct)

        best_audio = None
        best_zcr = -1.0

        for attempt in range(VOICE_REF_GEN_ATTEMPTS):
            audio = self._synthesize_audio(
                text=VOICE_DESIGN_REF_TEXT,
                instruct=instruct,
                speed=1.0,
                num_step=24,
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

        sf.write(ref_path, best_audio, SAMPLE_RATE)
        if best_zcr < VOICE_REF_MIN_ZCR:
            log.warning(
                "Using best-effort voice reference for '%s' despite low zcr=%.4f",
                instruct,
                best_zcr,
            )
        return ref_path, VOICE_DESIGN_REF_TEXT

    def generate(
        self,
        text: str,
        instruct: str | None = None,
        ref_audio: str | None = None,
        ref_text: str | None = None,
        speed: float = 1.0,
        num_step: int = 32,
        language: str | None = None,
    ) -> dict:
        """
        Returns:
            {
                audio_path: str,
                duration_sec: float,
                cache_hit: bool,
                cache_key: str,
            }
        """
        effective_instruct = _stabilize_voice_design_instruct(instruct)
        effective_ref_audio = ref_audio
        effective_ref_text = ref_text

        if self._needs_voice_design_stabilization(text, effective_instruct, ref_audio):
            effective_ref_audio, effective_ref_text = self._ensure_voice_design_reference(effective_instruct)

        key = self.cache_key(
            text,
            effective_instruct,
            effective_ref_audio,
            speed,
            ref_text=effective_ref_text,
            language=language,
        )
        path = self.cache_path(key)

        if os.path.exists(path):
            data, sr = sf.read(path)
            return {
                "audio_path": path,
                "duration_sec": len(data) / sr,
                "cache_hit": True,
                "cache_key": key,
            }

        audio = self._synthesize_audio(
            text=text,
            instruct=effective_instruct,
            ref_audio=effective_ref_audio,
            ref_text=effective_ref_text,
            speed=speed,
            num_step=num_step,
            language=language,
        )
        sf.write(path, audio, SAMPLE_RATE)

        return {
            "audio_path": path,
            "duration_sec": len(audio) / SAMPLE_RATE,
            "cache_hit": False,
            "cache_key": key,
        }

    def generate_preview(
        self,
        instruct: str,
        sample_text: str,
        ref_audio: str | None = None,
        ref_text: str | None = None,
    ) -> dict:
        return self.generate(
            text=sample_text,
            instruct=instruct,
            ref_audio=ref_audio,
            ref_text=ref_text,
            speed=1.0,
            num_step=24,
        )
