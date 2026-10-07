"""Export routes and job runners: audio formats, publishing packages, credits, music."""

import os
import shutil
import uuid
from flask import jsonify, request, send_file
from core.database import get_conn
from core import sfx
from core.tts_engine import TTSExportPool
from core import exporter, jobs, settings as app_settings
from flask import Blueprint

import app as application

bp = Blueprint('export_api', __name__)


def _make_export_job(job_type: str, input_data: dict) -> tuple[str, dict]:
    stored = jobs.create_job(
        job_type,
        input_data,
        book_id=input_data.get('book_id'),
        chapter_id=input_data.get('chapter_id'),
    )
    job_id = stored['id']
    job = application._legacy_job(stored)
    application._export_jobs[job_id] = job
    return job_id, job


EXPORT_AUDIO_FORMATS = ('wav', 'mp3', 'm4b', 'opus', 'flac')


EXPORT_PACKAGES = ('none', 'epub3', 'audiobookshelf', 'acx', 'daw')


DEFAULT_INTRO_TEMPLATE = '{title}. Írta: {author}. Felolvassa: {narrator}.'


DEFAULT_OUTRO_TEMPLATE = 'Vége. {title}. Írta: {author}.'


def _export_options(body: dict) -> dict:
    package = str(body.get('package') or 'none')
    if package not in EXPORT_PACKAGES:
        raise ValueError('Ismeretlen kiadási csomag.')
    return {
        'package': package,
        'intro': bool(body.get('intro', False)),
        'outro': bool(body.get('outro', False)),
        'sample': bool(body.get('sample', package == 'acx')),
        'abs_upload': bool(body.get('abs_upload', False)),
        'take_mode': _take_mode(body.get('take_mode')),
    }


def _take_mode(value) -> str:
    from core.take_selection import TAKE_MODES

    mode = str(value or 'normal')
    if mode not in TAKE_MODES:
        raise ValueError('Ismeretlen take-választási mód.')
    return mode


def _select_takes(job, book_id: int, segs: list[dict], export_pool) -> None:
    """Optional best-of-N pass after the normal render (export option take_mode)."""
    from core import take_selection

    mode = ((job.get('input') or {}).get('options') or {}).get('take_mode', 'normal')
    if mode != 'normal':
        take_selection.select_export_takes(application, book_id, segs, job, mode, export_pool=export_pool)
        application._check_job_cancelled(job)


def _book_background(book) -> dict | None:
    book = dict(book) if book else {}
    path = book.get('bg_music_path')
    if path and os.path.isfile(path):
        try:
            level = float(book.get('bg_music_db') if book.get('bg_music_db') is not None else -22)
        except (TypeError, ValueError):
            level = -22.0
        return {'path': path, 'db': max(-40.0, min(-6.0, level))}
    return None


def _credit_text(template: str, book: dict) -> str:
    narrator = (book.get('narrator_credit') or app_settings.get('narrator_credit', '')
                or 'mesterséges hang')
    values = {
        'title': book.get('title') or '', 'author': book.get('author') or '',
        'narrator': narrator, 'series': book.get('series') or '',
        'cím': book.get('title') or '', 'szerző': book.get('author') or '',
        'narrátor': narrator,
    }
    try:
        text = str(template or '').format(**values)
    except (KeyError, IndexError, ValueError):
        text = str(template or '')
    return ' '.join(text.split())


def _credit_chapter(book_id: int, book: dict, kind: str) -> dict | None:
    """Synthesize an opening or closing credit with the narrator's voice."""
    template = app_settings.get(
        f'export_{kind}_template',
        DEFAULT_INTRO_TEMPLATE if kind == 'intro' else DEFAULT_OUTRO_TEMPLATE,
    )
    text = _credit_text(template, book)
    if not text:
        return None
    ref_audio, ref_text = application._book_narrator_reference(book_id)
    instruct = book.get('narrator_instruct') or application._default_narrator_instruct()
    result = application.tts.generate(
        text=text, instruct=instruct, ref_audio=ref_audio, ref_text=ref_text,
        speed=1.0, language=book.get('language') or None,
    )
    title = 'Nyitó szöveg' if kind == 'intro' else 'Záró szöveg'
    return {
        'chapter_number': 0 if kind == 'intro' else 9999,
        'chapter_title': title,
        'segments': [{
            'audio_path': result['audio_path'], 'duration_sec': result['duration_sec'],
            'cache_key': result['cache_key'], 'text': text, 'ends_paragraph': 1,
            'block_kind': 'paragraph', 'character_name': None, 'segment_index': 0,
        }],
    }


