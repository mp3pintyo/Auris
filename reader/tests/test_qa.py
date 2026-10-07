import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app as app_module
from core import database, qa, jobs
from core import settings as app_settings


def _tone(path, seconds=1.0, amp=0.2, sr=24000, gap=None):
    t = np.arange(int(sr * seconds)) / sr
    audio = (np.sin(2 * np.pi * 220 * t) * amp).astype("float32")
    if gap:
        start, length = gap
        audio[int(start * sr):int((start + length) * sr)] = 0
    sf.write(path, audio, sr)
    return path


class ScoringTest(unittest.TestCase):
    def test_accents_matter_but_case_and_punctuation_do_not(self):
        self.assertEqual(qa.score_transcript("Kor, vagy kór?", "kor vagy kór", "hu")["cer"], 0)
        self.assertGreater(qa.score_transcript("tőr", "tör", "hu")["cer"], 0)

    def test_numbers_are_compared_in_spoken_form(self):
        result = qa.score_transcript("1848. március 15-én", "ezernyolcszáznegyvennyolc március tizenötödikén", "hu")
        self.assertEqual(result["cer"], 0)

    def test_missing_words_are_reported(self):
        result = qa.score_transcript("Anna gyorsan hazament", "Anna hazament", "hu")
        self.assertIn("gyorsan", result["missing_words"])
        self.assertGreater(result["wer"], 0.3)

    def test_compound_spacing_is_not_a_word_error(self):
        pairs = [
            ("A 2026-os évben", "a kétezerhuszonhatos évben"),
            ("a szurdokon át vezet a vízeséshez", "a szurdokon átvezet a vízeséshez"),
            ("a nagyterem bejárata", "a nagy terem bejárata"),
            ("Szentgyörgyvölgyi Ödön levelezése", "Szentgyörgy völgyi ödönlevelezése"),
        ]
        for expected, heard in pairs:
            with self.subTest(expected=expected):
                result = qa.score_transcript(expected, heard, "hu")
                self.assertEqual(result["wer"], 0)
                self.assertEqual(result["missing_words"], [])

    def test_real_word_changes_still_count(self):
        self.assertAlmostEqual(qa.score_transcript("a peronon állt", "a perronon állt", "hu")["wer"], 1 / 3, places=3)
        self.assertAlmostEqual(qa.score_transcript("nagy kert", "nagykertek", "hu")["wer"], 1.0)


class AudioCheckTest(unittest.TestCase):
    def test_long_pause_and_silence_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            gap = qa.analyze_audio(_tone(os.path.join(tmp, "a.wav"), 4, gap=(1.0, 2.0)), "Egy kettő három négy öt")
            self.assertIn("long_pause", gap["flags"])
            silent = qa.analyze_audio(_tone(os.path.join(tmp, "b.wav"), 1, amp=0.0), "Szöveg")
            self.assertIn("silent", silent["flags"])

    def test_too_fast_for_the_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = qa.analyze_audio(_tone(os.path.join(tmp, "a.wav"), 0.3),
                                       "Ez egy nagyon hosszú mondat, amit lehetetlen ennyi idő alatt kimondani.")
        self.assertIn("too_fast", metrics["flags"])

    def test_classify_uses_cer_and_flags(self):
        self.assertEqual(qa.classify(0.01, []), "ok")
        self.assertEqual(qa.classify(0.1, []), "warn")
        self.assertEqual(qa.classify(0.3, []), "fail")
        self.assertEqual(qa.classify(None, ["silent"]), "fail")
        self.assertEqual(qa.classify(None, ["long_pause"]), "warn")

    def test_loudness_report_checks_acx_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = qa.loudness_report(_tone(os.path.join(tmp, "a.wav"), 3, amp=0.15))
        self.assertIn("rms_db", report)
        self.assertTrue(report["acx_checks"]["peak"])
        self.assertIsInstance(report["acx_pass"], bool)


