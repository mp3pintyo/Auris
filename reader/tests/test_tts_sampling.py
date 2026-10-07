import unittest
from unittest.mock import patch

from core import tts_engine
from core.tts_engine import sampling_kwargs


class SamplingKwargsTest(unittest.TestCase):
    def test_keeps_known_fields_and_clamps(self):
        self.assertEqual(
            sampling_kwargs({"guidance_scale": 2, "position_temperature": 99,
                             "num_step": 64, "class_temperature": None}),
            {"guidance_scale": 2.0, "position_temperature": 20.0},
        )
        self.assertEqual(sampling_kwargs(None), {})

    def test_generate_kwargs_carry_overrides_only_when_given(self):
        engine = tts_engine.TTSEngine.__new__(tts_engine.TTSEngine)
        common = dict(texts=["Szia."], instruct="female", ref_audio=None, ref_text=None,
                      speeds=[1.0], num_step=32, language="hu", normalize_text=False)
        plain = engine._build_generate_kwargs(**common)
        self.assertNotIn("guidance_scale", plain)
        tuned = engine._build_generate_kwargs(
            **common, sampling={"guidance_scale": 2.0, "position_temperature": 0.5})
        self.assertEqual(tuned["guidance_scale"], 2.0)
        self.assertEqual(tuned["position_temperature"], 0.5)
        self.assertEqual(tuned["num_step"], 32)


if __name__ == "__main__":
    unittest.main()