def _publish_metadata(book: dict) -> dict:
    return {
        'title': book.get('title') or '', 'author': book.get('author') or '',
        'language': book.get('language') or 'hu',
        'narrator': book.get('narrator_credit') or app_settings.get('narrator_credit', '') or '',
        'description': book.get('description') or '', 'publisher': book.get('publisher') or '',
        'published': book.get('published') or '', 'series': book.get('series') or '',
        'series_index': book.get('series_index') or '', 'cover_b64': book.get('cover_b64'),
        'identifier': f"auris-book-{book.get('id')}",
    }


def _run_chapter_export(job_id: str, book_id: int, chapter_id: int, audio_fmt: str, sub_fmt: str):
    job = application._export_jobs[job_id]
    export_pool: TTSExportPool | None = None
    application._export_exclusive_begin()
    try:
        application._check_job_cancelled(job)
        job['state'] = 'running'
        job['message'] = 'Szövegrészek betöltése…'
        application._persist_job(job)
        with get_conn() as conn:
            ch = conn.execute('SELECT * FROM chapters WHERE id=? AND book_id=?',
                              (chapter_id, book_id)).fetchone()
            book = conn.execute(
                'SELECT title, author FROM books WHERE id=?', (book_id,)
            ).fetchone()
        if not ch:
            job['state'] = 'failed'
            job['error'] = 'A fejezet nem található'
            job['message'] = 'Az export nem sikerült'
            application._persist_job(job)
            return
        segs = sfx.attach(book_id, chapter_id, application._get_chapter_segments(chapter_id, book_id))
        job['total'] = len(segs)
        job['done'] = 0
        job['message'] = f'Hang készítése (0/{len(segs)})'
        export_pool = application._start_export_pool(job)
        application._ensure_audio_for_chapter(
            book_id, chapter_id, segs, job, export_pool=export_pool
        )
        application._check_job_cancelled(job)
        _select_takes(job, book_id, segs, export_pool)
        job['message'] = 'Hangok összefűzése…'
        colors = application._get_char_colors(book_id)
        mastering = bool(app_settings.get('audio_mastering', True))
        job['message'] = (
            'Hangok összefűzése és hangerő-kiegyenlítése…' if mastering else 'Hangok összefűzése…'
        )
        with get_conn() as conn:
            full_book = conn.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
        background = _book_background(full_book)
        options = (job.get('input') or {}).get('options') or {}
        if audio_fmt == 'm4b':
            result = exporter.export_m4b(
                book['title'], [{
                    'chapter_number': 1,
                    'chapter_title': ch['title'],
                    'segments': segs,
                }], colors, sub_fmt=sub_fmt, book_author=book['author'],
                mastering=mastering, book_metadata=dict(full_book),
                on_progress=lambda message: _export_stage(job, message),
                check_cancelled=lambda: application._check_job_cancelled(job),
                background=background,
            )
        else:
            result = exporter.export_single_chapter(
                ch['title'], book['title'], segs, colors, audio_fmt, sub_fmt,
                mastering=mastering,
                book_author=book['author'],
                background=background,
            )
        if options.get('package') == 'daw':
            from core import publish
            _export_stage(job, 'DAW-csomag készítése…')
            daw_zip = os.path.join(
                os.path.dirname(result['audio_path']),
                f"{exporter._safe_name(ch['title'])}_daw.zip",
            )
            timeline = result.get('timeline') or []
            publish.build_daw_package(ch['title'], timeline, daw_zip)
            result['audio_path'] = daw_zip
        job['state'] = 'complete'
        job['message'] = 'Elkészült'
        job['result'] = {
            'audio_path': result['audio_path'],
            'subtitle_path': result.get('subtitle_path'),
            'audio_download': f'/api/jobs/{job_id}/download/audio',
            'subtitle_download': (
                f'/api/jobs/{job_id}/download/subtitle'
                if result.get('subtitle_path') else None
            ),
            'mastering_applied': result.get('mastering_applied', False),
            'mastering_warning': result.get('mastering_warning'),
        }
        application._persist_job(job)
    except application.JobCancelled:
        jobs.mark_cancelled(job_id, 'Az export leállítva az aktuális csomag után')
        job['state'] = 'cancelled'
    except Exception as e:
        application.log.exception('Export job %s failed', job_id)
        job['state'] = 'failed'
        job['error'] = str(e)
        job['message'] = 'Az export nem sikerült'
        application._persist_job(job)
    finally:
        application._close_orphaned_job(job_id)
        if export_pool is not None:
            export_pool.close()
        application._export_exclusive_end()


