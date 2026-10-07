import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app as app_module
from core import database, reference_audition

SR = 24000


class FakeEngine:
    """Renders tag the clip they cloned; candidate 1 sounds most like the speaker."""

    engine_name = "omnivoice"

    def __init__(self, folder):
        self.folder, self.items, self.invalidated = folder, [], []

    def generate_many(self, items):
        self.items = items
        out = []
        for n, item in enumerate(items):
            clip = os.path.basename(item["ref_audio"]).split(".")[0]
            path = os.path.join(self.folder, f"{clip}-{n}.wav")
            sf.write(path, np.zeros(2400, dtype=np.float32), SR)
            out.append({"audio_path": path})
        return out

    def invalidate_voice_prompt(self, path, text):
        self.invalidated.append(os.path.basename(path))


class FakeEmbedder:
    VECTORS = {"jelolt1": [1.0, 0.5], "jelolt2": [1.0, 0.1], "jelolt3": [1.0, 0.0]}

    def embed_file(self, path):
        name = os.path.basename(path)
        for clip, vector in self.VECTORS.items():
            if name.startswith(clip):
                return np.array(vector)
        return np.array([1.0, 0.0])  # the whole recording


class FakeTranscriber:
    def transcribe(self, path, language=None, **kwargs):
        # Candidate 3 is the most similar but garbles every sentence.
        if os.path.basename(path).startswith("jelolt3"):
            return {"text": "valami egészen más"}
        index = int(os.path.basename(path).split("-")[1].split(".")[0]) // 2 % len(reference_audition.TEST_SENTENCES)
        return {"text": reference_audition.TEST_SENTENCES[index]}


def speech(path, seconds=40):
    t = np.arange(int(seconds * SR)) / SR
    sf.write(path, (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), SR)
    return path


class AuditionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.source = speech(os.path.join(self.tmp.name, "hosszu.wav"))
        self.engine = FakeEngine(self.tmp.name)
        self.cands = [{"start": 0, "end": 10, "text": "Egy."}, {"start": 10, "end": 22, "text": "Kettő."},
                      {"start": 22, "end": 35, "text": "Három."}]

    def tearDown(self):
        self.tmp.cleanup()

    def run_audition(self):
        return reference_audition.audition(self.engine, self.source, self.cands, "hu",
                                           embedder=FakeEmbedder(), transcriber=FakeTranscriber())

    def test_recommends_most_similar_within_word_error_guard(self):
        report = self.run_audition()
        self.assertEqual(report["recommended"], 1)
        rows = {r["index"]: r for r in report["results"]}
        self.assertGreater(rows[2]["similarity"], rows[1]["similarity"])  # excluded by its errors
        self.assertGreater(rows[2]["wer"], reference_audition.WER_GUARD)
        self.assertEqual(rows[0]["renders"], len(reference_audition.TEST_SENTENCES) * len(reference_audition.TAKES))

    def test_renders_use_cut_clips_with_their_text_and_are_cleaned_up(self):
        self.run_audition()
        texts = {(os.path.basename(i["ref_audio"]), i["ref_text"]) for i in self.engine.items}
        self.assertEqual(texts, {("jelolt1.wav", "Egy."), ("jelolt2.wav", "Kettő."), ("jelolt3.wav", "Három.")})
        self.assertEqual({i["take"] for i in self.engine.items}, set(reference_audition.TAKES))
        self.assertEqual(sorted(n for n in os.listdir(self.tmp.name) if n != "hosszu.wav"), [])
        self.assertEqual(sorted(self.engine.invalidated), ["jelolt1.wav", "jelolt2.wav", "jelolt3.wav"])

    def test_requires_candidates(self):
        with self.assertRaises(ValueError):
            reference_audition.audition(self.engine, self.source, [], "hu",
                                        embedder=FakeEmbedder(), transcriber=FakeTranscriber())


class AuditionApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original = (database.DB_PATH, app_module.UPLOAD_DIR, app_module._startup_complete)
        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        app_module.UPLOAD_DIR = self.tmp.name
        app_module._startup_complete = True
        database.init_db()
        ref = speech(os.path.join(self.tmp.name, "narrator_ref_1_abc.wav"), 30)
        with database.get_conn() as conn:
            conn.execute("INSERT INTO books (id, title, file_path, file_type, language, narrator_ref_audio_path, "
                         "narrator_ref_text) VALUES (1, 'T', 't', 'txt', 'hu', ?, 'Szöveg.')", (ref,))
        self.client = app_module.app.test_client()

    def tearDown(self):
        database.DB_PATH, app_module.UPLOAD_DIR, app_module._startup_complete = self.original
        self.tmp.cleanup()

    def post(self, candidates):
        return self.client.post("/api/books/1/narrator-ref-audio/audition", json={"candidates": candidates})

    def test_rejects_invalid_stretches(self):
        with patch.object(app_module.tts, "status", return_value={"state": "ready"}):
            for cand in ({"start": 0, "end": 2, "text": "x"}, {"start": 0, "end": 99, "text": "x"},
                         {"start": "a", "end": 9, "text": "x"}, {"start": 0, "end": 9}):
                with self.subTest(cand=cand):
                    self.assertEqual(self.post([cand]).status_code, 400)
            self.assertEqual(self.post([]).status_code, 400)

    def test_passes_valid_stretches_to_audition(self):
        fake = {"results": [], "recommended": 0, "sentences": 4, "takes": 2}
        with patch.object(app_module.tts, "status", return_value={"state": "ready"}), \
                patch("core.reference_audition.audition", return_value=fake) as run, \
                patch("core.qa.Transcriber.unload_all"):
            response = self.post([{"start": 1, "end": 12, "text": "Első."}])
        self.assertEqual(response.status_code, 200, response.get_json())
        args = run.call_args
        self.assertEqual(args.args[2], [{"start": 1.0, "end": 12.0, "text": "Első."}])
        self.assertEqual(args.kwargs["takes"], reference_audition.TAKES)


if __name__ == "__main__":
    unittest.main()
