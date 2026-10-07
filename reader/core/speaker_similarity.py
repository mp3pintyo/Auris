"""Speaker similarity: how much a rendered take sounds like the intended voice.

A CAM++ speaker-verification network (3D-Speaker, Apache-2.0, 192-dim
embeddings, trained on about 200k Chinese/English speakers) runs through
onnxruntime on the CPU, so it works on every Auris platform. The ONNX export
comes from the sherpa-onnx model collection and is downloaded on first use,
pinned to a revision and checked against its SHA-256.

Long audio is embedded in windows of up to 20 s whose vectors are averaged, so
a chapter-length file and a sentence are comparable. ``similarity`` returns the
cosine of two L2-normalised embeddings: about 0.8-0.9 for good clones of the
same voice, clearly lower for another speaker.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL_REPO = "csukuangfj/speaker-embedding-models"
MODEL_REVISION = "0743f301363dec56491a490f6d6cbc9d67f9a3bf"
MODEL_FILE = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"

SAMPLE_RATE = 16000
WINDOW_SECONDS = 20.0
MIN_TAIL_SECONDS = 0.5
MIN_AUDIO_SECONDS = 0.3


def model_path() -> Path:
    from core.paths import speaker_model_dir

    return speaker_model_dir() / MODEL_FILE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_model(*, download: bool = True) -> Path:
    """Return the verified model file, downloading it when allowed."""
    path = model_path()
    if path.is_file() and _sha256(path) == MODEL_SHA256:
        return path
    if not download:
        raise FileNotFoundError(f"A hanghasonlóság-modell hiányzik: {path}")
    from huggingface_hub import hf_hub_download

    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading speaker model %s@%s", MODEL_FILE, MODEL_REVISION[:7])
    hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE, revision=MODEL_REVISION,
                    local_dir=str(path.parent))
    if _sha256(path) != MODEL_SHA256:
        path.unlink(missing_ok=True)
        raise RuntimeError("A letöltött hanghasonlóság-modell ellenőrzőösszege eltér.")
    return path


def fbank(audio: np.ndarray) -> np.ndarray:
    """80-bin Kaldi filterbank of 16 kHz audio with per-utterance mean removal."""
    import torch
    import torchaudio.compliance.kaldi as kaldi

    wave = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
    feats = kaldi.fbank(wave, num_mel_bins=80, sample_frequency=SAMPLE_RATE, dither=0.0)
    feats = feats - feats.mean(dim=0, keepdim=True)
    return feats.numpy()


def windows(audio: np.ndarray, sr: int = SAMPLE_RATE) -> list[np.ndarray]:
    """Split into windows of at most 20 s; short tails are dropped unless alone."""
    size = int(WINDOW_SECONDS * sr)
    pieces = [audio[i:i + size] for i in range(0, len(audio), size)] or [audio]
    kept = [p for p in pieces if len(p) >= MIN_TAIL_SECONDS * sr]
    return kept or pieces[:1]


def normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(normalize(a), normalize(b)))


def centroid(vectors: list[np.ndarray]) -> np.ndarray:
    """Mean direction of several embeddings (a voice's typical sound)."""
    if not vectors:
        raise ValueError("centroid needs at least one embedding")
    return normalize(np.mean([normalize(v) for v in vectors], axis=0))


class SpeakerEmbedder:
    """Lazy, thread-safe CPU onnxruntime session."""

    def __init__(self, path: Path | None = None, *, download: bool = True):
        self._path = path
        self._download = download
        self._session = None
        self._lock = threading.Lock()

    def _load(self):
        import onnxruntime as ort

        path = self._path or ensure_model(download=self._download)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def unload(self) -> None:
        with self._lock:
            self._session = None

    def embed(self, audio: np.ndarray, sr: int) -> np.ndarray:
        from core.local_engines import resample

        audio = resample(np.asarray(audio, dtype=np.float32), int(sr), SAMPLE_RATE)
        if len(audio) < MIN_AUDIO_SECONDS * SAMPLE_RATE:
            raise ValueError("Túl rövid hang a hanghasonlóság méréséhez.")
        with self._lock:
            if self._session is None:
                self._load()
            vectors = [
                self._session.run(None, {self._input: fbank(piece)[None, :, :]})[0][0]
                for piece in windows(audio)
            ]
        return centroid(vectors)

    def embed_file(self, path: str | Path) -> np.ndarray:
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return self.embed(audio.mean(axis=1), sr)


_shared: SpeakerEmbedder | None = None
_shared_lock = threading.Lock()


def get_embedder() -> SpeakerEmbedder:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = SpeakerEmbedder()
        return _shared
