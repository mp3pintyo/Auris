"""
Offline Ebook Reader — Flask application.
"""

import base64
from pathlib import Path
import json
import logging
import os
import threading
import uuid
import sys
import re

# Blueprint services must share this module's engine and locks when launched as a script.
if __name__ == '__main__':
    sys.modules['app'] = sys.modules[__name__]

from flask import (
    Flask, g, jsonify, render_template, request,
    send_file,
)

from core.database import init_db, get_conn
from core import security
from core.cancellation import GenerationAborted
from core import text_editor
from core.tts_batcher import InteractiveTTSBatcher
from core.tts_engine import TTSExportPool
from core.tts_router import TTSEngineRouter
from core import characters as char_module
from core import llm_characters
from core import enrichment, exporter, jobs, structure, settings as app_settings
from core.parser import docx_parser, epub_parser, pdf_parser, prc_parser, txt_parser

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB
security.install(app)

_I18N_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'i18n', 'hu.json')
_i18n_cache: dict = {'mtime': None, 'data': {}}


@app.context_processor
def _inject_i18n():
    """Shared UI strings (static/i18n/hu.json) for Auris.t() in the browser."""
    try:
        mtime = os.path.getmtime(_I18N_PATH)
        if mtime != _i18n_cache['mtime']:
            with open(_I18N_PATH, encoding='utf-8') as handle:
                _i18n_cache['data'] = json.load(handle)
            _i18n_cache['mtime'] = mtime
    except (OSError, ValueError):
        pass
    try:
        theme = str(app_settings.load().get('theme') or 'night')
    except Exception:
        theme = 'night'
    if theme not in ('night', 'sepia', 'paper', 'amoled'):
        theme = 'night'
    # The saved theme is the first-paint default on every page, so a new
    # browser does not start light on some pages and dark on the reader.
    return {'i18n': _i18n_cache['data'], 'ui_theme': theme,
            'desktop_mode': 'desktop.setup_page' in app.view_functions}

from core.paths import user_path

UPLOAD_DIR = str(user_path('uploads'))
os.makedirs(UPLOAD_DIR, exist_ok=True)

tts = TTSEngineRouter()

DEFAULT_NARRATOR_INSTRUCT = app_settings.DEFAULT_NARRATOR_INSTRUCT

_export_jobs: dict = {}
_chapter_generation_jobs: dict = {}
_chapter_generation_by_chapter: dict[tuple[int, int], str] = {}
_chapter_generation_active_job_id: str | None = None
_chapter_generation_lock = threading.Lock()

# When > 0, an export job owns the TTS engine. Interactive /api/tts/generate
# must not start new synth work (cache hits still OK) so full-book batching
# is not interleaved with single-segment reader prewarm requests.
_export_tts_exclusive = 0
_export_tts_exclusive_lock = threading.Lock()

# Per-chapter locks prevent concurrent segment building from racing on the
# DELETE + INSERT in _store_segments when multiple requests hit the same
# chapter before segments are built (e.g. parallel prewarm requests).
_chapter_build_locks: dict = {}
_chapter_build_locks_meta = threading.Lock()
_startup_lock = threading.Lock()
_startup_complete = False
_character_analysis_lock = threading.Lock()
_character_analysis_state_lock = threading.Lock()
_character_analysis_pending = 0
_work_dispatch_lock = threading.RLock()
_interactive_request_count = 0

_WORK_BUSY_MESSAGE = (
    'Másik generálás, export vagy elemzés fut. '
    'Várd meg vagy állítsd le a Feladatok oldalon.'
)
_INTERACTIVE_BUSY_MESSAGE = (
    'Interaktív hangkészítés fut. Próbáld újra, amikor befejeződött.'
)
_INTERACTIVE_ENDPOINTS = {
    'voices.preview_character', 'voices.preview_narrator', 'reading.preview_chapter_text',
    # Reference check and audition use the speech recognizer and the TTS model.
    'voices.check_character_ref_audio', 'voices.check_narrator_ref_audio',
    'voices.audition_character_ref_audio', 'voices.audition_narrator_ref_audio',
}
_GATED_MUTATION_ENDPOINTS = {
    'import_book', 'delete_book', 'reading.update_speaker_annotation', 'reading.save_chapter_text',
    'reading.restore_chapter_text', 'voices.upload_ref_audio',
    'voices.delete_ref_audio', 'voices.upload_narrator_ref_audio',
    'voices.delete_narrator_ref_audio', 'settings_api.save_settings', 'tts_load', 'settings_api.tts_reload',
    'voices.trim_character_ref_audio', 'voices.trim_narrator_ref_audio',
}
_VOICE_MUTATION_ENDPOINTS = {'voices.update_character', 'voices.update_narrator'}
_CONSISTENT_READ_ENDPOINTS = {'reading.get_chapter_editor', 'reading.get_chapter', 'get_segments', 'tts_generate'}


class JobCancelled(GenerationAborted, RuntimeError):
    """Raised at cooperative job boundaries after cached work is persisted."""


def _legacy_job(stored: dict) -> dict:
    """Return the mutable shape consumed by the existing progress helpers."""
    return {
        'job_id': stored['id'],
        'type': stored['type'],
        'book_id': stored.get('book_id'),
        'chapter_id': stored.get('chapter_id'),
        'input': stored.get('input') or {},
        'state': stored['state'],
        'message': stored.get('message') or '',
        'done': int(stored.get('done') or 0),
        'total': int(stored.get('total') or 0),
        'eta_sec': None,
        'elapsed_sec': None,
        't0': None,
        'synth_t0': None,
        'synth_done': 0,
        'result': stored.get('result'),
        'error': stored.get('error'),
    }


def _persist_job(job: dict) -> dict:
    stored = jobs.update_job(
        job['job_id'],
        state=job.get('state', 'running'),
        message=job.get('message') or '',
        done=int(job.get('done') or 0),
        total=int(job.get('total') or 0),
        error=job.get('error'),
        result=job.get('result'),
    )
    return stored


def _close_orphaned_job(job_id: str | None) -> None:
    """Never leave a durable job 'running' after its worker thread exits.

    An active row gates every mutation with 409 until restart, so a runner that
    returned early (or crashed outside its handlers) must still close it.
    """
    if not job_id:
        return
    try:
        stored = jobs.get_job(job_id)
        if stored and stored['state'] in ('pending', 'running'):
            jobs.update_job(
                job_id,
                state='failed',
                error=stored.get('error') or 'A feladat váratlanul leállt.',
                message='A feladat nem fejeződött be',
            )
    except Exception:
        log.exception('Unable to close orphaned job %s', job_id)


def _check_job_cancelled(job: dict | None, *, throttle: bool = False) -> None:
    if job is None:
        return
    if throttle:
        import time

        now = time.monotonic()
        if now - float(job.get('_cancel_checked_at') or 0) < 0.3:
            return
        job['_cancel_checked_at'] = now
    if jobs.is_cancel_requested(job['job_id']):
        raise JobCancelled('Leállítás kérve')


def _active_durable_jobs(*, book_id: int | None = None) -> list[dict]:
    jobs.ensure_jobs()
    return [
        item for item in jobs.list_active_jobs(book_id=book_id)
        if item['state'] in ('pending', 'running')
    ]


def _work_conflict_response():
    """Return a consistent 409 response while the caller owns the gate."""
    if _active_durable_jobs():
        return jsonify({'error': _WORK_BUSY_MESSAGE}), 409
    if _interactive_request_count:
        return jsonify({'error': _INTERACTIVE_BUSY_MESSAGE}), 409
    return None


@app.before_request
def _coordinate_work_request():
    """Reserve interactive work or serialize short database mutations/reads."""
    global _interactive_request_count
    _startup()
    endpoint = request.endpoint
    if endpoint in _INTERACTIVE_ENDPOINTS:
        with _work_dispatch_lock:
            if _active_durable_jobs():
                return jsonify({'error': _WORK_BUSY_MESSAGE}), 409
            _interactive_request_count += 1
            g._auris_interactive_reserved = True
        return None
    if (
        endpoint in _GATED_MUTATION_ENDPOINTS
        or endpoint in _VOICE_MUTATION_ENDPOINTS
        or endpoint in _CONSISTENT_READ_ENDPOINTS
    ):
        _work_dispatch_lock.acquire()
        g._auris_work_gate_held = True
        if endpoint in _GATED_MUTATION_ENDPOINTS or endpoint in _VOICE_MUTATION_ENDPOINTS:
            # Voice instructions/profiles may change while an old interactive
            # render finishes: affected segment rows are deleted, so its late
            # UPDATE becomes a harmless no-op. Bulk jobs must still remain
            # isolated because they own a stable book-wide configuration.
            if endpoint in _VOICE_MUTATION_ENDPOINTS and _active_durable_jobs():
                conflict = jsonify({'error': _WORK_BUSY_MESSAGE}), 409
            else:
                conflict = (
                    None
                    if endpoint in _VOICE_MUTATION_ENDPOINTS
                    else _work_conflict_response()
                )
            if conflict is not None:
                g._auris_work_gate_held = False
                _work_dispatch_lock.release()
                return conflict
    return None


@app.teardown_request
def _release_work_request(_error=None):
    global _interactive_request_count
    if getattr(g, '_auris_interactive_reserved', False):
        with _work_dispatch_lock:
            _interactive_request_count = max(0, _interactive_request_count - 1)
        g._auris_interactive_reserved = False
    if getattr(g, '_auris_work_gate_held', False):
        g._auris_work_gate_held = False
        _work_dispatch_lock.release()


def _export_exclusive_begin() -> None:
    global _export_tts_exclusive
    with _export_tts_exclusive_lock:
        _export_tts_exclusive += 1
        log.info("TTS export-exclusive mode ON (depth=%d)", _export_tts_exclusive)


def _export_exclusive_end() -> None:
    global _export_tts_exclusive
    with _export_tts_exclusive_lock:
        _export_tts_exclusive = max(0, _export_tts_exclusive - 1)
        log.info("TTS export-exclusive mode depth=%d", _export_tts_exclusive)


def _export_exclusive_active() -> bool:
    with _export_tts_exclusive_lock:
        return _export_tts_exclusive > 0


def _get_chapter_build_lock(book_id: int, chapter_id: int) -> threading.Lock:
    key = (book_id, chapter_id)
    with _chapter_build_locks_meta:
        if key not in _chapter_build_locks:
            _chapter_build_locks[key] = threading.Lock()
        return _chapter_build_locks[key]


_interactive_tts_batcher = InteractiveTTSBatcher(
    lambda items, on_item=None: tts.generate_many(items, on_item=on_item),
    collect_ms=75,
    blocked=_export_exclusive_active,
)


VOICE_PREVIEW_TEXT = (
    'Hello. This is a voice preview sample. The afternoon is calm, the room is quiet, '
    'and every word should sound clear, steady, and natural.'
)


# ════════════════════════════════════════════════════════════════════════════
# Startup
# ════════════════════════════════════════════════════════════════════════════

@app.before_request
def _startup():
    global _startup_complete

    if _startup_complete:
        return

    with _startup_lock:
        if _startup_complete:
            return
        try:
            init_db()
            jobs.init_jobs()
            try:
                jobs.prune_finished_jobs()
            except Exception:
                log.exception('Unable to prune old jobs')
            # Old persisted prompts may contain [surprise-oh]/[question-oh],
            # which ask OmniVoice to vocalize an "oh" before the sentence.
            expression_policy_changed = (
                app_settings.migrate_tts_expression_policy_version()
            )
            segment_boundary_policy_changed = (
                app_settings.migrate_tts_segment_boundary_policy_version()
            )
            render_policy_changed = app_settings.migrate_tts_render_policy_version()
            if int(app_settings.get('speaker_segmenter_version', 1) or 1) != enrichment.SEGMENTER_VERSION:
                # Unit numbering changed: move saved speakers to the same text.
                with get_conn() as conn:
                    text_editor.migrate_legacy_annotations(conn)
                app_settings.save({'speaker_segmenter_version': enrichment.SEGMENTER_VERSION})
            if (
                expression_policy_changed or segment_boundary_policy_changed
                or render_policy_changed
            ):
                with get_conn() as conn:
                    conn.execute('DELETE FROM tts_segments')
        except Exception:
            raise
        # Load TTS lazily in the reader/voice studio. The library/import path
        # deliberately leaves VRAM free for a local language model.
        _startup_complete = True


