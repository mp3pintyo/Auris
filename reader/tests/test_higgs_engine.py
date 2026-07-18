import unittest
from unittest.mock import patch

import numpy as np

from core.higgs_engine import (
    HiggsTTSEngine,
    _language_cleanup,
    _parse_worker_response_line,
    _prepare_reference,
    _translate_inline_tags,
)
from core.tts_router import TTSEngineRouter


class HiggsPromptTests(unittest.TestCase):
    def test_worker_reply_parser_tolerates_progress_tail_and_prefix(self):
        line = (
            "\rLoading weights 100% "
            'AURIS_HIGGS_JSON:{"ok":true,"event":"ready"}'
            "\rprogress renderer tail"
        )
        self.assertEqual(
            _parse_worker_response_line(line),
            {"ok": True, "event": "ready"},
        )

    def test_existing_omnivoice_nonverbal_tags_are_translated(self):
        text = _translate_inline_tags("Wait. [laughter] Really? [question-oh]")
        self.assertIn("<|sfx:laughter|>Haha", text)
        self.assertIn("<|emotion:surprise|>", text)
        self.assertNotIn("[laughter]", text)

    def test_short_reference_is_mono_and_expanded_to_at_least_four_seconds(self):
        stereo = np.zeros((24_000, 2), dtype=np.float32)
        result = _prepare_reference(stereo, 24_000)
        self.assertEqual(result.ndim, 1)
        self.assertGreaterEqual(len(result), 4 * 24_000)

    def test_prompt_uses_higgs_delivery_controls(self):
        engine = HiggsTTSEngine()

        def setting(key, default):
            return {
                "higgs_prompt_mode": "expressive",
                "higgs_default_emotion": "contentment",
                "higgs_default_style": "none",
                "higgs_default_expressive": "expressive_high",
            }.get(key, default)

        with patch("core.higgs_engine._setting", side_effect=setting):
            prompt = engine._prompt(
                "Hello [sigh]", "female, low pitch, whisper", 1.2, "en", False
            )
        self.assertTrue(prompt.startswith("<|emotion:contentment|>"))
        self.assertIn("<|prosody:expressive_high|>", prompt)
        self.assertIn("<|style:whispering|>", prompt)
        self.assertIn("<|prosody:pitch_low|>", prompt)
        self.assertIn("<|prosody:speed_fast|>", prompt)
        self.assertIn("<|sfx:sigh|>Uh", prompt)

    def test_raw_prompt_matches_friend_app_plain_text_path(self):
        engine = HiggsTTSEngine()
        with patch(
            "core.higgs_engine._setting",
            side_effect=lambda key, default: (
                "raw" if key == "higgs_prompt_mode" else default
            ),
        ):
            prompt = engine._prompt(
                "[surprise-oh] Szia, ez egy rövid magyar teszt.",
                "male, elderly, low pitch, british accent",
                0.85,
                "hu",
                True,
            )
        self.assertEqual(prompt, "Szia, ez egy rövid magyar teszt.")

    def test_hungarian_legacy_pdf_accents_are_repaired(self):
        self.assertEqual(
            _language_cleanup("A bûnözõ õrzi a fõbejáratot.", "hu"),
            "A bűnöző őrzi a főbejáratot.",
        )
        self.assertEqual(_language_cleanup("São João", "pt"), "São João")

    def test_cache_key_changes_with_higgs_sampling(self):
        with patch(
            "core.higgs_engine.HiggsTTSEngine._generation_settings",
            return_value={"temperature": 0.8},
        ):
            first = HiggsTTSEngine.cache_key("Hello", None, None, 1.0)
        with patch(
            "core.higgs_engine.HiggsTTSEngine._generation_settings",
            return_value={"temperature": 1.1},
        ):
            second = HiggsTTSEngine.cache_key("Hello", None, None, 1.0)
        self.assertNotEqual(first, second)


class RouterTests(unittest.TestCase):
    def test_router_selects_higgs_without_importing_it_into_omnivoice_engine(self):
        with patch("core.tts_router.selected_engine_name", return_value="higgs"):
            router = TTSEngineRouter()
        self.assertEqual(router.engine_name, "higgs")
        self.assertIsInstance(router._engine, HiggsTTSEngine)


class HiggsLifecycleTests(unittest.TestCase):
    def test_unload_handles_worker_cleared_during_failed_rpc(self):
        class FakeWorker:
            def __init__(self):
                self.terminated = False

            def poll(self):
                return None if not self.terminated else 1

            def terminate(self):
                self.terminated = True

        engine = HiggsTTSEngine()
        worker = FakeWorker()
        engine._worker = worker

        def failed_rpc(_payload):
            engine._worker = None
            raise RuntimeError("worker exited")

        with patch.object(engine, "_rpc_raw", side_effect=failed_rpc):
            engine.unload()

        self.assertTrue(worker.terminated)
        self.assertIsNone(engine._worker)


if __name__ == "__main__":
    unittest.main()
