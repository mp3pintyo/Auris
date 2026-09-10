import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from core import database, jobs
from core import settings as app_settings


class BookImportModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_settings_file = app_settings.SETTINGS_FILE
        self.original_upload_dir = app_module.UPLOAD_DIR
        self.original_startup = app_module._startup_complete
        self.original_analysis_pending = app_module._character_analysis_pending

        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        app_settings.SETTINGS_FILE = Path(self.tmp.name) / "settings.json"
        app_module.UPLOAD_DIR = self.tmp.name
        app_module._startup_complete = True
        database.init_db()
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        app_settings.SETTINGS_FILE = self.original_settings_file
        app_module.UPLOAD_DIR = self.original_upload_dir
        app_module._startup_complete = self.original_startup
        app_module._character_analysis_pending = self.original_analysis_pending
        self.tmp.cleanup()

    def _book_file(self):
        return io.BytesIO(
            b"Test Book\n\nChapter One\nThis is a short imported chapter."
        )

    def test_single_narrator_skips_character_analysis(self):
        with patch.object(app_module.threading, "Thread") as thread:
            response = self.client.post(
                "/api/books/import",
                data={
                    "file": (self._book_file(), "single.txt"),
                    "narration_mode": "single",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["analysis_status"], "skipped")
        thread.assert_not_called()
        with database.get_conn() as conn:
            book = conn.execute("SELECT * FROM books").fetchone()
        self.assertEqual(book["single_narrator_mode"], 1)
        self.assertEqual(book["character_analysis_provider"], "none")
        self.assertEqual(book["character_analysis_status"], "skipped")

    def test_character_voices_require_configured_model(self):
        app_settings.save({"llm_base_url": "", "llm_model": ""})
        response = self.client.post(
            "/api/books/import",
            data={
                "file": (self._book_file(), "multi.txt"),
                "narration_mode": "multi",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("language-model URL", response.get_json()["error"])
        with database.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        self.assertEqual(count, 0)

    def test_character_voices_queue_llm_analysis(self):
        app_settings.save({
            "llm_base_url": "http://127.0.0.1:1234/v1",
            "llm_model": "test-model",
        })
        with (
            patch.object(app_module.threading, "Thread") as thread,
            patch.object(app_module.tts, "unload"),
        ):
            response = self.client.post(
                "/api/books/import",
                data={
                    "file": (self._book_file(), "multi.txt"),
                    "narration_mode": "multi",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["analysis_status"], "queued")
        thread.assert_called_once()
        with database.get_conn() as conn:
            book = conn.execute("SELECT * FROM books").fetchone()
        self.assertEqual(book["single_narrator_mode"], 0)
        self.assertEqual(book["character_analysis_provider"], "llm")
        analysis_jobs = jobs.list_jobs(book_id=book["id"])
        self.assertEqual(len(analysis_jobs), 1)
        self.assertEqual(analysis_jobs[0]["type"], "initial_analysis")
        self.assertNotIn("api_key", analysis_jobs[0]["input"])

    def test_openai_character_analysis_does_not_unload_local_tts(self):
        app_settings.save({
            "llm_provider": "openai",
            "openai_api_key": "test-key",
            "openai_model": "gpt-test",
        })
        with (
            patch.object(app_module.threading, "Thread") as thread,
            patch.object(app_module.tts, "unload") as unload,
        ):
            response = self.client.post(
                "/api/books/import",
                data={
                    "file": (self._book_file(), "openai.txt"),
                    "narration_mode": "multi",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        unload.assert_not_called()
        thread.assert_called_once()
        with database.get_conn() as conn:
            book = conn.execute("SELECT * FROM books").fetchone()
        self.assertEqual(book["character_analysis_model"], "gpt-test")

    def test_same_filename_imports_use_distinct_managed_paths(self):
        for content in (b"First book text.", b"Second book text."):
            response = self.client.post(
                "/api/books/import",
                data={
                    "file": (io.BytesIO(content), "same-name.txt"),
                    "narration_mode": "single",
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 200)

        with database.get_conn() as conn:
            paths = [
                row["file_path"]
                for row in conn.execute("SELECT file_path FROM books ORDER BY id")
            ]
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(os.path.isfile(path) for path in paths))

    def test_empty_parsed_document_is_rejected_before_book_insert(self):
        with patch.object(
            app_module.txt_parser,
            "parse",
            return_value={
                "title": "Empty", "author": "", "language": "hu",
                "chapters": [{"title": "Page", "content": "  \n"}],
            },
        ):
            response = self.client.post(
                "/api/books/import",
                data={
                    "file": (io.BytesIO(b"blank"), "empty.txt"),
                    "narration_mode": "single",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("OCR", response.get_json()["error"])
        with database.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0], 0)

    def test_library_uses_pre_import_dialog(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="import-dialog"', response.data)
        self.assertIn("Hogyan szólaljon meg?".encode("utf-8"), response.data)


if __name__ == "__main__":
    unittest.main()
