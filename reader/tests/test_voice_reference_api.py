import io
import os
import tempfile
import unittest
from unittest.mock import patch

import app as app_module
from core import database


class VoiceReferenceApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_upload_dir = app_module.UPLOAD_DIR
        self.original_startup = app_module._startup_complete
        database.DB_PATH = os.path.join(self.tmp.name, 'reader.db')
        app_module.UPLOAD_DIR = self.tmp.name
        app_module._startup_complete = True
        database.init_db()
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books (id, title, file_path, file_type) VALUES (1, 'Test', 'test.txt', 'txt')"
            )
            conn.execute(
                "INSERT INTO characters (id, book_id, name) VALUES (2, 1, 'Alice')"
            )
            conn.execute(
                "INSERT INTO characters (id, book_id, name) VALUES (3, 1, 'Bob')"
            )
            conn.execute(
                "INSERT INTO chapters "
                "(id, book_id, title, order_num, content, word_count) "
                "VALUES (4, 1, 'Opening', 0, 'Test chapter.', 2)"
            )
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        app_module.UPLOAD_DIR = self.original_upload_dir
        app_module._startup_complete = self.original_startup
        self.tmp.cleanup()

    def test_narrator_upload_is_visible_and_removable(self):
        response = self.client.post(
            '/api/books/1/narrator-ref-audio',
            data={
                'file': (io.BytesIO(b'RIFF-test'), 'narrator voice.wav'),
                'ref_text': 'The exact narrator transcript.',
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ref_audio_name'], 'narrator voice.wav')

        page = self.client.get('/voice-studio/1')
        self.assertIn(b'narrator voice.wav', page.data)
        self.assertIn(b'The exact narrator transcript.', page.data)

        response = self.client.delete('/api/books/1/narrator-ref-audio')
        self.assertEqual(response.status_code, 200)
        with database.get_conn() as conn:
            book = conn.execute('SELECT * FROM books WHERE id=1').fetchone()
        self.assertIsNone(book['narrator_ref_audio_path'])
        self.assertIsNone(book['narrator_ref_audio_name'])
        self.assertIsNone(book['narrator_ref_text'])

    def test_character_upload_and_api_return_filename_and_transcript(self):
        response = self.client.post(
            '/api/characters/2/ref-audio',
            data={
                'file': (io.BytesIO(b'RIFF-test'), 'alice.wav'),
                'ref_text': 'Alice speaks these words.',
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)

        characters = self.client.get('/api/books/1/characters').get_json()
        self.assertEqual(characters[0]['ref_audio_name'], 'alice.wav')
        self.assertEqual(characters[0]['ref_text'], 'Alice speaks these words.')

        response = self.client.delete('/api/characters/2/ref-audio')
        self.assertEqual(response.status_code, 200)
        characters = self.client.get('/api/books/1/characters').get_json()
        self.assertIsNone(characters[0]['ref_audio_path'])
        self.assertIsNone(characters[0]['ref_audio_name'])
        self.assertIsNone(characters[0]['ref_text'])

    def test_characters_can_be_filtered_to_current_chapter(self):
        chapter_segments = [
            {'character_name': None},
            {'character_name': 'alice'},
        ]
        with patch.object(
            app_module,
            '_compute_segments_for_chapter',
            return_value=chapter_segments,
        ) as compute_segments:
            response = self.client.get('/api/books/1/characters?chapter_id=4')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [character['name'] for character in response.get_json()],
            ['Alice'],
        )
        compute_segments.assert_called_once_with(
            1,
            4,
            single_narrator_mode=False,
        )

    def test_voice_studio_exposes_chapter_filter_for_requested_chapter(self):
        response = self.client.get('/voice-studio/1?chapter_id=4')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="chapter-character-filter"', response.data)
        self.assertIn('Csak az aktuális fejezet szereplői'.encode(), response.data)
        self.assertIn(b'Opening', response.data)
        self.assertIn(b'window.CURRENT_CHAPTER_ID = 4', response.data)

    def test_voice_studio_renders_profile_search_and_neutral_accent_controls(self):
        response = self.client.get('/voice-studio/1')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/static/css/voice-experience.css', response.data)
        self.assertIn(b'id="profile-narrator"', response.data)
        self.assertIn(b'id="profile-name-narrator"', response.data)
        self.assertIn(b'id="character-search"', response.data)
        self.assertIn('Semleges / nincs akcentus'.encode(), response.data)
        self.assertIn('aria-label="Mentett narrátorhang"'.encode(), response.data)


if __name__ == '__main__':
    unittest.main()