class _ToneEngine:
    engine_name = "omnivoice"

    def __init__(self, folder):
        self.folder = folder
        self.generated = []

    def status(self):
        return {"state": "ready", "engine": "omnivoice", "capabilities": {"takes": True}}

    def generate(self, text="", take=0, **kw):
        self.generated.append((text, take))
        self.last_voice = {key: kw.get(key) for key in ("instruct", "ref_audio", "ref_text")}
        key = f"k{abs(hash((text, take))) % 10**12}"
        path = os.path.join(self.folder, key + ".wav")
        # Take 0 is silent (a failed render); later takes are fine.
        _tone(path, max(1.0, len(text) * 0.07), amp=0.0 if take == 0 else 0.2)
        return {"audio_path": path, "cache_key": key, "duration_sec": 1.0, "cache_hit": False}

    def generate_many(self, items, on_item=None, **kw):
        results = []
        for index, item in enumerate(items):
            result = self.generate(**item)
            results.append(result)
            if on_item:
                on_item(index, result)
        return results

    def __getattr__(self, name):
        return lambda *a, **k: None


class QaApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmp.name, "reader.db")),
            patch.object(app_settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"),
            patch.object(app_module, "_startup_complete", True),
        ]
        for p in self.patches:
            p.start()
        database.init_db()
        jobs.init_jobs()
        self.engine = _ToneEngine(self.tmp.name)
        self.tts_patch = patch.object(app_module, "tts", self.engine)
        self.tts_patch.start()
        with database.get_conn() as conn:
            conn.execute("INSERT INTO books (id,title,file_path,file_type,language,single_narrator_mode) "
                         "VALUES (1,'K','k.txt','txt','hu',1)")
            conn.execute("INSERT INTO chapters (id,book_id,title,order_num,content) VALUES "
                         "(1,1,'F',0,'Első mondat itt van. Második mondat is.')")
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.tts_patch.stop()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _wait(self, job_id):
        for _ in range(600):
            job = jobs.get_job(job_id)
            if job["state"] not in ("pending", "running"):
                return job
            time.sleep(0.05)
        self.fail("QA job did not finish")

    def test_check_regenerates_failed_sentence_and_lists_takes(self):
        response = self.client.post("/api/books/1/chapters/1/qa", json={"asr": False, "auto_regenerate": True})
        self.assertEqual(response.status_code, 200, response.get_json())
        job = self._wait(response.get_json()["job_id"])
        self.assertEqual(job["state"], "complete", job)
        self.assertGreaterEqual(job["result"]["regenerated"], 1)
        data = self.client.get("/api/books/1/chapters/1/qa").get_json()
        first = data["segments"][0]
        self.assertEqual(first["status"], "ok", first)
        self.assertGreaterEqual(len(first["takes"]), 2)
        self.assertTrue(any(t["selected"] and t["take"] > 0 for t in first["takes"]))

    def test_manual_take_selection_and_approval(self):
        for expected in (1, 2):
            response = self.client.post("/api/books/1/chapters/1/segments/0/takes")
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["take"], expected)
        response = self.client.post("/api/books/1/chapters/1/segments/0/select-take", json={"take": 1})
        self.assertEqual(response.status_code, 200)
        data = self.client.get("/api/books/1/chapters/1/qa").get_json()
        selected = [t["take"] for t in data["segments"][0]["takes"] if t["selected"]]
        self.assertEqual(selected, [1])
        response = self.client.post("/api/books/1/chapters/1/segments/0/approve", json={"approved": True})
        self.assertTrue(response.get_json()["approved"])
        data = self.client.get("/api/books/1/chapters/1/qa").get_json()
        self.assertTrue(data["segments"][0]["approved"])
        self.assertEqual(data["summary"]["approved"], 1)

    def test_take_in_another_saved_voice_is_labelled(self):
        with database.get_conn() as conn:
            conn.execute("INSERT INTO voice_profiles (id,name,instruct) VALUES (4,'Mély mesélő','male, elderly, low pitch')")
        response = self.client.post("/api/books/1/chapters/1/segments/0/takes", json={"profile_id": 4})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.engine.last_voice["instruct"], "male, elderly, low pitch")
        self.assertIsNone(self.engine.last_voice["ref_audio"])
        takes = self.client.get("/api/books/1/chapters/1/qa").get_json()["segments"][0]["takes"]
        self.assertEqual([t["voice_label"] for t in takes if t["take"] == 1], ["Mély mesélő"])
        missing = self.client.post("/api/books/1/chapters/1/segments/0/takes", json={"profile_id": 99})
        self.assertEqual(missing.status_code, 400)


if __name__ == "__main__":
    unittest.main()
