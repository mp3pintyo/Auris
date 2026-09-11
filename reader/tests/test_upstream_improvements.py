import base64
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PIL import Image

from core import exporter, import_service, import_tools, database, playback_progress, backup_schedule


class StreamingExportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_mastered_m4b_metadata_cover_and_real_timing_without_whole_audio_arrays(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / 'voice.wav'
            # Speech-like amplitude modulation, enough dynamic range for loudnorm.
            t = np.arange(24000 * 6) / 24000
            sf.write(wav, .1 * (1 + .5 * np.sin(2 * np.pi * 3 * t)) * np.sin(2 * np.pi * 220 * t), 24000)
            cover = io.BytesIO()
            Image.new('RGB', (64, 64), '#387cab').save(cover, 'PNG')
            chapters = [{'chapter_title': 'Első = rész; #1', 'segments': [
                {'audio_path': str(wav), 'duration_sec': 99, 'text': 'Első…'},
                {'audio_path': str(wav), 'duration_sec': 99, 'text': 'Második.'}]},
                {'chapter_title': 'Befejezés', 'segments': [
                    {'audio_path': str(wav), 'duration_sec': 99, 'text': 'Vége.'}]}]
            stages = []
            with patch.object(exporter, 'EXPORTS_DIR', temp), patch.object(exporter, '_merge_wavs', side_effect=AssertionError('whole audio merge')):
                result = exporter.export_m4b('Árvíztűrő', chapters, book_author='Szerző', sub_fmt='srt', mastering=True,
                    book_metadata={'cover_b64': base64.b64encode(cover.getvalue()).decode(), 'language': 'hu',
                                   'series': 'Sorozat', 'series_index': '2', 'description': 'Leírás', 'publisher': 'Kiadó', 'published': '2026'},
                    on_progress=stages.append)
            info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-show_chapters', '-of', 'json', result['audio_path']]))
            self.assertTrue(result['mastering_applied'], result['mastering_warning'])
            self.assertEqual(info['format']['tags']['title'], 'Árvíztűrő')
            self.assertEqual(info['format']['tags']['series'], 'Sorozat')
            self.assertEqual(info['format']['tags']['series-part'], '2')
            self.assertEqual(info['format']['tags']['publisher'], 'Kiadó')
            self.assertEqual(info['format']['tags']['language'], 'hu')
            self.assertEqual(info['format']['tags']['description'], 'Leírás')
            self.assertEqual(info['format']['tags']['date'], '2026')
            self.assertTrue(any(s.get('disposition', {}).get('attached_pic') for s in info['streams']))
            self.assertAlmostEqual(float(info['chapters'][1]['start_time']), 13.85, places=2)
            self.assertIn('00:00:07,500', Path(result['subtitle_path']).read_text(encoding='utf-8'))
            self.assertIn('M4B ellenőrzése…', stages)
            self.assertFalse(list(Path(result['audio_path']).parent.glob('.m4b-*')))

    def test_cancel_preserves_existing_export_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(exporter, 'EXPORTS_DIR', temp):
            dest = Path(exporter._book_export_dir('A', 'B'))
            dest.mkdir()
            target = dest / 'B.m4b'
            target.write_bytes(b'previous complete book')
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                exporter.export_m4b('B', [{'segments': [{'audio_path': 'missing'}]}], book_author='A',
                                    check_cancelled=lambda: (_ for _ in ()).throw(RuntimeError('cancelled')))
            self.assertEqual(target.read_bytes(), b'previous complete book')
            self.assertEqual(len(list(dest.iterdir())), 1)


class ProgressAndScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patcher = patch.object(database, 'DB_PATH', str(self.root / 'reader.db'))
        self.patcher.start()
        database.init_db()
        with database.get_conn() as conn:
            conn.execute("INSERT INTO books(id,title,file_path,file_type) VALUES(1,'Book','','txt')")
            conn.execute("INSERT INTO chapters(id,book_id,title,content,order_num) VALUES(1,1,'Chapter','Hello',0)")
            conn.execute("INSERT INTO tts_segments(book_id,chapter_id,segment_index,text,enriched_text,cache_key,duration_sec) VALUES(1,1,0,'Hello','Hello','audio-v1',10)")

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_resume_invalidates_offset_after_voice_regeneration(self):
        playback_progress.save(1, {'chapter_id': 1, 'position': 0, 'offset_sec': 4.25, 'cache_key': 'audio-v1'})
        self.assertEqual(playback_progress.load(1)['offset_sec'], 4.25)
        with database.get_conn() as conn:
            conn.execute("UPDATE tts_segments SET cache_key='audio-v2'")
        self.assertEqual(playback_progress.load(1)['offset_sec'], 0)
        playback_progress.save(1, {'chapter_id': 1, 'position': 0, 'offset_sec': 9, 'cache_key': 'audio-v1'})
        self.assertEqual(playback_progress.load(1)['offset_sec'], 0)

    def test_invalid_offsets_and_foreign_chapter_rejected(self):
        for value in (-1, float('nan'), float('inf'), 'x'):
            with self.assertRaises(ValueError):
                playback_progress.save(1, {'chapter_id': 1, 'offset_sec': value})
        with self.assertRaises(ValueError):
            playback_progress.save(1, {'chapter_id': 999})

    def test_delayed_request_cannot_overwrite_newer_pause_position(self):
        playback_progress.save(1, {'chapter_id': 1, 'offset_sec': 4, 'cache_key': 'audio-v1', 'event_time_ms': 200})
        playback_progress.save(1, {'chapter_id': 1, 'offset_sec': 1, 'cache_key': 'audio-v1', 'event_time_ms': 100})
        self.assertEqual(playback_progress.load(1)['offset_sec'], 4)

    def test_schedule_catches_up_and_retains_only_managed_backups(self):
        state = backup_schedule.configure({'frequency': 'daily', 'keep': 1}, now=100)
        self.assertEqual(state['next_due'], 86500)
        self.assertFalse(backup_schedule.run_backup(now=200))
        backup_schedule.folder().mkdir(parents=True)
        manual = backup_schedule.folder() / 'manual.zip'
        manual.write_bytes(b'keep')
        with patch('core.experience_api._assert_idle'):
            self.assertTrue(backup_schedule.run_backup(now=90000))
            self.assertTrue(backup_schedule.run_backup(force=True, now=180000))
        state = backup_schedule.status()
        self.assertEqual(len(state['files']), 1)
        self.assertEqual(state['last_success'], 180000)
        self.assertTrue(manual.exists())
        with patch('core.experience_api._assert_idle', side_effect=ValueError('busy')):
            self.assertFalse(backup_schedule.run_backup(force=True, now=190000))
        self.assertEqual(backup_schedule.status()['last_success'], 180000)
        self.assertEqual(backup_schedule.status()['last_error'], 'busy')
        self.assertFalse(list(backup_schedule.folder().glob('*.partial')))


class OptionalImportTests(unittest.TestCase):
    def test_multipage_tiff_recognizes_every_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'scan.tiff'
            Image.new('RGB', (50, 50), 'white').save(source, save_all=True,
                append_images=[Image.new('RGB', (50, 50), 'white')])
            with patch.object(import_tools, 'executable', return_value='tesseract'), patch.object(import_tools, 'languages', return_value=['hun']), patch.object(import_tools.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, b'First page.', b''), subprocess.CompletedProcess([], 0, b'Second page.', b'')]) as run:
                parsed = import_service.prepare_file(source, ocr=True)
            self.assertEqual(run.call_count, 2)
            self.assertIn('Second page.', '\n'.join(c['content'] for c in parsed['chapters']))

    def test_calibre_adapter_runs_and_removes_converted_temporary_file(self):
        from ebooklib import epub
        seen = []
        def convert(command, **kwargs):
            seen.append(command)
            book = epub.EpubBook()
            book.set_identifier('test')
            book.set_title('Converted book')
            book.set_language('hu')
            chapter = epub.EpubHtml(title='Fejezet', file_name='chapter.xhtml', lang='hu')
            chapter.content = '<h1>Fejezet</h1><p>Olvasható magyar történet.</p>'
            book.add_item(chapter)
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.toc = [chapter]
            book.spine = [chapter]
            epub.write_epub(command[2], book)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(import_tools, 'executable', return_value='ebook-convert'), patch.object(import_tools.subprocess, 'run', side_effect=convert):
            result = import_tools.convert_document('example.fb2')
        self.assertEqual(result['title'], 'Converted book')
        self.assertIn('Olvasható', result['chapters'][0]['content'])
        self.assertFalse(Path(seen[0][2]).exists())

    def test_missing_tools_have_actionable_errors(self):
        with patch.object(import_tools, 'executable', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Tesseract'):
                import_tools.ocr_document('scan.pdf')
            with self.assertRaisesRegex(ValueError, 'Calibre'):
                import_tools.convert_document('book.fb2')

    def test_calibre_requires_opt_in_and_keeps_original_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'book.fb2'
            source.write_bytes(b'<FictionBook/>')
            with self.assertRaisesRegex(ValueError, 'engedélyezd'):
                import_service.prepare_file(source)
            parsed = {'title': 'Book', 'chapters': [{'content': 'Readable content'}]}
            with patch.object(import_tools, 'convert_document', return_value=parsed):
                result = import_service.prepare_file(source, calibre=True)
            import hashlib
            self.assertEqual(result['content_hash'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_mixed_pdf_preserves_native_text_and_ocrs_only_empty_pages(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'mixed.pdf'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((50, 50), 'Native text remains readable.')
                doc.new_page()
                doc.save(source)
            with patch.object(import_tools, 'executable', return_value='tesseract'), patch.object(import_tools, 'languages', return_value=['hun']), patch.object(import_tools.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Felismert magyar szöveg.'.encode(), b'')) as run:
                parsed = import_service.prepare_file(source, ocr=True)
            self.assertEqual(run.call_count, 1)
            text = '\n'.join(c['content'] for c in parsed['chapters'])
            self.assertIn('Native text remains readable.', text)
            self.assertIn('Felismert magyar szöveg.', text)


if __name__ == '__main__':
    unittest.main()
