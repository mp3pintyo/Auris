"""
Offline Ebook Reader — Flask application.
"""

import base64
import logging
import os
import threading
import uuid

from flask import (
    Flask, jsonify, render_template, request,
    send_file,
)

from core.database import init_db, get_conn
from core.tts_engine import TTSEngine
from core import characters as char_module
from core import enrichment, exporter, structure, settings as app_settings
from core.parser import epub_parser, pdf_parser, txt_parser

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

tts = TTSEngine()

DEFAULT_NARRATOR_INSTRUCT = app_settings.DEFAULT_NARRATOR_INSTRUCT

_export_jobs: dict = {}

# Per-chapter locks prevent concurrent segment building from racing on the
# DELETE + INSERT in _store_segments when multiple requests hit the same
# chapter before segments are built (e.g. parallel prewarm requests).
_chapter_build_locks: dict = {}
_chapter_build_locks_meta = threading.Lock()
_startup_lock = threading.Lock()
_startup_complete = False


def _get_chapter_build_lock(book_id: int, chapter_id: int) -> threading.Lock:
    key = (book_id, chapter_id)
    with _chapter_build_locks_meta:
        if key not in _chapter_build_locks:
            _chapter_build_locks[key] = threading.Lock()
        return _chapter_build_locks[key]


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
        except Exception:
            tts.load_async()
            raise
        tts.load_async()
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


def _load_book(book_id: int):
    with get_conn() as conn:
        return conn.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()


def _clear_book_tts_segments(book_id: int):
    with get_conn() as conn:
        conn.execute('DELETE FROM tts_segments WHERE book_id=?', (book_id,))


def _compute_segments_for_chapter(book_id: int, chapter_id: int) -> list[dict]:
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
            'SELECT narrator_instruct, single_narrator_mode FROM books WHERE id=?',
            (book_id,)
        ).fetchone()

    if not ch:
        return []

    char_map = {r['name']: dict(r) for r in chars}
    segs = enrichment.enrich_chapter(
        ch['content'],
        char_map,
        _book_narrator_instruct(dict(book) if book else None),
        single_narrator_mode=_book_single_narrator_mode(dict(book) if book else None),
        chapter_title=ch['title'],
    )
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
        return 'Book not found', 404
    book_data = dict(book)
    book_data['narrator_instruct'] = _book_narrator_instruct(book_data)
    book_data['single_narrator_mode'] = _book_single_narrator_mode(book_data)
    return render_template('reader.html', book=book_data)


@app.route('/voice-studio/<int:book_id>')
def voice_studio_page(book_id):
    book = _load_book(book_id)
    if not book:
        return 'Book not found', 404
    book_data = dict(book)
    book_data['narrator_instruct'] = _book_narrator_instruct(book_data)
    book_data['single_narrator_mode'] = _book_single_narrator_mode(book_data)
    return render_template('voice_studio.html', book=book_data)


# ════════════════════════════════════════════════════════════════════════════
# Book import
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books/import', methods=['POST'])
def import_book():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ('epub', 'pdf', 'txt'):
        return jsonify({'error': f'Unsupported format: {ext}'}), 400

    dest = os.path.join(UPLOAD_DIR, f.filename)
    f.save(dest)

    try:
        if ext == 'epub':
            data = epub_parser.parse(dest)
        elif ext == 'pdf':
            data = pdf_parser.parse(dest)
        else:
            data = txt_parser.parse(dest)
    except Exception as e:
        return jsonify({'error': f'Parse error: {e}'}), 500

    chapters = structure.enrich_chapters(data['chapters'])

    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO books (title, author, file_path, file_type, cover_b64, language, single_narrator_mode, total_chapters) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (data['title'], data['author'], dest, ext,
             data.get('cover_b64'), data.get('language', 'en'),
             int(bool(app_settings.get('single_narrator_mode', False))), len(chapters))
        )
        book_id = cur.lastrowid

        for ch in chapters:
            conn.execute(
                'INSERT INTO chapters (book_id, title, order_num, section_type, content, word_count) '
                'VALUES (?,?,?,?,?,?)',
                (book_id, ch['title'], ch['order_num'], ch.get('section_type', 'chapter'),
                 ch['content'], ch['word_count'])
            )

    # Detect characters in background
    threading.Thread(target=_detect_characters, args=(book_id, data), daemon=True).start()

    return jsonify({'book_id': book_id, 'title': data['title'], 'chapters': len(chapters)})


