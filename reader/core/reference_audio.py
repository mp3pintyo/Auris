"""Clean uploaded voice-cloning references before they are stored.

Cloning copies everything in the reference: hum, room noise, long silences
and level. A light, speech-safe chain improves every engine that clones:

- 70 Hz fourth-order high-pass and 50/60 Hz notches (rumble, mains hum);
- FFT denoise (``afftdn``) tuned for steady background noise;
- leading/trailing silence trimmed to ~0.15 s;
- loudness normalised to about -20 LUFS with -2 dBTP headroom;
- mono, 24 kHz, 16-bit PCM.

Any ffmpeg failure keeps the original file: cleaning is an improvement,
never a reason to lose an upload.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

import soundfile as sf

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
_EDGE = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15"
CLEAN_FILTER = ",".join([
    "highpass=f=70,highpass=f=70",  # 4th order: rumble and mains hum
    "bandreject=f=50:width_type=q:w=4,bandreject=f=60:width_type=q:w=4",
    "afftdn=nf=-25:nt=w",
    _EDGE, "areverse", _EDGE, "areverse",
    "loudnorm=I=-20:TP=-2:LRA=11",
])
MIN_CLEAN_SEC = 1.0


def clean_reference(src: str, dst: str) -> dict:
    """Write a cleaned copy of ``src`` to ``dst``.

    Returns ``{'cleaned': bool, 'duration_sec': float, 'message': str}``;
    when ``cleaned`` is false, ``dst`` was not written.
    """
    if not shutil.which("ffmpeg"):
        return {"cleaned": False, "duration_sec": 0.0, "message": "Az ffmpeg nem érhető el; a tisztítás kimaradt."}
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
           "-af", CLEAN_FILTER, "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", dst]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        info = sf.info(dst)
        duration = float(info.frames) / float(info.samplerate or 1)
    except Exception as exc:  # keep the original upload on any failure
        log.warning("Reference cleaning failed for %s: %s", src, exc)
        _remove(dst)
        return {"cleaned": False, "duration_sec": 0.0, "message": "A tisztítás nem sikerült; az eredeti felvétel maradt."}
    if duration < MIN_CLEAN_SEC:
        _remove(dst)
        return {"cleaned": False, "duration_sec": duration,
                "message": "A tisztítás után túl rövid maradt a felvétel; az eredeti maradt."}
    return {"cleaned": True, "duration_sec": duration, "message": ""}


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ── Upload formats ──────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".webm")


def is_audio_filename(name: str) -> bool:
    return str(name or "").lower().endswith(AUDIO_EXTENSIONS)


def convert_to_wav(src: str, dst: str) -> bool:
    """Decode any ffmpeg-readable audio to mono 24 kHz PCM16 without filtering."""
    if not shutil.which("ffmpeg"):
        return False
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
           "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", dst]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return sf.info(dst).frames > 0
    except Exception as exc:
        log.warning("Reference conversion failed for %s: %s", src, exc)
        _remove(dst)
        return False


# ── Reference check ─────────────────────────────────────────────────────────
#
# Measured on Hungarian OmniVoice cloning (docs/superpowers/specs/
# 2026-10-07-indextts2-premium-atvetel.md): a 55 s reference gave ten times the
# word errors of 10-15 s clips cut from the same recording, and a reference
# whose last word was cut off while the transcript spelled it out gave 23-25 %
# word errors against 2-4 % for the same stretch ending in a pause.

IDEAL_MIN_SECONDS = 6.0
IDEAL_MAX_SECONDS = 15.0
TOO_SHORT_SECONDS = 3.0
TOO_LONG_SECONDS = 20.0
EDGE_FRAMES = 2  # 40 ms at the very edge must already be quiet
TRANSCRIPT_CER_WARN = 0.15


def _issue(code: str, level: str, message: str) -> dict:
    return {"code": code, "level": level, "message": message}


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def edge_quiet_seconds(audio, sr: int) -> tuple[float, float]:
    """Quiet time before the first and after the last loud 20 ms frame.

    Unsmoothed frames, so a clip cut in a short pause (a few tens of ms of
    quiet) passes while one cut inside a word (still loud at the edge) fails.
    """
    from core.reference_candidates import FRAME_SECONDS, QUIET_BELOW_SPEECH_DB
    import numpy as np

    size = max(1, int(FRAME_SECONDS * sr))
    frames = audio[:len(audio) // size * size].reshape(-1, size)
    if not len(frames):
        return 0.0, 0.0
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)
    loud = np.flatnonzero(db >= np.percentile(db, 90) - QUIET_BELOW_SPEECH_DB)
    if not len(loud):
        return 0.0, 0.0
    return loud[0] * FRAME_SECONDS, (len(db) - 1 - loud[-1]) * FRAME_SECONDS


def _edge_words(expected: str, heard: str, language: str) -> tuple[bool, bool]:
    """Whether the transcript's first and last words open and close what was heard."""
    from core.qa import comparable_text

    ref = comparable_text(expected, language).split()
    hyp = comparable_text(heard, language).replace(" ", "")
    if not ref or not hyp:
        return True, True
    return hyp.startswith(ref[0]), hyp.endswith(ref[-1])


