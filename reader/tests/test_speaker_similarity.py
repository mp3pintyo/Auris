import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core import speaker_similarity as ss


class VectorMathTest(unittest.TestCase):
    def test_similarity_is_scale_invariant_cosine(self):
        a = np.array([1.0, 0.0, 0.0])
        self.assertAlmostEqual(ss.similarity(a, 5 * a), 1.0, places=6)
        self.assertAlmostEqual(ss.similarity(a, np.array([0.0, 2.0, 0.0])), 0.0, places=6)

    def test_centroid_weights_each_vector_equally(self):
        c = ss.centroid([np.array([10.0, 0.0]), np.array([0.0, 1.0])])
        self.assertAlmostEqual(float(np.linalg.norm(c)), 1.0, places=6)
        self.assertAlmostEqual(float(c[0]), float(c[1]), places=6)
        with self.assertRaises(ValueError):
            ss.centroid([])


class WindowTest(unittest.TestCase):
    def test_long_audio_drops_short_tail(self):
        sr = ss.SAMPLE_RATE
        pieces = ss.windows(np.zeros(int(sr * 40.2)), sr)
        self.assertEqual([len(p) for p in pieces], [20 * sr, 20 * sr])

    def test_keeps_usable_tail_and_short_audio(self):
        sr = ss.SAMPLE_RATE
        self.assertEqual(len(ss.windows(np.zeros(int(sr * 21)), sr)), 2)
        self.assertEqual(len(ss.windows(np.zeros(int(sr * 0.4)), sr)), 1)


class FakeSession:
    def __init__(self):
        self.shapes = []

    def run(self, _outputs, feeds):
        x = feeds["x"]
        self.shapes.append(x.shape)
        return [np.ones((1, 192), dtype=np.float32) * (len(self.shapes))]


class EmbedTest(unittest.TestCase):
    def test_embeds_resampled_windows_with_80_bin_features(self):
        embedder = ss.SpeakerEmbedder(Path("unused.onnx"))
        embedder._session, embedder._input = FakeSession(), "x"
        rng = np.random.default_rng(0)
        vector = embedder.embed(0.1 * rng.standard_normal(24000 * 25).astype(np.float32), 24000)
        shapes = embedder._session.shapes
        self.assertEqual(len(shapes), 2)
        self.assertTrue(all(s[0] == 1 and s[2] == 80 for s in shapes))
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)

    def test_rejects_too_short_audio(self):
        embedder = ss.SpeakerEmbedder(Path("unused.onnx"))
        with self.assertRaises(ValueError):
            embedder.embed(np.zeros(1000, dtype=np.float32), 16000)

    def test_fbank_removes_mean(self):
        feats = ss.fbank(0.1 * np.random.default_rng(1).standard_normal(16000).astype(np.float32))
        self.assertEqual(feats.shape[1], 80)
        self.assertTrue(np.allclose(feats.mean(axis=0), 0.0, atol=1e-4))


class EnsureModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.tmp.name) / ss.MODEL_FILE
        self.patcher = patch.object(ss, "model_path", return_value=self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_missing_model_without_download_raises(self):
        with self.assertRaises(FileNotFoundError):
            ss.ensure_model(download=False)

    def test_checksum_mismatch_deletes_download(self):
        def fake_download(**kwargs):
            self.assertEqual(kwargs["revision"], ss.MODEL_REVISION)
            self.path.write_bytes(b"not a model")
            return str(self.path)

        with patch("huggingface_hub.hf_hub_download", side_effect=fake_download):
            with self.assertRaises(RuntimeError):
                ss.ensure_model()
        self.assertFalse(self.path.exists())

    def test_verified_file_is_reused(self):
        self.path.write_bytes(b"model")
        with patch.object(ss, "MODEL_SHA256", ss._sha256(self.path)), \
                patch("huggingface_hub.hf_hub_download") as download:
            self.assertEqual(ss.ensure_model(), self.path)
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