def _default_narrator_instruct() -> str:
    return app_settings.get('narrator_instruct', DEFAULT_NARRATOR_INSTRUCT)


def _book_narrator_instruct(book: dict | None) -> str:
    if not book:
        return _default_narrator_instruct()
    return book.get('narrator_instruct') or _default_narrator_instruct()


def _book_single_narrator_mode(book: dict | None) -> bool:
    if not book:
        return False
    return bool(book.get('single_narrator_mode'))


def _book_narrator_reference(book_id: int) -> tuple[str | None, str | None]:
    try:
        with get_conn() as conn:
            row = conn.execute(
                'SELECT narrator_ref_audio_path, narrator_ref_text FROM books WHERE id=?',
                (book_id,),
            ).fetchone()
    except Exception as exc:
        log.warning('Unable to load narrator reference audio for book %s: %s', book_id, exc)
        return None, None

    if not row:
        return None, None

    data = dict(row)
    path = data.get('narrator_ref_audio_path')
    if not isinstance(path, str) or not path.strip():
        return None, None

    resolved = os.path.abspath(path)
    ref_text = data.get('narrator_ref_text')
    ref_text = ref_text.strip() if isinstance(ref_text, str) and ref_text.strip() else None
    return (resolved, ref_text) if os.path.exists(resolved) else (None, None)


def _book_narrator_ref_audio(book_id: int) -> str | None:
    return _book_narrator_reference(book_id)[0]


def _delete_file_if_exists(path: str | None):
    if not isinstance(path, str) or not path.strip():
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        log.warning('Unable to delete file %s: %s', path, exc)


def _save_reference_upload(file_storage, prefix: str, clean: bool = False) -> str:
    """Store an uploaded reference WAV under a content-addressed name.

    Audio cache keys include the reference path, so a replacement voice must
    never reuse the previous file name; otherwise cached audio of the old voice
    would be returned for the new one. With ``clean`` the file is denoised,
    trimmed and level-matched first (core.reference_audio); the name is taken
    from the stored content either way.
    """
    import hashlib
    from core import reference_audio
    tmp = os.path.join(UPLOAD_DIR, f'.{prefix}.{uuid.uuid4().hex}.upload')
    file_storage.save(tmp)
    cleaned = False
    if clean:
        target = tmp + '.clean.wav'
        if reference_audio.clean_reference(tmp, target)['cleaned']:
            os.replace(target, tmp)
            cleaned = True
    if not cleaned and not str(file_storage.filename or '').lower().endswith('.wav'):
        target = tmp + '.wav'
        if not reference_audio.convert_to_wav(tmp, target):
            _delete_file_if_exists(tmp)
            raise ValueError('A hangfájl nem olvasható be (ffmpeg szükséges a nem WAV formátumokhoz).')
        os.replace(target, tmp)
    return _store_reference_file(tmp, prefix)


def _store_reference_file(tmp: str, prefix: str) -> str:
    """Move a finished reference WAV to its content-addressed upload name."""
    import hashlib
    digest = hashlib.sha256()
    with open(tmp, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    path = os.path.join(UPLOAD_DIR, f'{prefix}_{digest.hexdigest()[:16]}.wav')
    os.replace(tmp, path)
    return path


def _delete_replaced_reference(old_path: str | None, new_path: str | None, prefix: str):
    """Remove a superseded managed reference file, never a profile or foreign file."""
    if not old_path or old_path == new_path:
        return
    try:
        old = Path(old_path).resolve()
        if old.parent != Path(UPLOAD_DIR).resolve():
            return
    except OSError:
        return
    name = old.name
    if name == f'{prefix}.wav' or name.startswith(f'{prefix}_'):
        _delete_file_if_exists(str(old))


def _is_inside_exports(path: str) -> bool:
    """True when ``path`` resolves inside the export directory.

    ``os.path.commonpath`` raises for paths on different Windows drives, so the
    check uses resolved ``Path`` ancestry instead.
    """
    try:
        return Path(path).resolve().is_relative_to(Path(exporter.EXPORTS_DIR).resolve())
    except (OSError, ValueError):
        return False


def _load_book(book_id: int):
    with get_conn() as conn:
        return conn.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()


def _clear_book_tts_segments(book_id: int):
    with get_conn() as conn:
        conn.execute('DELETE FROM tts_segments WHERE book_id=?', (book_id,))


def _compute_segments_for_chapter(
    book_id: int,
    chapter_id: int,
    single_narrator_mode: bool | None = None,
    chapter_override=None, annotation_override=None,
) -> list[dict]:
    with get_conn() as conn:
        ch = conn.execute(
            'SELECT * FROM chapters WHERE id=? AND book_id=?',
            (chapter_id, book_id)
        ).fetchone()
        chars = conn.execute(
            'SELECT * FROM characters WHERE book_id=?',
            (book_id,)
        ).fetchall()
        book = conn.execute(
            'SELECT narrator_instruct, single_narrator_mode, character_analysis_status, '
            'character_analysis_provider '
            'FROM books WHERE id=?',
            (book_id,)
        ).fetchone()
        annotation_rows = conn.execute(
            'SELECT unit_index, speaker_name FROM speaker_annotations '
            'WHERE chapter_id=? ORDER BY unit_index',
            (chapter_id,),
        ).fetchall()

    if chapter_override is not None:
        ch = chapter_override
    if annotation_override is not None:
        annotation_rows = annotation_override
    if not ch:
        return []

    char_map = {r['name']: dict(r) for r in chars}
    use_llm_annotations = bool(annotation_rows) or bool(
        book
        and book['character_analysis_status'] in ('complete', 'partial')
        and book['character_analysis_provider'] == 'llm'
    )
    speaker_annotations = (
        {int(row['unit_index']): row['speaker_name'] for row in annotation_rows}
        if use_llm_annotations else None
    )
    if speaker_annotations is not None:
        speaker_annotations = enrichment.expand_speaker_annotations(
            ch['content'], speaker_annotations
        )
    segs = text_editor.enrich_blocks(
        text_editor.chapter_blocks(ch), char_map,
        _book_narrator_instruct(dict(book) if book else None),
        (_book_single_narrator_mode(dict(book) if book else None)
         if single_narrator_mode is None else single_narrator_mode),
        speaker_annotations,
    )
    from core import experience
    rules = experience.list_rules(book_id)
    for seg in segs:
        seg['enriched_text'] = experience.apply_pronunciation(seg['enriched_text'], book_id, rules=rules)
    return segs


def _build_segments_for_chapter(book_id: int, chapter_id: int) -> list[dict]:
    segs = _compute_segments_for_chapter(book_id, chapter_id)
    if not segs:
        return []
    _store_segments(book_id, chapter_id, segs)
    return segs


def _segments_match_rows(segs: list[dict], rows) -> bool:
    if len(segs) != len(rows):
        return False

    for idx, (seg, row) in enumerate(zip(segs, rows)):
        if row['segment_index'] != idx:
            return False
        if row['text'] != seg['text']:
            return False
        if row['enriched_text'] != seg['enriched_text']:
            return False
        if (row['character_name'] or None) != seg['character_name']:
            return False
        if (row['instruct'] or None) != seg['instruct']:
            return False
        if round(float(row['speed'] or 1.0), 2) != round(float(seg['speed'] or 1.0), 2):
            return False
        if bool(row['is_dialogue']) != bool(seg['is_dialogue']):
            return False
        if row['unit_index'] != seg.get('unit_index'):
            return False
        if bool(row['speaker_candidate']) != bool(seg.get('speaker_candidate')):
            return False
        if bool(row['ends_paragraph']) != bool(seg.get('ends_paragraph')):
            return False
        for field in ('block_index', 'block_kind', 'pause_ms'):
            if row[field] != seg.get(field):
                return False

    return True


def _ensure_chapter_segments(book_id: int, chapter_id: int):
    segs = _compute_segments_for_chapter(book_id, chapter_id)
    if not segs:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? ORDER BY segment_index',
            (book_id, chapter_id)
        ).fetchall()

    if not _segments_match_rows(segs, rows):
        _store_segments(book_id, chapter_id, segs)
        with get_conn() as conn:
            rows = conn.execute(
                'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? ORDER BY segment_index',
                (book_id, chapter_id)
            ).fetchall()

    return rows


_JOB_CACHE_LIMIT = 64


def _prune_job_cache(cache: dict) -> None:
    """Drop the oldest finished in-memory job mirrors; SQLite keeps history."""
    excess = len(cache) - _JOB_CACHE_LIMIT
    if excess <= 0:
        return
    for job_id in [
        key for key, value in cache.items()
        if value.get('state') not in ('pending', 'running')
    ][:excess]:
        cache.pop(job_id, None)
        for chapter_key, mapped in list(_chapter_generation_by_chapter.items()):
            if mapped == job_id:
                _chapter_generation_by_chapter.pop(chapter_key, None)


def _launch_durable_job_unlocked(stored: dict) -> bool:
    """Attach a persisted pending job to its worker without changing its input."""
    global _chapter_generation_active_job_id
    job = _legacy_job(stored)
    job_id = job['job_id']
    payload = job['input']
    job_type = stored['type']
    target = None
    args: tuple = ()
    if job_type == 'generate_chapter':
        book_id = int(payload['book_id'])
        chapter_id = int(payload['chapter_id'])
        with _chapter_generation_lock:
            _prune_job_cache(_chapter_generation_jobs)
            _chapter_generation_jobs[job_id] = job
            _chapter_generation_by_chapter[(book_id, chapter_id)] = job_id
            _chapter_generation_active_job_id = job_id
        target = _run_chapter_generation
        args = (job_id, book_id, chapter_id)
    elif job_type == 'export_chapter':
        _prune_job_cache(_export_jobs)
        _export_jobs[job_id] = job
        from core.export_api import _run_chapter_export
        target = _run_chapter_export
        args = (
            job_id, int(payload['book_id']), int(payload['chapter_id']),
            payload.get('audio_fmt', 'wav'), payload.get('sub_fmt', 'srt'),
        )
    elif job_type == 'export_book':
        _prune_job_cache(_export_jobs)
        _export_jobs[job_id] = job
        from core.export_api import _run_chapterwise_export
        target = _run_chapterwise_export
        args = (
            job_id, int(payload['book_id']), payload.get('audio_fmt', 'wav'),
            payload.get('sub_fmt', 'srt'), list(payload.get('chapter_numbers') or []),
        )
    elif job_type == 'qa_chapter':
        from core.qa_api import run_qa_job
        target = run_qa_job
        args = (
            job_id, int(payload['book_id']), int(payload['chapter_id']),
            bool(payload.get('asr', True)), bool(payload.get('auto_regenerate', True)),
        )
    elif job_type == 'generate_book':
        from core.production_api import run_book_generation
        target = run_book_generation
        args = (job_id, int(payload['book_id']), list(payload['chapter_ids']))
    elif job_type == 'voice_suggestions':
        from core.assist_api import run_voice_suggestions
        target = run_voice_suggestions
        args = (job_id, int(payload['book_id']))
    elif job_type == 'speaker_review':
        from core.assist_api import run_speaker_review
        target = run_speaker_review
        args = (job_id, int(payload['book_id']), list(payload['chapter_ids']))
    elif job_type == 'reanalyze':
        target = _run_reanalysis_job
        args = (job_id, int(payload['book_id']), list(payload['chapter_ids']))
    elif job_type == 'initial_analysis':
        book_id = int(payload['book_id'])
        with get_conn() as conn:
            book = conn.execute(
                'SELECT title, author FROM books WHERE id=?', (book_id,)
            ).fetchone()
            chapters = conn.execute(
                'SELECT id, title, content FROM chapters WHERE book_id=? ORDER BY order_num',
                (book_id,),
            ).fetchall()
        if not book:
            jobs.update_job(
                job_id, state='failed', error='A könyv nem található',
                message='Ez a feladat nem folytatható',
            )
            return False
        data = {
            'title': book['title'], 'author': book['author'],
            'chapters': [dict(chapter) for chapter in chapters],
        }
        target = _detect_characters
        args = (
            book_id, data, payload.get('mode', 'legacy'),
            app_settings.load(), job_id,
        )
    else:
        jobs.update_job(
            job_id, state='failed', error=f'Unsupported job type: {job_type}',
            message='Ez a feladat nem folytatható',
        )
        return False
    threading.Thread(target=target, args=args, daemon=True).start()
    return True


