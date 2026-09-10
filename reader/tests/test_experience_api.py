import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app as application
from core import database, settings
from core.experience_api import bp


if "experience" not in application.app.blueprints:
    application.app.register_blueprint(bp)


class ExperienceApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [
            patch.object(database, "DB_PATH", str(self.root / "reader.db")),
            patch.object(settings, "SETTINGS_FILE", self.root / "settings.json"),
            patch.object(application, "UPLOAD_DIR", str(self.root / "uploads")),
            patch.object(application, "_startup_complete", True),
            patch.object(application, "_export_exclusive_active", return_value=False),
            patch.object(
                application, "_character_analysis_is_active", return_value=False
            ),
            patch.object(application, "_chapter_generation_jobs", {}),
        ]
        for p in self.patches:
            p.start()
        database.init_db()
        Path(application.UPLOAD_DIR).mkdir()
        application.app.config["TESTING"] = True
        self.client = application.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def preview(
        self,
        text=b"Magyar konyv\n\nThis is a readable story with enough text to import and then read.",
    ):
        r = self.client.post(
            "/api/import/preview", data={"file": (io.BytesIO(text), "book.txt")}
        )
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def test_preview_confirmation_is_single_use_and_overrides_metadata(self):
        preview = self.preview()
        with database.get_conn() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM books").fetchone()[0], 0)
        r = self.client.post(
            "/api/import/confirm",
            json={
                "token": preview["token"],
                "title": "Saját cím",
                "author": "Szerző",
                "language": "hu",
            },
        )
        self.assertEqual(r.status_code, 200, r.get_json())
        with database.get_conn() as c:
            book = c.execute("SELECT * FROM books").fetchone()
            self.assertEqual(book["title"], "Saját cím")
            self.assertEqual(book["language"], "hu")
            self.assertNotEqual(Path(book["file_path"]).name, "book.txt")
            self.assertTrue(Path(book["file_path"]).exists())
        again = self.client.post(
            "/api/import/confirm", json={"token": preview["token"]}
        )
        self.assertEqual(again.status_code, 400)

    def test_duplicate_does_not_add_second_book(self):
        first = self.preview()
        self.client.post("/api/import/confirm", json={"token": first["token"]})
        second = self.preview()
        self.assertIsNotNone(second["duplicate"])
        r = self.client.post("/api/import/confirm", json={"token": second["token"]})
        self.assertEqual(r.status_code, 409)

    def test_bad_token_cannot_read_local_files(self):
        r = self.client.post("/api/import/confirm", json={"token": "../../settings"})
        self.assertEqual(r.status_code, 400)

    def test_pronunciation_reaches_synthesis_without_changing_original(self):
        p = self.preview(
            "Magyar könyv\n\nGorcsev sétált a városban. Másnap hazament.".encode()
        )
        bid = self.client.post(
            "/api/import/confirm", json={"token": p["token"], "language": "hu"}
        ).get_json()["book_id"]
        self.client.post(
            "/api/pronunciation",
            json={"book_id": bid, "source": "Gorcsev", "replacement": "Gorcsef"},
        )
        with database.get_conn() as c:
            cid = c.execute(
                "SELECT id FROM chapters WHERE book_id=?", (bid,)
            ).fetchone()[0]
        segments = application._compute_segments_for_chapter(bid, cid)
        self.assertIn("Gorcsev", " ".join(s["text"] for s in segments))
        self.assertIn("Gorcsef", " ".join(s["enriched_text"] for s in segments))
        with (
            patch.object(application.tts, "status", return_value={"state": "ready"}),
            patch.object(
                application.tts,
                "generate_preview",
                return_value={"cache_key": "sample"},
            ) as generate,
        ):
            response = self.client.post(
                f"/api/books/{bid}/characters/narrator/preview",
                json={"text": "Árvíztűrő tükörfúrógép."},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            generate.call_args.kwargs["sample_text"], "Árvíztűrő tükörfúrógép."
        )
        self.assertEqual(generate.call_args.kwargs["language"], "hu")

    def test_invalid_pdf_returns_readable_error(self):
        response = self.client.post(
            "/api/import/preview", data={"file": (io.BytesIO(b"not a pdf"), "bad.pdf")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_restored_audio_is_served_from_its_portable_path(self):
        from core import library_backup

        p = self.preview()
        bid = self.client.post(
            "/api/import/confirm", json={"token": p["token"]}
        ).get_json()["book_id"]
        with database.get_conn() as c:
            cid = c.execute(
                "SELECT id FROM chapters WHERE book_id=?", (bid,)
            ).fetchone()[0]
        application._build_segments_for_chapter(bid, cid)
        source = self.root / "audio.wav"
        source.write_bytes(b"RIFF-test-audio")
        with database.get_conn() as c:
            c.execute(
                "UPDATE tts_segments SET audio_path=?,cache_key=? WHERE chapter_id=?",
                (str(source), "portable-sample", cid),
            )
        archive = library_backup.create_backup(
            self.root / "audio.zip", include_audio=True
        )
        source.unlink()
        library_backup.restore_backup(
            archive, Path(application.UPLOAD_DIR) / "restored", confirm=True
        )
        response = self.client.get("/api/audio/portable-sample")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"RIFF-test-audio")
        response.close()

    def test_metadata_and_search_use_stored_text(self):
        p = self.preview(
            "Magyar könyv\n\nGorcsev sétált a városban. Másnap ismét sétált, majd hazament.".encode()
        )
        bid = self.client.post(
            "/api/import/confirm", json={"token": p["token"]}
        ).get_json()["book_id"]
        r = self.client.patch(
            f"/api/books/{bid}/metadata", json={"collection": "Kedvencek"}
        )
        self.assertEqual(r.status_code, 200)
        result = self.client.get(f"/api/books/{bid}/search?q=Gorcsev").get_json()
        self.assertTrue(result)
        self.assertIn("Gorcsev", result[0]["excerpt"])

    def test_source_deletion_is_opt_in(self):
        p = self.preview()
        bid = self.client.post(
            "/api/import/confirm", json={"token": p["token"]}
        ).get_json()["book_id"]
        with database.get_conn() as c:
            path = c.execute(
                "SELECT file_path FROM books WHERE id=?", (bid,)
            ).fetchone()[0]
        r = self.client.post(f"/api/books/{bid}/remove", json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Path(path).exists())

    def test_removing_book_keeps_completed_export_download(self):
        from core import jobs, exporter

        p = self.preview()
        bid = self.client.post(
            "/api/import/confirm", json={"token": p["token"]}
        ).get_json()["book_id"]
        artifact = self.root / "exports" / "book.wav"
        artifact.parent.mkdir()
        artifact.write_bytes(b"RIFF-export")
        job = jobs.create_job("export_book", {"book_id": bid}, book_id=bid)
        jobs.update_job(
            job["id"], state="complete", result={"audio_path": str(artifact)}
        )
        with patch.object(exporter, "EXPORTS_DIR", str(artifact.parent)):
            response = self.client.post(f"/api/books/{bid}/remove", json={})
            self.assertEqual(response.status_code, 200)
            response = self.client.get(f"/api/jobs/{job['id']}/download/audio")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"RIFF-export")
            response.close()
        self.assertIsNone(jobs.get_job(job["id"])["book_id"])

    def test_dictionary_mutation_rejected_during_export(self):
        with patch.object(application, "_export_exclusive_active", return_value=True):
            r = self.client.post(
                "/api/pronunciation", json={"source": "Név", "replacement": "Más"}
            )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
