"""Tests for editing a book's title, author and language.

The destructive behavior under test is that changing the language clears the
book's cached audio, because language is part of the audio cache key but an
already-generated segment is served from disk without being re-keyed. A title
or author edit must never clear audio.
"""
import os
import tempfile
import unittest
from pathlib import Path

import app as app_module
from core import database
from core import settings as app_settings


class BookMetadataApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._original = (
            database.DB_PATH,
            app_settings.SETTINGS_FILE,
            app_module._startup_complete,
        )
        database.DB_PATH = os.path.join(self.tmp.name, 'reader.db')
        app_settings.SETTINGS_FILE = Path(self.tmp.name) / 'settings.json'
        app_module._startup_complete = True
        database.init_db()
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books (id, title, author, file_path, file_type, language) "
                "VALUES (1, 'Unknown Title', 'Unknown Author', '/books/x.pdf', 'pdf', 'en')"
            )
            conn.execute(
                "INSERT INTO chapters (id, book_id, title, order_num, content) "
                "VALUES (1, 1, 'Chapter 1', 0, 'Text.')"
            )
            conn.execute(
                "INSERT INTO tts_segments "
                "(book_id, chapter_id, segment_index, text, enriched_text, cache_key, audio_path) "
                "VALUES (1, 1, 0, 'Text.', 'Text.', 'key-1', '/audio/one.wav')"
            )
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        self.addCleanup(self._restore)

    def _restore(self):
        (
            database.DB_PATH,
            app_settings.SETTINGS_FILE,
            app_module._startup_complete,
        ) = self._original
        self.tmp.cleanup()

    def _book(self):
        with database.get_conn() as conn:
            return dict(conn.execute('SELECT * FROM books WHERE id=1').fetchone())

    def _segment_count(self):
        with database.get_conn() as conn:
            return conn.execute(
                'SELECT COUNT(*) FROM tts_segments WHERE book_id=1'
            ).fetchone()[0]

    def test_updates_title_and_author(self):
        response = self.client.put(
            '/api/books/1', json={'title': 'The Fur Coat', 'author': 'Valics Lehel'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'ok': True, 'segments_cleared': False})
        book = self._book()
        self.assertEqual(book['title'], 'The Fur Coat')
        self.assertEqual(book['author'], 'Valics Lehel')

    def test_title_only_edit_keeps_generated_audio(self):
        """The guard against destroying hours of synthesis on a rename."""
        response = self.client.put('/api/books/1', json={'title': 'Renamed'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['segments_cleared'])
        self.assertEqual(self._segment_count(), 1)

    def test_language_change_clears_generated_audio(self):
        response = self.client.put('/api/books/1', json={'language': 'ro'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['segments_cleared'])
        self.assertEqual(self._segment_count(), 0)
        self.assertEqual(self._book()['language'], 'ro')

    def test_uppercase_stored_language_is_not_seen_as_changed(self):
        """The EPUB parser stores the raw dc:language prefix uncased, so a
        book can hold 'EN'. Submitting the lowercased equivalent alongside an
        unrelated title edit must not look like a language change."""
        with database.get_conn() as conn:
            conn.execute("UPDATE books SET language='EN' WHERE id=1")

        response = self.client.put(
            '/api/books/1', json={'title': 'Fixed Title', 'author': 'A', 'language': 'en'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['segments_cleared'])
        self.assertEqual(self._segment_count(), 1)
        self.assertEqual(self._book()['title'], 'Fixed Title')

    def test_null_language_accepts_title_only_update(self):
        """A book with no stored language cannot echo one back, so the field
        must be optional: this must succeed rather than fail the language
        format check on an empty string."""
        with database.get_conn() as conn:
            conn.execute("UPDATE books SET language=NULL WHERE id=1")

        response = self.client.put('/api/books/1', json={'title': 'Fixed Title'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._book()['title'], 'Fixed Title')

    def test_unchanged_language_does_not_clear_audio(self):
        response = self.client.put(
            '/api/books/1', json={'title': 'Renamed', 'language': 'en'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['segments_cleared'])
        self.assertEqual(self._segment_count(), 1)

    def test_language_is_lowercased(self):
        response = self.client.put('/api/books/1', json={'language': 'RO'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._book()['language'], 'ro')

    def test_regional_language_code_is_accepted(self):
        response = self.client.put('/api/books/1', json={'language': 'zh-cn'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._book()['language'], 'zh-cn')

    def test_empty_title_is_rejected(self):
        response = self.client.put('/api/books/1', json={'title': '   '})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Title', response.get_json()['error'])
        self.assertEqual(self._book()['title'], 'Unknown Title')

    def test_empty_author_becomes_unknown_author(self):
        response = self.client.put('/api/books/1', json={'author': '  '})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._book()['author'], 'Unknown Author')

    def test_malformed_language_is_rejected(self):
        response = self.client.put('/api/books/1', json={'language': 'Romanian'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._book()['language'], 'en')
        self.assertEqual(self._segment_count(), 1)

    def test_unknown_book_returns_404(self):
        response = self.client.put('/api/books/999', json={'title': 'Nope'})

        self.assertEqual(response.status_code, 404)

    def test_body_without_known_fields_is_rejected(self):
        response = self.client.put('/api/books/1', json={'colour': 'blue'})

        self.assertEqual(response.status_code, 400)

    def test_numeric_title_is_rejected(self):
        response = self.client.put('/api/books/1', json={'title': 42})

        self.assertEqual(response.status_code, 400)
        self.assertIn('title', response.get_json()['error'])
        self.assertEqual(self._book()['title'], 'Unknown Title')

    def test_list_author_is_rejected(self):
        # Seeded to a value distinct from 'Unknown Author', the default the
        # server would fall back to for an empty string, so this assertion
        # can actually tell "rejected" apart from "wrote the normalized
        # default" instead of passing either way.
        with database.get_conn() as conn:
            conn.execute("UPDATE books SET author='Original Author' WHERE id=1")

        response = self.client.put('/api/books/1', json={'author': [1, 2]})

        self.assertEqual(response.status_code, 400)
        self.assertIn('author', response.get_json()['error'])
        self.assertEqual(self._book()['author'], 'Original Author')

    def test_zero_title_is_not_coerced_to_empty(self):
        response = self.client.put('/api/books/1', json={'title': 0})

        self.assertEqual(response.status_code, 400)
        self.assertIn('title', response.get_json()['error'])
        self.assertNotIn('Title cannot be empty', response.get_json()['error'])

    def test_file_path_cannot_be_changed(self):
        """The allowed whitelist is a security boundary: file_path and
        file_type live in the same row as the editable fields."""
        response = self.client.put(
            '/api/books/1',
            json={'title': 'Renamed', 'file_path': '/etc/passwd', 'file_type': 'txt'},
        )

        self.assertEqual(response.status_code, 200)
        book = self._book()
        self.assertEqual(book['file_path'], '/books/x.pdf')
        self.assertEqual(book['file_type'], 'pdf')


if __name__ == '__main__':
    unittest.main()