def _export_stage(job, message):
    job['message'] = message
    application._persist_job(job)


def _run_chapterwise_export(
    job_id: str,
    book_id: int,
    audio_fmt: str,
    sub_fmt: str,
    chapter_numbers: list[int],
):
    job = application._export_jobs[job_id]
    export_pool: TTSExportPool | None = None
    application._export_exclusive_begin()
    try:
        application._check_job_cancelled(job)
        job['state'] = 'running'
        job['message'] = 'Fejezetek betöltése…'
        application._persist_job(job)
        with get_conn() as conn:
            book = conn.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
            chapters = conn.execute(
                'SELECT id, title FROM chapters WHERE book_id=? ORDER BY order_num', (book_id,)
            ).fetchall()
        chapters_data: list[dict] = []
        selected = set(chapter_numbers)
        for chapter_number, ch in enumerate(chapters, 1):
            if chapter_number not in selected:
                continue
            segs = sfx.attach(book_id, ch['id'], application._get_chapter_segments(ch['id'], book_id))
            chapters_data.append({
                'chapter_number': chapter_number,
                'chapter_title': ch['title'],
                'ch_id': ch['id'],
                'segments': segs,
            })
        total = sum(len(c['segments']) for c in chapters_data)
        job['total'] = total
        job['done'] = 0
        job['message'] = f'Hang készítése (0/{total})'
        export_pool = application._start_export_pool(job)
        # One synthesis pass for all selected chapters: voice groups and
        # length-sorted GPU packs span chapter boundaries, so packs stay full
        # instead of every chapter ending with a half-empty batch. Segment
        # dicts are shared, so results land in each chapter's list.
        all_segments = [
            seg for ch_data in chapters_data for seg in ch_data['segments']
        ]
        application._check_job_cancelled(job)
        application._ensure_audio_for_chapter(
            book_id,
            chapters_data[0]['ch_id'] if chapters_data else 0,
            all_segments,
            job,
            export_pool=export_pool,
        )
        application._check_job_cancelled(job)
        _select_takes(job, book_id, all_segments, export_pool)
        mastering = bool(app_settings.get('audio_mastering', True))
        job['message'] = (
            'Fejezetfájlok írása és masterelése…'
            if mastering else 'Fejezetfájlok írása…'
        )
        colors = application._get_char_colors(book_id)
        export_chapters = [c for c in chapters_data if c['segments']]
        options = (job.get('input') or {}).get('options') or {}
        package = options.get('package', 'none')
        book_dict = dict(book)
        background = _book_background(book)
        if options.get('intro'):
            _export_stage(job, 'Nyitó szöveg felolvasása…')
            intro = _credit_chapter(book_id, book_dict, 'intro')
            if intro:
                export_chapters.insert(0, intro)
        if options.get('outro'):
            _export_stage(job, 'Záró szöveg felolvasása…')
            outro = _credit_chapter(book_id, book_dict, 'outro')
            if outro:
                export_chapters.append(outro)
        for number, chapter in enumerate(export_chapters, 1):
            chapter['chapter_number'] = number
        package_result = {}
        if package == 'epub3':
            audio_fmt = 'mp3'
        elif package == 'acx':
            audio_fmt = 'mp3'
        if audio_fmt == 'm4b':
            result = exporter.export_m4b(
                book['title'], export_chapters, colors,
                sub_fmt=sub_fmt, book_author=book['author'],
                mastering=mastering, book_metadata=book_dict,
                on_progress=lambda message: _export_stage(job, message),
                check_cancelled=lambda: application._check_job_cancelled(job),
                background=background,
            )
            download_path = result['audio_path']
            audio_files = [result['audio_path']]
        else:
            # One subfolder per target, so an Opus export never ships the
            # MP3 files of an earlier export in its ZIP.
            target_dir = os.path.join(
                exporter._book_export_dir(book['author'], book['title']),
                package if package != 'none' else audio_fmt,
            )
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir, ignore_errors=True)
            result = exporter.export_chapter_folder(
                book['title'], export_chapters,
                colors, audio_fmt, sub_fmt,
                mastering=mastering,
                book_author=book['author'],
                acx=package == 'acx',
                background=background,
                output_dir=target_dir,
            )
            audio_files = [item['audio_path'] for item in result['chapters']]
            download_path = None
        if package != 'none' or options.get('sample'):
            from core import publish
            meta = _publish_metadata(book_dict)
            folder = result.get('directory_path') or os.path.dirname(result['audio_path'])
            if options.get('sample') and audio_files:
                _export_stage(job, 'Ötperces minta készítése…')
                sample_path = os.path.join(folder, f"{exporter._safe_name(book['title'])}_minta.mp3")
                publish.retail_sample(audio_files[0], sample_path)
                package_result['sample_path'] = sample_path
            if package == 'epub3':
                _export_stage(job, 'EPUB3 felolvasós könyv készítése…')
                chapters_for_epub = [
                    {'title': chapter['chapter_title'], 'audio_path': item['audio_path'],
                     'segments': item.get('timeline') or []}
                    for chapter, item in zip(export_chapters, result['chapters'])
                ]
                epub_path = os.path.join(folder, f"{exporter._safe_name(book['title'])}_felolvasos.epub")
                publish.build_epub3_media_overlay(meta, chapters_for_epub, epub_path)
                download_path = epub_path
            elif package == 'audiobookshelf':
                _export_stage(job, 'Audiobookshelf-mappa készítése…')
                abs_root = os.path.join(exporter.EXPORTS_DIR, 'audiobookshelf')
                abs_folder = publish.build_audiobookshelf_folder(
                    meta, audio_files, abs_root, overwrite=True,
                    chapters=[{'title': chapter['chapter_title']} for chapter in export_chapters]
                    if len(audio_files) > 1 else None,
                )
                package_result['audiobookshelf_folder'] = abs_folder
                download_path = shutil.make_archive(abs_folder, 'zip', abs_folder)
                if options.get('abs_upload'):
                    _export_stage(job, 'Feltöltés az Audiobookshelf szerverre…')
                    package_result['audiobookshelf_upload'] = publish.upload_to_audiobookshelf(
                        abs_folder, app_settings.get('abs_url', ''),
                        app_settings.get('abs_api_token', ''),
                        app_settings.get('abs_library_id', ''),
                        folder_id=app_settings.get('abs_folder_id', '') or None,
                    )
        if download_path is None:
            download_path = shutil.make_archive(
                result['directory_path'], 'zip', result['directory_path']
            )
        job['state'] = 'complete'
        job['message'] = 'Elkészült'
        job['result'] = {
            'export_path': result.get('directory_path') or result.get('audio_path'),
            'download_path': download_path,
            'download': f'/api/jobs/{job_id}/download/export',
            'subtitle_path': result.get('subtitle_path'),
            'subtitle_download': (
                f'/api/jobs/{job_id}/download/subtitle'
                if result.get('subtitle_path') else None
            ),
            'chapter_count': result.get('chapter_count', len(export_chapters)),
            'mastering_applied': result.get('mastering_applied', False),
            'mastering_warning': result.get('mastering_warning'),
            'mastered_chapters': sum(
                1 for chapter in result['chapters']
                if chapter.get('mastering_applied')
            ) if result.get('chapters') else 0,
            'package': package,
            **package_result,
        }
        application._persist_job(job)
    except application.JobCancelled:
        jobs.mark_cancelled(job_id, 'Az export leállítva az aktuális csomag után')
        job['state'] = 'cancelled'
    except Exception as e:
        application.log.exception('Export job %s failed', job_id)
        job['state'] = 'failed'
        job['error'] = str(e)
        job['message'] = 'Az export nem sikerült'
        application._persist_job(job)
    finally:
        application._close_orphaned_job(job_id)
        if export_pool is not None:
            export_pool.close()
        application._export_exclusive_end()


