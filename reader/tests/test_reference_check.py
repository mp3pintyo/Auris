import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app as app_module
from core import database, reference_audio

SR = 24000
TEXT = "Az első mondat itt van. A második mondat következik. A harmadik zárja a sort."


def speech(path, seconds=6.0, lead=0.3, tail=0.3, cut_off=False):
    """Tone bursts as 'words' between quiet edges; cut_off ends inside a burst."""
    t = np.arange(int(seconds * SR)) / SR
    audio = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    audio[:int(lead * SR)] = 0.0
    if not cut_off:
        audio[len(audio) - int(tail * SR):] = 0.0
    sf.write(path, audio, SR)
    return path


class FakeTranscriber:
    def __init__(self, text, words=None):
        self.text, self.words, self.calls = text, words or [], []

    def transcribe(self, path, language=None, *, prompt="", word_timestamps=False):
        self.calls.append((language, word_timestamps))
        return {"text": self.text, "words": self.words if word_timestamps else []}


class InspectReferenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "ref.wav")

    def tearDown(self):
        self.tmp.cleanup()

    def codes(self, report):
        return {issue["code"]: issue["level"] for issue in report["issues"]}

    def test_good_reference_passes(self):
        report = reference_audio.inspect_reference(speech(self.path, 9), TEXT, "hu", FakeTranscriber(TEXT))
        self.assertTrue(report["ok"])
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["cer"], 0)

    def test_cut_off_ending_is_an_error(self):
        report = reference_audio.inspect_reference(speech(self.path, 9, cut_off=True), TEXT, "hu")
        self.assertFalse(report["ok"])
        self.assertEqual(self.codes(report)["abrupt_end"], "error")

    def test_length_limits(self):
        self.assertEqual(self.codes(reference_audio.inspect_reference(speech(self.path, 2.5), TEXT))["too_short"], "error")
        self.assertEqual(self.codes(reference_audio.inspect_reference(speech(self.path, 17), TEXT))["long"], "warn")
        self.assertEqual(self.codes(reference_audio.inspect_reference(speech(self.path, 25), TEXT))["too_long"], "error")

    def test_missing_transcript_is_suggested_from_asr(self):
        report = reference_audio.inspect_reference(speech(self.path, 9), "", "hu", FakeTranscriber(TEXT))
        self.assertEqual(report["suggested_text"], TEXT)
        self.assertIsNone(report["cer"])

    def test_transcript_disagreement_and_unheard_last_word_warn(self):
        heard = "Az első mondat itt van. Valami egészen más hangzik el a felvételen."
        codes = self.codes(reference_audio.inspect_reference(speech(self.path, 9), TEXT, "hu", FakeTranscriber(heard)))
        self.assertEqual(codes["transcript_mismatch"], "warn")
        self.assertEqual(codes["last_word"], "warn")

    def test_long_recording_offers_sentence_aligned_cuts(self):
        sentences = ["Az első mondat itt van.", "A második mondat következik.", "A harmadik zárja a sort."]
        words, t = [], 0.3
        for sentence in sentences:
            for token in sentence.split():
                words.append({"word": token, "start": t, "end": t + 1.0})
                t += 1.0
            t += 2.0
        transcriber = FakeTranscriber(TEXT, words)
        report = reference_audio.inspect_reference(speech(self.path, 30), TEXT, "hu", transcriber)
        self.assertTrue(transcriber.calls[0][1])  # word timestamps requested
        self.assertTrue(report["candidates"])
        for cand in report["candidates"]:
            self.assertLessEqual(cand["duration"], reference_audio.IDEAL_MAX_SECONDS)
            self.assertIn(cand["text"].split(".")[0], TEXT)

    def test_cut_reference_writes_stretch_and_rejects_short(self):
        dst = os.path.join(self.tmp.name, "cut.wav")
        self.assertAlmostEqual(reference_audio.cut_reference(speech(self.path, 10), dst, 2, 7), 5.0)
        self.assertAlmostEqual(sf.info(dst).duration, 5.0, places=2)
        with self.assertRaises(ValueError):
            reference_audio.cut_reference(self.path, dst, 2, 3)


class ReferenceCheckApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original = (database.DB_PATH, app_module.UPLOAD_DIR, app_module._startup_complete)
        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        app_module.UPLOAD_DIR = self.tmp.name
        app_module._startup_complete = True
        database.init_db()
        with database.get_conn() as conn:
            conn.execute("INSERT INTO books (id, title, file_path, file_type, language) "
                         "VALUES (1, 'Teszt', 't.txt', 'txt', 'hu')")
            conn.execute("INSERT INTO characters (id, book_id, name) VALUES (2, 1, 'Anna')")
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        database.DB_PATH, app_module.UPLOAD_DIR, app_module._startup_complete = self.original
        self.tmp.cleanup()

    def upload(self, url, seconds=9.0, text=""):
        with open(speech(os.path.join(self.tmp.name, "src.wav"), seconds), "rb") as fh:
            data = {"file": (io.BytesIO(fh.read()), "hang.wav"), "ref_text": text}
        response = self.client.post(url, data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_check_fills_empty_transcript_from_asr(self):
        self.upload("/api/books/1/narrator-ref-audio")
        with patch("core.qa.Transcriber.whisper_for", return_value=FakeTranscriber(TEXT)) as whisper, \
                patch("core.qa.Transcriber.unload_all"):
            report = self.client.post("/api/books/1/narrator-ref-audio/check").get_json()
        whisper.assert_called_once_with("hu")
        self.assertTrue(report["ref_text_saved"])
        self.assertEqual(report["ref_text"], TEXT)
        with database.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT narrator_ref_text FROM books WHERE id=1").fetchone()[0], TEXT)

    def test_check_keeps_existing_transcript(self):
        self.upload("/api/characters/2/ref-audio", text="Saját átirat.")
        with patch("core.qa.Transcriber.whisper_for", return_value=FakeTranscriber("Saját átirat.")), \
                patch("core.qa.Transcriber.unload_all"):
            report = self.client.post("/api/characters/2/ref-audio/check").get_json()
        self.assertFalse(report["ref_text_saved"])
        self.assertTrue(report["ok"])

    def test_trim_replaces_reference_and_transcript(self):
        self.upload("/api/characters/2/ref-audio", seconds=30, text=TEXT)
        with database.get_conn() as conn:
            old = conn.execute("SELECT ref_audio_path FROM characters WHERE id=2").fetchone()[0]
        response = self.client.post("/api/characters/2/ref-audio/trim",
                                    json={"start": 3.0, "end": 14.0, "text": "A második mondat következik."})
        self.assertEqual(response.status_code, 200, response.get_json())
        with database.get_conn() as conn:
            row = conn.execute("SELECT ref_audio_path, ref_audio_name, ref_text FROM characters WHERE id=2").fetchone()
        self.assertNotEqual(row[0], old)
        self.assertFalse(os.path.exists(old))
        self.assertAlmostEqual(sf.info(row[0]).duration, 11.0, places=2)
        self.assertEqual(row[2], "A második mondat következik.")
        self.assertIn("3,0–14,0 s", row[1])

    def test_trim_validates_input(self):
        self.upload("/api/characters/2/ref-audio", seconds=10, text=TEXT)
        for body in ({"start": 1, "end": 2, "text": "x"}, {"start": "a", "end": 5, "text": "x"},
                     {"start": 1, "end": 8}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/characters/2/ref-audio/trim", json=body).status_code, 400)

    def test_upload_accepts_audio_formats_only(self):
        response = self.client.post("/api/characters/2/ref-audio",
                                    data={"file": (io.BytesIO(b"x"), "jegyzet.txt")},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_unreadable_non_wav_upload_is_rejected(self):
        response = self.client.post("/api/characters/2/ref-audio",
                                    data={"file": (io.BytesIO(b"not audio"), "hang.mp3"), "clean": "0"},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertIn("nem olvasható", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