def _launch_durable_job(stored: dict) -> bool:
    """Dispatch one claimed job under the shared work-start gate."""
    with _work_dispatch_lock:
        return _launch_durable_job_unlocked(stored)


@app.route('/api/jobs')
def durable_jobs_list():
    jobs.ensure_jobs()
    book_id = request.args.get('book_id', type=int)
    if request.args.get('state') == 'active':
        return jsonify(jobs.list_active_jobs(book_id=book_id))
    rows = jobs.list_jobs(book_id=book_id)
    limit = request.args.get('limit', type=int)
    return jsonify(rows[:limit] if limit and limit > 0 else rows)


@app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def durable_job_cancel(job_id):
    jobs.ensure_jobs()
    job = jobs.cancel_job(job_id)
    if job is None:
        return jsonify({'error': 'Ismeretlen feladat'}), 404
    return jsonify(job)


@app.route('/api/jobs/<job_id>/resume', methods=['POST'])
def durable_job_resume(job_id):
    jobs.ensure_jobs()
    with _work_dispatch_lock:
        current = jobs.get_job(job_id)
        if current is None:
            return jsonify({'error': 'Ismeretlen feladat'}), 404
        if _active_durable_jobs():
            return jsonify({'error': _WORK_BUSY_MESSAGE}), 409
        if _interactive_request_count:
            return jsonify({'error': _INTERACTIVE_BUSY_MESSAGE}), 409
        try:
            resumed = jobs.resume_job(job_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 409
        _launch_durable_job(resumed)
        return jsonify(jobs.get_job(job_id))


@app.route('/api/jobs/<job_id>/download/<artifact>')
def durable_job_download(job_id, artifact):
    jobs.ensure_jobs()
    job = jobs.get_job(job_id)
    result = (job or {}).get('result') or {}
    key = {
        'audio': 'audio_path',
        'subtitle': 'subtitle_path',
        'export': 'download_path',
    }.get(artifact)
    path = result.get(key) if key else None
    if not isinstance(path, str) or not path:
        return jsonify({'error': 'A feladat eredménye nem található'}), 404
    abs_path = os.path.abspath(path)
    if not _is_inside_exports(abs_path):
        return jsonify({'error': 'Tiltott hozzáférés'}), 403
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'Az eredményfájl hiányzik'}), 404
    return send_file(abs_path, as_attachment=True)


# ════════════════════════════════════════════════════════════════════════════
# Page routes
# ════════════════════════════════════════════════════════════════════════════

@app.route('/')
def library_page():
    return render_template('library.html')


@app.route('/reader/<int:book_id>')
def reader_page(book_id):
    book = _load_book(book_id)
    if not book:
        return 'A könyv nem található', 404
    book_data = dict(book)
    book_data['narrator_instruct'] = _book_narrator_instruct(book_data)
    book_data['single_narrator_mode'] = _book_single_narrator_mode(book_data)
    if not _character_analysis_is_active():
        tts.load_async()
    return render_template('reader.html', book=book_data)


@app.route('/voice-studio/<int:book_id>')
def voice_studio_page(book_id):
    book = _load_book(book_id)
    if not book:
        return 'A könyv nem található', 404
    book_data = dict(book)
    book_data['narrator_instruct'] = _book_narrator_instruct(book_data)
    book_data['single_narrator_mode'] = _book_single_narrator_mode(book_data)
    try:
        requested_chapter_id = int(request.args.get('chapter_id', ''))
    except (TypeError, ValueError):
        requested_chapter_id = None
    with get_conn() as conn:
        current_chapter = None
        if requested_chapter_id is not None:
            current_chapter = conn.execute(
                'SELECT id, title FROM chapters WHERE id=? AND book_id=?',
                (requested_chapter_id, book_id),
            ).fetchone()
        if current_chapter is None:
            current_chapter = conn.execute(
                'SELECT c.id, c.title FROM reading_progress rp '
                'JOIN chapters c ON c.id=rp.chapter_id AND c.book_id=rp.book_id '
                'WHERE rp.book_id=?',
                (book_id,),
            ).fetchone()
        if current_chapter is None:
            current_chapter = conn.execute(
                'SELECT id, title FROM chapters WHERE book_id=? ORDER BY order_num LIMIT 1',
                (book_id,),
            ).fetchone()
    if not _character_analysis_is_active():
        tts.load_async()
    return render_template(
        'voice_studio.html',
        book=book_data,
        current_chapter=dict(current_chapter) if current_chapter else None,
    )


# ════════════════════════════════════════════════════════════════════════════
# Book import
# ════════════════════════════════════════════════════════════════════════════

def _selected_llm_config(config: dict | None = None) -> dict:
    """Resolve the active speaker-analysis provider without losing local settings."""
    config = config or app_settings.load()
    provider = str(config.get('llm_provider') or 'local').strip().lower()
    if provider == 'openai':
        return {
            'provider': 'openai',
            'base_url': 'https://api.openai.com/v1',
            'api_key': str(config.get('openai_api_key') or ''),
            'model': str(config.get('openai_model') or '').strip(),
        }
    return {
        'provider': 'local',
        'base_url': str(config.get('llm_base_url') or '').strip(),
        'api_key': str(config.get('llm_api_key') or ''),
        'model': str(config.get('llm_model') or '').strip(),
    }


def _character_detection_for_import(llm_config: dict) -> tuple[str | None, str | None]:
    """Pick the character-analysis path for a character-voices import.

    A configured language model is used as before. With no local model name set
    (the factory state), the local HuSpaCy/spaCy detection runs instead (no LLM,
    nothing leaves the machine). A model name without a server address, or an
    explicitly chosen OpenAI provider without key/model, still returns an error
    so a broken setting is never silently replaced by the simpler method.
    Returns ``(mode, error)``.
    """
    if llm_config['provider'] == 'openai':
        if not llm_config['api_key']:
            return None, 'Az OpenAI-alapú szereplőfelismeréshez előbb add meg az OpenAI API-kulcsot.'
        if not llm_config['model']:
            return None, 'A szereplőhangokhoz előbb válassz nyelvi modellt a Beállításokban.'
        return 'llm', None
    if not llm_config['model']:
        # The factory setup has a local server address but no model name.
        return 'legacy', None
    if not llm_config['base_url']:
        return None, 'A szereplőhangokhoz előbb add meg a helyi nyelvi modell címét a Beállításokban.'
    return 'llm', None