def _resolve_sub_fmt(book_id: int, requested: str) -> str:
    if requested == 'none':
        return 'none'
    book = application._load_book(book_id)
    if book and application._book_single_narrator_mode(dict(book)):
        return 'srt'
    return requested


@bp.route('/api/books/<int:book_id>/export/chapter/<int:chapter_id>', methods=['POST'])
def export_chapter(book_id, chapter_id):
    jobs.ensure_jobs()
    body = request.get_json(force=True) or {}
    audio_fmt = body.get('audio_fmt', 'wav')
    sub_fmt = _resolve_sub_fmt(book_id, body.get('sub_fmt', 'srt'))

    if audio_fmt not in EXPORT_AUDIO_FORMATS or sub_fmt not in ('srt', 'ass', 'none'):
        return jsonify({'error': 'Nem támogatott exportformátum'}), 400
    try:
        options = _export_options(body)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if application.tts.status()['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen'}), 503

    with application._work_dispatch_lock:
        conflict = application._work_conflict_response()
        if conflict is not None:
            return conflict
        with application._chapter_generation_lock:
            active_id = application._chapter_generation_active_job_id
            active = application._chapter_generation_jobs.get(active_id) if active_id else None
            if active and active.get('state') in ('pending', 'running'):
                return jsonify({'error': 'Egy fejezethang már készül.'}), 409
        job_id, _ = _make_export_job('export_chapter', {
            'book_id': book_id, 'chapter_id': chapter_id,
            'audio_fmt': audio_fmt, 'sub_fmt': sub_fmt, 'options': options,
        })
        application._launch_durable_job(jobs.get_job(job_id))
        return jsonify({'job_id': job_id})


