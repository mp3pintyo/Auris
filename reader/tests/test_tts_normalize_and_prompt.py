import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from core.tts_engine import (
    TTSEngine,
    apply_text_normalization,
    _coalesce_pending_items,
    _num2words_fallback,
    _pack_items_for_batch,
    _prompt_cache_key,
    _split_audio_by_char_weights,
)


class _FakePrompt:
    def __init__(self, ref_text="ref"):
        self.ref_audio_tokens = MagicMock()
        self.ref_audio_tokens.detach.return_value.cpu.return_value = "tokens"
        self.ref_text = ref_text
        self.ref_rms = 0.05
        self.saved_to = None

    def save(self, path):
        self.saved_to = path
        # Minimal torch-free marker file for existence checks.
        with open(path, "wb") as f:
            f.write(b"PROMPT")


class _FakeModel:
    def __init__(self):
        self.kwargs = None
        self.generate_calls = 0
        self.prompt_calls = 0
        self.prompt = _FakePrompt()
        self.batch_sizes: list[int] = []

    def generate(self, **kwargs):
        self.generate_calls += 1
        self.kwargs = kwargs
        text = kwargs.get("text")
        n = len(text) if isinstance(text, list) else 1
        self.batch_sizes.append(n)
        return [np.zeros(16, dtype=np.float32) for _ in range(n)]

    def create_voice_clone_prompt(self, ref_audio=None, ref_text=None, **kwargs):
        self.prompt_calls += 1
        self.prompt = _FakePrompt(ref_text=ref_text or "ref")
        return self.prompt


class NormalizeTextTest(unittest.TestCase):
    def test_normalize_flag_is_part_of_cache_key(self):
        off = TTSEngine.cache_key("I have 12 apples.", None, None, 1.0, normalize_text=False)
        on = TTSEngine.cache_key("I have 12 apples.", None, None, 1.0, normalize_text=True)
        self.assertNotEqual(off, on)

    def test_num2words_fallback_expands_integers(self):
        try:
            import num2words  # noqa: F401
        except ImportError:
            self.skipTest("num2words not installed")

        out = _num2words_fallback("Van 12 alma.", "hu")
        self.assertNotIn("12", out)
        self.assertTrue(len(out) > len("Van  alma."))

    def test_num2words_preserves_control_tags(self):
        try:
            import num2words  # noqa: F401
        except ImportError:
            self.skipTest("num2words not installed")

        out = _num2words_fallback("[laughter] 3 times", "en")
        self.assertIn("[laughter]", out)
        self.assertNotIn("3", out.replace("[laughter]", ""))

    def test_apply_text_normalization_falls_back_without_wetext(self):
        try:
            import num2words  # noqa: F401
        except ImportError:
            self.skipTest("num2words not installed")

        with patch(
            "core.tts_engine._wetext_normalize", return_value=None
        ), patch.dict("sys.modules", {"omnivoice.utils.text": None}):
            # Simulate missing OmniVoice TN module → num2words path.
            import core.tts_engine as te

            with patch.object(
                te,
                "apply_text_normalization",
                side_effect=lambda text, language=None: te._num2words_fallback(
                    text, language
                ),
            ):
                out = te._num2words_fallback("I have 7 cats.", "en")
                self.assertNotIn("7", out)

    def test_wetext_path_used_when_available(self):
        with patch(
            "core.tts_engine._wetext_normalize",
            return_value="I have twelve apples.",
        ), patch(
            "omnivoice.utils.text.normalize_text",
            side_effect=ImportError("WeTextProcessing missing"),
        ):
            out = apply_text_normalization("I have 12 apples.", "en")
            self.assertEqual(out, "I have twelve apples.")

    def test_generate_uses_settings_normalize_flag_in_cache(self):
        engine = TTSEngine()
        engine.model = _FakeModel()
        engine._ready = True

        with tempfile.TemporaryDirectory() as tmp:
            engine_cache = os.path.join(tmp, "audio_cache")
            os.makedirs(engine_cache, exist_ok=True)
            with patch("core.tts_engine.AUDIO_CACHE_DIR", engine_cache), patch(
                "core.tts_engine.VOICE_REF_DIR", os.path.join(tmp, "refs")
            ), patch(
                "core.tts_engine.VOICE_PROMPT_DIR", os.path.join(tmp, "prompts")
            ), patch(
                "core.tts_engine._normalize_text_enabled", return_value=True
            ), patch(
                "core.tts_engine._tts_num_step_from_settings", return_value=16
            ), patch(
                "core.tts_engine.apply_text_normalization",
                side_effect=lambda t, language=None: t.replace("12", "twelve"),
            ):
                os.makedirs(os.path.join(tmp, "prompts"), exist_ok=True)
                os.makedirs(os.path.join(tmp, "refs"), exist_ok=True)
                result = engine.generate(text="I have 12 apples.", instruct=None)
                self.assertFalse(result["cache_hit"])
                self.assertEqual(engine.model.kwargs["text"], "I have twelve apples.")
                # Cache key must include normalize=True and num_step
                expected = TTSEngine.cache_key(
                    "I have 12 apples.", None, None, 1.0, normalize_text=True, num_step=16
                )
                self.assertEqual(result["cache_key"], expected)


