import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from core import database, settings


class LibraryBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = patch.object(database, "DB_PATH", str(self.root / "reader.db"))
        self.db.start()
        self.config = patch.object(
            settings, "SETTINGS_FILE", self.root / "settings.json"
        )
        self.config.start()
        database.init_db()

    def tearDown(self):
        self.config.stop()
        self.db.stop()
        self.tmp.cleanup()

    def test_portable_restore_preserves_text_and_omits_keys(self):
        from core import library_backup

        source = self.root / "book.txt"
        source.write_text("Magyar szöveg.", encoding="utf-8")
        settings.save({"openai_api_key": "secret-do-not-export"})
        reference = self.root / "reference.wav"
        reference.write_bytes(b"RIFF-reference")
        with database.get_conn() as c:
            c.execute(
                "INSERT INTO books(id,title,file_path,file_type) VALUES(1,?,?,?)",
                ("Próba", str(source), "txt"),
            )
            c.execute(
                "UPDATE books SET narrator_ref_audio_path=?,narrator_ref_audio_name=?,narrator_ref_text=? WHERE id=1",
                (str(reference), "sajat.wav", "Pontos magyar átirat."),
            )
            c.execute(
                "INSERT INTO voice_profiles(name,instruct,ref_audio_path,ref_audio_name,ref_text) VALUES(?,?,?,?,?)",
                (
                    "Mentett hang",
                    "neutral",
                    str(reference),
                    "sajat.wav",
                    "Pontos magyar átirat.",
                ),
            )
        archive = library_backup.create_backup(self.root / "copy.zip")
        from core import jobs

        jobs.ensure_jobs()
        with database.get_conn() as c:
            c.execute(
                "INSERT INTO jobs(id,type,book_id,state) VALUES('old','export_book',1,'failed')"
            )
        with zipfile.ZipFile(archive) as z:
            self.assertNotIn(b"secret-do-not-export", z.read("manifest.json"))
            import json

            self.assertNotIn(
                "model_path", json.loads(z.read("manifest.json"))["settings"]
            )
        source.unlink()
        reference.unlink()
        result = library_backup.restore_backup(
            archive, self.root / "restored", confirm=True
        )
        self.assertEqual(result["books"], 1)
        with database.get_conn() as c:
            book = c.execute("SELECT * FROM books").fetchone()
            self.assertEqual(
                Path(book["file_path"]).read_text(encoding="utf-8"), "Magyar szöveg."
            )
            self.assertEqual(c.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            self.assertEqual(
                Path(book["narrator_ref_audio_path"]).read_bytes(), b"RIFF-reference"
            )
            profile = c.execute("SELECT * FROM voice_profiles").fetchone()
            self.assertEqual(profile["ref_audio_path"], book["narrator_ref_audio_path"])
            self.assertEqual(profile["ref_text"], "Pontos magyar átirat.")
        self.assertEqual(settings.get("openai_api_key"), "secret-do-not-export")

    def test_bad_archive_leaves_library_untouched(self):
        from core import library_backup

        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../outside.txt", "bad")
        with self.assertRaises(ValueError):
            library_backup.restore_backup(archive, self.root / "restored", confirm=True)
        self.assertFalse((self.root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
