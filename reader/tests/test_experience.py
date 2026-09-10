import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import database, settings


class ExperienceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            database, "DB_PATH", str(Path(self.tmp.name) / "reader.db")
        )
        self.settings_patch = patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        self.db_patch.start()
        self.settings_patch.start()
        database.init_db()
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books(id,title,file_path,file_type) VALUES(1,'Magyar könyv','book.txt','txt')"
            )
            conn.execute(
                "INSERT INTO books(id,title,file_path,file_type) VALUES(2,'Másik','other.txt','txt')"
            )

    def tearDown(self):
        self.settings_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    def service(self):
        from core import experience

        return experience

    def test_pronunciation_overrides_without_cascade_or_substring_damage(self):
        e = self.service()
        e.save_rule(None, "Gorcsev", "Gorcsef")
        e.save_rule(1, "Gorcsev", "Gorcseff")
        e.save_rule(None, "Gorcseff", "más")
        self.assertEqual(
            e.apply_pronunciation("Gorcsev és Gorcsevék.", 1), "Gorcseff és Gorcsevék."
        )
        self.assertEqual(e.apply_pronunciation("Gorcsev.", 2), "Gorcsef.")

    def test_rule_change_invalidates_only_affected_book(self):
        e = self.service()
        with database.get_conn() as conn:
            for book_id in [1, 2]:
                conn.execute(
                    "INSERT INTO chapters(id,book_id,title,order_num,content) VALUES(?,?,?,0,?)",
                    (book_id, book_id, "Fejezet", "Gorcsev."),
                )
                conn.execute(
                    "INSERT INTO tts_segments(book_id,chapter_id,segment_index,text,enriched_text,audio_path) VALUES(?,?,0,?,?,?)",
                    (book_id, book_id, "Gorcsev.", "Gorcsev.", "cached.wav"),
                )
        e.save_rule(1, "Gorcsev", "Gorcsef")
        with database.get_conn() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM tts_segments WHERE book_id=1"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM tts_segments WHERE book_id=2"
                ).fetchone()[0],
                1,
            )

    def test_profile_copies_reference_and_applies_to_other_book(self):
        e = self.service()
        ref = Path(self.tmp.name) / "voice.wav"
        ref.write_bytes(b"reference")
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE books SET narrator_instruct=?,narrator_ref_audio_path=?,narrator_ref_text=? WHERE id=1",
                ("male, elderly", str(ref), "Magyar próba."),
            )
        profile = e.save_profile("Mesélő", 1)
        ref.unlink()
        e.apply_profile(profile["id"], 2)
        with database.get_conn() as conn:
            book = conn.execute("SELECT * FROM books WHERE id=2").fetchone()
            self.assertTrue(Path(book["narrator_ref_audio_path"]).exists())
            self.assertEqual(book["narrator_ref_text"], "Magyar próba.")

    def test_metadata_validation(self):
        e = self.service()
        with self.assertRaises(ValueError):
            e.update_metadata(1, {"title": "  "})
        e.update_metadata(
            1,
            {"title": "Új cím", "collection": "Kedvencek", "reading_state": "finished"},
        )
        with database.get_conn() as conn:
            self.assertEqual(
                conn.execute("SELECT collection FROM books WHERE id=1").fetchone()[0],
                "Kedvencek",
            )

    def test_profile_captures_the_active_global_narrator_default(self):
        settings.save({"narrator_instruct": "warm Hungarian voice, calm narration"})
        profile = self.service().save_profile("Alapértelmezett mesélő", 1)
        self.assertEqual(profile["instruct"], "warm Hungarian voice, calm narration")


if __name__ == "__main__":
    unittest.main()