class VoiceClonePromptCacheTest(unittest.TestCase):
    def test_prompt_cache_key_changes_with_ref_text(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF")
            path = f.name
        try:
            a = _prompt_cache_key(path, "one")
            b = _prompt_cache_key(path, "two")
            self.assertNotEqual(a, b)
        finally:
            os.unlink(path)

    def test_prompt_is_reused_across_generations(self):
        engine = TTSEngine()
        model = _FakeModel()
        engine.model = model
        engine._ready = True

        with tempfile.TemporaryDirectory() as tmp:
            ref_path = os.path.join(tmp, "speaker.wav")
            with open(ref_path, "wb") as f:
                f.write(b"RIFF" + b"\x00" * 64)

            prompts_dir = os.path.join(tmp, "prompts")
            audio_dir = os.path.join(tmp, "audio")
            os.makedirs(prompts_dir, exist_ok=True)
            os.makedirs(audio_dir, exist_ok=True)

            with patch("core.tts_engine.AUDIO_CACHE_DIR", audio_dir), patch(
                "core.tts_engine.VOICE_REF_DIR", os.path.join(tmp, "refs")
            ), patch(
                "core.tts_engine.VOICE_PROMPT_DIR", prompts_dir
            ), patch(
                "core.tts_engine._normalize_text_enabled", return_value=False
            ), patch(
                "core.tts_engine.apply_text_normalization", side_effect=lambda t, language=None: t
            ):
                os.makedirs(os.path.join(tmp, "refs"), exist_ok=True)

                r1 = engine.generate(
                    text="First line.",
                    ref_audio=ref_path,
                    ref_text="Hello speaker.",
                )
                r2 = engine.generate(
                    text="Second line.",
                    ref_audio=ref_path,
                    ref_text="Hello speaker.",
                )

                self.assertEqual(model.prompt_calls, 1)
                self.assertEqual(model.generate_calls, 2)
                self.assertIn("voice_clone_prompt", model.kwargs)
                self.assertNotIn("ref_audio", model.kwargs)
                self.assertTrue(os.path.exists(r1["audio_path"]))
                self.assertTrue(os.path.exists(r2["audio_path"]))
                self.assertNotEqual(r1["cache_key"], r2["cache_key"])

    def test_invalidate_clears_memory_prompt(self):
        engine = TTSEngine()
        model = _FakeModel()
        engine.model = model
        engine._ready = True

        with tempfile.TemporaryDirectory() as tmp:
            ref_path = os.path.join(tmp, "speaker.wav")
            with open(ref_path, "wb") as f:
                f.write(b"RIFF" + b"\x00" * 64)
            prompts_dir = os.path.join(tmp, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)

            with patch("core.tts_engine.AUDIO_CACHE_DIR", os.path.join(tmp, "audio")), patch(
                "core.tts_engine.VOICE_REF_DIR", os.path.join(tmp, "refs")
            ), patch(
                "core.tts_engine.VOICE_PROMPT_DIR", prompts_dir
            ), patch(
                "core.tts_engine._normalize_text_enabled", return_value=False
            ):
                os.makedirs(os.path.join(tmp, "audio"), exist_ok=True)
                os.makedirs(os.path.join(tmp, "refs"), exist_ok=True)
                engine.generate(text="A.", ref_audio=ref_path, ref_text="T.")
                self.assertEqual(model.prompt_calls, 1)
                engine.invalidate_voice_prompt(ref_path, "T.")
                engine.generate(text="B.", ref_audio=ref_path, ref_text="T.")
                self.assertEqual(model.prompt_calls, 2)


class NumStepCacheKeyTest(unittest.TestCase):
    def test_num_step_is_part_of_cache_key(self):
        a = TTSEngine.cache_key("Hello.", None, None, 1.0, num_step=16)
        b = TTSEngine.cache_key("Hello.", None, None, 1.0, num_step=32)
        self.assertNotEqual(a, b)


class PackBatchTest(unittest.TestCase):
    def test_pack_respects_item_and_char_caps(self):
        items = [{"text": "x" * 100} for _ in range(10)]
        packs = _pack_items_for_batch(items, max_items=4, max_chars=250)
        self.assertTrue(all(len(p) <= 4 for p in packs))
        self.assertTrue(all(sum(len(i["text"]) for i in p) <= 250 or len(p) == 1 for p in packs))
        self.assertEqual(sum(len(p) for p in packs), 10)

    def test_pack_fills_max_items(self):
        items = [{"text": f"line-{i}-" + ("x" * 40)} for i in range(10)]
        packs = _pack_items_for_batch(items, max_items=4, max_chars=50000)
        self.assertEqual([len(p) for p in packs], [4, 4, 2])


class AccelResolveTest(unittest.TestCase):
    def test_resolve_off(self):
        from core.tts_accel import resolve_accel_mode

        self.assertEqual(resolve_accel_mode("off"), "off")

    def test_probe_keys(self):
        from core.tts_accel import probe_accel

        p = probe_accel()
        self.assertIn("cuda", p)
        self.assertIn("triton", p)
        self.assertIn("recommended", p)


class CoalesceTest(unittest.TestCase):
    def test_coalesce_merges_same_voice(self):
        pending = [
            {
                "idx": i,
                "text": f"Mondat {i}.",
                "instruct": "male",
                "ref_audio": "a.wav",
                "ref_text": "r",
                "speed": 1.0,
                "language": "hu",
                "normalize_text": False,
                "cache_key": f"k{i}",
                "cache_path": f"p{i}.wav",
            }
            for i in range(5)
        ]
        units = _coalesce_pending_items(pending, max_chars=80)
        self.assertLess(len(units), 5)
        self.assertEqual(sum(len(u["members"]) for u in units), 5)

    def test_split_audio_weights(self):
        audio = np.arange(100, dtype=np.float32)
        parts = _split_audio_by_char_weights(audio, ["aa", "aaaa", "aaaaaa"])
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(len(p) for p in parts), 100)


