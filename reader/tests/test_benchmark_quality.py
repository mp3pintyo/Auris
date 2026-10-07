import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "auris_benchmark_quality", ROOT / "scripts" / "benchmark_quality.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def take(wer, sim, cer=None, n=0):
    return dict(wer=wer, cer=wer if cer is None else cer, similarity=sim, take=n,
                gen_seconds=1.0, audio_seconds=4.0)


class SelectionPolicyTest(unittest.TestCase):
    def test_fewest_errors_stops_at_first_clean_take(self):
        takes = [take(0.2, 0.9), take(0.0, 0.7), take(0.0, 0.95)]
        chosen, renders, checks = bench.pick_fewest_errors(takes)
        self.assertIs(chosen, takes[1])
        self.assertEqual((renders, checks), (2, 2))

    def test_fewest_errors_without_clean_take_keeps_lowest(self):
        takes = [take(0.3, 0.9), take(0.1, 0.7), take(0.2, 0.95), take(0.0, 0.99)]
        chosen, renders, _ = bench.pick_fewest_errors(takes)
        self.assertIs(chosen, takes[1])
        self.assertEqual(renders, 3)

    def test_most_similar_checks_in_likeness_order(self):
        takes = [take(0.0, 0.70), take(0.1, 0.90), take(0.0, 0.85), take(0.0, 0.60), take(0.0, 0.95)]
        chosen, renders, checks = bench.pick_most_similar(takes, 5, 3)
        self.assertIs(chosen, takes[4])
        self.assertEqual((renders, checks), (5, 3))
        takes[4]["wer"] = 0.2
        chosen, _, _ = bench.pick_most_similar(takes, 5, 3)
        self.assertIs(chosen, takes[2])

    def test_most_similar_falls_back_to_fewest_errors_then_likeness(self):
        takes = [take(0.2, 0.9), take(0.1, 0.8), take(0.1, 0.85), take(0.0, 0.1), take(0.3, 0.7)]
        chosen, _, _ = bench.pick_most_similar(takes, 5, 3)
        self.assertIs(chosen, takes[2])

    def test_policies_follow_available_seeds(self):
        self.assertEqual([p[0] for p in bench.policies(1)], ["1 take"])
        self.assertEqual(len(bench.policies(5)), 3)
        self.assertEqual(len(bench.policies(10)), 4)

    def test_summary_reports_selection_and_spread(self):
        cells = {("r", "s32"): {0: [take(0.1, 0.8, n=0), take(0.0, 0.9, n=1)],
                                1: [take(0.0, 0.7, n=0), take(0.0, 0.6, n=1)]}}
        rows = {r["policy"]: r for r in bench.summarize(cells, 2)}
        self.assertEqual(rows["1 take"]["clean_lines"], 1)
        self.assertEqual(rows["fewest errors of 2"]["clean_lines"], 2)
        self.assertAlmostEqual(rows["1 take"]["rtf"], 0.25)
        self.assertAlmostEqual(rows["1 take"]["take_similarity_spread"], 0.05)

    def test_bundled_texts_are_hungarian_sentences(self):
        texts = bench.load_texts(bench.TEXTS_FILE, None)
        self.assertGreaterEqual(len(texts), 40)
        self.assertTrue(all(not t.startswith("#") for t in texts))


if __name__ == "__main__":
    unittest.main()