def _detect_characters(book_id: int, data: dict):
    full_text = ' '.join(ch['content'] for ch in data['chapters'])
    chars = char_module.extract_characters(full_text, top_n=20)
    with get_conn() as conn:
        for ch in chars:
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO characters '
                    '(book_id, name, gender, frequency, instruct, color_hex) '
                    'VALUES (?,?,?,?,?,?)',
                    (book_id, ch['name'], ch['gender'], ch['frequency'],
                     ch['instruct'], ch['color_hex'])
                )
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════════════════
# Library API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books')
def list_books():
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT b.id, b.title, b.author, b.file_type, b.cover_b64, b.added_at, '
            'b.last_read, b.total_chapters, rp.chapter_id AS progress_chapter_id, '
            'rp.position AS progress_position, c.title AS progress_chapter_title '
            'FROM books b '
            'LEFT JOIN reading_progress rp ON rp.book_id = b.id '
            'LEFT JOIN chapters c ON c.id = rp.chapter_id '
            'ORDER BY COALESCE(b.last_read, b.added_at) DESC, b.added_at DESC'
        ).fetchall()
    books = []
    for r in rows:
        d = dict(r)
        if d['cover_b64']:
            d['cover_url'] = f'/api/books/{d["id"]}/cover'
            d.pop('cover_b64')
        else:
            d['cover_url'] = None
        books.append(d)
    return jsonify(books)


@app.route('/api/books/<int:book_id>/cover')
def book_cover(book_id):
    with get_conn() as conn:
        row = conn.execute('SELECT cover_b64, file_type FROM books WHERE id=?', (book_id,)).fetchone()
    if not row or not row['cover_b64']:
        return '', 204
    img_bytes = base64.b64decode(row['cover_b64'])
    ext = 'png' if row['file_type'] == 'pdf' else 'jpeg'
    return app.response_class(img_bytes, mimetype=f'image/{ext}')


