import os
import sqlite3
import tempfile
import unittest

import numpy as np

from core import database
from core.tts_engine import TTSEngine


class _FakeModel:
    def __init__(self):
        self.kwargs = None

    def generate(self, **kwargs):
        self.kwargs = kwargs
        return [np.zeros(16, dtype=np.float32)]


class VoiceReferenceTest(unittest.TestCase):
    def test_reference_text_is_forwarded_to_omnivoice(self):
        engine = TTSEngine()
        engine.model = _FakeModel()
        engine._ready = True

        engine._synthesize_audio(
            'Target speech.',
            ref_audio='speaker.wav',
            ref_text='Exact reference transcript.',
        )

        self.assertEqual(engine.model.kwargs['ref_text'], 'Exact reference transcript.')

    def test_reference_text_changes_cache_key(self):
        first = TTSEngine.cache_key('Target.', None, 'speaker.wav', 1.0, ref_text='First.')
        second = TTSEngine.cache_key('Target.', None, 'speaker.wav', 1.0, ref_text='Second.')

        self.assertNotEqual(first, second)

    def test_database_stores_reference_names_and_transcripts(self):
        original_path = database.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                database.DB_PATH = os.path.join(tmp, 'reader.db')
                database.init_db()
                conn = sqlite3.connect(database.get_db_path())
                try:
                    book_columns = {
                        row[1] for row in conn.execute('PRAGMA table_info(books)')
                    }
                    character_columns = {
                        row[1] for row in conn.execute('PRAGMA table_info(characters)')
                    }
                finally:
                    conn.close()

                self.assertIn('narrator_ref_audio_name', book_columns)
                self.assertIn('narrator_ref_text', book_columns)
                self.assertIn('ref_audio_name', character_columns)
                self.assertIn('ref_text', character_columns)
        finally:
            database.DB_PATH = original_path


if __name__ == '__main__':
    unittest.main()