@app.route('/api/books/import', methods=['POST'])
def import_book():
    if 'file' not in request.files:
        return jsonify({'error': 'Nincs feltöltött fájl'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Üres fájlnév'}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext == 'doc':
        return jsonify({
            'error': 'Ez egy régi .doc fájl. Nyisd meg Wordben, és mentsd .docx formátumban.'
        }), 400
    if ext not in ('epub', 'pdf', 'docx', 'txt', 'prc', 'mobi'):
        return jsonify({'error': f'Nem támogatott formátum: {ext}'}), 400

    detection_config = app_settings.load()
    llm_config = _selected_llm_config(detection_config)
    requested_mode = str(request.form.get('narration_mode') or '').strip().lower()
    if requested_mode == 'single':
        detection_mode = 'none'
        single_narrator_mode = True
    elif requested_mode == 'multi':
        detection_mode, detection_error = _character_detection_for_import(llm_config)
        single_narrator_mode = False
        if detection_error:
            return jsonify({'error': detection_error}), 400
    else:
        # Backwards compatibility for API clients that predate the import dialog.
        detection_mode = str(
            detection_config.get('character_detection_mode', 'legacy') or 'legacy'
        ).lower()
        single_narrator_mode = bool(
            detection_config.get('single_narrator_mode', False)
        )

    original_name = f.filename.replace('\\', '/').rsplit('/', 1)[-1]
    dest = os.path.join(UPLOAD_DIR, f'{uuid.uuid4().hex}_{original_name}')
    f.save(dest)

    try:
        if ext == 'epub':
            data = epub_parser.parse(dest)
        elif ext == 'pdf':
            data = pdf_parser.parse(dest)
        elif ext == 'docx':
            data = docx_parser.parse(dest)
        elif ext in ('prc', 'mobi'):
            data = prc_parser.parse(dest)
        else:
            data = txt_parser.parse(dest)
    except Exception as e:
        _delete_file_if_exists(dest)
        return jsonify({'error': f'A fájl feldolgozása nem sikerült: {e}'}), 500

    from core.parser.structure import attach_blocks
    from core.text_cleanup import clean_parsed_book
    data['chapters'] = attach_blocks(data.get('chapters') or [])
    clean_parsed_book(data)
    parsed_chapters = data.get('chapters') or []
    if not any(str(chapter.get('content') or '').strip() for chapter in parsed_chapters):
        _delete_file_if_exists(dest)
        return jsonify({
            'error': (
                'A dokumentum nem tartalmaz olvasható szöveget. '
                'Aurisba importálás előtt OCR szükséges.'
            )
        }), 400
    chapters = [
        chapter for chapter in structure.enrich_chapters(parsed_chapters)
        if str(chapter.get('content') or '').strip()
    ]
    if not chapters:
        _delete_file_if_exists(dest)
        return jsonify({
            'error': 'Nem található importálható fejezet; előzetes OCR szükséges.'
        }), 400

    analysis_status = (
        'queued' if detection_mode == 'llm'
        else 'skipped' if detection_mode == 'none'
        else 'running'
    )

    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO books (title, author, file_path, file_type, cover_b64, language, '
            'single_narrator_mode, total_chapters, character_analysis_status, '
            'character_analysis_provider, character_analysis_model) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (data['title'], data['author'], dest, ext,
             data.get('cover_b64'), data.get('language', 'en'),
             int(single_narrator_mode), len(chapters),
             analysis_status, detection_mode,
             llm_config['model'] if detection_mode == 'llm'
             else 'single narrator' if detection_mode == 'none'
             else 'spaCy/regex')
        )
        book_id = cur.lastrowid

        for ch in chapters:
            conn.execute(
                'INSERT INTO chapters (book_id, title, order_num, section_type, content, word_count, blocks_json) '
                'VALUES (?,?,?,?,?,?,?)',
                (book_id, ch['title'], ch['order_num'], ch.get('section_type', 'chapter'),
                 ch['content'], ch['word_count'], json.dumps(ch.get('blocks'), ensure_ascii=False) if ch.get('blocks') else None)
            )

    if detection_mode == 'none':
        analysis_job_id = None
        _set_character_analysis_status(
            book_id,
            'skipped',
            'Egy narrátor van kiválasztva, szereplőelemzés nélkül.',
        )
    else:
        # The durable record is committed before its worker thread can start.
        analysis_job_id = _detect_characters(
            book_id, data, detection_mode, detection_config
        )

    return jsonify({
        'book_id': book_id,
        'title': data['title'],
        'chapters': len(chapters),
        'analysis_status': analysis_status,
        'analysis_job_id': analysis_job_id,
        'narration_mode': 'single' if single_narrator_mode else 'multi',
    })


def _detect_characters(
    book_id: int,
    data: dict,
    mode: str | None = None,
    config: dict | None = None,
    job_id: str | None = None,
):
    config = config or app_settings.load()
    mode = str(
        mode or config.get('character_detection_mode', 'legacy') or 'legacy'
    ).lower()
    if job_id is None:
        jobs.ensure_jobs()
        with _work_dispatch_lock:
            conflict = _work_conflict_response()
            if conflict is not None:
                raise RuntimeError(
                    _WORK_BUSY_MESSAGE if _active_durable_jobs()
                    else _INTERACTIVE_BUSY_MESSAGE
                )
            stored = jobs.create_job(
                'initial_analysis',
                {'book_id': book_id, 'mode': mode},
                book_id=book_id,
                total=len(data.get('chapters') or []),
            )
            _launch_durable_job(stored)
            return stored['id']
    analysis_job = _legacy_job(jobs.get_job(job_id))
    analysis_job.update(state='running', message='Szereplőelemzés előkészítése…')
    _persist_job(analysis_job)
    if mode != 'llm':
        try:
            _check_job_cancelled(analysis_job)
            full_text = ' '.join(ch['content'] for ch in data['chapters'])
            chars = char_module.extract_characters(
                full_text, top_n=20, language=data.get('language')
            )
            _store_character_analysis(
                book_id, chars, [], 'complete',
                f'A szereplőfelismerés kész (nyelvi modell nélkül): {len(chars)} szereplő.'
            )
            analysis_job.update(
                state='complete', done=len(data.get('chapters') or []),
                message='A szereplőfelismerés kész.', result={'book_id': book_id},
            )
            _persist_job(analysis_job)
        except JobCancelled:
            jobs.mark_cancelled(job_id, 'A szereplőelemzés leállítva')
        except Exception as exc:
            _set_character_analysis_status(book_id, 'failed', str(exc))
            analysis_job.update(state='failed', error=str(exc), message='Az elemzés nem sikerült')
            _persist_job(analysis_job)
        return

    llm_config = _selected_llm_config(config)
    uses_local_llm = llm_config['provider'] == 'local'
    if uses_local_llm:
        _character_analysis_reserve()
        tts.unload()
    try:
        with _character_analysis_lock:
            if uses_local_llm and not tts.wait_until_unloaded(timeout=600):
                raise RuntimeError(
                    'Lejárt a várakozás: a beszédmotor nem szabadította fel a videomemóriát.'
                )
            _set_character_analysis_status(
                book_id,
                'running',
                'Kapcsolódás a helyi nyelvi modellhez…'
                if uses_local_llm else 'Kapcsolódás az OpenAI-hoz…',
            )
            with get_conn() as conn:
                rows = conn.execute(
                    'SELECT id, title, content FROM chapters '
                    'WHERE book_id=? ORDER BY order_num',
                    (book_id,),
                ).fetchall()
            parsed_chapters = [dict(row) for row in rows]

            def progress(current: int, total: int, chapter_title: str):
                _check_job_cancelled(analysis_job)
                _set_character_analysis_status(
                    book_id,
                    'running',
                    f'Fejezet elemzése ({current}/{total}): {chapter_title}',
                )
                analysis_job.update(
                    done=max(0, current - 1), total=total,
                    message=f'Fejezet elemzése ({current}/{total}): {chapter_title}',
                )
                _persist_job(analysis_job)

            result = llm_characters.analyze_book(
                title=str(data.get('title') or ''),
                author=str(data.get('author') or ''),
                chapters=parsed_chapters,
                base_url=llm_config['base_url'],
                api_key=llm_config['api_key'],
                model=llm_config['model'],
                timeout=float(config.get('llm_timeout_sec', 600)),
                max_tokens=int(config.get('llm_max_output_tokens', 8192)),
                max_characters=int(config.get('llm_max_characters', 60)),
                batch_chars=int(config.get('llm_batch_chars', 10000)),
                progress=progress,
                provider=llm_config['provider'],
            )
            failed_batches = len(result.get('errors') or [])
            final_status = 'partial' if failed_batches else 'complete'
            message = (
                f"{'Részben kész' if failed_batches else 'Kész'}: "
                f"{len(result['characters'])} szereplő, "
                f"{len(result['annotations'])} beszélőhöz rendelt párbeszédrész."
            )
            if failed_batches:
                message += (f" {failed_batches} fejezetcsomag elemzése nem sikerült; "
                            "a részletek a szervernaplóban.")
            _store_character_analysis(
                book_id,
                result['characters'],
                result['annotations'],
                final_status,
                message,
            )
            analysis_job.update(
                state='complete', done=len(parsed_chapters), total=len(parsed_chapters),
                message=message,
                result={'book_id': book_id, 'failed_batches': failed_batches},
            )
            _persist_job(analysis_job)
    except JobCancelled:
        jobs.mark_cancelled(job_id, 'A szereplőelemzés leállítva az aktuális csomag után')
    except Exception as exc:
        log.exception('LLM character analysis failed for book %s', book_id)
        _set_character_analysis_status(book_id, 'failed', str(exc))
        analysis_job.update(state='failed', error=str(exc), message='Az elemzés nem sikerült')
        _persist_job(analysis_job)
    finally:
        _close_orphaned_job(job_id)
        if uses_local_llm:
            _character_analysis_release()


def _character_analysis_reserve() -> None:
    global _character_analysis_pending
    with _character_analysis_state_lock:
        _character_analysis_pending += 1


def _character_analysis_release() -> None:
    global _character_analysis_pending
    with _character_analysis_state_lock:
        _character_analysis_pending = max(0, _character_analysis_pending - 1)


def _character_analysis_is_active() -> bool:
    with _character_analysis_state_lock:
        return _character_analysis_pending > 0


def _set_character_analysis_status(book_id: int, status: str, message: str) -> None:
    with get_conn() as conn:
        conn.execute(
            'UPDATE books SET character_analysis_status=?, character_analysis_message=?, '
            "character_analysis_updated_at=datetime('now') WHERE id=?",
            (status, str(message or '')[:1000], book_id),
        )


def _store_character_analysis(
    book_id: int,
    chars: list[dict],
    annotations: list[dict],
    status: str,
    message: str,
) -> None:
    with get_conn() as conn:
        # Human decisions are durable overrides: re-running the automatic
        # analysis must not erase either a corrected assignment or an explicit
        # "this is narration" decision.
        conn.execute(
            "DELETE FROM speaker_annotations "
            "WHERE book_id=? AND COALESCE(source, 'automatic') <> 'manual'",
            (book_id,),
        )
        conn.execute(
            "DELETE FROM characters WHERE book_id=? AND name NOT IN ("
            "SELECT speaker_name FROM speaker_annotations "
            "WHERE book_id=? AND source='manual' AND speaker_name <> ''"
            ")",
            (book_id, book_id),
        )
        conn.execute('DELETE FROM tts_segments WHERE book_id=?', (book_id,))
        for ch in chars:
            conn.execute(
                'INSERT INTO characters '
                '(book_id, name, gender, frequency, instruct, color_hex) '
                'VALUES (?,?,?,?,?,?) '
                'ON CONFLICT(book_id, name) DO NOTHING',
                (
                    book_id, ch['name'], ch['gender'], ch['frequency'],
                    ch['instruct'], ch['color_hex'],
                ),
            )
        for annotation in annotations:
            conn.execute(
                'INSERT INTO speaker_annotations '
                '(book_id, chapter_id, unit_index, unit_text, speaker_name, '
                'confidence, source) VALUES (?,?,?,?,?,?,?) '
                'ON CONFLICT(chapter_id, unit_index) DO NOTHING',
                (
                    book_id, annotation['chapter_id'], annotation['unit_index'],
                    annotation['unit_text'], annotation['speaker_name'],
                    annotation['confidence'], 'automatic',
                ),
            )
        conn.execute(
            'UPDATE characters SET frequency=('
            'SELECT COUNT(*) FROM speaker_annotations a '
            'WHERE a.book_id=characters.book_id '
            'AND a.speaker_name=characters.name COLLATE NOCASE'
            ') WHERE book_id=?',
            (book_id,),
        )
        conn.execute(
            'UPDATE books SET character_analysis_status=?, character_analysis_message=?, '
            "character_analysis_updated_at=datetime('now') WHERE id=?",
            (status, message, book_id),
        )


def _capture_position_anchors(book_id: int, chapter_id: int) -> dict:
    with get_conn() as conn:
        segments = conn.execute(
            'SELECT segment_index, text FROM tts_segments '
            'WHERE book_id=? AND chapter_id=? ORDER BY segment_index',
            (book_id, chapter_id),
        ).fetchall()
        progress = conn.execute(
            'SELECT position FROM reading_progress WHERE book_id=? AND chapter_id=?',
            (book_id, chapter_id),
        ).fetchone()
        bookmarks = conn.execute(
            'SELECT id, segment_index, text_excerpt FROM bookmarks '
            'WHERE book_id=? AND chapter_id=?',
            (book_id, chapter_id),
        ).fetchall()
    by_index = {int(row['segment_index']): row['text'] for row in segments}
    return {
        'progress_text': by_index.get(int(progress['position'])) if progress else None,
        'bookmarks': [
            (row['id'], row['text_excerpt'] or by_index.get(int(row['segment_index'])))
            for row in bookmarks
        ],
    }


def _best_segment_index(segments: list[dict], text: str | None) -> int | None:
    needle = ' '.join(str(text or '').casefold().split())
    if not needle:
        return None
    for index, segment in enumerate(segments):
        candidate = ' '.join(str(segment.get('text') or '').casefold().split())
        if needle == candidate or needle in candidate or candidate in needle:
            return index
    return None


def _store_reanalysis_chapter(
    book_id: int,
    chapter_id: int,
    chars: list[dict],
    annotations: list[dict],
) -> None:
    """Replace automatic chapter analysis while preserving human voice choices."""
    anchors = _capture_position_anchors(book_id, chapter_id)
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM speaker_annotations WHERE book_id=? AND chapter_id=? "
            "AND COALESCE(source, 'automatic') <> 'manual'",
            (book_id, chapter_id),
        )
        for character in chars:
            conn.execute(
                'INSERT INTO characters '
                '(book_id, name, gender, frequency, instruct, color_hex) '
                'VALUES (?,?,?,?,?,?) ON CONFLICT(book_id, name) DO NOTHING',
                (
                    book_id, character['name'], character.get('gender', 'unknown'),
                    int(character.get('frequency') or 0), character.get('instruct'),
                    character.get('color_hex'),
                ),
            )
        for annotation in annotations:
            if int(annotation.get('chapter_id') or chapter_id) != chapter_id:
                continue
            conn.execute(
                'INSERT INTO speaker_annotations '
                '(book_id, chapter_id, unit_index, unit_text, speaker_name, confidence, source) '
                "VALUES (?,?,?,?,?,?,'automatic') "
                'ON CONFLICT(chapter_id, unit_index) DO NOTHING',
                (
                    book_id, chapter_id, annotation['unit_index'],
                    annotation['unit_text'], annotation['speaker_name'],
                    annotation.get('confidence', 1.0),
                ),
            )
        conn.execute(
            'UPDATE characters SET frequency=('
            'SELECT COUNT(*) FROM speaker_annotations a '
            'WHERE a.book_id=characters.book_id '
            'AND a.speaker_name=characters.name COLLATE NOCASE) WHERE book_id=?',
            (book_id,),
        )
        conn.execute(
            'DELETE FROM tts_segments WHERE book_id=? AND chapter_id=?',
            (book_id, chapter_id),
        )

    rebuilt = _compute_segments_for_chapter(book_id, chapter_id)
    if rebuilt:
        _store_segments(book_id, chapter_id, rebuilt)
    with get_conn() as conn:
        progress_index = _best_segment_index(rebuilt, anchors['progress_text'])
        if progress_index is not None:
            conn.execute(
                'UPDATE reading_progress SET position=?, updated_at=datetime(\'now\') '
                'WHERE book_id=? AND chapter_id=?',
                (progress_index, book_id, chapter_id),
            )
        for bookmark_id, text in anchors['bookmarks']:
            bookmark_index = _best_segment_index(rebuilt, text)
            if bookmark_index is not None:
                conn.execute(
                    'UPDATE bookmarks SET segment_index=? WHERE id=? AND book_id=?',
                    (bookmark_index, bookmark_id, book_id),
                )


