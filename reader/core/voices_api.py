"""Character and narrator voices: listing, editing, previews and reference audio."""

import logging
import os
import uuid
from flask import Blueprint, jsonify, request
from core.database import get_conn

import app as application

bp = Blueprint('voices', __name__)
log = logging.getLogger(__name__)

_NOT_AUDIO = 'A referenciahang hangfájl legyen (WAV, MP3, FLAC, OGG, M4A…)'


@bp.route('/api/books/<int:book_id>/characters')
def list_characters(book_id):
    chapter_id = request.args.get('chapter_id', type=int)
    chapter_character_names = None
    if chapter_id is not None:
        with get_conn() as conn:
            chapter = conn.execute(
                'SELECT id FROM chapters WHERE id=? AND book_id=?',
                (chapter_id, book_id),
            ).fetchone()
        if not chapter:
            return jsonify({'error': 'A fejezet nem található'}), 404
        chapter_character_names = {
            str(segment['character_name']).casefold()
            for segment in application._compute_segments_for_chapter(
                book_id,
                chapter_id,
                single_narrator_mode=False,
            )
            if segment['character_name']
        }

    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM characters WHERE book_id=? ORDER BY frequency DESC',
            (book_id,)
        ).fetchall()
        # Rule-based attribution (no language model) lives in the segments,
        # not in speaker_annotations; count whichever is larger.
        segment_lines = {
            row[0]: row[1] for row in conn.execute(
                'SELECT character_name, COUNT(*) FROM tts_segments '
                'WHERE book_id=? AND character_name IS NOT NULL GROUP BY character_name',
                (book_id,))
        }
    characters = [dict(r) for r in rows]
    for character in characters:
        character['line_count'] = max(int(character.get('frequency') or 0),
                                      int(segment_lines.get(character['name'], 0)))
    characters.sort(key=lambda c: -c['line_count'])
    if chapter_character_names is not None:
        characters = [
            character
            for character in characters
            if str(character['name']).casefold() in chapter_character_names
        ]
    return jsonify(characters)


@bp.route('/api/books/<int:book_id>/characters/<int:char_id>', methods=['PUT'])
def update_character(book_id, char_id):
    body = request.get_json(force=True)
    allowed = {'instruct', 'gender', 'color_hex', 'ref_text'}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'Nincs mit módosítani'}), 400
    set_clause = ', '.join(f'{k}=?' for k in updates)
    with get_conn() as conn:
        prev = conn.execute(
            'SELECT ref_audio_path, ref_text FROM characters WHERE id=? AND book_id=?',
            (char_id, book_id),
        ).fetchone()
        conn.execute(
            f'UPDATE characters SET {set_clause} WHERE id=? AND book_id=?',
            (*updates.values(), char_id, book_id)
        )
    if prev and prev['ref_audio_path'] and 'ref_text' in updates:
        application.tts.invalidate_voice_prompt(prev['ref_audio_path'], prev['ref_text'])
        application.tts.invalidate_voice_prompt(prev['ref_audio_path'], updates.get('ref_text'))
    application._clear_book_tts_segments(book_id)
    return jsonify({'ok': True, 'segments_cleared': True})