@bp.route('/api/books/<int:book_id>/export/full', methods=['POST'])
def export_full(book_id):
    jobs.ensure_jobs()
    body = request.get_json(force=True) or {}
    audio_fmt = body.get('audio_fmt', 'wav')
    sub_fmt = _resolve_sub_fmt(book_id, body.get('sub_fmt', 'srt'))

    if audio_fmt not in EXPORT_AUDIO_FORMATS or sub_fmt not in ('srt', 'ass', 'none'):
        return jsonify({'error': 'Nem támogatott exportformátum'}), 400
    try:
        options = _export_options(body)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if options['abs_upload'] and not (
        app_settings.get('abs_url') and app_settings.get('abs_api_token')
        and app_settings.get('abs_library_id')
    ):
        return jsonify({'error': 'Az Audiobookshelf-feltöltéshez add meg a szerver címét, '
                                 'a tokent és a könyvtárat a Beállításokban.'}), 400

    if application.tts.status()['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen'}), 503

    with get_conn() as conn:
        chapter_count = conn.execute(
            'SELECT COUNT(*) FROM chapters WHERE book_id=?', (book_id,)
        ).fetchone()[0]
    chapter_numbers = exporter.parse_chapter_selection('all', chapter_count)
    with application._work_dispatch_lock:
        conflict = application._work_conflict_response()
        if conflict is not None:
            return conflict
        with application._chapter_generation_lock:
            active_id = application._chapter_generation_active_job_id
            active = application._chapter_generation_jobs.get(active_id) if active_id else None
            if active and active.get('state') in ('pending', 'running'):
                return jsonify({'error': 'Egy fejezethang már készül.'}), 409
        job_id, _ = _make_export_job('export_book', {
            'book_id': book_id, 'audio_fmt': audio_fmt, 'sub_fmt': sub_fmt,
            'chapter_numbers': chapter_numbers, 'options': options,
        })
        application._launch_durable_job(jobs.get_job(job_id))
        return jsonify({'job_id': job_id})


