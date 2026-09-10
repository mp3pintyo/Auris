"""Single-file voice preset container (``.aurisvoice``).

A saved narrator voice is only useful together with its transcript: the
cloning is zero-shot, so the engine rebuilds the voice profile from the
reference waveform *and* the matching ``ref_text`` on every call. Keeping
those two apart makes a preset easy to lose and impossible to hand over in
one piece.

This module packs both into a single ZIP archive with its own extension::

    Kern.aurisvoice
      audio.wav   - the reference recording, byte for byte
      meta.json   - {"format": 1, "name": "Kern", "ref_text": "...",
                     "source_filename": "kern.wav", "sample_rate": 24000,
                     "duration_sec": 8.4, "created_at": "2026-07-27T11:40:54"}

The reader side is deliberately paranoid: archives arrive from outside the
application, so entry names are validated against path traversal, both the
archive and its members are size-capped against zip bombs, and the WAV is
parsed before anything is written to disk or to the database.

Nothing here touches the network or the database; ``app.py`` owns both.
"""

from __future__ import annotations

import io
import json
import os
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime

FORMAT_VERSION = 1
EXTENSION = ".aurisvoice"

AUDIO_MEMBER = "audio.wav"
META_MEMBER = "meta.json"
_ALLOWED_MEMBERS = frozenset({AUDIO_MEMBER, META_MEMBER})

# Reference clips are 3-10 seconds; the caps leave room for long, high rate
# recordings while keeping a hostile archive from exhausting memory.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_AUDIO_BYTES = 128 * 1024 * 1024
MAX_META_BYTES = 64 * 1024
MAX_NAME_LENGTH = 80
MAX_REF_TEXT_LENGTH = 20000

# Anything outside this is not a speech recording we could clone from.
_MIN_SAMPLE_RATE = 4000
_MAX_SAMPLE_RATE = 384000
_MAX_CHANNELS = 8


class VoicePresetFileError(Exception):
    """The archive is missing, malformed, oversized or not a voice preset."""


@dataclass
class VoicePresetPayload:
    """What a ``.aurisvoice`` archive contained, after validation."""

    name: str
    ref_text: str
    source_filename: str
    audio_bytes: bytes
    sample_rate: int | None = None
    duration_sec: float | None = None
    created_at: str | None = None
    instruct: str = ""


# ────────────────────────────────────────────────────────────────────────────
# WAV probing
# ────────────────────────────────────────────────────────────────────────────