def inspect_reference(path: str, ref_text: str | None, language: str | None = "hu",
                      transcriber=None) -> dict:
    """Check a cloning reference: length, cut-off edges and transcript agreement.

    ``transcriber`` (core.qa Transcriber-like) hears the recording; without a
    transcript its result is offered as ``suggested_text``. A recording longer
    than the ideal range gets sentence-aligned ``candidates`` to cut to.
    """
    from core import reference_candidates
    from core.qa import score_transcript
    import numpy as np

    language = (language or "hu").lower()[:2]
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    duration = len(audio) / sr if sr else 0.0
    issues = []
    if duration < TOO_SHORT_SECONDS:
        issues.append(_issue("too_short", "error",
                             f"A felvétel csak {_seconds(duration)} s. Legalább 6 másodperc kell a megbízható klónhoz."))
    elif duration < IDEAL_MIN_SECONDS:
        issues.append(_issue("short", "warn",
                             f"Rövid felvétel ({_seconds(duration)} s); 6–15 másodperc az ideális."))
    elif duration > TOO_LONG_SECONDS:
        issues.append(_issue("too_long", "error",
                             f"A felvétel {_seconds(duration)} s hosszú. 15 másodperc felett a klón romlik és "
                             f"lassul (55 s-os referenciánál tízszeres szóhibát mértünk). Válassz egy rövidebb szakaszt."))
    elif duration > IDEAL_MAX_SECONDS:
        issues.append(_issue("long", "warn",
                             f"Kicsit hosszú felvétel ({_seconds(duration)} s); 6–15 másodperc az ideális."))
    from core.reference_candidates import FRAME_SECONDS

    lead, tail = edge_quiet_seconds(audio, sr)
    edge = EDGE_FRAMES * FRAME_SECONDS
    if lead < edge:
        issues.append(_issue("abrupt_start", "warn",
                             "A felvétel csend nélkül indul; ha az első szó csonka, a klón pontatlan lehet."))
    if tail < edge:
        issues.append(_issue("abrupt_end", "error",
                             "A felvétel vége hirtelen szakad meg. A csonka utolsó szó miatt a klón szóvégeket nyelhet el."))

    heard, words, cer = "", [], None
    expected = (ref_text or "").strip()
    if transcriber is not None:
        result = transcriber.transcribe(path, language, word_timestamps=duration > IDEAL_MAX_SECONDS)
        heard, words = str(result.get("text") or "").strip(), result.get("words") or []
    if expected and heard:
        cer = score_transcript(expected, heard, language)["cer"]
        first_ok, last_ok = _edge_words(expected, heard, language)
        if cer > TRANSCRIPT_CER_WARN:
            issues.append(_issue("transcript_mismatch", "warn",
                                 f"Az átirat {round(cer * 100)} %-ban eltér attól, ami elhangzik. "
                                 f"A pontatlan átirat rontja a klónt."))
        if not last_ok:
            issues.append(_issue("last_word", "warn",
                                 "A felismerő nem hallja az átirat utolsó szavát. Hallgasd meg a felvétel végét: "
                                 "ha a szó csonka, válassz másik szakaszt; ha csak halk, rendben van."))
        if not first_ok:
            issues.append(_issue("first_word", "warn",
                                 "A felvétel első szava nem az, amivel az átirat kezdődik."))

    text_for_cuts = expected or heard
    candidates = []
    if duration > IDEAL_MAX_SECONDS and text_for_cuts and words:
        found = reference_candidates.candidates(audio, sr, text_for_cuts, words,
                                                min_seconds=8.0, max_seconds=IDEAL_MAX_SECONDS,
                                                target_seconds=12.0)
        candidates = [{"start": round(c.start, 2), "end": round(c.end, 2),
                       "duration": round(c.duration, 1), "text": c.text} for c in found[:4]]
    return {
        "duration": round(duration, 2),
        "issues": issues,
        "ok": not any(i["level"] == "error" for i in issues),
        "heard": heard,
        "cer": cer,
        "suggested_text": heard if not expected else "",
        "candidates": candidates,
        "edge_quiet": [round(lead, 2), round(tail, 2)],
        "rms_db": round(float(20 * np.log10(np.sqrt(np.mean(audio ** 2)) + 1e-9)), 1),
    }


def cut_reference(src: str, dst: str, start: float, end: float) -> float:
    """Write [start, end] seconds of ``src`` to ``dst`` with 10 ms fades."""
    from core import reference_candidates

    audio, sr = sf.read(src, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    total = len(audio) / sr
    start, end = max(0.0, float(start)), min(total, float(end))
    if end - start < TOO_SHORT_SECONDS:
        raise ValueError("A kivágott szakasz túl rövid.")
    piece = reference_candidates.cut(audio, sr, reference_candidates.Candidate(start, end, "", 0, 0))
    sf.write(dst, piece, sr, subtype="PCM_16", format="WAV")
    return end - start
