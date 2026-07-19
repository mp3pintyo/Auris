import os
import tempfile
import unittest
from pathlib import Path

import app as app_module
from core import database, settings


class SettingsTtsCacheInvalidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_settings_file = settings.SETTINGS_FILE
        self.original_startup = app_module._startup_complete
        database.DB_PATH = os.path.join(self.tmp.name, 'reader.db')
        settings.SETTINGS_FILE = Path(self.tmp.name) / 'settings.json'
        app_module._startup_complete = True
        database.init_db()
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books (id, title, file_path, file_type) "
                "VALUES (1, 'Test', 'test.txt', 'txt')"
            )
            conn.execute(
                "INSERT INTO chapters (id, book_id, title, order_num, content) "
                "VALUES (1, 1, 'Chapter 1', 0, 'Test text.')"
            )
            conn.execute(
                "INSERT INTO tts_segments "
                "(book_id, chapter_id, segment_index, text, enriched_text, cache_key, audio_path) "
                "VALUES (1, 1, 0, 'Test text.', 'Test text.', 'old-key', 'old.wav')"
            )
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        settings.SETTINGS_FILE = self.original_settings_file
        app_module._startup_complete = self.original_startup
        self.tmp.cleanup()

    def _segment_count(self):
        with database.get_conn() as conn:
            return conn.execute('SELECT COUNT(*) FROM tts_segments').fetchone()[0]

    def test_quality_change_clears_persisted_playback_segments(self):
        response = self.client.post('/api/settings', json={'tts_num_step': 32})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._segment_count(), 0)

    def test_unchanged_quality_keeps_persisted_playback_segments(self):
        response = self.client.post('/api/settings', json={'tts_num_step': 16})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._segment_count(), 1)


if __name__ == '__main__':
    unittest.main()
