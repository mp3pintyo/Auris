"""
Audio + subtitle exporter.

Modes:
  - full_book   : single merged audio + subtitle for entire book
  - chapter_zip : zip of per-chapter audio + subtitle files
  - single      : one chapter audio + subtitle

Audio formats:
  - mp3  (via pydub + ffmpeg if available)
  - wav  (always available, soundfile)

Subtitle formats:
  - ass  (Advanced SubStation Alpha — per-character colours/styles)
  - srt  (plain SubRip — universal)
"""

import io
import os
import zipfile
import logging
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
EXPORTS_DIR = str(Path(__file__).resolve().parent.parent / 'exports')
os.makedirs(EXPORTS_DIR, exist_ok=True)

DEFAULT_SEGMENT_PAUSE_SEC = 0.35
DIALOGUE_TURN_PAUSE_SEC = 0.55
ELLIPSIS_PAUSE_SEC = 1.5


# ── ffmpeg / pydub detection ──────────────────────────────────────────────────

def _ffmpeg_available() -> bool:
    return shutil.which('ffmpeg') is not None


def _wav_to_mp3_bytes(wav_path: str) -> bytes | None:
    if not _ffmpeg_available():
        return None
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_wav(wav_path)
        buf = io.BytesIO()
        seg.export(buf, format='mp3', bitrate='192k')
        return buf.getvalue()
    except Exception as e:
        log.warning(f'MP3 conversion failed: {e}')
        return None


# ── Time formatting ───────────────────────────────────────────────────────────