@bp.route('/api/books/<int:book_id>/characters/<int:char_id>/preview', methods=['POST'])
def preview_character(book_id, char_id):
    body = request.get_json(silent=True) or {}
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM characters WHERE id=? AND book_id=?',
                           (char_id, book_id)).fetchone()
    if not row:
        return jsonify({'error': 'Nem található'}), 404

    status = application.tts.status()
    if status['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen', 'status': status}), 503

    instruct = (body.get('instruct') or row['instruct'] or '').strip()
    ref_audio = row['ref_audio_path'] if row['ref_audio_path'] else None
    requested_ref_text = body.get('ref_text', row['ref_text'])
    ref_text = requested_ref_text.strip() if ref_audio and isinstance(requested_ref_text, str) and requested_ref_text.strip() else None
    book = application._load_book(book_id)
    language = book['language'] or 'hu'
    sample_text = str(body.get('text') or (
        'A délutáni fényben csendesen lapoztam a könyvet. Új történet kezdődik.'
        if language == 'hu' else application.VOICE_PREVIEW_TEXT
    )).strip()[:1500]

    try:
        result = application.tts.generate_preview(
            instruct=instruct,
            sample_text=sample_text,
            language=language,
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        return jsonify({'audio_url': f'/api/audio/{result["cache_key"]}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/books/<int:book_id>/narrator', methods=['GET'])
def get_narrator(book_id):
    book = application._load_book(book_id)
    if not book:
        return jsonify({'error': 'Nem található'}), 404
    book_data = dict(book)
    return jsonify({
        'instruct': application._book_narrator_instruct(book_data),
        'single_narrator_mode': application._book_single_narrator_mode(book_data),
        'ref_audio_name': book_data.get('narrator_ref_audio_name'),
        'ref_text': book_data.get('narrator_ref_text') or '',
    })


@bp.route('/api/books/<int:book_id>/narrator', methods=['PUT'])
def update_narrator(book_id):
    body = request.get_json(force=True) or {}
    book = application._load_book(book_id)
    if not book:
        return jsonify({'error': 'Nem található'}), 404
    book_data = dict(book)

    raw_instruct = body.get('instruct')
    instruct = (
        raw_instruct.strip()
        if isinstance(raw_instruct, str)
        else application._book_narrator_instruct(book_data)
    )
    if not instruct:
        return jsonify({'error': 'A narrátor hangleírása kötelező'}), 400

    raw_mode = body.get('single_narrator_mode', application._book_single_narrator_mode(book_data))
    if isinstance(raw_mode, str):
        single_narrator_mode = raw_mode.strip().lower() in {'1', 'true', 'yes', 'on'}
    else:
        single_narrator_mode = bool(raw_mode)
    narrator_changed = instruct != application._book_narrator_instruct(book_data)
    mode_changed = single_narrator_mode != application._book_single_narrator_mode(book_data)
    raw_ref_text = body.get('ref_text', book_data.get('narrator_ref_text') or '')
    ref_text = raw_ref_text.strip() if isinstance(raw_ref_text, str) else ''
    ref_text_changed = ref_text != (book_data.get('narrator_ref_text') or '')

    with get_conn() as conn:
        if ref_text_changed and book_data.get('narrator_ref_audio_path'):
            application.tts.invalidate_voice_prompt(
                book_data['narrator_ref_audio_path'],
                book_data.get('narrator_ref_text'),
            )
            application.tts.invalidate_voice_prompt(
                book_data['narrator_ref_audio_path'],
                ref_text or None,
            )
        conn.execute(
            'UPDATE books SET narrator_instruct=?, single_narrator_mode=?, '
            'narrator_ref_text=? WHERE id=?',
            (instruct, int(single_narrator_mode), ref_text, book_id)
        )

    if narrator_changed or mode_changed or ref_text_changed:
        application._clear_book_tts_segments(book_id)

    return jsonify({
        'ok': True,
        'instruct': instruct,
        'single_narrator_mode': single_narrator_mode,
        'ref_text': ref_text,
        'segments_cleared': narrator_changed or mode_changed or ref_text_changed,
    })


@bp.route('/api/books/<int:book_id>/characters/narrator/preview', methods=['POST'])
def preview_narrator(book_id):
    body = request.get_json(silent=True) or {}
    book = application._load_book(book_id)
    if not book:
        return jsonify({'error': 'Nem található'}), 404

    status = application.tts.status()
    if status['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen', 'status': status}), 503

    instruct = (body.get('instruct') or application._book_narrator_instruct(dict(book))).strip()
    narrator_ref, saved_ref_text = application._book_narrator_reference(book_id)
    requested_ref_text = body.get('ref_text', saved_ref_text)
    narrator_ref_text = requested_ref_text.strip() if narrator_ref and isinstance(requested_ref_text, str) and requested_ref_text.strip() else None
    try:
        result = application.tts.generate_preview(
            instruct=instruct,
            sample_text=str(body.get('text') or (
                'A délutáni fényben csendesen lapoztam a könyvet. Új történet kezdődik.'
                if (book['language'] or 'hu') == 'hu' else application.VOICE_PREVIEW_TEXT
            )).strip()[:1500],
            language=book['language'] or 'hu',
            ref_audio=narrator_ref,
            ref_text=narrator_ref_text,
        )
        return jsonify({'audio_url': f'/api/audio/{result["cache_key"]}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/characters/<int:char_id>/ref-audio', methods=['POST'])
def upload_ref_audio(char_id):
    if 'file' not in request.files:
        return jsonify({'error': 'Nincs kiválasztott fájl'}), 400
    f = request.files['file']
    from core.reference_audio import is_audio_filename
    if not f.filename or not is_audio_filename(f.filename):
        return jsonify({'error': _NOT_AUDIO}), 400
    ref_text = (request.form.get('ref_text') or '').strip()
    with get_conn() as conn:
        row = conn.execute(
            'SELECT book_id, ref_audio_path, ref_text FROM characters WHERE id=?',
            (char_id,),
        ).fetchone()
        if not row:
            return jsonify({'error': 'Nem található'}), 404
        if row['ref_audio_path']:
            application.tts.invalidate_voice_prompt(row['ref_audio_path'], row['ref_text'])
    try:
        path = application._save_reference_upload(f, f'ref_{char_id}', clean=request.form.get('clean') == '1')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    with get_conn() as conn:
        conn.execute(
            'UPDATE characters SET ref_audio_path=?, ref_audio_name=?, ref_text=? WHERE id=?',
            (path, os.path.basename(f.filename), ref_text, char_id),
        )
    application._delete_replaced_reference(row['ref_audio_path'], path, f'ref_{char_id}')
    application._clear_book_tts_segments(row['book_id'])
    return jsonify({
        'ok': True,
        'ref_audio_name': os.path.basename(f.filename),
        'ref_text': ref_text,
    })


@bp.route('/api/characters/<int:char_id>/ref-audio', methods=['DELETE'])
def delete_ref_audio(char_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT book_id, ref_audio_path, ref_text FROM characters WHERE id=?',
            (char_id,),
        ).fetchone()
        if not row:
            return jsonify({'error': 'Nem található'}), 404
        conn.execute(
            'UPDATE characters SET ref_audio_path=NULL, ref_audio_name=NULL, ref_text=NULL '
            'WHERE id=?', (char_id,)
        )
    if row['ref_audio_path']:
        application.tts.invalidate_voice_prompt(row['ref_audio_path'], row['ref_text'])
    application._delete_file_if_exists(row['ref_audio_path'])
    application._clear_book_tts_segments(row['book_id'])
    return jsonify({'ok': True, 'segments_cleared': True})


@bp.route('/api/books/<int:book_id>/narrator-ref-audio', methods=['POST'])
def upload_narrator_ref_audio(book_id):
    if 'file' not in request.files:
        return jsonify({'error': 'Nincs kiválasztott fájl'}), 400
    f = request.files['file']
    from core.reference_audio import is_audio_filename
    if not f.filename or not is_audio_filename(f.filename):
        return jsonify({'error': _NOT_AUDIO}), 400
    ref_text = (request.form.get('ref_text') or '').strip()
    with get_conn() as conn:
        prev = conn.execute(
            'SELECT narrator_ref_audio_path, narrator_ref_text FROM books WHERE id=?',
            (book_id,),
        ).fetchone()
        if not prev:
            return jsonify({'error': 'Nem található'}), 404
        if prev['narrator_ref_audio_path']:
            application.tts.invalidate_voice_prompt(
                prev['narrator_ref_audio_path'], prev['narrator_ref_text']
            )
    try:
        path = application._save_reference_upload(f, f'narrator_ref_{book_id}', clean=request.form.get('clean') == '1')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    with get_conn() as conn:
        conn.execute(
            'UPDATE books SET narrator_ref_audio_path=?, narrator_ref_audio_name=?, '
            'narrator_ref_text=? WHERE id=?',
            (path, os.path.basename(f.filename), ref_text, book_id),
        )
    application._delete_replaced_reference(
        prev['narrator_ref_audio_path'], path, f'narrator_ref_{book_id}'
    )
    application.tts.invalidate_voice_prompt(path, ref_text or None)
    application._clear_book_tts_segments(book_id)
    return jsonify({
        'ok': True,
        'ref_audio_name': os.path.basename(f.filename),
        'ref_text': ref_text,
    })


@bp.route('/api/books/<int:book_id>/narrator-ref-audio', methods=['DELETE'])
def delete_narrator_ref_audio(book_id):
    with get_conn() as conn:
        row = conn.execute(
            'SELECT narrator_ref_audio_path, narrator_ref_text FROM books WHERE id=?',
            (book_id,),
        ).fetchone()
        if not row:
            return jsonify({'error': 'Nem található'}), 404
        path = row['narrator_ref_audio_path']
        ref_text = row['narrator_ref_text']
        conn.execute(
            'UPDATE books SET narrator_ref_audio_path=NULL, narrator_ref_audio_name=NULL, '
            'narrator_ref_text=NULL WHERE id=?', (book_id,)
        )

    if path:
        application.tts.invalidate_voice_prompt(path, ref_text)
    application._delete_file_if_exists(path)
    application._clear_book_tts_segments(book_id)
    return jsonify({'ok': True, 'segments_cleared': True})


# ── Reference check and trimming (characters and narrator alike) ────────────

def _reference_owner(kind: str, key: int) -> dict | None:
    with get_conn() as conn:
        if kind == 'narrator':
            row = conn.execute(
                'SELECT id AS book_id, narrator_ref_audio_path AS path, narrator_ref_audio_name AS name, '
                'narrator_ref_text AS text, language FROM books WHERE id=?', (key,),
            ).fetchone()
        else:
            row = conn.execute(
                'SELECT c.book_id, c.ref_audio_path AS path, c.ref_audio_name AS name, '
                'c.ref_text AS text, b.language FROM characters c JOIN books b ON b.id=c.book_id '
                'WHERE c.id=?', (key,),
            ).fetchone()
    if not row:
        return None
    prefix = f'narrator_ref_{key}' if kind == 'narrator' else f'ref_{key}'
    return dict(row, kind=kind, key=key, prefix=prefix)


def _save_reference_fields(owner: dict, path: str, name: str | None, text: str | None) -> None:
    with get_conn() as conn:
        if owner['kind'] == 'narrator':
            conn.execute(
                'UPDATE books SET narrator_ref_audio_path=?, narrator_ref_audio_name=?, '
                'narrator_ref_text=? WHERE id=?', (path, name, text, owner['key']),
            )
        else:
            conn.execute(
                'UPDATE characters SET ref_audio_path=?, ref_audio_name=?, ref_text=? WHERE id=?',
                (path, name, text, owner['key']),
            )
    application.tts.invalidate_voice_prompt(owner['path'], owner['text'])
    application.tts.invalidate_voice_prompt(path, text or None)
    application._delete_replaced_reference(owner['path'], path, owner['prefix'])
    application._clear_book_tts_segments(owner['book_id'])


def _check_reference(kind: str, key: int):
    """Inspect the stored reference; an empty transcript is filled from ASR."""
    from core import qa, reference_audio, settings

    owner = _reference_owner(kind, key)
    if not owner:
        return jsonify({'error': 'Nem található'}), 404
    if not owner['path'] or not os.path.exists(owner['path']):
        return jsonify({'error': 'Nincs feltöltött referenciahang.'}), 400
    language = owner['language'] or 'hu'
    try:
        report = reference_audio.inspect_reference(
            owner['path'], owner['text'], language, qa.Transcriber.whisper_for(language))
    except Exception as exc:
        log.warning('Reference check failed for %s %s: %s', kind, key, exc)
        return jsonify({'error': f'Az ellenőrzés nem sikerült: {exc}'}), 500
    finally:
        if not settings.get('asr_keep_loaded', False):
            qa.Transcriber.unload_all()
    report['ref_text'] = owner['text'] or ''
    report['ref_text_saved'] = False
    if not (owner['text'] or '').strip() and report['suggested_text']:
        _save_reference_fields(owner, owner['path'], owner['name'], report['suggested_text'])
        report['ref_text'], report['ref_text_saved'] = report['suggested_text'], True
    return jsonify(report)


def _trim_reference(kind: str, key: int):
    """Replace the reference with one of its stretches and that stretch's text."""
    from core import reference_audio

    owner = _reference_owner(kind, key)
    if not owner:
        return jsonify({'error': 'Nem található'}), 404
    if not owner['path'] or not os.path.exists(owner['path']):
        return jsonify({'error': 'Nincs feltöltött referenciahang.'}), 400
    body = request.get_json(silent=True) or {}
    try:
        start, end = float(body.get('start')), float(body.get('end'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Hibás kezdő- vagy végpont.'}), 400
    text = str(body.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'A kivágott szakasz átirata hiányzik.'}), 400
    tmp = os.path.join(application.UPLOAD_DIR, f'.{owner["prefix"]}.{uuid.uuid4().hex}.cut.wav')
    try:
        duration = reference_audio.cut_reference(owner['path'], tmp, start, end)
    except ValueError as exc:
        application._delete_file_if_exists(tmp)
        return jsonify({'error': str(exc)}), 400
    path = application._store_reference_file(tmp, owner['prefix'])
    stem = os.path.splitext(owner['name'] or 'referencia')[0].split(' · ')[0]
    span = f'{start:.1f}–{end:.1f}'.replace('.', ',')
    name = f'{stem} · {span} s.wav'
    _save_reference_fields(owner, path, name, text)
    return jsonify({'ok': True, 'ref_audio_name': name, 'ref_text': text,
                    'duration': round(duration, 2), 'segments_cleared': True})


@bp.route('/api/characters/<int:char_id>/ref-audio/check', methods=['POST'])
def check_character_ref_audio(char_id):
    return _check_reference('character', char_id)


@bp.route('/api/books/<int:book_id>/narrator-ref-audio/check', methods=['POST'])
def check_narrator_ref_audio(book_id):
    return _check_reference('narrator', book_id)


@bp.route('/api/characters/<int:char_id>/ref-audio/trim', methods=['POST'])
def trim_character_ref_audio(char_id):
    return _trim_reference('character', char_id)


@bp.route('/api/books/<int:book_id>/narrator-ref-audio/trim', methods=['POST'])
def trim_narrator_ref_audio(book_id):
    return _trim_reference('narrator', book_id)
