import unittest

from core.tts_engine import TTSEngine


class TtsCacheKeyRenderVariantTest(unittest.TestCase):
    """The audio cache key must distinguish renders produced by different
    devices or dtypes.

    Without this, audio generated on one backend is served for a request on
    another. A user who switches device, or who sets a dtype override, keeps
    hearing the previously cached render and the change looks like it had no
    effect.
    """

    ARGS = ("Hello there.", None, None, 1.0)
    KWARGS = {
        "ref_text": None,
        "language": "en",
        "normalize_text": False,
        "num_step": 24,
    }

    def _key(self, **extra):
        return TTSEngine.cache_key(*self.ARGS, **self.KWARGS, **extra)

    def test_same_variant_is_stable(self):
        self.assertEqual(
            self._key(variant="mps/torch.float32"),
            self._key(variant="mps/torch.float32"),
        )

    def test_dtype_change_changes_key(self):
        self.assertNotEqual(
            self._key(variant="mps/torch.float32"),
            self._key(variant="mps/torch.bfloat16"),
        )

    def test_device_change_changes_key(self):
        self.assertNotEqual(
            self._key(variant="mps/torch.float32"),
            self._key(variant="cpu/torch.float32"),
        )

    def test_omitted_variant_matches_empty_variant(self):
        """Callers that pass no variant keep the historical key, so existing
        cache entries and stored tts_segments.cache_key values stay valid."""
        self.assertEqual(self._key(), self._key(variant=""))

    def test_render_variant_is_empty_before_load(self):
        engine = TTSEngine(model_path="/nonexistent/model")
        self.assertEqual(engine.render_variant, "")


if __name__ == "__main__":
    unittest.main()
