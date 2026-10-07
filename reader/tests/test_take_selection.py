import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app  # noqa: F401  (registers the blueprints before core.export_api)
from core import database, take_selection
from core.export_api import _export_options


def judged(wer, sim=0.0):
    return {"similarity": sim, "judge": lambda: (wer, wer)}


class SelectionRuleTest(unittest.TestCase):
    def test_most_similar_clean_checks_in_likeness_order(self):
        takes = [judged(0.0, 0.7), judged(0.1, 0.9), judged(0.0, 0.8)]
        choice = take_selection.most_similar_clean(takes, 3)
        self.assertIs(choice.take, takes[2])
        self.assertEqual(choice.checks, 2)

    def test_most_similar_without_clean_take_keeps_fewest_errors(self):
        takes = [judged(0.3, 0.9), judged(0.1, 0.8), judged(0.1, 0.7), judged(0.0, 0.1)]
        choice = take_selection.most_similar_clean(takes, 3)
        self.assertIs(choice.take, takes[1])
        self.assertEqual(choice.reason, "similar-fewest-errors")

    def test_fewest_errors_stops_at_first_clean(self):
        takes = [judged(0.2), judged(0.0), judged(0.0)]
        choice = take_selection.fewest_errors(takes, 3)
        self.assertIs(choice.take, takes[1])
        self.assertEqual(choice.checks, 2)

    def test_modes_and_options(self):
        self.assertIsNone(take_selection.policy_name("normal"))
        self.assertEqual(take_selection.policy_name("similar10"), "similar:10:5")
        self.assertEqual(_export_options({"take_mode": "similar5"})["take_mode"], "similar5")
        self.assertEqual(_export_options({})["take_mode"], "normal")
        with self.assertRaises(ValueError):
            _export_options({"take_mode": "best-of-99"})


class FakeEngine:
    """Take t of a sentence sounds like voice vector [t, 1]; take 3 is the only clean one."""

    engine_name = "omnivoice"

    def __init__(self, folder):
        self.folder, self.calls = folder, []

    def generate_many(self, items, num_step=None, on_item=None, on_status=None):
        self.calls.append(items)
        results = []
        for i, item in enumerate(items):
            path = os.path.join(self.folder, f"{abs(hash(item['text'])) % 10_000}-take{item['take']}.wav")
            sf.write(path, np.zeros(2400, dtype=np.float32), 24000)
            result = {"audio_path": path, "duration_sec": 0.1, "cache_key": f"k{item['take']}", "cache_hit": False}
            results.append(result)
            on_item(i, result)
        return results


class FakeEmbedder:
    def embed_file(self, path):
        name = os.path.basename(path)
        if name == "ref.wav":
            return np.array([1.0, 0.0])
        if name == "original.wav":  # take 0: an ordinary first render
            return np.array([1.0, 0.5])
        take = int(name.rsplit("take", 1)[1].split(".")[0]) if "take" in name else 0
        return np.array([1.0, 0.2 * take]) if take != 4 else np.array([1.0, 0.0])


class FakeTranscriber:
    def __init__(self):
        self.heard = []

    def transcribe(self, path, language=None, **kwargs):
        self.heard.append(os.path.basename(path))
        clean = "take3" in path or "take4" in path
        return {"text": "Jó reggelt kívánok." if clean else "Jó reggel kívánok."}


class ExportTakeSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_db = database.DB_PATH
        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        database.init_db()
        self.ref = os.path.join(self.tmp.name, "ref.wav")
        self.take0 = os.path.join(self.tmp.name, "original.wav")
        for path in (self.ref, self.take0):
            sf.write(path, np.zeros(2400, dtype=np.float32), 24000)
        with database.get_conn() as conn:
            conn.execute("INSERT INTO books (id, title, file_path, file_type, language) VALUES (1,'T','t','txt','hu')")
            conn.execute("INSERT INTO chapters (id, book_id, title, order_num, content, word_count) "
                         "VALUES (2, 1, 'Egy', 0, 'x', 1)")
            conn.execute("INSERT INTO tts_segments (id, book_id, chapter_id, segment_index, text, enriched_text, "
                         "audio_path, duration_sec, cache_key) VALUES (3, 1, 2, 0, 'Jó reggelt kívánok.', "
                         "'Jó reggelt kívánok.', ?, 0.1, 'k0')", (self.take0,))
        self.engine = FakeEngine(self.tmp.name)
        self.app = SimpleNamespace(
            tts=self.engine,
            _book_narrator_reference=lambda book_id: (self.ref, "Referencia."),
            _check_job_cancelled=lambda job, throttle=False: None,
            _bump_export_progress=lambda job, n=1, synthesized=False: (
                job is not None and job.__setitem__("done", job.get("done", 0) + n)),
        )
        self.transcriber = FakeTranscriber()
        patches = [
            patch("core.speaker_similarity.get_embedder", return_value=FakeEmbedder()),
            patch("core.qa.Transcriber.whisper_for", return_value=self.transcriber),
            patch("core.qa.Transcriber.unload_all"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        database.DB_PATH = self.original_db
        self.tmp.cleanup()

    def segments(self):
        with database.get_conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM tts_segments")]

    def test_keeps_most_similar_clean_take_and_removes_losers(self):
        segs, job = self.segments(), {"total": 1, "done": 1}
        changed = take_selection.select_export_takes(self.app, 1, segs, job, "similar5")
        self.assertEqual(changed, 1)
        self.assertEqual([item["take"] for item in self.engine.calls[0]], [1, 2, 3, 4])
        row = self.segments()[0]
        # Take 4 is closest to the reference and clean; 3 is clean but less similar.
        self.assertTrue(row["audio_path"].endswith("take4.wav"))
        self.assertEqual(row["take_policy"], "similar:5:3")
        self.assertEqual(self.transcriber.heard, [os.path.basename(row["audio_path"])])
        self.assertFalse(os.path.exists(self.take0))  # replaced and used by no segment
        leftovers = [n for n in os.listdir(self.tmp.name) if "-take" in n]
        self.assertEqual(leftovers, [os.path.basename(row["audio_path"])])
        self.assertEqual((job["total"], job["done"]), (2, 2))

    def test_same_mode_is_not_repeated(self):
        take_selection.select_export_takes(self.app, 1, self.segments(), None, "similar5")
        self.engine.calls.clear()
        self.assertEqual(take_selection.select_export_takes(self.app, 1, self.segments(), None, "similar5"), 0)
        self.assertEqual(self.engine.calls, [])

    def test_engine_without_takes_is_left_alone(self):
        self.engine.engine_name = "piper"
        self.assertEqual(take_selection.select_export_takes(self.app, 1, self.segments(), None, "similar5"), 0)
        self.assertEqual(self.engine.calls, [])

    def test_normal_render_clears_policy(self):
        take_selection.select_export_takes(self.app, 1, self.segments(), None, "similar5")
        with database.get_conn() as conn:
            conn.execute("UPDATE tts_segments SET audio_path=?, duration_sec=?, cache_key=?, "
                         "take_policy=NULL WHERE id=?", (self.take0, 0.1, "k0", 3))
        self.assertIsNone(self.segments()[0]["take_policy"])


if __name__ == "__main__":
    unittest.main()