def _run_reanalysis_job(job_id: str, book_id: int, chapter_ids: list[int]) -> None:
    job = _legacy_job(jobs.get_job(job_id))
    config = app_settings.load()
    llm_config = _selected_llm_config(config)
    uses_local_llm = llm_config['provider'] == 'local'
    failures: list[dict] = []
    if uses_local_llm:
        _character_analysis_reserve()
        tts.unload()
    try:
        job.update(state='running', total=len(chapter_ids), message='Újraelemzés előkészítése…')
        _persist_job(job)
        with _character_analysis_lock:
            if uses_local_llm and not tts.wait_until_unloaded(timeout=600):
                raise RuntimeError('Timed out waiting for the TTS model to release VRAM.')
            with get_conn() as conn:
                book = conn.execute(
                    'SELECT title, author FROM books WHERE id=?', (book_id,)
                ).fetchone()
                chapter_rows = conn.execute(
                    'SELECT id, title, content FROM chapters WHERE book_id=? '
                    f"AND id IN ({','.join('?' for _ in chapter_ids)}) ORDER BY order_num",
                    (book_id, *chapter_ids),
                ).fetchall()
            for row in chapter_rows:
                _check_job_cancelled(job)
                chapter = dict(row)
                jobs.set_chapter_analysis_state(book_id, chapter['id'], 'running', None)
                job['message'] = f"Elemzés: {chapter['title']}"
                _persist_job(job)
                try:
                    result = llm_characters.analyze_book(
                        title=book['title'], author=book['author'], chapters=[chapter],
                        base_url=llm_config['base_url'], api_key=llm_config['api_key'],
                        model=llm_config['model'],
                        timeout=float(config.get('llm_timeout_sec', 600)),
                        max_tokens=int(config.get('llm_max_output_tokens', 8192)),
                        max_characters=int(config.get('llm_max_characters', 60)),
                        batch_chars=int(config.get('llm_batch_chars', 10000)),
                        provider=llm_config['provider'],
                    )
                    if result.get('errors'):
                        raise RuntimeError(result['errors'][0].get('message') or 'Az elemzés nem sikerült')
                    _store_reanalysis_chapter(
                        book_id, chapter['id'], result['characters'], result['annotations']
                    )
                    jobs.set_chapter_analysis_state(book_id, chapter['id'], 'complete', None)
                except Exception as exc:
                    log.exception('Chapter reanalysis failed for book %s chapter %s', book_id, chapter['id'])
                    jobs.set_chapter_analysis_state(book_id, chapter['id'], 'failed', str(exc))
                    failures.append({'chapter_id': chapter['id'], 'error': str(exc)})
                job['done'] += 1
                _persist_job(job)
                _check_job_cancelled(job)
        status = 'partial' if failures else 'complete'
        message = (
            f'Az újraelemzés elkészült; {len(failures)} fejezet hibás.'
            if failures else 'Az újraelemzés elkészült.'
        )
        _set_character_analysis_status(book_id, status, message)
        job.update(
            state='complete', message=message,
            result={'book_id': book_id, 'failed_chapters': failures}, error=None,
        )
        _persist_job(job)
    except JobCancelled:
        jobs.mark_cancelled(job_id, 'Újraelemzés leállítva az aktuális fejezet után')
    except Exception as exc:
        log.exception('Reanalysis job %s failed', job_id)
        job.update(state='failed', error=str(exc), message='Az újraelemzés nem sikerült')
        _persist_job(job)
    finally:
        _close_orphaned_job(job_id)
        if uses_local_llm:
            _character_analysis_release()


# ════════════════════════════════════════════════════════════════════════════
# Library API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books')
def list_books():
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT b.id, b.title, b.author, b.language, b.file_type, b.cover_b64, b.added_at, '
            'b.last_read, b.total_chapters, b.character_analysis_status, '
            'b.character_analysis_message, b.character_analysis_provider, '
            'b.character_analysis_model, b.collection, b.series, b.reading_state, '
            'b.source_url, rp.chapter_id AS progress_chapter_id, '
            'rp.position AS progress_position, c.title AS progress_chapter_title '
            'FROM books b '
            'LEFT JOIN reading_progress rp ON rp.book_id = b.id '
            'LEFT JOIN chapters c ON c.id = rp.chapter_id '
            'ORDER BY COALESCE(b.last_read, b.added_at) DESC, b.added_at DESC'
        ).fetchall()
    stats: dict[int, list] = {}
    if request.args.get('include') == 'stats':
        # One aggregate query instead of one /chapters request per book.
        with get_conn() as conn:
            for row in conn.execute(
                'SELECT c.book_id, c.id, c.order_num, COUNT(s.id) AS audio_total, '
                'COALESCE(SUM(CASE WHEN s.audio_path IS NOT NULL THEN 1 ELSE 0 END), 0) AS audio_ready '
                'FROM chapters c LEFT JOIN tts_segments s ON s.chapter_id=c.id AND s.book_id=c.book_id '
                'GROUP BY c.book_id, c.id, c.order_num ORDER BY c.book_id, c.order_num'
            ):
                stats.setdefault(row['book_id'], []).append(
                    {'id': row['id'], 'audio_total': row['audio_total'], 'audio_ready': row['audio_ready']}
                )
    books = []
    for r in rows:
        d = dict(r)
        if d['cover_b64']:
            d['cover_url'] = f'/api/books/{d["id"]}/cover'
            d.pop('cover_b64')
        else:
            d['cover_url'] = None
        if stats:
            d['chapter_stats'] = stats.get(d['id'], [])
        books.append(d)
    return jsonify(books)


@app.route('/api/books/<int:book_id>/character-analysis')
def character_analysis_status(book_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT character_analysis_status AS status, '
            'character_analysis_message AS message, '
            'character_analysis_provider AS provider, '
            'character_analysis_model AS model, '
            'character_analysis_updated_at AS updated_at, '
            '(SELECT COUNT(*) FROM characters c WHERE c.book_id=books.id) '
            'AS character_count, '
            "(SELECT COUNT(*) FROM speaker_annotations a "
            "WHERE a.book_id=books.id AND a.speaker_name <> '') "
            'AS dialogue_count '
            'FROM books WHERE id=?',
            (book_id,),
        ).fetchone()
    if not row:
        return jsonify({'error': 'A könyv nem található'}), 404
    return jsonify(dict(row))


@app.route('/api/books/<int:book_id>/reanalyze', methods=['POST'])
def reanalyze_book(book_id):
    jobs.ensure_jobs()
    body = request.get_json(silent=True) or {}
    requested = body.get('chapter_ids')
    failed_only = bool(body.get('failed_only', False))
    if requested is not None and not isinstance(requested, list):
        return jsonify({'error': 'chapter_ids must be an array'}), 400
    try:
        requested_ids = [int(value) for value in requested] if requested is not None else None
    except (TypeError, ValueError):
        return jsonify({'error': 'chapter_ids must contain integers'}), 400

    with get_conn() as conn:
        book = conn.execute('SELECT id FROM books WHERE id=?', (book_id,)).fetchone()
        rows = conn.execute(
            'SELECT id FROM chapters WHERE book_id=? ORDER BY order_num', (book_id,)
        ).fetchall()
    if not book:
        return jsonify({'error': 'A könyv nem található'}), 404
    existing_ids = [int(row['id']) for row in rows]
    if requested_ids is not None and not set(requested_ids).issubset(existing_ids):
        return jsonify({'error': 'Egy vagy több fejezet nem ehhez a könyvhöz tartozik'}), 400
    selected = requested_ids if requested_ids is not None else existing_ids
    if failed_only:
        failed = set(jobs.failed_chapter_ids(book_id))
        selected = [chapter_id for chapter_id in selected if chapter_id in failed]
    selected = list(dict.fromkeys(selected))
    if not selected:
        return jsonify({'error': 'Nincs újraelemzésre kijelölt vagy hibás fejezet'}), 400

    config = app_settings.load()
    llm_config = _selected_llm_config(config)
    if not llm_config['base_url'] or not llm_config['model']:
        return jsonify({'error': 'Az újraelemzéshez előbb állíts be nyelvi modellt.'}), 400
    if llm_config['provider'] == 'openai' and not llm_config['api_key']:
        return jsonify({'error': 'Az OpenAI-elemzéshez API-kulcs szükséges.'}), 400
    with _work_dispatch_lock:
        conflict = _work_conflict_response()
        if conflict is not None:
            return conflict
        stored = jobs.create_job(
            'reanalyze',
            {'book_id': book_id, 'chapter_ids': selected, 'failed_only': failed_only},
            book_id=book_id,
            total=len(selected),
        )
        _launch_durable_job(stored)
        return jsonify(stored), 202


@app.route('/api/books/<int:book_id>/cover')
def book_cover(book_id):
    with get_conn() as conn:
        row = conn.execute('SELECT cover_b64, file_type FROM books WHERE id=?', (book_id,)).fetchone()
    if not row or not row['cover_b64']:
        return '', 204
    img_bytes = base64.b64decode(row['cover_b64'])
    if img_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        media_type = 'image/png'
    elif img_bytes.startswith((b'GIF87a', b'GIF89a')):
        media_type = 'image/gif'
    elif img_bytes.startswith(b'BM'):
        media_type = 'image/bmp'
    else:
        media_type = 'image/jpeg'
    return app.response_class(img_bytes, mimetype=media_type)