@app.route('/api/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    with get_conn() as conn:
        conn.execute('DELETE FROM books WHERE id=?', (book_id,))
    return jsonify({'ok': True})


# ════════════════════════════════════════════════════════════════════════════
# Chapter API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books/<int:book_id>/chapters')
def list_chapters(book_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT id, title, order_num, section_type, word_count FROM chapters '
            'WHERE book_id=? ORDER BY order_num',
            (book_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/books/<int:book_id>/chapters/<int:chapter_id>')
def get_chapter(book_id, chapter_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM chapters WHERE id=? AND book_id=?', (chapter_id, book_id)
        ).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(row))


@app.route('/api/books/<int:book_id>/progress', methods=['POST'])
def save_progress(book_id):
    body = request.get_json(force=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO reading_progress (book_id, chapter_id, position, updated_at) '
            'VALUES (?,?,?,datetime("now")) '
            'ON CONFLICT(book_id) DO UPDATE SET chapter_id=excluded.chapter_id, '
            'position=excluded.position, updated_at=excluded.updated_at',
            (book_id, body.get('chapter_id'), body.get('position', 0))
        )
        conn.execute('UPDATE books SET last_read=datetime("now") WHERE id=?', (book_id,))
    return jsonify({'ok': True})


@app.route('/api/books/<int:book_id>/progress')
def get_progress(book_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM reading_progress WHERE book_id=?', (book_id,)
        ).fetchone()
    return jsonify(dict(row) if row else {})


# ════════════════════════════════════════════════════════════════════════════
# Characters API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books/<int:book_id>/characters')
def list_characters(book_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM characters WHERE book_id=? ORDER BY frequency DESC',
            (book_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/books/<int:book_id>/characters/<int:char_id>', methods=['PUT'])
def update_character(book_id, char_id):
    body = request.get_json(force=True)
    allowed = {'instruct', 'gender', 'color_hex', 'ref_text'}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'Nothing to update'}), 400
    set_clause = ', '.join(f'{k}=?' for k in updates)
    with get_conn() as conn:
        conn.execute(
            f'UPDATE characters SET {set_clause} WHERE id=? AND book_id=?',
            (*updates.values(), char_id, book_id)
        )
    _clear_book_tts_segments(book_id)
    return jsonify({'ok': True, 'segments_cleared': True})


@app.route('/api/books/<int:book_id>/characters/<int:char_id>/preview', methods=['POST'])
def preview_character(book_id, char_id):
    body = request.get_json(silent=True) or {}
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM characters WHERE id=? AND book_id=?',
                           (char_id, book_id)).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404

    status = tts.status()
    if status['state'] != 'ready':
        return jsonify({'error': 'Model not ready', 'status': status}), 503

    instruct = (body.get('instruct') or row['instruct'] or '').strip()
    ref_audio = row['ref_audio_path'] if row['ref_audio_path'] else None
    requested_ref_text = body.get('ref_text', row['ref_text'])
    ref_text = requested_ref_text.strip() if ref_audio and isinstance(requested_ref_text, str) and requested_ref_text.strip() else None
    sample_text = (
        f'Hello. I am {row["name"]}. '
        'This preview should sound clear, steady, and easy to understand.'
    )

    try:
        result = tts.generate_preview(
            instruct=instruct,
            sample_text=sample_text,
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        return jsonify({'audio_url': f'/api/audio/{result["cache_key"]}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/books/<int:book_id>/narrator', methods=['GET'])
def get_narrator(book_id):
    book = _load_book(book_id)
    if not book:
        return jsonify({'error': 'Not found'}), 404
    book_data = dict(book)
    return jsonify({
        'instruct': _book_narrator_instruct(book_data),
        'single_narrator_mode': _book_single_narrator_mode(book_data),
        'ref_audio_name': book_data.get('narrator_ref_audio_name'),
        'ref_text': book_data.get('narrator_ref_text') or '',
    })


@app.route('/api/books/<int:book_id>/narrator', methods=['PUT'])
def update_narrator(book_id):
    body = request.get_json(force=True) or {}
    book = _load_book(book_id)
    if not book:
        return jsonify({'error': 'Not found'}), 404
    book_data = dict(book)

    raw_instruct = body.get('instruct')
    instruct = (
        raw_instruct.strip()
        if isinstance(raw_instruct, str)
        else _book_narrator_instruct(book_data)
    )
    if not instruct:
        return jsonify({'error': 'Narrator instruct is required'}), 400

    raw_mode = body.get('single_narrator_mode', _book_single_narrator_mode(book_data))
    if isinstance(raw_mode, str):
        single_narrator_mode = raw_mode.strip().lower() in {'1', 'true', 'yes', 'on'}
    else:
        single_narrator_mode = bool(raw_mode)
    narrator_changed = instruct != _book_narrator_instruct(book_data)
    mode_changed = single_narrator_mode != _book_single_narrator_mode(book_data)
    raw_ref_text = body.get('ref_text', book_data.get('narrator_ref_text') or '')
    ref_text = raw_ref_text.strip() if isinstance(raw_ref_text, str) else ''
    ref_text_changed = ref_text != (book_data.get('narrator_ref_text') or '')

    with get_conn() as conn:
        conn.execute(
            'UPDATE books SET narrator_instruct=?, single_narrator_mode=?, '
            'narrator_ref_text=? WHERE id=?',
            (instruct, int(single_narrator_mode), ref_text, book_id)
        )

    if narrator_changed or mode_changed or ref_text_changed:
        _clear_book_tts_segments(book_id)

    return jsonify({
        'ok': True,
        'instruct': instruct,
        'single_narrator_mode': single_narrator_mode,
        'ref_text': ref_text,
        'segments_cleared': narrator_changed or mode_changed or ref_text_changed,
    })


@app.route('/api/books/<int:book_id>/characters/narrator/preview', methods=['POST'])
def preview_narrator(book_id):
    body = request.get_json(silent=True) or {}
    book = _load_book(book_id)
    if not book:
        return jsonify({'error': 'Not found'}), 404

    status = tts.status()
    if status['state'] != 'ready':
        return jsonify({'error': 'Model not ready', 'status': status}), 503

    instruct = (body.get('instruct') or _book_narrator_instruct(dict(book))).strip()
    narrator_ref, saved_ref_text = _book_narrator_reference(book_id)
    requested_ref_text = body.get('ref_text', saved_ref_text)
    narrator_ref_text = requested_ref_text.strip() if narrator_ref and isinstance(requested_ref_text, str) and requested_ref_text.strip() else None
    try:
        result = tts.generate_preview(
            instruct=instruct,
            sample_text=VOICE_PREVIEW_TEXT,
            ref_audio=narrator_ref,
            ref_text=narrator_ref_text,
        )
        return jsonify({'audio_url': f'/api/audio/{result["cache_key"]}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/characters/<int:char_id>/ref-audio', methods=['POST'])
def upload_ref_audio(char_id):
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or not f.filename.lower().endswith('.wav'):
        return jsonify({'error': 'Reference audio must be a WAV file'}), 400
    ref_text = (request.form.get('ref_text') or '').strip()
    path = os.path.join(UPLOAD_DIR, f'ref_{char_id}.wav')
    f.save(path)
    with get_conn() as conn:
        row = conn.execute('SELECT book_id FROM characters WHERE id=?', (char_id,)).fetchone()
        if not row:
            _delete_file_if_exists(path)
            return jsonify({'error': 'Not found'}), 404
        conn.execute(
            'UPDATE characters SET ref_audio_path=?, ref_audio_name=?, ref_text=? WHERE id=?',
            (path, os.path.basename(f.filename), ref_text, char_id),
        )
    _clear_book_tts_segments(row['book_id'])
    return jsonify({
        'ok': True,
        'ref_audio_name': os.path.basename(f.filename),
        'ref_text': ref_text,
    })


@app.route('/api/characters/<int:char_id>/ref-audio', methods=['DELETE'])
def delete_ref_audio(char_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT book_id, ref_audio_path FROM characters WHERE id=?', (char_id,)
        ).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        conn.execute(
            'UPDATE characters SET ref_audio_path=NULL, ref_audio_name=NULL, ref_text=NULL '
            'WHERE id=?', (char_id,)
        )
    _delete_file_if_exists(row['ref_audio_path'])
    _clear_book_tts_segments(row['book_id'])
    return jsonify({'ok': True, 'segments_cleared': True})


@app.route('/api/books/<int:book_id>/narrator-ref-audio', methods=['POST'])
def upload_narrator_ref_audio(book_id):
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or not f.filename.lower().endswith('.wav'):
        return jsonify({'error': 'Reference audio must be a WAV file'}), 400
    ref_text = (request.form.get('ref_text') or '').strip()
    path = os.path.join(UPLOAD_DIR, f'narrator_ref_{book_id}.wav')
    f.save(path)
    with get_conn() as conn:
        exists = conn.execute('SELECT id FROM books WHERE id=?', (book_id,)).fetchone()
        if not exists:
            _delete_file_if_exists(path)
            return jsonify({'error': 'Not found'}), 404
        conn.execute(
            'UPDATE books SET narrator_ref_audio_path=?, narrator_ref_audio_name=?, '
            'narrator_ref_text=? WHERE id=?',
            (path, os.path.basename(f.filename), ref_text, book_id),
        )
    _clear_book_tts_segments(book_id)
    return jsonify({
        'ok': True,
        'ref_audio_name': os.path.basename(f.filename),
        'ref_text': ref_text,
    })


@app.route('/api/books/<int:book_id>/narrator-ref-audio', methods=['DELETE'])
def delete_narrator_ref_audio(book_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT narrator_ref_audio_path FROM books WHERE id=?', (book_id,)
        ).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        path = row['narrator_ref_audio_path']
        conn.execute(
            'UPDATE books SET narrator_ref_audio_path=NULL, narrator_ref_audio_name=NULL, '
            'narrator_ref_text=NULL WHERE id=?', (book_id,)
        )

    _delete_file_if_exists(path)
    _clear_book_tts_segments(book_id)
    return jsonify({'ok': True, 'segments_cleared': True})


# ════════════════════════════════════════════════════════════════════════════
# TTS API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/tts/status')
def tts_status():
    return jsonify(tts.status())


@app.route('/api/tts/load', methods=['POST'])
def tts_load():
    tts.load_async()
    return jsonify({'ok': True})


@app.route('/api/tts/generate', methods=['POST'])
def tts_generate():
    body = request.get_json(force=True)
    book_id = body.get('book_id')
    chapter_id = body.get('chapter_id')
    segment_index = body.get('segment_index', 0)

    status = tts.status()
    if status['state'] != 'ready':
        return jsonify({'error': 'Model not ready', 'status': status}), 503

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
                    return jsonify({'error': 'Chapter not found'}), 404
                with get_conn() as conn:
                    seg = conn.execute(
                        'SELECT * FROM tts_segments WHERE book_id=? AND chapter_id=? AND segment_index=?',
                        (book_id, chapter_id, segment_index)
                    ).fetchone()

    if not seg:
        return jsonify({'error': 'Segment index out of range'}), 404

    seg = dict(seg)
    if seg.get('audio_path') and os.path.exists(seg['audio_path']):
        return jsonify({
            'audio_url': f'/api/audio/{seg["cache_key"]}',
            'duration_sec': seg['duration_sec'],
            'text': seg['text'],
            'character_name': seg['character_name'],
            'is_dialogue': bool(seg['is_dialogue']),
            'segment_index': segment_index,
            'cached': True,
        })

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

    try:
        result = tts.generate(
            text=seg['enriched_text'],
            instruct=seg['instruct'],
            ref_audio=ref_audio,
            ref_text=ref_text,
            speed=seg['speed'],
            language=language,
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
    return jsonify([{
        'segment_index': r['segment_index'],
        'text': r['text'],
        'character_name': r['character_name'],
        'is_dialogue': bool(r['is_dialogue']),
        'has_audio': bool(r['audio_path'] and os.path.exists(r['audio_path'])),
        'duration_sec': r['duration_sec'],
        'cache_key': r['cache_key'],
    } for r in rows])


def _store_segments(book_id, chapter_id, segs):
    with get_conn() as conn:
        conn.execute(
            'DELETE FROM tts_segments WHERE book_id=? AND chapter_id=?',
            (book_id, chapter_id)
        )
        for i, s in enumerate(segs):
            cache_key = f'pending:{book_id}:{chapter_id}:{i}:{uuid.uuid4().hex}'
            conn.execute(
                'INSERT INTO tts_segments '
                '(book_id, chapter_id, segment_index, text, enriched_text, '
                'character_name, instruct, speed, is_dialogue, cache_key) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (book_id, chapter_id, i, s['text'], s['enriched_text'],
                 s['character_name'], s['instruct'], s['speed'],
                 int(s['is_dialogue']), cache_key)
            )


@app.route('/api/audio/<cache_key>')
def serve_audio(cache_key):
    from core.tts_engine import AUDIO_CACHE_DIR
    path = os.path.join(AUDIO_CACHE_DIR, f'{cache_key}.wav')
    if not os.path.exists(path):
        return '', 404
    return send_file(path, mimetype='audio/wav')


# ════════════════════════════════════════════════════════════════════════════
# Export API
# ════════════════════════════════════════════════════════════════════════════

def _ensure_audio_for_chapter(book_id: int, chapter_id: int, segs: list[dict], job: dict | None = None):
    """Generate TTS for any segment in segs that has no audio yet, updating DB and segs in-place."""
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
    for seg in segs:
        if seg.get('audio_path') and os.path.exists(seg['audio_path']):
            if job is not None:
                job['done'] = job.get('done', 0) + 1
            continue
        char = chars.get(seg['character_name']) if seg['character_name'] else None
        if char:
            ref_audio = char['ref_audio_path'] if char.get('ref_audio_path') else None
            ref_text = (char.get('ref_text') or None) if ref_audio else None
        else:
            ref_audio = narrator_ref
            ref_text = narrator_ref_text
        try:
            result = tts.generate(
                text=seg['enriched_text'],
                instruct=seg['instruct'],
                ref_audio=ref_audio,
                ref_text=ref_text,
                speed=seg['speed'],
                language=language,
            )
            with get_conn() as conn:
                conn.execute(
                    'UPDATE tts_segments SET audio_path=?, duration_sec=?, cache_key=? WHERE id=?',
                    (result['audio_path'], result['duration_sec'], result['cache_key'], seg['id'])
                )
            seg['audio_path'] = result['audio_path']
            seg['duration_sec'] = result['duration_sec']
            seg['cache_key'] = result['cache_key']
        except Exception as e:
            log.warning('Audio generation failed for segment %s: %s', seg.get('id'), e)
        if job is not None:
            job['done'] = job.get('done', 0) + 1


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


def _make_export_job() -> tuple[str, dict]:
    job_id = str(uuid.uuid4())
    job: dict = {'state': 'pending', 'message': 'Starting...', 'done': 0, 'total': 0, 'result': None, 'error': None}
    _export_jobs[job_id] = job
    return job_id, job


def _run_chapter_export(job_id: str, book_id: int, chapter_id: int, audio_fmt: str, sub_fmt: str):
    job = _export_jobs[job_id]
    try:
        job['state'] = 'running'
        job['message'] = 'Loading segments...'
        with get_conn() as conn:
            ch = conn.execute('SELECT * FROM chapters WHERE id=? AND book_id=?',
                              (chapter_id, book_id)).fetchone()
            book = conn.execute('SELECT title FROM books WHERE id=?', (book_id,)).fetchone()
        if not ch:
            job['state'] = 'failed'
            job['error'] = 'Chapter not found'
            return
        segs = _get_chapter_segments(chapter_id, book_id)
        job['total'] = len(segs)
        job['done'] = 0
        job['message'] = f'Generating audio ({len(segs)} segments)...'
        _ensure_audio_for_chapter(book_id, chapter_id, segs, job)
        job['message'] = 'Merging audio...'
        colors = _get_char_colors(book_id)
        result = exporter.export_single_chapter(ch['title'], book['title'], segs, colors, audio_fmt, sub_fmt)
        job['state'] = 'complete'
        job['message'] = 'Done'
        job['result'] = {
            'audio_download': f'/api/export/download?path={result["audio_path"]}',
            'subtitle_download': f'/api/export/download?path={result["subtitle_path"]}',
        }
    except Exception as e:
        log.exception('Export job %s failed', job_id)
        job['state'] = 'failed'
        job['error'] = str(e)


def _run_full_export(job_id: str, book_id: int, audio_fmt: str, sub_fmt: str):
    job = _export_jobs[job_id]
    try:
        job['state'] = 'running'
        job['message'] = 'Loading chapters...'
        with get_conn() as conn:
            book = conn.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
            chapters = conn.execute(
                'SELECT id FROM chapters WHERE book_id=? ORDER BY order_num', (book_id,)
            ).fetchall()
        chapters_segs: list[tuple[int, list[dict]]] = []
        for ch in chapters:
            segs = _get_chapter_segments(ch['id'], book_id)
            chapters_segs.append((ch['id'], segs))
        total = sum(len(s) for _, s in chapters_segs)
        job['total'] = total
        job['done'] = 0
        job['message'] = f'Generating audio ({total} segments)...'
        for ch_id, segs in chapters_segs:
            _ensure_audio_for_chapter(book_id, ch_id, segs, job)
        job['message'] = 'Merging audio...'
        all_segs = [s for _, segs in chapters_segs for s in segs]
        colors = _get_char_colors(book_id)
        result = exporter.export_full_book(book['title'], all_segs, colors, audio_fmt, sub_fmt)
        job['state'] = 'complete'
        job['message'] = 'Done'
        job['result'] = {
            'audio_download': f'/api/export/download?path={result["audio_path"]}',
            'subtitle_download': f'/api/export/download?path={result["subtitle_path"]}',
        }
    except Exception as e:
        log.exception('Export job %s failed', job_id)
        job['state'] = 'failed'
        job['error'] = str(e)


def _run_chapterwise_export(job_id: str, book_id: int, audio_fmt: str, sub_fmt: str):
    job = _export_jobs[job_id]
    try:
        job['state'] = 'running'
        job['message'] = 'Loading chapters...'
        with get_conn() as conn:
            book = conn.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
            chapters = conn.execute(
                'SELECT id, title FROM chapters WHERE book_id=? ORDER BY order_num', (book_id,)
            ).fetchall()
        chapters_data: list[dict] = []
        for ch in chapters:
            segs = _get_chapter_segments(ch['id'], book_id)
            chapters_data.append({'chapter_title': ch['title'], 'ch_id': ch['id'], 'segments': segs})
        total = sum(len(c['segments']) for c in chapters_data)
        job['total'] = total
        job['done'] = 0
        job['message'] = f'Generating audio ({total} segments)...'
        for ch_data in chapters_data:
            _ensure_audio_for_chapter(book_id, ch_data['ch_id'], ch_data['segments'], job)
        job['message'] = 'Packaging ZIP...'
        colors = _get_char_colors(book_id)
        zip_path = exporter.export_chapter_zip(
            book['title'],
            [{'chapter_title': c['chapter_title'], 'segments': c['segments']} for c in chapters_data if c['segments']],
            colors, audio_fmt, sub_fmt,
        )
        job['state'] = 'complete'
        job['message'] = 'Done'
        job['result'] = {'zip_download': f'/api/export/download?path={zip_path}'}
    except Exception as e:
        log.exception('Export job %s failed', job_id)
        job['state'] = 'failed'
        job['error'] = str(e)


def _resolve_sub_fmt(book_id: int, requested: str) -> str:
    book = _load_book(book_id)
    if book and _book_single_narrator_mode(dict(book)):
        return 'srt'
    return requested


@app.route('/api/books/<int:book_id>/export/chapter/<int:chapter_id>', methods=['POST'])
def export_chapter(book_id, chapter_id):
    body = request.get_json(force=True) or {}
    audio_fmt = body.get('audio_fmt', 'wav')
    sub_fmt = _resolve_sub_fmt(book_id, body.get('sub_fmt', 'srt'))

    if tts.status()['state'] != 'ready':
        return jsonify({'error': 'TTS model not ready'}), 503

    job_id, _ = _make_export_job()
    threading.Thread(
        target=_run_chapter_export,
        args=(job_id, book_id, chapter_id, audio_fmt, sub_fmt),
        daemon=True,
    ).start()
    return jsonify({'job_id': job_id})


@app.route('/api/books/<int:book_id>/export/full', methods=['POST'])
def export_full(book_id):
    body = request.get_json(force=True) or {}
    audio_fmt = body.get('audio_fmt', 'wav')
    sub_fmt = _resolve_sub_fmt(book_id, body.get('sub_fmt', 'srt'))

    if tts.status()['state'] != 'ready':
        return jsonify({'error': 'TTS model not ready'}), 503

    job_id, _ = _make_export_job()
    threading.Thread(
        target=_run_full_export,
        args=(job_id, book_id, audio_fmt, sub_fmt),
        daemon=True,
    ).start()
    return jsonify({'job_id': job_id})


@app.route('/api/books/<int:book_id>/export/chapterwise', methods=['POST'])
def export_chapterwise(book_id):
    body = request.get_json(force=True) or {}
    audio_fmt = body.get('audio_fmt', 'wav')
    sub_fmt = _resolve_sub_fmt(book_id, body.get('sub_fmt', 'srt'))

    if tts.status()['state'] != 'ready':
        return jsonify({'error': 'TTS model not ready'}), 503

    job_id, _ = _make_export_job()
    threading.Thread(
        target=_run_chapterwise_export,
        args=(job_id, book_id, audio_fmt, sub_fmt),
        daemon=True,
    ).start()
    return jsonify({'job_id': job_id})


@app.route('/api/export/status/<job_id>')
def export_job_status(job_id):
    job = _export_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Unknown job'}), 404
    return jsonify(job)


@app.route('/api/export/download')
def export_download():
    path = request.args.get('path', '')
    exports_dir = os.path.abspath(exporter.EXPORTS_DIR)
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(exports_dir):
        return 'Forbidden', 403
    if not os.path.exists(abs_path):
        return 'Not found', 404
    return send_file(abs_path, as_attachment=True)


# ════════════════════════════════════════════════════════════════════════════
# Bookmarks API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/books/<int:book_id>/bookmarks')
def list_bookmarks(book_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT b.*, c.title as chapter_title FROM bookmarks b '
            'JOIN chapters c ON b.chapter_id = c.id '
            'WHERE b.book_id=? ORDER BY b.created_at DESC',
            (book_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/books/<int:book_id>/bookmarks', methods=['POST'])
def add_bookmark(book_id):
    body = request.get_json(force=True) or {}
    chapter_id = body.get('chapter_id')
    segment_index = body.get('segment_index', 0)
    text_excerpt = (body.get('text_excerpt', '') or '')[:200]
    label = body.get('label', '')
    if not chapter_id:
        return jsonify({'error': 'chapter_id required'}), 400
    with get_conn() as conn:
        cur = conn.execute(
            'INSERT INTO bookmarks (book_id, chapter_id, segment_index, text_excerpt, label) '
            'VALUES (?,?,?,?,?)',
            (book_id, chapter_id, segment_index, text_excerpt, label)
        )
    return jsonify({'ok': True, 'id': cur.lastrowid})


@app.route('/api/books/<int:book_id>/bookmarks/<int:bm_id>', methods=['DELETE'])
def delete_bookmark(book_id, bm_id):
    with get_conn() as conn:
        conn.execute('DELETE FROM bookmarks WHERE id=? AND book_id=?', (bm_id, book_id))
    return jsonify({'ok': True})


# ════════════════════════════════════════════════════════════════════════════
# Settings API
# ════════════════════════════════════════════════════════════════════════════

@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(app_settings.load())


@app.route('/api/settings', methods=['POST'])
def save_settings():
    body = request.get_json(force=True) or {}
    previous = app_settings.load()
    allowed = {
        'model_source', 'model_path', 'model_repo', 'hf_endpoint',
        'narrator_instruct', 'single_narrator_mode', 'default_speed', 'audio_format',
        'subtitle_format', 'theme', 'font_size', 'font_family', 'line_height',
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    result = app_settings.save(updates)

    # If model path changed, reset TTS so it reloads from new path
    if 'model_path' in updates:
        tts.model_path = updates['model_path']
        tts._ready = False
        tts._error = None
        tts.model = None

    if 'narrator_instruct' in updates and updates['narrator_instruct'] != previous.get('narrator_instruct'):
        with get_conn() as conn:
            conn.execute(
                'DELETE FROM tts_segments WHERE book_id IN (SELECT id FROM books WHERE narrator_instruct IS NULL)'
            )

    return jsonify({'ok': True, 'settings': result})


@app.route('/api/settings/spacy-status')
def spacy_status_route():
    status = app_settings.spacy_status()
    status['error'] = char_module.spacy_error()
    return jsonify(status)


@app.route('/api/settings/spacy-install', methods=['POST'])
def spacy_install():
    result = app_settings.install_spacy_model()
    if result['ok']:
        # Reset spaCy NLP so it reloads the new model
        import core.characters as cm
        cm._nlp = None
        cm._spacy_error = ''
    return jsonify(result)


@app.route('/api/settings/model-download', methods=['POST'])
def start_download():
    body = request.get_json(force=True) or {}
    repo_id = body.get('repo_id', app_settings.get('model_repo', 'k2-fsa/OmniVoice'))
    dest = body.get('dest', app_settings.get('model_path'))
    hf_endpoint = body.get('hf_endpoint', app_settings.get('hf_endpoint', ''))
    app_settings.start_model_download(repo_id, dest, hf_endpoint)
    return jsonify({'ok': True, 'dest': dest})


@app.route('/api/settings/model-download/progress')
def download_progress():
    return jsonify(app_settings.download_state())


@app.route('/api/settings/tts-reload', methods=['POST'])
def tts_reload():
    tts.reload()
    return jsonify({'ok': True})


@app.route('/api/settings/check-model-path', methods=['POST'])
def check_model_path():
    body = request.get_json(force=True) or {}
    path = body.get('path', '')
    exists = os.path.isdir(path)
    has_config = os.path.exists(os.path.join(path, 'config.json'))
    return jsonify({'exists': exists, 'has_config': has_config, 'path': path})


# ════════════════════════════════════════════════════════════════════════════
# Run
# ════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=7860, debug=False, threaded=True)
