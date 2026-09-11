"""Bounded-memory audiobook assembly, metadata and verified atomic publication."""
import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf


def export(book_title, chapters_data, character_colors=None, *, sub_fmt='none',
           book_author='Unknown', mastering=False, book_metadata=None,
           on_progress=None, check_cancelled=None):
    from core import exporter as e

    if not chapters_data:
        raise ValueError('Nincs exportálható fejezet.')
    if not e._ffmpeg_available() or not e.shutil.which('ffprobe'):
        raise RuntimeError('Az M4B-exporthoz FFmpeg és ffprobe szükséges.')
    destination = Path(e._book_export_dir(book_author, book_title))
    destination.mkdir(parents=True, exist_ok=True)
    safe = e._safe_name(book_title)
    target = destination / (safe + '.m4b')
    metadata = dict(book_metadata or {})

    def report(message):
        if check_cancelled:
            check_cancelled()
        if on_progress:
            on_progress(message)

    def run(command, **kwargs):
        # Log to disk to avoid pipe deadlocks and retain cancellability even in
        # the two mastering passes. Do not accumulate FFmpeg output in memory.
        with tempfile.TemporaryFile() as log, tempfile.TemporaryFile() as stdin:
            value = kwargs.get('input', '')
            stdin.write(value.encode('utf-8') if isinstance(value, str) else value)
            stdin.seek(0)
            proc = subprocess.Popen(command, stdin=stdin, stdout=log, stderr=log)
            try:
                while proc.poll() is None:
                    if check_cancelled:
                        check_cancelled()
                    time.sleep(.1)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            log.seek(0 if command[0] == 'ffprobe' else max(0, log.tell() - 65536))
            output = log.read().decode('utf-8', errors='replace')
            return subprocess.CompletedProcess(command, proc.returncode, output, output)

    with tempfile.TemporaryDirectory(prefix='.m4b-', dir=destination) as work:
        work = Path(work)
        raw = work / 'source.wav'
        timeline, chapters, cursor = [], [], 0
        total = sum(len(c.get('segments') or []) for c in chapters_data)
        done = 0
        # RF64 supports books whose temporary PCM audio exceeds 4 GiB.
        with sf.SoundFile(raw, 'w', samplerate=e.SAMPLE_RATE, channels=1,
                          format='RF64', subtype='PCM_16') as out:
            for ci, chapter in enumerate(chapters_data):
                segments = chapter.get('segments') or []
                if not segments:
                    raise ValueError('Üres fejezet nem exportálható.')
                start = cursor
                for si, segment in enumerate(segments):
                    report(f'Hangok összefűzése: {done}/{total}')
                    path = segment.get('audio_path')
                    if not path or not Path(path).is_file():
                        raise ValueError('Hiányzó mondathang. Generáld újra a fejezetet.')
                    seg_start = cursor
                    with sf.SoundFile(path) as source:
                        if source.samplerate != e.SAMPLE_RATE or not len(source):
                            raise ValueError('Érvénytelen mondathang vagy mintavételi frekvencia.')
                        for block in source.blocks(blocksize=65536, dtype='float32', always_2d=True):
                            if check_cancelled:
                                check_cancelled()
                            out.write(block.mean(axis=1))
                            cursor += len(block)
                    timeline.append({**segment, 't_start': seg_start / e.SAMPLE_RATE,
                                     't_end': cursor / e.SAMPLE_RATE})
                    pause = (e.pause_after_segment(segment, segments[si + 1])
                             if si + 1 < len(segments) else
                             e.DEFAULT_SEGMENT_PAUSE_SEC if ci + 1 < len(chapters_data) else 0)
                    silence = round(pause * e.SAMPLE_RATE)
                    out.write(np.zeros(silence, dtype='float32'))
                    cursor += silence
                    done += 1
                chapters.append((start, cursor, chapter.get('chapter_title') or f'Fejezet {ci + 1}'))
        report(f'Hangok összefűzése: {total}/{total}')
        applied, warning = False, None
        if mastering:
            report('Hangerő-kiegyenlítés: elemzés és feldolgozás…')
            mastered = work / 'mastered.wav'
            applied, warning = e._master_wav(str(raw), str(mastered), runner=run)
            if applied:
                raw = mastered
        tags = {'title': book_title, 'artist': book_author, 'album': book_title,
                'language': metadata.get('language'), 'description': metadata.get('description'),
                'series': metadata.get('series'), 'series-part': metadata.get('series_index'),
                'publisher': metadata.get('publisher'), 'date': metadata.get('published')}
        lines = [';FFMETADATA1'] + [f'{key}={e._ffmetadata_value(value)}'
                                            for key, value in tags.items() if value]
        for start, end, title in chapters:
            lines.extend(['[CHAPTER]', f'TIMEBASE=1/{e.SAMPLE_RATE}',
                          f'START={start}', f'END={end}', f'title={e._ffmetadata_value(title)}'])
        meta = work / 'metadata.txt'
        meta.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        staged = work / 'book.m4b'
        command = ['ffmpeg', '-hide_banner', '-nostats', '-y', '-i', str(raw),
                   '-f', 'ffmetadata', '-i', str(meta)]
        cover = metadata.get('cover_b64')
        if cover:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(base64.b64decode(cover, validate=True))) as picture:
                picture.thumbnail((1600, 1600))
                picture.convert('RGB').save(work / 'cover.jpg')
            command += ['-i', str(work / 'cover.jpg')]
        command += ['-map', '0:a', '-map_metadata', '1', '-map_chapters', '1']
        if cover:
            command += ['-map', '2:v', '-c:v', 'copy', '-disposition:v:0', 'attached_pic']
        command += ['-c:a', 'aac', '-b:a', '192k', '-metadata', 'media_type=2', str(staged)]
        report('M4B kódolása…')
        result = run(command)
        if result.returncode:
            raise RuntimeError('M4B kódolási hiba: ' + result.stderr[-1500:])
        from core.mp4_metadata import add_book_tags
        add_book_tags(staged, {key: tags[key] for key in ('language', 'series', 'series-part', 'publisher')})
        report('M4B ellenőrzése…')
        probe = run(['ffprobe', '-v', 'error', '-show_chapters', '-show_format',
                     '-show_streams', '-of', 'json', str(staged)])
        if probe.returncode:
            raise RuntimeError('Az elkészült M4B nem ellenőrizhető.')
        info = json.loads(probe.stdout)
        actual = info.get('chapters', [])
        if len(actual) != len(chapters) or abs(float(info['format']['duration']) - cursor / e.SAMPLE_RATE) > .25:
            raise RuntimeError('Az M4B hossza vagy fejezetszáma eltér a forrástól.')
        for item, (start, end, title) in zip(actual, chapters):
            if (abs(float(item['start_time']) - start / e.SAMPLE_RATE) > .02
                    or abs(float(item['end_time']) - end / e.SAMPLE_RATE) > .02
                    or item.get('tags', {}).get('title') != title):
                raise RuntimeError('Az M4B fejezethatárai vagy címei hibásak.')
        if cover and not any(s.get('disposition', {}).get('attached_pic') for s in info['streams']):
            raise RuntimeError('A borító nem került az M4B-fájlba.')
        subtitle = None
        if sub_fmt != 'none':
            subtitle = destination / (safe + ('.ass' if sub_fmt == 'ass' else '.srt'))
            content = (e.build_ass(timeline, character_colors or {}, book_title)
                       if sub_fmt == 'ass' else e.build_srt(timeline))
            (work / 'subtitle').write_text(content, encoding='utf-8')
        report('Export véglegesítése…')
        if subtitle:
            os.replace(work / 'subtitle', subtitle)
        os.replace(staged, target)
    return {'audio_path': str(target), 'subtitle_path': str(subtitle) if subtitle else None,
            'audio_fmt': 'm4b', 'sub_fmt': sub_fmt, 'chapter_count': len(chapters),
            'mastering_applied': applied, 'mastering_warning': warning}