def probe_wav(data: bytes) -> dict | None:
    """Parse a RIFF/WAVE header. Returns ``None`` if this is not a usable WAV.

    Deliberately hand-rolled instead of using :mod:`wave`, which refuses
    float32 (``WAVE_FORMAT_IEEE_FLOAT``) and extensible files that recording
    tools produce all the time.
    """
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None

    fmt = None
    data_size = None
    pos = 12
    end = len(data)
    while pos + 8 <= end:
        chunk_id = data[pos:pos + 4]
        (chunk_size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        body = pos + 8
        if chunk_id == b"fmt " and chunk_size >= 16 and body + 16 <= end:
            audio_format, channels, sample_rate, _byte_rate, _align, bits = \
                struct.unpack("<HHIIHH", data[body:body + 16])
            fmt = {
                "audio_format": audio_format,
                "channels": channels,
                "sample_rate": sample_rate,
                "bits_per_sample": bits,
            }
        elif chunk_id == b"data":
            # Trust the smaller of declared and actual size: truncated
            # downloads declare more than they carry.
            data_size = min(chunk_size, max(0, end - body))
        pos = body + chunk_size + (chunk_size & 1)

    if not fmt or data_size is None:
        return None
    if not (_MIN_SAMPLE_RATE <= fmt["sample_rate"] <= _MAX_SAMPLE_RATE):
        return None
    if not (1 <= fmt["channels"] <= _MAX_CHANNELS):
        return None

    duration = None
    frame_size = (fmt["bits_per_sample"] // 8) * fmt["channels"]
    if frame_size > 0:
        duration = round(data_size / frame_size / fmt["sample_rate"], 3)
    return {
        "sample_rate": fmt["sample_rate"],
        "channels": fmt["channels"],
        "bits_per_sample": fmt["bits_per_sample"],
        "duration_sec": duration,
    }


# ────────────────────────────────────────────────────────────────────────────
# Writing
# ────────────────────────────────────────────────────────────────────────────

def safe_download_name(name: str) -> str:
    """Turn a preset name into a filename that is safe on every platform."""
    cleaned = "".join(
        " " if ch in '\\/:*?"<>|\0' or ord(ch) < 32 else ch
        for ch in (name or "")
    ).strip().strip(".")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = "voice"
    return cleaned[:MAX_NAME_LENGTH] + EXTENSION


def build_archive(
    name: str,
    audio_bytes: bytes,
    ref_text: str | None = None,
    source_filename: str | None = None,
    created_at: str | None = None,
    instruct: str | None = None,
) -> bytes:
    """Serialise one preset into ``.aurisvoice`` bytes."""
    if not audio_bytes:
        raise VoicePresetFileError("The preset has no reference audio.")

    probe = probe_wav(audio_bytes) or {}
    meta = {
        "format": FORMAT_VERSION,
        "name": (name or "").strip(),
        "ref_text": ref_text or "",
        "source_filename": os.path.basename(source_filename or "") or "audio.wav",
        "sample_rate": probe.get("sample_rate"),
        "duration_sec": probe.get("duration_sec"),
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "app": "Auris",
        "instruct": instruct or "",
    }

    buffer = io.BytesIO()
    # The WAV is already incompressible; storing it keeps export instant and
    # the round trip byte-identical.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo(META_MEMBER),
            json.dumps(meta, ensure_ascii=False, indent=2),
        )
        zf.writestr(zipfile.ZipInfo(AUDIO_MEMBER), audio_bytes,
                    compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def build_archive_from_path(
    name: str,
    audio_path: str,
    ref_text: str | None = None,
    source_filename: str | None = None,
    created_at: str | None = None,
    instruct: str | None = None,
) -> bytes:
    """Same as :func:`build_archive`, reading the WAV from disk."""
    try:
        with open(audio_path, "rb") as fh:
            audio_bytes = fh.read(MAX_AUDIO_BYTES + 1)
    except OSError as exc:
        raise VoicePresetFileError(
            "The preset audio file is missing on disk."
        ) from exc
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise VoicePresetFileError("The preset audio file is too large to export.")
    return build_archive(
        name,
        audio_bytes,
        ref_text=ref_text,
        source_filename=source_filename or os.path.basename(audio_path),
        created_at=created_at,
        instruct=instruct,
    )


# ────────────────────────────────────────────────────────────────────────────
# Reading
# ────────────────────────────────────────────────────────────────────────────

def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise VoicePresetFileError(
            f"'{info.filename}' is too large for a voice preset."
        )
    with zf.open(info, "r") as fh:
        payload = fh.read(limit + 1)
    # Guard against a lying central directory as well as a declared size.
    if len(payload) > limit:
        raise VoicePresetFileError(
            f"'{info.filename}' is too large for a voice preset."
        )
    return payload


def read_archive(data: bytes) -> VoicePresetPayload:
    """Validate and unpack ``.aurisvoice`` bytes.

    Raises :class:`VoicePresetFileError` with a message meant for the user.
    """
    if not data:
        raise VoicePresetFileError("The file is empty.")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise VoicePresetFileError("The file is too large for a voice preset.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise VoicePresetFileError(
            "This is not a valid Auris voice preset file."
        ) from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > len(_ALLOWED_MEMBERS):
            raise VoicePresetFileError(
                "The voice preset archive contains unexpected entries."
            )
        by_name: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            entry = info.filename
            # Reject traversal, absolute paths and directories outright rather
            # than normalising them: a genuine preset never has any of these.
            if (
                entry not in _ALLOWED_MEMBERS
                or info.is_dir()
                or "/" in entry
                or "\\" in entry
                or os.path.isabs(entry)
                or ".." in entry.split("/")
            ):
                raise VoicePresetFileError(
                    "The voice preset archive contains unexpected entries."
                )
            if entry in by_name:
                raise VoicePresetFileError(
                    "The voice preset archive contains duplicate entries."
                )
            by_name[entry] = info

        if META_MEMBER not in by_name or AUDIO_MEMBER not in by_name:
            raise VoicePresetFileError(
                "This is not a valid Auris voice preset file."
            )

        try:
            raw_meta = _read_member(zf, by_name[META_MEMBER], MAX_META_BYTES)
            audio_bytes = _read_member(zf, by_name[AUDIO_MEMBER], MAX_AUDIO_BYTES)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise VoicePresetFileError(
                "The voice preset file is damaged and could not be read."
            ) from exc

    try:
        meta = json.loads(raw_meta.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise VoicePresetFileError(
            "The voice preset description is unreadable."
        ) from exc
    if not isinstance(meta, dict):
        raise VoicePresetFileError("The voice preset description is unreadable.")

    version = meta.get("format")
    if not isinstance(version, int) or version < 1:
        raise VoicePresetFileError(
            "This is not a valid Auris voice preset file."
        )
    if version > FORMAT_VERSION:
        raise VoicePresetFileError(
            f"This preset was made by a newer Auris (format {version}). "
            "Update the app to import it."
        )

    probe = probe_wav(audio_bytes)
    if not probe:
        raise VoicePresetFileError(
            "The reference audio inside the file is not a readable WAV recording."
        )

    name = str(meta.get("name") or "").strip()[:MAX_NAME_LENGTH]
    ref_text = str(meta.get("ref_text") or "")[:MAX_REF_TEXT_LENGTH]
    instruct = str(meta.get("instruct") or "")[:1000]
    source = os.path.basename(str(meta.get("source_filename") or "")) or "audio.wav"
    created_at = meta.get("created_at")

    return VoicePresetPayload(
        name=name,
        ref_text=ref_text,
        source_filename=source,
        audio_bytes=audio_bytes,
        sample_rate=probe["sample_rate"],
        duration_sec=probe["duration_sec"],
        created_at=str(created_at) if created_at else None,
        instruct=instruct,
    )


def read_archive_from_stream(stream) -> VoicePresetPayload:
    """Read at most one archive worth of bytes from a file-like object."""
    data = stream.read(MAX_ARCHIVE_BYTES + 1)
    if data is None:
        raise VoicePresetFileError("The file is empty.")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise VoicePresetFileError("The file is too large for a voice preset.")
    return read_archive(data)
