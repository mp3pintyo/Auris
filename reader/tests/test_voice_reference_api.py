import io
import os
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