@app.route('/api/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    # Keep the legacy DELETE URL, but use the storage-aware removal path so
    # completed export downloads and their title snapshot remain available.
    from core.experience_api import remove_book
    return remove_book(book_id)


# Language codes accepted for a book: "en", "hu", "ro", or a regional form
# such as "zh-cn". Deliberately permissive, because the value is passed
# through to the TTS engine and no whitelist of supported languages exists.
_BOOK_LANGUAGE_RE = re.compile(r'^[a-z]{2}(-[a-z]{2,4})?$')


@app.route('/api/books/<int:book_id>', methods=['PUT'])
def update_book(book_id):
    body = request.get_json(force=True) or {}
    # A fixed-order tuple, not a set: iteration order feeds directly into the
    # 400 error message below, and a set's order is not guaranteed, so which
    # field got named would vary between runs when a body carries more than
    # one non-string value.
    allowed = ('title', 'author', 'language')
    # The whitelist is a security boundary as well as a filter: file_path and
    # file_type live in the same row and must not be settable from a request.
    updates = {}
    for key in allowed:
        if key not in body:
            continue
        value = body[key]
        # Reject non-string JSON types rather than coercing them. A number, a
        # list or an object would otherwise be written into the column as its
        # Python repr, and a numeric 0 would silently become an empty string.
        if not isinstance(value, str):
            return jsonify({'error': f'{key} must be text.'}), 400
        updates[key] = value.strip()
    if not updates:
        return jsonify({'error': 'Nincs mit módosítani'}), 400

    if 'title' in updates and not updates['title']:
        return jsonify({'error': 'A cím nem lehet üres'}), 400
    if 'author' in updates and not updates['author']:
        updates['author'] = 'Unknown Author'
    if 'language' in updates:
        updates['language'] = updates['language'].lower()
        if not _BOOK_LANGUAGE_RE.match(updates['language']):
            return jsonify({
                'error': 'A nyelv kódja legyen például hu, en, ro vagy zh-cn.'
            }), 400

    with get_conn() as conn:
        book = conn.execute(
            'SELECT language FROM books WHERE id=?', (book_id,)
        ).fetchone()
        if not book:
            return jsonify({'error': 'A könyv nem található'}), 404
        # Language is part of the audio cache key, but an already-generated
        # segment is served from disk without being re-keyed, so a language
        # change has to discard the cached audio or the book keeps its old
        # pronunciation forever. A title or author edit changes nothing audible.
        #
        # Compare normalized values. Stored languages are not guaranteed
        # lowercase: the EPUB parser writes the raw dc:language prefix, so a
        # book can hold "EN" while the submitted value is always lowercased.
        # Without this, a title-only edit that echoes the language back would
        # look like a change and would discard every generated segment.
        stored_language = (book['language'] or '').strip().lower()
        language_changed = (
            'language' in updates and updates['language'] != stored_language
        )
        set_clause = ', '.join(f'{k}=?' for k in updates)
        conn.execute(
            f'UPDATE books SET {set_clause} WHERE id=?',
            (*updates.values(), book_id),
        )

    if language_changed:
        _clear_book_tts_segments(book_id)

    return jsonify({'ok': True, 'segments_cleared': language_changed})


# ════════════════════════════════════════════════════════════════════════════
# Chapter API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books/<int:book_id>/chapters')
def list_chapters(book_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT c.id, c.title, c.order_num, c.section_type, c.word_count, '
            'COUNT(s.id) AS audio_total, '
            'COALESCE(SUM(CASE WHEN s.audio_path IS NOT NULL THEN 1 ELSE 0 END), 0) '
            'AS audio_ready '
            'FROM chapters c '
            'LEFT JOIN tts_segments s ON s.chapter_id=c.id AND s.book_id=c.book_id '
            'WHERE c.book_id=? '
            'GROUP BY c.id, c.title, c.order_num, c.section_type, c.word_count '
            'ORDER BY c.order_num',
            (book_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


def _editor_payload(chapter):
    return {'title': chapter['title'], 'blocks': text_editor.chapter_blocks(chapter),
            'revision': chapter['text_revision'] or 0,
            'can_restore': bool(chapter['previous_text_json']),
            'speed_supported': _engine_supports_speed()}


def _engine_supports_speed() -> bool:
    from core.local_engines import ENGINE_INFO
    engine = app_settings.get('tts_engine', 'omnivoice')
    if engine == 'higgs':
        return app_settings.get('higgs_prompt_mode', 'raw') != 'raw'
    return bool(ENGINE_INFO.get(engine, {}).get('speed', True))




def _save_editor(book_id, chapter_id, restore=False):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Érvénytelen szerkesztési kérés.'}), 400
    with _get_chapter_build_lock(book_id, chapter_id):
        with get_conn() as conn:
            chapter = conn.execute('SELECT * FROM chapters WHERE id=? AND book_id=?',
                                   (chapter_id, book_id)).fetchone()
            old_annotations = [dict(r) for r in conn.execute(
                'SELECT * FROM speaker_annotations WHERE chapter_id=? AND book_id=? ORDER BY unit_index',
                (chapter_id, book_id))]
        if chapter is None:
            return jsonify({'error': 'A fejezet nem található.'}), 404
        revision = body.get('revision')
        if type(revision) is not int or revision != (chapter['text_revision'] or 0):
            return jsonify({'error': 'A fejezet közben megváltozott. Nyisd meg újra a szerkesztőt; a mostani módosításaid még nem kerültek mentésre.'}), 409
        try:
            target = body
            if restore:
                if not chapter['previous_text_json']:
                    return jsonify({'error': 'Nincs visszaállítható változat.'}), 409
                target = json.loads(chapter['previous_text_json'])
            title = target.get('title')
            if not isinstance(title, str) or not title.strip() or len(title) > 500:
                raise ValueError('A fejezetcím 1–500 karakter lehet.')
            blocks = text_editor.validate_blocks(target.get('blocks'))
        except (ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400
        content = text_editor.content_of(blocks)
        if (not restore and title.strip() == chapter['title']
                and blocks == text_editor.chapter_blocks(chapter)):
            return jsonify(_editor_payload(chapter))
        mapping = text_editor.unit_mapping(chapter['content'], content)
        new_units = enrichment.build_speaker_units(content)
        annotations = []
        for old in old_annotations:
            index = mapping.get(old['unit_index'])
            if index is not None:
                annotations.append({**old, 'unit_index': index, 'unit_text': new_units[index]['text']})
        if restore and 'annotations' in target:
            annotations = target['annotations']
        prospective = {**dict(chapter), 'title': title.strip(), 'content': content,
                       'blocks_json': json.dumps(blocks, ensure_ascii=False)}
        rebuilt = _compute_segments_for_chapter(book_id, chapter_id,
                    chapter_override=prospective, annotation_override=annotations)
        if not rebuilt:
            return jsonify({'error': 'A fejezet nem tartalmaz felolvasható szöveget.'}), 400
        anchors = _capture_position_anchors(book_id, chapter_id)
        with get_conn() as conn:
            old_segments = conn.execute('SELECT text FROM tts_segments WHERE book_id=? AND chapter_id=? ORDER BY segment_index', (book_id, chapter_id)).fetchall()
            old_progress = conn.execute('SELECT position FROM reading_progress WHERE book_id=? AND chapter_id=?', (book_id, chapter_id)).fetchone()
            old_bookmarks = {r['id']: r['segment_index'] for r in conn.execute('SELECT id,segment_index FROM bookmarks WHERE book_id=? AND chapter_id=?', (book_id, chapter_id))}
        positions = text_editor.position_mapping(old_segments, rebuilt)
        previous = {**_editor_payload(chapter), 'annotations': old_annotations}
        with get_conn() as conn:
            updated = conn.execute('UPDATE chapters SET title=?,content=?,word_count=?,blocks_json=?, '
                         'text_revision=COALESCE(text_revision,0)+1,previous_text_json=? WHERE id=? AND book_id=? '
                         'AND COALESCE(text_revision,0)=?',
                         (prospective['title'], content, len(content.split()), prospective['blocks_json'],
                          json.dumps(previous, ensure_ascii=False), chapter_id, book_id, revision))
            if updated.rowcount != 1:
                return jsonify({'error': 'A fejezet közben megváltozott. Nyisd meg újra a szerkesztőt.'}), 409
            conn.execute('DELETE FROM speaker_annotations WHERE chapter_id=? AND book_id=?', (chapter_id, book_id))
            for annotation in annotations:
                conn.execute('INSERT INTO speaker_annotations '
                    '(book_id,chapter_id,unit_index,unit_text,speaker_name,confidence,source) VALUES(?,?,?,?,?,?,?)',
                    (book_id,chapter_id,annotation['unit_index'],annotation['unit_text'],
                     annotation['speaker_name'],annotation['confidence'],annotation['source']))
            _store_segments(book_id, chapter_id, rebuilt, connection=conn)
            position = positions.get(old_progress['position']) if old_progress else None
            if position is None:
                position = _best_segment_index(rebuilt, anchors['progress_text'])
            conn.execute("UPDATE reading_progress SET position=?,offset_sec=0,cache_key='',"
                         "updated_at=datetime('now') WHERE book_id=? AND chapter_id=?",
                         (position or 0, book_id, chapter_id))
            for bookmark_id, excerpt in anchors['bookmarks']:
                index = positions.get(old_bookmarks.get(bookmark_id))
                if index is None:
                    index = _best_segment_index(rebuilt, excerpt)
                conn.execute('UPDATE bookmarks SET segment_index=? WHERE id=? AND book_id=?',
                             (index or 0, bookmark_id, book_id))
            conn.execute('UPDATE characters SET frequency=(SELECT COUNT(*) FROM speaker_annotations a '
                         'WHERE a.book_id=characters.book_id AND a.speaker_name=characters.name) WHERE book_id=?', (book_id,))
            result = conn.execute('SELECT * FROM chapters WHERE id=?', (chapter_id,)).fetchone()
        return jsonify({**_editor_payload(result), 'annotations_removed': len(old_annotations) - len(annotations)})
















# ════════════════════════════════════════════════════════════════════════════
# Characters API
# ════════════════════════════════════════════════════════════════════════════





















# ════════════════════════════════════════════════════════════════════════════
# TTS API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/tts/status')
def tts_status():
    if _character_analysis_is_active():
        return jsonify({
            'state': 'paused',
            'message': 'A szereplőelemzés idejére a beszédmotor ki van töltve a videomemóriából.',
        })
    status = tts.status()
    if status.get('state') == 'not_loaded':
        tts.load_async()
        status = {**status, 'state': 'loading'}
    return jsonify(status)


@app.route('/api/tts/load', methods=['POST'])
def tts_load():
    if _character_analysis_is_active():
        return jsonify({
            'ok': False,
            'error': 'Szereplőelemzés fut; a beszédmotor a videomemória védelmében addig nem töltődik be.',
        }), 409
    tts.load_async()
    return jsonify({'ok': True})


@app.route('/api/tts/cancel', methods=['POST'])
def tts_cancel():
    return jsonify({'ok': True, 'cancel_requested': tts.cancel()})


@app.route('/api/tts/generate', methods=['POST'])
def tts_generate():
    body = request.get_json(force=True)
    book_id = body.get('book_id')
    chapter_id = body.get('chapter_id')
    segment_index = body.get('segment_index', 0)
    playback_priority = bool(body.get('playback_priority', False))

    status = tts.status()
    if status['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen', 'status': status}), 503

    with get_conn() as conn:
        seg = conn.execute(
            'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? AND segment_index=?',
            (book_id, chapter_id, segment_index)
        ).fetchone()
        book = conn.execute('SELECT language FROM books WHERE id=?', (book_id,)).fetchone()

    language = book['language'] if book and book['language'] else None

    if not seg:
        ch_lock = _get_chapter_build_lock(book_id, chapter_id)
        with ch_lock:
            # Re-check after acquiring the lock: another thread may have built it.
            with get_conn() as conn:
                seg = conn.execute(
                    'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? AND segment_index=?',
                    (book_id, chapter_id, segment_index)
                ).fetchone()
            if not seg:
                if not _build_segments_for_chapter(book_id, chapter_id):
                    return jsonify({'error': 'A fejezet nem található'}), 404
                with get_conn() as conn:
                    seg = conn.execute(
                        'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? AND segment_index=?',
                        (book_id, chapter_id, segment_index)
                    ).fetchone()

    if not seg:
        return jsonify({'error': 'A szakasz sorszáma érvénytelen'}), 404

    seg = dict(seg)
    if seg.get('audio_path') and os.path.exists(seg['audio_path']):
        return jsonify({
            'audio_url': f'/api/audio/{seg["cache_key"]}',
            'cache_key': seg['cache_key'],
            'duration_sec': seg['duration_sec'],
            'text': seg['text'],
            'character_name': seg['character_name'],
            'is_dialogue': bool(seg['is_dialogue']),
            'segment_index': segment_index,
            'cached': True,
        })

    # Cache misses reserve interactive synthesis until the response teardown,
    # including the late tts_segments write. The dispatch lock is held only
    # while changing the counter, so InteractiveTTSBatcher can still coalesce.
    global _interactive_request_count
    with _work_dispatch_lock:
        if _active_durable_jobs():
            return jsonify({
                'error': 'Háttérben futó hangkészítés vagy elemzés mellett az interaktív hang várakozik.',
                'export_busy': True,
            }), 503
        _interactive_request_count += 1
        g._auris_interactive_reserved = True
        # The request-level read gate protected segment lookup/build and the
        # cache decision. Release it before GPU work; the reservation counter
        # now prevents mutations and new background dispatches.
        if getattr(g, '_auris_work_gate_held', False):
            g._auris_work_gate_held = False
            _work_dispatch_lock.release()

    # Do not steal the GPU from a running full-book/chapter export with
    # single-segment synth (reader prewarm / playback buffer).
    if _export_exclusive_active():
        return jsonify({
            'error': 'Export fut – az azonnali felolvasás az export végéig szünetel.',
            'export_busy': True,
        }), 503

    if seg['character_name']:
        with get_conn() as conn:
            char = conn.execute(
                'SELECT * FROM characters WHERE book_id=? AND name=?',
                (book_id, seg['character_name'])
            ).fetchone()
        char_data = dict(char) if char else {}
        ref_audio = char_data.get('ref_audio_path') or None
        ref_text = (char_data.get('ref_text') or None) if ref_audio else None
    else:
        ref_audio, ref_text = _book_narrator_reference(book_id)

    item = {
        'text': seg['enriched_text'],
        'instruct': seg['instruct'],
        'ref_audio': ref_audio,
        'ref_text': ref_text,
        'speed': seg['speed'],
        'language': language,
    }
    request_key = (
        seg['id'],
        seg['enriched_text'],
        seg['instruct'],
        ref_audio,
        ref_text,
        float(seg['speed']),
        language,
    )
    try:
        result = _interactive_tts_batcher.submit(
            request_key,
            item,
            priority=playback_priority,
        )
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503

    with get_conn() as conn:
        conn.execute(
            'UPDATE tts_segments SET audio_path=?, duration_sec=?, cache_key=? WHERE id=?',
            (result['audio_path'], result['duration_sec'], result['cache_key'], seg['id'])
        )

    return jsonify({
        'audio_url': f'/api/audio/{result["cache_key"]}',
        'cache_key': result['cache_key'],
        'duration_sec': result['duration_sec'],
        'text': seg['text'],
        'character_name': seg['character_name'],
        'is_dialogue': bool(seg['is_dialogue']),
        'segment_index': segment_index,
        'cached': result['cache_hit'],
    })


@app.route('/api/tts/segments/<int:book_id>/<int:chapter_id>')
def get_segments(book_id, chapter_id):
    """Return segment metadata, rebuilding if enriched_text is stale (e.g. emotion tags changed)."""
    ch_lock = _get_chapter_build_lock(book_id, chapter_id)
    with ch_lock:
        rows = _ensure_chapter_segments(book_id, chapter_id)
    if not rows:
        return jsonify([])
    with get_conn() as conn:
        annotation_rows = conn.execute(
            'SELECT unit_index, source FROM speaker_annotations '
            'WHERE book_id=? AND chapter_id=?',
            (book_id, chapter_id),
        ).fetchall()
        chapter = conn.execute(
            'SELECT content FROM chapters WHERE id=? AND book_id=?',
            (chapter_id, book_id),
        ).fetchone()
    annotation_sources = {
        int(row['unit_index']): row['source'] or 'automatic'
        for row in annotation_rows
    }
    speaker_units = (
        enrichment.build_speaker_units(chapter['content']) if chapter else []
    )
    unit_metadata = {int(unit['index']): unit for unit in speaker_units}
    return jsonify([{
        'segment_index': r['segment_index'],
        'text': r['text'],
        'character_name': r['character_name'],
        'is_dialogue': bool(r['is_dialogue']),
        'has_audio': bool(r['audio_path'] and os.path.exists(r['audio_path'])),
        'duration_sec': r['duration_sec'],
        'cache_key': r['cache_key'],
        'unit_index': r['unit_index'],
        'speaker_candidate': bool(r['speaker_candidate']),
        'speaker_source': annotation_sources.get(r['unit_index']),
        'speaker_turn_index': (
            unit_metadata.get(r['unit_index'], {}).get('turn_index')
        ),
        'speaker_continuation': bool(
            unit_metadata.get(r['unit_index'], {}).get('continuation')
        ),
        'ends_paragraph': bool(r['ends_paragraph']),
        'block_index': r['block_index'],
        'block_kind': r['block_kind'],
        'pause_ms': r['pause_ms'],
    } for r in rows])


def _store_segments(book_id, chapter_id, segs, connection=None):
    from contextlib import nullcontext
    from collections import defaultdict, deque
    # Keep already rendered audio only when every voice/text input still matches.
    with (nullcontext(connection) if connection is not None else get_conn()) as conn:
        previous = conn.execute(
            'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? ORDER BY segment_index',
            (book_id, chapter_id),
        ).fetchall()
        def signature(seg):
            return (seg['text'], seg['enriched_text'], seg['character_name'],
                    seg['instruct'], float(seg['speed']), bool(seg['is_dialogue']))
        reusable = defaultdict(deque)
        for row in previous:
            if row['audio_path'] and os.path.exists(row['audio_path']):
                reusable[signature(row)].append(row)
        conn.execute('DELETE FROM tts_segments WHERE book_id=? AND chapter_id=?', (book_id, chapter_id))
        for i, seg in enumerate(segs):
            candidates = reusable[signature(seg)]
            old = candidates.popleft() if candidates else None
            key = old['cache_key'] if old else f'pending:{book_id}:{chapter_id}:{i}:{uuid.uuid4().hex}'
            conn.execute(
                'INSERT INTO tts_segments '
                '(book_id,chapter_id,segment_index,text,enriched_text,character_name,instruct,speed,'
                'is_dialogue,unit_index,speaker_candidate,ends_paragraph,cache_key,'
                'block_index,block_kind,pause_ms,audio_path,duration_sec) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (book_id,chapter_id,i,seg['text'],seg['enriched_text'],seg['character_name'],
                 seg['instruct'],seg['speed'],int(seg['is_dialogue']),seg.get('unit_index'),
                 int(bool(seg.get('speaker_candidate'))),int(bool(seg.get('ends_paragraph'))),key,
                 seg.get('block_index'),seg.get('block_kind'),seg.get('pause_ms'),
                 old['audio_path'] if old else None,old['duration_sec'] if old else None),
            )


@app.route('/api/audio/<cache_key>')
def serve_audio(cache_key):
    from core.tts_engine import AUDIO_CACHE_DIR
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', cache_key):
        return '', 404
    path = os.path.join(AUDIO_CACHE_DIR, f'{cache_key}.wav')
    if not os.path.exists(path):
        # Portable backups restore audio to new managed paths, retaining cache identity.
        with get_conn() as conn:
            row = conn.execute('SELECT audio_path FROM tts_segments WHERE cache_key=? AND audio_path IS NOT NULL', (cache_key,)).fetchone()
        restored = Path(row['audio_path']).resolve() if row else None
        if not restored or not restored.is_relative_to((Path(UPLOAD_DIR) / 'restored').resolve()) or not restored.is_file():
            return '', 404
        path = str(restored)
    requested_name = request.args.get('download')
    if requested_name is not None:
        cleaned = ''.join(
            char for char in str(requested_name)
            if char.isalnum() or char in {' ', '-', '_'}
        ).strip()[:60]
        return send_file(
            path,
            mimetype='audio/wav',
            as_attachment=True,
            download_name=f'{cleaned or "proba"}.wav',
        )
    return send_file(path, mimetype='audio/wav')


# ════════════════════════════════════════════════════════════════════════════
# Export API
# ════════════════════════════════════════════════════════════════════════════

def _fmt_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN
        return ''
    s = int(round(seconds))
    if s < 60:
        return f'{s}s'
    m, s = divmod(s, 60)
    if m < 60:
        return f'{m}m {s:02d}s'
    h, m = divmod(m, 60)
    return f'{h}h {m:02d}m'


def _refresh_export_job_fields(job: dict | None) -> None:
    """Recompute elapsed/ETA/message from current counters (safe to call on poll)."""
    if not job or job.get('state') not in ('running', 'pending'):
        return
    import time

    now = time.time()
    done = int(job.get('done') or 0)
    total = int(job.get('total') or 0)
    t0 = job.get('t0')
    elapsed = (now - float(t0)) if t0 else 0.0
    job['elapsed_sec'] = elapsed if t0 else None

    # Prefer synthesis-only rate so early cache hits do not make ETA absurdly low.
    synth_done = int(job.get('synth_done') or 0)
    synth_t0 = job.get('synth_t0')
    eta_sec = None
    if total > done:
        if synth_t0 and synth_done >= 1:
            synth_elapsed = now - float(synth_t0)
            if synth_elapsed >= 2.0 and synth_done >= 2:
                rate = synth_done / synth_elapsed
                if rate > 0:
                    eta_sec = (total - done) / rate
            elif synth_elapsed >= 1.0 and synth_done >= 1:
                rate = synth_done / synth_elapsed
                if rate > 0:
                    eta_sec = (total - done) / rate
        elif t0 and done > 0 and elapsed >= 3.0:
            # Fallback before any real synth samples exist (all cache so far).
            rate = done / elapsed
            if rate > 0:
                eta_sec = (total - done) / rate

    job['eta_sec'] = eta_sec

    if total > 0:
        msg = f'Hang készítése ({done}/{total})'
        if eta_sec is not None and done < total:
            msg += f' · ~{_fmt_eta(eta_sec)} left'
        elif done < total and synth_done == 0 and done > 0:
            msg += ' · estimating…'
        elif done < total and synth_done > 0 and eta_sec is None:
            msg += ' · working…'
        job['message'] = msg
    else:
        job['message'] = job.get('message') or 'Hang készítése…'


def _bump_export_progress(job: dict | None, n: int = 1, *, synthesized: bool = False) -> None:
    """Increment export job progress and refresh message + ETA estimate."""
    if job is None or n <= 0:
        return
    import time

    now = time.time()
    if not job.get('t0'):
        job['t0'] = now
    job['done'] = int(job.get('done') or 0) + n
    if synthesized:
        if not job.get('synth_t0'):
            job['synth_t0'] = now
        job['synth_done'] = int(job.get('synth_done') or 0) + n
    _refresh_export_job_fields(job)
    if job.get('job_id'):
        # SQLite progress rows are for other pages and restarts; writing one
        # per segment costs several connections per sentence during export.
        last = float(job.get('_persisted_at') or 0)
        finished = int(job.get('total') or 0) and job['done'] >= int(job.get('total') or 0)
        if finished or now - last >= 0.5:
            job['_persisted_at'] = now
            _persist_job(job)


ENGINE_WAIT_SEC = 1800.0


def _wait_for_engine(job: dict | None) -> None:
    """Hold a background job until the speech engine is ready, loading it if
    needed, so work can be started while the model is still loading."""
    import time

    deadline = time.monotonic() + ENGINE_WAIT_SEC
    announced = False
    while True:
        status = tts.status()
        state = status.get('state')
        if state == 'ready':
            return
        if state == 'error':
            raise RuntimeError('A beszédmotor nem tölthető be: ' + str(status.get('message') or ''))
        if state == 'not_loaded':
            tts.load_async()
        if job is not None and not announced:
            job['message'] = 'A beszédmotor betöltése…'
            _persist_job(job)
            announced = True
        _check_job_cancelled(job)
        if time.monotonic() > deadline:
            raise RuntimeError('A beszédmotor nem töltődött be időben.')
        time.sleep(0.5)


def _ensure_audio_for_chapter(
    book_id: int,
    chapter_id: int,
    segs: list[dict],
    job: dict | None = None,
    export_pool: TTSExportPool | None = None,
):
    """Generate TTS for any segment in segs that has no audio yet, updating DB and segs in-place.

    Pending segments are batched through OmniVoice so full-book export uses the GPU
    efficiently. Quality is controlled by settings ``tts_num_step``.
    Progress is updated after every finished segment (including mid-batch).
    """
    _check_job_cancelled(job)
    with get_conn() as conn:
        book = conn.execute('SELECT language FROM books WHERE id=?', (book_id,)).fetchone()
        language = book['language'] if book and book['language'] else None
        chars = {
            r['name']: dict(r)
            for r in conn.execute(
                'SELECT * FROM characters WHERE book_id=?', (book_id,)
            ).fetchall()
        }
    narrator_ref, narrator_ref_text = _book_narrator_reference(book_id)

    pending_idx: list[int] = []
    pending_items: list[dict] = []

    for i, seg in enumerate(segs):
        _check_job_cancelled(job)
        if seg.get('audio_path') and os.path.exists(seg['audio_path']):
            _bump_export_progress(job, 1, synthesized=False)
            continue

        char = chars.get(seg['character_name']) if seg['character_name'] else None
        if char:
            ref_audio = char['ref_audio_path'] if char.get('ref_audio_path') else None
            ref_text = (char.get('ref_text') or None) if ref_audio else None
        else:
            ref_audio = narrator_ref
            ref_text = narrator_ref_text

        pending_idx.append(i)
        pending_items.append({
            'text': seg['enriched_text'],
            'instruct': seg['instruct'],
            'ref_audio': ref_audio,
            'ref_text': ref_text,
            'speed': seg['speed'],
            'language': language,
        })

    if not pending_items:
        return

    try:
        from core.tts_engine import _tts_num_step_from_settings
        from core.settings import get as _settings_get
        num_step = _tts_num_step_from_settings()
        log.info(
            "Export synth settings: num_step=%s tts_batch_size=%s pending_segments=%d",
            num_step,
            _settings_get("tts_batch_size", 0),
            len(pending_items),
        )
    except Exception:
        num_step = 16

    db_buffer: list[tuple] = []
    result_lock = threading.RLock()

    def _flush_db(force: bool = False) -> None:
        nonlocal db_buffer
        if not db_buffer:
            return
        if not force and len(db_buffer) < 24:
            return
        with get_conn() as conn:
            conn.executemany(
                'UPDATE tts_segments SET audio_path=?, duration_sec=?, cache_key=?, '
                'take_policy=NULL WHERE id=?',
                db_buffer,
            )
        db_buffer = []

    def _apply_result(local_i: int, result: dict | None) -> None:
        with result_lock:
            if result is None:
                _bump_export_progress(job, 1, synthesized=False)
                return
            seg = segs[pending_idx[local_i]]
            seg['audio_path'] = result['audio_path']
            seg['duration_sec'] = result['duration_sec']
            seg['cache_key'] = result['cache_key']
            seg['take_policy'] = None
            db_buffer.append((
                result['audio_path'],
                result['duration_sec'],
                result['cache_key'],
                seg['id'],
            ))
            _bump_export_progress(
                job,
                1,
                synthesized=not bool(result.get('cache_hit')),
            )
            _flush_db(force=False)
            _check_job_cancelled(job, throttle=True)

    try:
        def on_item(local_i: int, result: dict) -> None:
            _apply_result(local_i, result)

        def on_status(msg: str) -> None:
            if job is None:
                return
            with result_lock:
                done = job.get('done', 0)
                total = job.get('total', 0)
                job['message'] = f'Hang készítése ({done}/{total}) · {msg}'

        if job is not None:
            on_status(f'preparing {len(pending_items)} pending segments…')
        if export_pool is not None:
            export_pool.generate_many(
                pending_items,
                num_step=num_step,
                on_item=on_item,
                on_status=on_status,
            )
        else:
            tts.generate_many(
                pending_items,
                num_step=num_step,
                on_item=on_item,
                on_status=on_status,
            )
        _check_job_cancelled(job)
    except JobCancelled:
        with result_lock:
            _flush_db(force=True)
        raise
    except Exception as e:
        if export_pool is not None and export_pool.worker_count > 1:
            export_pool.close()
        log.warning(
            'Batch audio generation failed for chapter %s (%d items): %s; '
            'falling back to per-segment',
            chapter_id, len(pending_items), e,
        )
        for local_i, item in enumerate(pending_items):
            _check_job_cancelled(job)
            # Skip items already filled by a partial batch before the exception.
            if segs[pending_idx[local_i]].get('audio_path') and os.path.exists(
                segs[pending_idx[local_i]]['audio_path']
            ):
                continue
            try:
                result = tts.generate(
                    text=item['text'],
                    instruct=item['instruct'],
                    ref_audio=item['ref_audio'],
                    ref_text=item['ref_text'],
                    speed=item['speed'],
                    language=item['language'],
                    num_step=num_step,
                )
            except Exception as seg_exc:
                log.warning('Audio generation failed for segment: %s', seg_exc)
                result = None
            _apply_result(local_i, result)

    with result_lock:
        _flush_db(force=True)


def _start_export_pool(job: dict) -> TTSExportPool:
    try:
        requested = int(app_settings.get('tts_export_workers', 0) or 0)
    except (TypeError, ValueError):
        requested = 0
    pool = TTSExportPool(tts, requested_workers=requested)
    if requested != 1:
        job['message'] = 'Második GPU-feldolgozó betöltése…'
    workers = pool.start()
    job['workers'] = workers
    log.info('Export TTS worker count=%d (requested=%d)', workers, requested)
    return pool


def _chapter_audio_counts(segs: list[dict]) -> tuple[int, int]:
    total = len(segs)
    ready = sum(
        1
        for seg in segs
        if seg.get('audio_path') and os.path.exists(seg['audio_path'])
    )
    return ready, total


def _chapter_generation_snapshot(
    book_id: int,
    chapter_id: int,
    segs: list[dict] | None = None,
) -> dict:
    if segs is None:
        segs = _get_chapter_segments(chapter_id, book_id)
    ready, total = _chapter_audio_counts(segs)
    key = (book_id, chapter_id)

    with _chapter_generation_lock:
        job_id = _chapter_generation_by_chapter.get(key)
        job = _chapter_generation_jobs.get(job_id) if job_id else None
        active_id = _chapter_generation_active_job_id
        active_job = _chapter_generation_jobs.get(active_id) if active_id else None

    if job and job.get('state') in ('pending', 'running', 'failed'):
        _refresh_export_job_fields(job)
        snapshot = dict(job)
    else:
        complete = bool(total and ready >= total)
        snapshot = {
            'job_id': job_id,
            'state': 'complete' if complete else 'idle',
            'message': 'Kész' if complete else 'Még nem készült el',
            'done': ready,
            'total': total,
            'eta_sec': None,
            'elapsed_sec': None,
            'error': None,
        }

    snapshot.update({
        'book_id': book_id,
        'chapter_id': chapter_id,
        'ready': ready,
        'percent': round((snapshot.get('done', ready) / total) * 100) if total else 0,
    })
    if active_job and active_job.get('state') in ('pending', 'running'):
        snapshot['busy_job_id'] = active_id
        snapshot['busy_chapter_id'] = active_job.get('chapter_id')
    return snapshot


def _run_chapter_generation(job_id: str, book_id: int, chapter_id: int) -> None:
    global _chapter_generation_active_job_id
    job = _chapter_generation_jobs[job_id]
    generation_pool: TTSExportPool | None = None
    _export_exclusive_begin()
    try:
        _check_job_cancelled(job)
        job['state'] = 'running'
        job['message'] = 'Fejezetszöveg betöltése…'
        _persist_job(job)
        segs = _get_chapter_segments(chapter_id, book_id)
        job['total'] = len(segs)
        job['done'] = 0
        job['message'] = f'Hang készítése (0/{len(segs)})'
        generation_pool = _start_export_pool(job)
        _ensure_audio_for_chapter(
            book_id,
            chapter_id,
            segs,
            job,
            export_pool=generation_pool,
        )
        ready, total = _chapter_audio_counts(segs)
        if ready < total:
            raise RuntimeError(
                f'Only {ready} of {total} chapter segments were generated.'
            )
        job['done'] = total
        job['state'] = 'complete'
        job['message'] = 'Elkészült'
        job['result'] = {
            'book_id': book_id,
            'chapter_id': chapter_id,
            'ready': ready,
            'total': total,
        }
        _persist_job(job)
    except JobCancelled:
        jobs.mark_cancelled(job_id, 'A generálás leállítva az aktuális csomag után')
        job['state'] = 'cancelled'
    except Exception as exc:
        log.exception('Chapter generation job %s failed', job_id)
        job['state'] = 'failed'
        job['error'] = str(exc)
        job['message'] = 'A hang készítése nem sikerült'
        _persist_job(job)
    finally:
        _close_orphaned_job(job_id)
        if generation_pool is not None:
            generation_pool.close()
        _export_exclusive_end()
        with _chapter_generation_lock:
            if _chapter_generation_active_job_id == job_id:
                _chapter_generation_active_job_id = None


@app.route(
    '/api/books/<int:book_id>/chapters/<int:chapter_id>/generate',
    methods=['GET'],
)
def chapter_generation_status(book_id, chapter_id):
    with get_conn() as conn:
        exists = conn.execute(
            'SELECT 1 FROM chapters WHERE id=? AND book_id=?',
            (chapter_id, book_id),
        ).fetchone()
    if not exists:
        return jsonify({'error': 'A fejezet nem található'}), 404
    return jsonify(_chapter_generation_snapshot(book_id, chapter_id))


@app.route(
    '/api/books/<int:book_id>/chapters/<int:chapter_id>/generate',
    methods=['POST'],
)
def generate_chapter_audio(book_id, chapter_id):
    with get_conn() as conn:
        exists = conn.execute(
            'SELECT 1 FROM chapters WHERE id=? AND book_id=?',
            (chapter_id, book_id),
        ).fetchone()
    if not exists:
        return jsonify({'error': 'A fejezet nem található'}), 404

    jobs.ensure_jobs()
    key = (book_id, chapter_id)
    with _chapter_generation_lock:
        existing_id = _chapter_generation_by_chapter.get(key)
        existing = (
            _chapter_generation_jobs.get(existing_id) if existing_id else None
        )
        if existing and existing.get('state') in ('pending', 'running'):
            return jsonify(dict(existing))

        active_id = _chapter_generation_active_job_id
        active = _chapter_generation_jobs.get(active_id) if active_id else None
        if active and active.get('state') in ('pending', 'running'):
            return jsonify({
                'error': 'Egy másik fejezet vagy export már hangot készít.',
                'busy_job_id': active_id,
                'busy_chapter_id': active.get('chapter_id'),
            }), 409
        if _active_durable_jobs():
            return jsonify({'error': 'Már fut egy hangexport.'}), 409

    if _export_exclusive_active():
        return jsonify({'error': 'Már fut egy hanggenerálás vagy export.'}), 409
    if tts.status()['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen'}), 503

    segs = _get_chapter_segments(chapter_id, book_id)
    ready, total = _chapter_audio_counts(segs)
    if total and ready >= total:
        return jsonify({
            'state': 'complete',
            'message': 'Kész',
            'done': total,
            'total': total,
            'ready': ready,
            'percent': 100,
            'book_id': book_id,
            'chapter_id': chapter_id,
        })

    with _work_dispatch_lock:
        conflict = _work_conflict_response()
        if conflict is not None:
            return conflict
        with _chapter_generation_lock:
            active_id = _chapter_generation_active_job_id
            active = _chapter_generation_jobs.get(active_id) if active_id else None
            if active and active.get('state') in ('pending', 'running'):
                return jsonify({
                    'error': 'Egy másik fejezet vagy export már hangot készít.',
                    'busy_job_id': active_id,
                    'busy_chapter_id': active.get('chapter_id'),
                }), 409
        stored = jobs.create_job(
            'generate_chapter',
            {'book_id': book_id, 'chapter_id': chapter_id},
            book_id=book_id,
            chapter_id=chapter_id,
            done=ready,
            total=total,
        )
        _launch_durable_job(stored)
        return jsonify({**stored, **_legacy_job(stored)})


@app.route('/api/chapter-generation/status/<job_id>')
def chapter_generation_job_status(job_id):
    job = _chapter_generation_jobs.get(job_id)
    if not job:
        stored = jobs.get_job(job_id)
        if not stored or stored['type'] != 'generate_chapter':
            return jsonify({'error': 'Ismeretlen feladat'}), 404
        return jsonify({**stored, **_legacy_job(stored)})
    _refresh_export_job_fields(job)
    if job.get('job_id'):
        _persist_job(job)
    snapshot = dict(job)
    total = int(snapshot.get('total') or 0)
    done = int(snapshot.get('done') or 0)
    snapshot['percent'] = round((done / total) * 100) if total else 0
    return jsonify(snapshot)


def _get_char_colors(book_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT name, color_hex FROM characters WHERE book_id=?', (book_id,)
        ).fetchall()
    return {r['name']: r['color_hex'] for r in rows}


def _get_chapter_segments(chapter_id, book_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? ORDER BY segment_index',
            (book_id, chapter_id)
        ).fetchall()
    if not rows:
        _build_segments_for_chapter(book_id, chapter_id)
        with get_conn() as conn:
            rows = conn.execute(
                'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? ORDER BY segment_index',
                (book_id, chapter_id)
            ).fetchall()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# Bookmarks API
# ════════════════════════════════════════════════════════════════════════════







# ════════════════════════════════════════════════════════════════════════════
# Settings API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/docs')
def docs_page():
    return render_template('docs.html')


# ════════════════════════════════════════════════════════════════════════════
# Run
# ════════════════════════════════════════════════════════════════════════════

from core.experience_api import bp as experience_blueprint
from core.qa_api import bp as qa_blueprint
from core.assist_api import bp as assist_blueprint
from core.openai_api import bp as openai_blueprint
from core.production_api import bp as production_blueprint
from core.events_api import bp as events_blueprint
from core.pwa_api import bp as pwa_blueprint
from core.settings_api import bp as settings_blueprint
from core.export_api import bp as export_blueprint
from core.voices_api import bp as voices_blueprint
from core.reading_api import bp as reading_blueprint
app.register_blueprint(experience_blueprint)
app.register_blueprint(settings_blueprint)
app.register_blueprint(export_blueprint)
app.register_blueprint(voices_blueprint)
app.register_blueprint(reading_blueprint)
app.register_blueprint(pwa_blueprint)
app.register_blueprint(events_blueprint)
app.register_blueprint(production_blueprint)
app.register_blueprint(openai_blueprint)
app.register_blueprint(qa_blueprint)
app.register_blueprint(assist_blueprint)

if __name__ == '__main__':
    with app.app_context():
        _startup()
    from core import backup_schedule
    backup_schedule.start()
    # AURIS_HOST=0.0.0.0 (for example in Docker) exposes the server; add the
    # names clients use in AURIS_ALLOWED_HOSTS so the Host check accepts them.
    host = os.environ.get('AURIS_HOST', '127.0.0.1')
    port = int(os.environ.get('AURIS_PORT', '7860'))
    app.run(host=host, port=port, debug=False, threaded=True)
