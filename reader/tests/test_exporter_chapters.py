import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from core import exporter


class ChapterSelectionTests(unittest.TestCase):
    def test_all_selects_every_chapter(self):
        for value in (None, '', '*', 'all', 'mind', 'összes'):
            with self.subTest(value=value):
                self.assertEqual(exporter.parse_chapter_selection(value, 4), [1, 2, 3, 4])

    def test_numbers_ranges_and_duplicates_are_sorted(self):
        self.assertEqual(
            exporter.parse_chapter_selection('5, 1, 3-4, 3', 6),
            [1, 3, 4, 5],
        )

    def test_invalid_selection_is_rejected(self):
        for value in ('0', '1,,2', '4-2', '1,a', '7'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    exporter.parse_chapter_selection(value, 6)


class ChapterFolderExportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
    def test_real_m4b_contains_seekable_ffmpeg_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, 'first.wav')
            second = os.path.join(tmp, 'second.wav')
            sf.write(first, np.zeros(exporter.SAMPLE_RATE, dtype=np.float32), exporter.SAMPLE_RATE)
            sf.write(second, np.zeros(exporter.SAMPLE_RATE * 2, dtype=np.float32), exporter.SAMPLE_RATE)
            chapters = [
                {'chapter_number': 1, 'chapter_title': 'Első', 'segments': [
                    {'audio_path': first, 'duration_sec': 1.0, 'text': 'Első.'},
                ]},
                {'chapter_number': 2, 'chapter_title': 'Második', 'segments': [
                    {'audio_path': second, 'duration_sec': 2.0, 'text': 'Második.'},
                ]},
            ]
            with patch.object(exporter, 'EXPORTS_DIR', tmp):
                result = exporter.export_m4b(
                    'Tesztkönyv', chapters, book_author='Szerző', sub_fmt='none'
                )

            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_chapters', '-of', 'json', result['audio_path']],
                capture_output=True, check=True,
            )
            parsed = json.loads(probe.stdout.decode('utf-8'))
            self.assertEqual(
                [chapter['tags']['title'] for chapter in parsed['chapters']],
                ['Első', 'Második'],
            )
            self.assertGreater(os.path.getsize(result['audio_path']), 0)

    def test_subtitle_none_does_not_create_subtitle_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, 'source.wav')
            sf.write(source, np.zeros(100, dtype=np.float32), exporter.SAMPLE_RATE)
            with patch.object(exporter, 'EXPORTS_DIR', tmp):
                result = exporter.export_single_chapter(
                    'Chapter', 'Book',
                    [{'audio_path': source, 'duration_sec': 0.1, 'text': 'Text'}],
                    {}, audio_fmt='wav', sub_fmt='none', book_author='Writer',
                )

            self.assertIsNone(result['subtitle_path'])
            self.assertEqual(result['sub_fmt'], 'none')
            self.assertEqual(
                sorted(os.listdir(os.path.dirname(result['audio_path']))),
                ['Chapter.wav'],
            )

    def test_m4b_missing_audio_does_not_publish_a_partial_book(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(exporter, 'EXPORTS_DIR', tmp):
            with self.assertRaises(ValueError):
                exporter.export_m4b('Book', [{'segments': [{'audio_path': 'missing.wav'}]}])
            self.assertFalse(list(Path(tmp).rglob('*.m4b')))

    def test_mastering_falls_back_to_unprocessed_wav_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, 'source.wav')
            sf.write(
                source,
                np.sin(np.linspace(0, np.pi * 20, 2400)).astype(np.float32),
                exporter.SAMPLE_RATE,
            )
            with (
                patch.object(exporter, 'EXPORTS_DIR', tmp),
                patch.object(exporter, '_ffmpeg_available', return_value=False),
            ):
                result = exporter.export_single_chapter(
                    'Chapter',
                    'Book',
                    [{
                        'audio_path': source,
                        'duration_sec': 0.1,
                        'text': 'Text',
                    }],
                    {},
                    mastering=True,
                    book_author='Writer',
                )

            self.assertTrue(os.path.isfile(result['audio_path']))
            self.assertEqual(
                os.path.dirname(result['audio_path']),
                os.path.join(tmp, 'Writer - Book'),
            )
            self.assertFalse(result['mastering_applied'])
            self.assertIn('FFmpeg', result['mastering_warning'])
            self.assertFalse(
                os.path.exists(
                    os.path.join(tmp, 'Writer - Book', '.Chapter.premaster.wav')
                )
            )

    def test_loudnorm_measurements_are_parsed_from_ffmpeg_output(self):
        measurements = exporter._extract_loudnorm_measurements(
            'noise before\n'
            '{\n'
            '  "input_i" : "-22.10",\n'
            '  "input_tp" : "-4.20",\n'
            '  "input_lra" : "3.50",\n'
            '  "input_thresh" : "-32.20",\n'
            '  "output_i" : "-19.00",\n'
            '  "target_offset" : "0.10"\n'
            '}\n'
        )

        self.assertEqual(measurements['input_i'], '-22.10')
        self.assertEqual(measurements['target_offset'], '0.10')

    def test_export_creates_book_folder_with_numbered_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, 'source.wav')
            sf.write(source, np.zeros(100, dtype=np.float32), exporter.SAMPLE_RATE)
            chapters = [
                {
                    'chapter_number': 2,
                    'chapter_title': 'The Beginning',
                    'segments': [{
                        'audio_path': source,
                        'duration_sec': 100 / exporter.SAMPLE_RATE,
                        'text': 'Hello.',
                    }],
                },
                {
                    'chapter_number': 11,
                    'chapter_title': 'The End',
                    'segments': [{
                        'audio_path': source,
                        'duration_sec': 100 / exporter.SAMPLE_RATE,
                        'text': 'Goodbye.',
                    }],
                },
            ]

            with patch.object(exporter, 'EXPORTS_DIR', tmp):
                result = exporter.export_chapter_folder(
                    'My Book', chapters, {}, audio_fmt='wav', sub_fmt='srt',
                    book_author='Jane Writer',
                )

            self.assertEqual(
                result['directory_path'],
                os.path.join(tmp, 'Jane Writer - My Book'),
            )
            self.assertTrue(os.path.isfile(os.path.join(result['directory_path'], '02_The_Beginning.wav')))
            self.assertTrue(os.path.isfile(os.path.join(result['directory_path'], '02_The_Beginning.srt')))
            self.assertTrue(os.path.isfile(os.path.join(result['directory_path'], '11_The_End.wav')))

    def test_successful_mp3_conversion_removes_intermediate_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, 'source.wav')
            sf.write(source, np.zeros(100, dtype=np.float32), exporter.SAMPLE_RATE)
            with (
                patch.object(exporter, 'EXPORTS_DIR', tmp),
                patch.object(
                    exporter,
                    '_wav_to_mp3_bytes',
                    return_value=b'mp3',
                ) as encode_mp3,
            ):
                result = exporter.export_single_chapter(
                    'Chapter', 'Book',
                    [{'audio_path': source, 'duration_sec': 0.1, 'text': 'Text'}],
                    {}, audio_fmt='mp3', sub_fmt='srt',
                    book_author='Writer',
                )

            self.assertTrue(os.path.isfile(result['audio_path']))
            encode_mp3.assert_called_once()
            self.assertEqual(
                encode_mp3.call_args.kwargs['tags'],
                {
                    'title': 'Chapter',
                    'artist': 'Writer',
                    'album': 'Book',
                    'track': '',
                },
            )
            self.assertFalse(
                os.path.exists(os.path.join(tmp, 'Writer - Book', 'Chapter.wav'))
            )

    def test_book_folder_removes_invalid_filename_characters(self):
        with patch.object(exporter, 'EXPORTS_DIR', 'exports'):
            path = exporter._book_export_dir('A: Writer', 'Book? <One>')

        self.assertEqual(path, os.path.join('exports', 'A Writer - Book One'))


if __name__ == '__main__':
    unittest.main()