@bp.route('/api/books/<int:book_id>/export/chapterwise', methods=['POST'])
def export_chapterwise(book_id):
    jobs.ensure_jobs()
    body = request.get_json(force=True) or {}
    audio_fmt = body.get('audio_fmt', 'wav')
    sub_fmt = _resolve_sub_fmt(book_id, body.get('sub_fmt', 'srt'))

    if audio_fmt not in EXPORT_AUDIO_FORMATS or sub_fmt not in ('srt', 'ass', 'none'):
        return jsonify({'error': 'Nem támogatott exportformátum'}), 400
    try:
        options = _export_options(body)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if options['abs_upload'] and not (
        app_settings.get('abs_url') and app_settings.get('abs_api_token')
        and app_settings.get('abs_library_id')
    ):
        return jsonify({'error': 'Az Audiobookshelf-feltöltéshez add meg a szerver címét, '
                                 'a tokent és a könyvtárat a Beállításokban.'}), 400

    if application.tts.status()['state'] != 'ready':
        return jsonify({'error': 'A beszédmotor még nem áll készen'}), 503

    with get_conn() as conn:
        chapter_count = conn.execute(
            'SELECT COUNT(*) FROM chapters WHERE book_id=?', (book_id,)
        ).fetchone()[0]
    try:
        chapter_numbers = exporter.parse_chapter_selection(
            body.get('chapters'), chapter_count
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    with application._work_dispatch_lock:
        conflict = application._work_conflict_response()
        if conflict is not None:
            return conflict
        with application._chapter_generation_lock:
            active_id = application._chapter_generation_active_job_id
            active = application._chapter_generation_jobs.get(active_id) if active_id else None
            if active and active.get('state') in ('pending', 'running'):
                return jsonify({'error': 'Egy fejezethang már készül.'}), 409
        job_id, _ = _make_export_job('export_book', {
            'book_id': book_id, 'audio_fmt': audio_fmt, 'sub_fmt': sub_fmt,
            'chapter_numbers': chapter_numbers, 'options': options,
        })
        application._launch_durable_job(jobs.get_job(job_id))
        return jsonify({'job_id': job_id})


@bp.route('/api/books/<int:book_id>/background-music', methods=['POST'])
def upload_background_music(book_id):
    f = request.files.get('file')
    allowed = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.opus')
    if not f or not f.filename or not f.filename.lower().endswith(allowed):
        return jsonify({'error': 'Zenefájl szükséges (MP3, WAV, OGG, FLAC, M4A vagy Opus).'}), 400
    book = application._load_book(book_id)
    if not book:
        return jsonify({'error': 'Nem található'}), 404
    suffix = os.path.splitext(f.filename)[1].lower()
    path = os.path.join(application.UPLOAD_DIR, f'bg_music_{book_id}_{uuid.uuid4().hex[:8]}{suffix}')
    f.save(path)
    with get_conn() as conn:
        conn.execute('UPDATE books SET bg_music_path=?, bg_music_name=? WHERE id=?',
                     (path, os.path.basename(f.filename), book_id))
    if book['bg_music_path'] and book['bg_music_path'] != path:
        application._delete_file_if_exists(book['bg_music_path'])
    return jsonify({'ok': True, 'name': os.path.basename(f.filename)})


@bp.route('/api/books/<int:book_id>/background-music', methods=['DELETE'])
def delete_background_music(book_id):
    book = application._load_book(book_id)
    if not book:
        return jsonify({'error': 'Nem található'}), 404
    with get_conn() as conn:
        conn.execute('UPDATE books SET bg_music_path=NULL, bg_music_name=NULL WHERE id=?', (book_id,))
    application._delete_file_if_exists(book['bg_music_path'])
    return jsonify({'ok': True})


@bp.route('/api/books/<int:book_id>/publishing', methods=['GET', 'PATCH'])
def book_publishing(book_id):
    book = application._load_book(book_id)
    if not book:
        return jsonify({'error': 'Nem található'}), 404
    if request.method == 'PATCH':
        body = request.get_json(silent=True) or {}
        updates = {}
        if 'narrator_credit' in body:
            updates['narrator_credit'] = str(body.get('narrator_credit') or '').strip()[:200] or None
        if 'bg_music_db' in body:
            try:
                updates['bg_music_db'] = max(-40.0, min(-6.0, float(body['bg_music_db'])))
            except (TypeError, ValueError):
                return jsonify({'error': 'Érvénytelen zenehangerő.'}), 400
        if updates:
            with get_conn() as conn:
                conn.execute(
                    'UPDATE books SET ' + ', '.join(f'{k}=?' for k in updates) + ' WHERE id=?',
                    (*updates.values(), book_id),
                )
        book = application._load_book(book_id)
    return jsonify({
        'narrator_credit': book['narrator_credit'] or '',
        'bg_music_name': book['bg_music_name'] or '',
        'bg_music_db': book['bg_music_db'] if book['bg_music_db'] is not None else -22,
        'intro_preview': _credit_text(
            app_settings.get('export_intro_template', DEFAULT_INTRO_TEMPLATE), dict(book)),
        'outro_preview': _credit_text(
            app_settings.get('export_outro_template', DEFAULT_OUTRO_TEMPLATE), dict(book)),
    })


@bp.route('/api/export/status/<job_id>')
def export_job_status(job_id):
    job = application._export_jobs.get(job_id)
    if not job:
        stored = jobs.get_job(job_id)
        if not stored or stored['type'] not in ('export_chapter', 'export_book'):
            return jsonify({'error': 'Ismeretlen feladat'}), 404
        return jsonify({**stored, **application._legacy_job(stored)})
    # Recompute ETA on every poll so the UI keeps moving while a GPU batch runs.
    application._refresh_export_job_fields(job)
    return jsonify(job)


@bp.route('/api/export/download')
def export_download():
    path = request.args.get('path', '')
    abs_path = os.path.abspath(path)
    if not application._is_inside_exports(abs_path):
        return 'Forbidden', 403
    if not os.path.exists(abs_path):
        return 'Not found', 404
    return send_file(abs_path, as_attachment=True)