class GenerateManyBatchTest(unittest.TestCase):
    def test_same_voice_items_are_batched(self):
        engine = TTSEngine()
        model = _FakeModel()
        engine.model = model
        engine._ready = True

        with tempfile.TemporaryDirectory() as tmp:
            ref_path = os.path.join(tmp, "speaker.wav")
            with open(ref_path, "wb") as f:
                f.write(b"RIFF" + b"\x00" * 64)
            audio_dir = os.path.join(tmp, "audio")
            prompts_dir = os.path.join(tmp, "prompts")
            os.makedirs(audio_dir, exist_ok=True)
            os.makedirs(prompts_dir, exist_ok=True)
            os.makedirs(os.path.join(tmp, "refs"), exist_ok=True)

            items = [
                {
                    "text": f"Line {i}.",
                    "instruct": "male, elderly, low pitch",
                    "ref_audio": ref_path,
                    "ref_text": "Hello speaker.",
                    "speed": 1.0,
                    "language": "hu",
                    "normalize_text": False,
                }
                for i in range(5)
            ]

            with patch("core.tts_engine.AUDIO_CACHE_DIR", audio_dir), patch(
                "core.tts_engine.VOICE_REF_DIR", os.path.join(tmp, "refs")
            ), patch(
                "core.tts_engine.VOICE_PROMPT_DIR", prompts_dir
            ), patch(
                "core.tts_engine._normalize_text_enabled", return_value=False
            ):
                results = engine.generate_many(items, num_step=16, batch_size=4)

            self.assertEqual(len(results), 5)
            self.assertTrue(all(r["cache_hit"] is False for r in results))
            # 4 + 1 leftovers; prompt encoded once.
            self.assertEqual(model.generate_calls, 2)
            self.assertEqual(model.batch_sizes, [4, 1])
            self.assertEqual(model.prompt_calls, 1)
            self.assertEqual(model.kwargs["num_step"], 16)
            self.assertIn(4, model.batch_sizes)

    def test_generate_many_reuses_disk_cache(self):
        engine = TTSEngine()
        model = _FakeModel()
        engine.model = model
        engine._ready = True

        with tempfile.TemporaryDirectory() as tmp:
            audio_dir = os.path.join(tmp, "audio")
            prompts_dir = os.path.join(tmp, "prompts")
            os.makedirs(audio_dir, exist_ok=True)
            os.makedirs(prompts_dir, exist_ok=True)
            os.makedirs(os.path.join(tmp, "refs"), exist_ok=True)

            items = [
                {
                    "text": "Cached line.",
                    "instruct": None,
                    "ref_audio": None,
                    "ref_text": None,
                    "speed": 1.0,
                    "language": "en",
                    "normalize_text": False,
                }
            ]

            with patch("core.tts_engine.AUDIO_CACHE_DIR", audio_dir), patch(
                "core.tts_engine.VOICE_REF_DIR", os.path.join(tmp, "refs")
            ), patch(
                "core.tts_engine.VOICE_PROMPT_DIR", prompts_dir
            ), patch(
                "core.tts_engine._normalize_text_enabled", return_value=False
            ):
                first = engine.generate_many(items, num_step=16, batch_size=4)
                second = engine.generate_many(items, num_step=16, batch_size=4)

            self.assertEqual(model.generate_calls, 1)
            self.assertFalse(first[0]["cache_hit"])
            self.assertTrue(second[0]["cache_hit"])
            self.assertEqual(first[0]["cache_key"], second[0]["cache_key"])

    def test_generate_many_on_item_callback(self):
        engine = TTSEngine()
        model = _FakeModel()
        engine.model = model
        engine._ready = True
        seen = []

        with tempfile.TemporaryDirectory() as tmp:
            audio_dir = os.path.join(tmp, "audio")
            os.makedirs(audio_dir, exist_ok=True)
            os.makedirs(os.path.join(tmp, "prompts"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "refs"), exist_ok=True)

            items = [
                {
                    "text": f"Line {i}.",
                    "instruct": None,
                    "ref_audio": None,
                    "ref_text": None,
                    "speed": 1.0,
                    "language": "en",
                    "normalize_text": False,
                }
                for i in range(3)
            ]

            with patch("core.tts_engine.AUDIO_CACHE_DIR", audio_dir), patch(
                "core.tts_engine.VOICE_REF_DIR", os.path.join(tmp, "refs")
            ), patch(
                "core.tts_engine.VOICE_PROMPT_DIR", os.path.join(tmp, "prompts")
            ), patch(
                "core.tts_engine._normalize_text_enabled", return_value=False
            ):
                engine.generate_many(
                    items,
                    num_step=16,
                    batch_size=2,
                    on_item=lambda idx, result: seen.append(idx),
                )

        self.assertEqual(sorted(seen), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