def _fmt_ass(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f'{h}:{m:02d}:{s:05.2f}'


def _fmt_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


# ── ASS subtitle builder ──────────────────────────────────────────────────────

_ASS_HEADER = """\
[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Narrator,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,30,1
{char_styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}"""

_ASS_CHAR_STYLE = (
    'Style: {name},Arial,28,&H00{color},&H000000FF,&H00000000,'
    '&H80000000,0,-1,0,0,100,100,0,0,1,2,1,2,10,10,30,1'
)


def _hex_to_ass(hex_color: str) -> str:
    """Convert #RRGGBB → AABBGGRR (ASS BGR order, alpha=00)."""
    h = hex_color.lstrip('#')
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f'{b}{g}{r}'.upper()


def build_ass(segments: list[dict], character_colors: dict, title: str) -> str:
    char_styles = []
    seen = set()
    for name, color in character_colors.items():
        safe = name.replace(' ', '_')
        if safe in seen:
            continue
        seen.add(safe)
        char_styles.append(_ASS_CHAR_STYLE.format(
            name=safe, color=_hex_to_ass(color)
        ))

    events = []
    for seg in segments:
        start = _fmt_ass(seg['t_start'])
        end = _fmt_ass(seg['t_end'])
        char = seg.get('character_name') or 'Narrator'
        style = char.replace(' ', '_') if char in character_colors else 'Narrator'
        text = seg['text'].replace('\n', '\\N')
        if seg.get('is_dialogue'):
            text = '{\\i1}' + text + '{\\i0}'
        events.append(
            f'Dialogue: 0,{start},{end},{style},{char},0000,0000,0000,,{text}'
        )

    return _ASS_HEADER.format(
        title=title,
        char_styles='\n'.join(char_styles),
        events='\n'.join(events),
    )


def build_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_srt(seg['t_start'])
        end = _fmt_srt(seg['t_end'])
        lines.append(f'{i}\n{start} --> {end}\n{seg["text"]}\n')
    return '\n'.join(lines)


# ── Audio merge ───────────────────────────────────────────────────────────────

def pause_after_segment(segment: dict, next_segment: dict | None = None) -> float:
    """Return the spoken-program pause after a segment.

    Ellipses represent an intentional trailing-off pause. Consecutive dialogue
    segments get a slightly longer beat so a new voice does not cut in
    unnaturally fast.
    """
    text = str(segment.get('text') or '').rstrip()
    text = text.rstrip('"\'”’»').rstrip()
    if text.endswith(('...', '…')):
        return ELLIPSIS_PAUSE_SEC
    if (
        next_segment
        and segment.get('is_dialogue')
        and next_segment.get('is_dialogue')
    ):
        return DIALOGUE_TURN_PAUSE_SEC
    return DEFAULT_SEGMENT_PAUSE_SEC


def _merge_wavs(segments: list[dict]) -> np.ndarray:
    arrays = []
    playable = [
        seg
        for seg in segments
        if seg.get('audio_path') and os.path.exists(seg['audio_path'])
    ]
    for idx, seg in enumerate(playable):
        p = seg['audio_path']
        if p and os.path.exists(p):
            data, _ = sf.read(p)
            if data.ndim > 1:
                data = data.mean(axis=1)
            arrays.append(data)
            if idx + 1 < len(playable):
                pause = pause_after_segment(seg, playable[idx + 1])
                arrays.append(np.zeros(int(SAMPLE_RATE * pause)))
    return np.concatenate(arrays) if arrays else np.zeros(SAMPLE_RATE)


# ── Segment timeline builder ──────────────────────────────────────────────────

def build_timeline(segments_db: list[dict]) -> list[dict]:
    """
    segments_db: rows from tts_segments with audio_path + duration_sec.
    Returns same list enriched with t_start / t_end fields.
    """
    timeline = []
    cursor = 0.0
    for idx, seg in enumerate(segments_db):
        dur = seg.get('duration_sec') or 0.0
        timeline.append({**seg, 't_start': cursor, 't_end': cursor + dur})
        next_seg = segments_db[idx + 1] if idx + 1 < len(segments_db) else None
        cursor += dur
        if next_seg is not None:
            cursor += pause_after_segment(seg, next_seg)
    return timeline


# ── Public export functions ───────────────────────────────────────────────────

def export_single_chapter(
    chapter_title: str,
    book_title: str,
    segments: list[dict],
    character_colors: dict,
    audio_fmt: str = 'wav',
    sub_fmt: str = 'ass',
) -> dict:
    """Returns {'audio_path': ..., 'subtitle_path': ..., 'audio_fmt': ..., 'sub_fmt': ...}"""
    safe_title = _safe_name(chapter_title)
    timeline = build_timeline(segments)
    merged = _merge_wavs(timeline)

    wav_path = os.path.join(EXPORTS_DIR, f'{safe_title}.wav')
    sf.write(wav_path, merged, SAMPLE_RATE)

    out_audio = wav_path
    actual_fmt = 'wav'
    if audio_fmt == 'mp3':
        mp3 = _wav_to_mp3_bytes(wav_path)
        if mp3:
            out_audio = wav_path.replace('.wav', '.mp3')
            with open(out_audio, 'wb') as f:
                f.write(mp3)
            actual_fmt = 'mp3'

    sub_content = (
        build_ass(timeline, character_colors, f'{book_title} — {chapter_title}')
        if sub_fmt == 'ass'
        else build_srt(timeline)
    )
    sub_ext = 'ass' if sub_fmt == 'ass' else 'srt'
    sub_path = os.path.join(EXPORTS_DIR, f'{safe_title}.{sub_ext}')
    with open(sub_path, 'w', encoding='utf-8') as f:
        f.write(sub_content)

    return {'audio_path': out_audio, 'subtitle_path': sub_path,
            'audio_fmt': actual_fmt, 'sub_fmt': sub_ext}


def export_chapter_zip(
    book_title: str,
    chapters_data: list[dict],
    character_colors: dict,
    audio_fmt: str = 'wav',
    sub_fmt: str = 'ass',
) -> str:
    """chapters_data: list of {chapter_title, segments}. Returns zip file path."""
    safe_book = _safe_name(book_title)
    zip_path = os.path.join(EXPORTS_DIR, f'{safe_book}_chapters.zip')

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for ch in chapters_data:
            result = export_single_chapter(
                ch['chapter_title'], book_title, ch['segments'],
                character_colors, audio_fmt, sub_fmt,
            )
            ch_safe = _safe_name(ch['chapter_title'])
            ext = result['audio_fmt']
            zf.write(result['audio_path'], f'{ch_safe}.{ext}')
            zf.write(result['subtitle_path'], f'{ch_safe}.{result["sub_fmt"]}')

    return zip_path


def export_full_book(
    book_title: str,
    all_segments: list[dict],
    character_colors: dict,
    audio_fmt: str = 'wav',
    sub_fmt: str = 'ass',
) -> dict:
    """Merges all segments from all chapters into one file."""
    return export_single_chapter(
        book_title, book_title, all_segments, character_colors, audio_fmt, sub_fmt
    )


def _safe_name(name: str) -> str:
    import re
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:80] or 'export'
