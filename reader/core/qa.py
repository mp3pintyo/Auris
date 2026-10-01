"""Audiobook quality control: ASR verification, audio checks and loudness.

* ``score_transcript`` compares what the TTS was asked to say with what a
  speech recognizer heard. Hungarian accents are kept (kor/kór, tör/tőr are
  different words), punctuation and case are ignored, and numbers are
  compared in their spoken form.
* ``analyze_audio`` finds clipping, long internal silences, truncated or
  runaway takes (seconds per character outliers) and too quiet audio.
* ``loudness_report`` measures a rendered chapter against ACX requirements
  (RMS −23…−18 dB, peak ≤ −3 dB, noise floor ≤ −60 dB) and EBU R128.
* ``Transcriber`` wraps a Whisper model (Hungarian fine-tune by default) and
  can prompt it with the book's names so they are not counted as errors.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import threading
import unicodedata

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

HUNGARIAN_ASR_MODEL = "sarpba/whisper-hu-large-v3-turbo-finetuned"
MULTILINGUAL_ASR_MODEL = "openai/whisper-large-v3-turbo"

# Status thresholds on the character error rate.
DEFAULT_CER_WARN = 0.08
DEFAULT_CER_FAIL = 0.15

ACX_RMS_MIN_DB = -23.0
ACX_RMS_MAX_DB = -18.0
ACX_PEAK_MAX_DB = -3.0
ACX_NOISE_FLOOR_MAX_DB = -60.0

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


# ── Text comparison ─────────────────────────────────────────────────────────

def comparable_text(text: str, language: str | None = None) -> str:
    """Lowercase, spoken-form text without punctuation; accents are kept."""
    text = unicodedata.normalize("NFC", str(text or ""))
    text = re.sub(r"\[[a-z][a-z0-9_\- ]{0,40}\]", " ", text, flags=re.IGNORECASE)
    if str(language or "").lower().startswith("hu") or not language:
        try:
            from core.hungarian_numbers import looks_hungarian, normalize_hungarian

            if str(language or "").lower().startswith("hu") or looks_hungarian(text):
                text = normalize_hungarian(text)
        except Exception:
            pass
    text = text.lower().replace("-", " ").replace("–", " ").replace("—", " ")
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _levenshtein(a, b) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def score_transcript(expected: str, heard: str, language: str | None = None) -> dict:
    ref = comparable_text(expected, language)
    hyp = comparable_text(heard, language)
    ref_chars, hyp_chars = ref.replace(" ", ""), hyp.replace(" ", "")
    ref_words, hyp_words = ref.split(), hyp.split()
    cer = _levenshtein(ref_chars, hyp_chars) / max(1, len(ref_chars))
    wer = _levenshtein(ref_words, hyp_words) / max(1, len(ref_words))
    missing = [w for w in ref_words if w not in set(hyp_words)]
    return {
        "cer": round(min(cer, 9.99), 4),
        "wer": round(min(wer, 9.99), 4),
        "expected": ref,
        "heard": hyp,
        "missing_words": missing[:20],
    }


# ── Audio checks ────────────────────────────────────────────────────────────

def _db(value: float) -> float:
    return 20 * math.log10(max(float(value), 1e-9))


def _frame_rms(audio: np.ndarray, sr: int, frame_sec: float = 0.05) -> np.ndarray:
    size = max(1, int(sr * frame_sec))
    usable = len(audio) // size * size
    if usable == 0:
        return np.array([float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0])
    frames = audio[:usable].reshape(-1, size)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def analyze_audio(path: str, text: str = "", *, silence_db: float = -45.0) -> dict:
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    duration = len(audio) / sr if sr else 0.0
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    frames = _frame_rms(audio, sr)
    silent = frames < 10 ** (silence_db / 20)
    # Leading/trailing silence and the longest silence between speech.
    speech = np.flatnonzero(~silent)
    leading = trailing = longest_gap = 0.0
    if speech.size:
        leading = speech[0] * 0.05
        trailing = (len(frames) - 1 - speech[-1]) * 0.05
        run = best = 0
        for value in silent[speech[0]:speech[-1] + 1]:
            run = run + 1 if value else 0
            best = max(best, run)
        longest_gap = best * 0.05
    clipped = int(np.sum(np.abs(audio) >= 0.999))
    letters = len(re.sub(r"\W", "", str(text or "")))
    flags = []
    if clipped > max(3, len(audio) // 20000):
        flags.append("clipping")
    if longest_gap >= 1.5:
        flags.append("long_pause")
    if speech.size == 0 or rms < 10 ** (-45 / 20):
        flags.append("silent")
    if letters >= 8 and duration:
        per_char = duration / letters
        if per_char < 0.035:
            flags.append("too_fast")
        elif per_char > 0.25:
            flags.append("too_slow")
    return {
        "duration_sec": round(duration, 3),
        "peak_db": round(_db(peak), 2),
        "rms_db": round(_db(rms), 2),
        "leading_silence_sec": round(leading, 2),
        "trailing_silence_sec": round(trailing, 2),
        "longest_pause_sec": round(longest_gap, 2),
        "clipped_samples": clipped,
        "sec_per_char": round(duration / letters, 4) if letters else None,
        "flags": flags,
    }


def duration_outliers(items: list[dict], factor: float = 2.2) -> set[int]:
    """Indices whose seconds per character deviate strongly from the median."""
    rates = [(i, it.get("sec_per_char")) for i, it in enumerate(items) if it.get("sec_per_char")]
    if len(rates) < 5:
        return set()
    median = float(np.median([r for _, r in rates]))
    return {i for i, r in rates if r > median * factor or r < median / factor}


def classify(cer: float | None, flags: list[str], *, warn: float = DEFAULT_CER_WARN,
             fail: float = DEFAULT_CER_FAIL) -> str:
    if "silent" in flags or (cer is not None and cer >= fail):
        return "fail"
    if flags or (cer is not None and cer >= warn):
        return "warn"
    return "ok"


# ── Loudness ────────────────────────────────────────────────────────────────

def _ebur128(path: str) -> dict:
    if not shutil.which("ffmpeg"):
        return {}
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    match = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr or "", flags=re.DOTALL)
    if not match:
        return {}
    data = json.loads(match[-1])
    try:
        return {"lufs": float(data["input_i"]), "lra": float(data["input_lra"]),
                "true_peak_db": float(data["input_tp"])}
    except (KeyError, ValueError):
        return {}


def loudness_report(path: str) -> dict:
    """ACX-style measurements of a rendered chapter file."""
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    rms_db = _db(float(np.sqrt(np.mean(audio ** 2)))) if len(audio) else -120.0
    peak_db = _db(float(np.max(np.abs(audio)))) if len(audio) else -120.0
    frames = _frame_rms(audio, sr, 0.5)
    quiet = np.sort(frames)[: max(1, len(frames) // 20)]
    noise_floor_db = _db(float(np.mean(quiet))) if len(quiet) else -120.0
    report = {
        "duration_sec": round(len(audio) / sr, 2) if sr else 0,
        "rms_db": round(rms_db, 2),
        "peak_db": round(peak_db, 2),
        "noise_floor_db": round(noise_floor_db, 2),
    }
    report.update({k: round(v, 2) for k, v in _ebur128(path).items()})
    checks = {
        "rms": ACX_RMS_MIN_DB <= rms_db <= ACX_RMS_MAX_DB,
        "peak": peak_db <= ACX_PEAK_MAX_DB,
        "noise_floor": noise_floor_db <= ACX_NOISE_FLOOR_MAX_DB,
        "length": report["duration_sec"] <= 120 * 60,
    }
    report["acx_checks"] = checks
    report["acx_pass"] = all(checks.values())
    return report


# ── Speech recognition ──────────────────────────────────────────────────────

def asr_model_for(language: str | None) -> str:
    try:
        from core import settings

        custom = str(settings.get("asr_model", "") or "").strip()
        if custom:
            return custom
    except Exception:
        pass
    if str(language or "").lower().startswith("hu"):
        return HUNGARIAN_ASR_MODEL
    return MULTILINGUAL_ASR_MODEL


PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v3"
# NVIDIA Parakeet TDT 0.6B v3 (CC-BY-4.0) covers these 25 European languages.
PARAKEET_LANGUAGES = frozenset(
    "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk".split())
ASR_BACKENDS = ("auto", "whisper", "parakeet", "hybrid")


def parakeet_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("onnx_asr") is not None


def asr_backend_for(language: str | None) -> str:
    """Effective ASR backend: ``whisper``, ``parakeet`` or ``hybrid``.

    ``auto`` keeps Whisper on a CUDA GPU (fast and already measured) and uses
    Parakeet on CPU, where Whisper large-v3-turbo is several times slower;
    ``hybrid`` re-checks only the suspicious sentences with Whisper.
    """
    try:
        from core import settings

        requested = str(settings.get("asr_backend", "auto") or "auto")
    except Exception:
        requested = "auto"
    if requested not in ASR_BACKENDS:
        requested = "auto"
    lang = str(language or "").lower()[:2]
    parakeet_ok = parakeet_available() and (not lang or lang in PARAKEET_LANGUAGES)
    if requested == "auto":
        try:
            import torch

            gpu = bool(torch.cuda.is_available())
        except Exception:
            gpu = False
        return "whisper" if gpu or not parakeet_ok else "hybrid"
    if requested in ("parakeet", "hybrid") and not parakeet_ok:
        return "whisper"
    return requested


def _parakeet_words(tokens, timestamps, duration: float) -> list[dict]:
    """Group Parakeet sub-word tokens (a leading space starts a word)."""
    words = []
    boundary = True
    for token, start in zip(tokens or [], timestamps or []):
        if not token.strip():  # a lone space token also separates words (" ", "8")
            boundary = True
            continue
        if token.startswith(" ") or boundary or not words:
            words.append({"word": token.strip(), "start": float(start), "end": None})
        else:
            words[-1]["word"] += token
        boundary = False
    for current, following in zip(words, words[1:] + [None]):
        current["end"] = following["start"] if following else max(current["start"] + 0.2, duration)
    return [w for w in words if any(ch.isalnum() for ch in w["word"])]


class ParakeetTranscriber:
    """NVIDIA Parakeet TDT v3 through ONNX Runtime (CPU); text and word
    timings come from one pass. The ~2.4 GB model is downloaded on first use."""

    single_pass_words = True
    confirms = False

    def __init__(self):
        self.model_id = PARAKEET_MODEL
        self._model = None
        self._lock = threading.Lock()

    def unload(self) -> None:
        self._model = None

    def transcribe(self, path: str, language: str | None = None, *,
                   prompt: str = "", word_timestamps: bool = False) -> dict:
        with self._lock:
            if self._model is None:
                import onnx_asr
                from core.onnx_device import load_with_cpu_fallback, onnx_device_label, onnx_providers

                self._model, providers = load_with_cpu_fallback(
                    lambda p: onnx_asr.load_model(PARAKEET_MODEL, providers=p).with_timestamps(),
                    onnx_providers())
                log.info("ASR model %s loaded (%s)", PARAKEET_MODEL, onnx_device_label(providers))
            audio, sr = sf.read(path, dtype="float32", always_2d=True)
            audio = audio.mean(axis=1)
            if sr != 16000:
                from core.local_engines import resample

                audio = resample(audio, sr, 16000)
            result = self._model.recognize(audio)
        duration = len(audio) / 16000.0
        return {"text": str(result.text or "").strip(),
                "words": _parakeet_words(result.tokens, result.timestamps, duration)}


class HybridTranscriber(ParakeetTranscriber):
    """Parakeet first; Whisper only re-listens to sentences that look wrong."""

    confirms = True

    def __init__(self, whisper: "Transcriber"):
        super().__init__()
        self.whisper = whisper
        self.model_id = f"{PARAKEET_MODEL} + {whisper.model_id}"

    def confirm(self, path: str, language: str | None = None, *, prompt: str = "") -> dict:
        return self.whisper.transcribe(path, language, prompt=prompt)


class Transcriber:
    """Lazy Whisper pipeline; one instance per model, loaded on first use."""

    single_pass_words = False
    confirms = False

    _instances: dict[str, "Transcriber"] = {}
    _instances_lock = threading.Lock()

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._pipe = None
        self._lock = threading.Lock()

    @classmethod
    def whisper_for(cls, language: str | None) -> "Transcriber":
        model_id = asr_model_for(language)
        with cls._instances_lock:
            if model_id not in cls._instances:
                cls._instances[model_id] = cls(model_id)
            return cls._instances[model_id]

    @classmethod
    def for_language(cls, language: str | None):
        """The configured ASR backend for this language (see asr_backend_for)."""
        backend = asr_backend_for(language)
        if backend == "whisper":
            return cls.whisper_for(language)
        key = f"{backend}:{PARAKEET_MODEL}"
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = (ParakeetTranscriber() if backend == "parakeet"
                                       else HybridTranscriber(cls.whisper_for_unlocked(language)))
            return cls._instances[key]

    @classmethod
    def whisper_for_unlocked(cls, language: str | None) -> "Transcriber":
        model_id = asr_model_for(language)
        if model_id not in cls._instances:
            cls._instances[model_id] = cls(model_id)
        return cls._instances[model_id]

    @classmethod
    def unload_all(cls) -> None:
        with cls._instances_lock:
            for item in cls._instances.values():
                if isinstance(item, ParakeetTranscriber):
                    item.unload()
                else:
                    item._pipe = None
            cls._instances.clear()
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _load(self):
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32
        model = AutoModelForSpeechSeq2Seq.from_pretrained(self.model_id, dtype=dtype).to(device)
        processor = AutoProcessor.from_pretrained(self.model_id)
        self._pipe = pipeline(
            "automatic-speech-recognition", model=model, tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor, dtype=dtype, device=device,
        )
        log.info("ASR model %s loaded on %s", self.model_id, device)

    def transcribe(self, path: str, language: str | None = None, *,
                   prompt: str = "", word_timestamps: bool = False) -> dict:
        with self._lock:
            if self._pipe is None:
                self._load()
            audio, sr = sf.read(path, dtype="float32", always_2d=True)
            audio = audio.mean(axis=1)
            if sr != 16000:
                from core.local_engines import resample

                audio = resample(audio, sr, 16000)
            generate_kwargs = {"task": "transcribe"}
            lang = str(language or "").lower()[:2]
            if lang:
                generate_kwargs["language"] = lang
            if prompt:
                try:
                    ids = self._pipe.tokenizer.get_prompt_ids(prompt[:200], return_tensors="pt")
                    generate_kwargs["prompt_ids"] = ids.to(self._pipe.device)
                except Exception:
                    pass
            result = self._pipe(
                {"raw": audio, "sampling_rate": 16000},
                generate_kwargs=generate_kwargs,
                return_timestamps="word" if word_timestamps else False,
            )
        text = str(result.get("text") or "").strip()
        if prompt and text.startswith(prompt.strip()):
            text = text[len(prompt.strip()):].strip()
        words = []
        for chunk in result.get("chunks") or []:
            start, end = chunk.get("timestamp") or (None, None)
            words.append({"word": str(chunk.get("text") or "").strip(), "start": start, "end": end})
        return {"text": text, "words": words}
