import importlib.util
import random
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(f"auris_{name}", ROOT / "scripts" / "voice_training" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


train = load("train_omnivoice")
prepare = load("prepare_dataset")
reading = load("make_reading_script")


class TrainingHelpersTest(unittest.TestCase):
    def test_auto_epochs_scale_with_training_audio(self):
        self.assertEqual(train.auto_epochs(14), 25)
        self.assertEqual(train.auto_epochs(2), 66)
        self.assertEqual(train.auto_epochs(0.05), 100)
        self.assertEqual(train.auto_epochs(200), 10)

    def test_batches_respect_padded_token_budget_and_keep_every_sample(self):
        rng = random.Random(1)
        samples = [{"length": rng.randint(100, 900), "id": n} for n in range(200)]
        batches = train.batches_by_tokens(samples, 4096, random.Random(0))
        self.assertTrue(all(max(s["length"] for s in b) * len(b) <= 4096 for b in batches))
        self.assertEqual(sorted(s["id"] for b in batches for s in b), list(range(200)))


class PrepareDatasetTest(unittest.TestCase):
    def test_clip_quality_gates(self):
        sr = prepare.SAMPLE_RATE
        voice = 0.3 * np.sin(np.arange(sr * 4) / 8).astype(np.float32)
        self.assertIsNone(prepare.clip_problem(voice, "egy kettő három négy öt hat hét nyolc"))
        self.assertIn("tempó", prepare.clip_problem(voice, "egy"))
        self.assertEqual(prepare.clip_problem(voice * 0.01, "egy kettő három négy öt hat"), "túl halk")
        loud = np.clip(voice * 10, -1, 1)
        self.assertEqual(prepare.clip_problem(loud, "egy kettő három négy öt hat"), "túlvezérelt")


class ReadingScriptTest(unittest.TestCase):
    def test_sessions_keep_whole_paragraphs_and_stop_at_the_limit(self):
        paragraphs = [" ".join(["szó"] * 50) for _ in range(20)]
        parts = reading.sessions(paragraphs, 120, 3)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(len(p) == 3 for p in parts))


if __name__ == "__main__":
    unittest.main()
