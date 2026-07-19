import unittest
from collections import Counter
from unittest.mock import patch

from core import llm_characters
from core.enrichment import build_speaker_units, enrich_chapter


class SpeakerUnitTest(unittest.TestCase):
    def test_hungarian_dash_dialogue_is_isolated_from_narration(self):
        units = build_speaker_units(
            "A tanár feltette a szemüvegét. - Ki maga? "
            "- Gorcsev Iván vagyok. A tanár bólintott."
        )

        self.assertEqual(
            [unit["text"] for unit in units],
            [
                "A tanár feltette a szemüvegét.",
                "- Ki maga?",
                "- Gorcsev Iván vagyok.",
                "A tanár bólintott.",
            ],
        )
        self.assertEqual(
            [unit["dialogue_candidate"] for unit in units],
            [False, True, True, False],
        )

    def test_low_high_hungarian_quotes_are_dialogue_candidates(self):
        units = build_speaker_units(
            "A professzor kérdezett. „Hová készül?” Gorcsev felelt. "
            "„Nizzába.”"
        )

        quoted = [unit for unit in units if unit["dialogue_candidate"]]
        self.assertEqual(
            [unit["text"] for unit in quoted],
            ["„Hová készül?”", "„Nizzába.”"],
        )

    def test_lowercase_dash_attribution_is_context_not_dialogue(self):
        units = build_speaker_units(
            "- Bizony, tanárovics bátyuska - felelte sóhajtva Gorcsev. "
            "- Atyám kapitány volt."
        )

        attribution = next(
            unit for unit in units if "felelte sóhajtva" in unit["text"]
        )
        self.assertFalse(attribution["dialogue_candidate"])

    def test_stored_annotations_drive_tts_character_assignment(self):
        text = "A tanár nézett. - Ki maga? - Gorcsev Iván vagyok."
        units = build_speaker_units(text)
        annotations = {
            unit["index"]: (
                "Bertinus professzor"
                if "Ki maga" in unit["text"]
                else "Gorcsev Iván"
            )
            for unit in units
            if unit["dialogue_candidate"]
        }
        characters = {
            "Bertinus professzor": {"instruct": "male, elderly"},
            "Gorcsev Iván": {"instruct": "male, young adult"},
        }

        segments = enrich_chapter(
            text, characters, speaker_annotations=annotations
        )

        self.assertEqual(
            [segment["character_name"] for segment in segments],
            [None, "Bertinus professzor", "Gorcsev Iván"],
        )
        self.assertEqual(
            [segment["is_dialogue"] for segment in segments],
            [False, True, True],
        )

    def test_single_narrator_ignores_fine_grained_speaker_units(self):
        text = (
            "A hajó állt. A szél fújt. Az ég sötét volt. "
            "A kapitány csendben várt."
        )

        fine_grained = enrich_chapter(
            text,
            {},
            speaker_annotations={},
        )
        single_narrator = enrich_chapter(
            text,
            {},
            narrator_instruct="one narrator voice",
            single_narrator_mode=True,
            speaker_annotations={},
        )

        self.assertEqual(len(fine_grained), 4)
        self.assertLess(len(single_narrator), len(fine_grained))
        self.assertTrue(
            all(segment["character_name"] is None for segment in single_narrator)
        )
        self.assertTrue(
            all(
                segment["instruct"] == "one narrator voice"
                for segment in single_narrator
            )
        )


class LLMBookAnalysisTest(unittest.TestCase):
    def test_legacy_hungarian_glyphs_in_model_name_are_repaired(self):
        infos = {}
        canonical = llm_characters._merge_character(
            infos,
            name="Verdier õrmester",
            gender="male",
            source_text="Verdier őrmester mögött feltűnt egy rendőr.",
        )

        self.assertEqual(canonical, "Verdier őrmester")

    def test_unambiguous_short_name_merges_into_full_name(self):
        infos = {
            "gorcsev": llm_characters.CharacterInfo("Gorcsev", "male"),
            "gorcsev iván": llm_characters.CharacterInfo("Gorcsev Iván", "male"),
            "würfli": llm_characters.CharacterInfo("Würfli", "male"),
            "würfli egon": llm_characters.CharacterInfo("Würfli Egon", "male"),
            "würfli fedor": llm_characters.CharacterInfo("Würfli Fedor", "male"),
        }
        frequencies = Counter(
            {
                "Gorcsev": 4,
                "Gorcsev Iván": 7,
                "Würfli": 2,
                "Würfli Egon": 3,
                "Würfli Fedor": 3,
            }
        )
        annotations = [
            {"speaker_name": "Gorcsev"},
            {"speaker_name": "Würfli"},
        ]

        llm_characters._consolidate_canonical_names(
            infos, frequencies, annotations
        )

        self.assertNotIn("Gorcsev", frequencies)
        self.assertEqual(frequencies["Gorcsev Iván"], 11)
        self.assertEqual(annotations[0]["speaker_name"], "Gorcsev Iván")
        # Ambiguous family name must stay separate.
        self.assertEqual(frequencies["Würfli"], 2)
        self.assertEqual(annotations[1]["speaker_name"], "Würfli")

    @patch("core.llm_characters._chat")
    def test_compact_assignments_are_persistable_per_chapter(self, chat):
        chapters = [
            {
                "id": 10,
                "title": "Első",
                "content": "Bertinus nézett. - Ki maga? - Gorcsev Iván vagyok.",
            },
            {
                "id": 11,
                "title": "Második",
                "content": "Gorcsev kérdezett. - Hogy hívják? - Vanek.",
            },
        ]

        def response_for_prompt(**kwargs):
            prompt = kwargs["prompt"]
            lines = [
                line for line in prompt.splitlines()
                if line.startswith("[D ")
            ]
            ids = [
                int(line.split("]", 1)[0].split()[1])
                for line in lines
            ]
            return {
                "dialogues": [
                    f"{ids[0]}|Bertinus",
                    f"{ids[1]}|Gorcsev Iván",
                    f"{ids[2]}|Gorcsev Iván",
                    f"{ids[3]}|Vanek",
                ],
                "characters": [
                    {"name": "Bertinus", "gender": "male", "aliases": []},
                    {"name": "Gorcsev Iván", "gender": "male", "aliases": ["Gorcsev"]},
                    {"name": "Vanek", "gender": "male", "aliases": []},
                ],
            }

        chat.side_effect = response_for_prompt
        result = llm_characters.analyze_book(
            title="A tizennégy karátos autó",
            author="Rejtő Jenő",
            chapters=chapters,
            base_url="http://localhost:1234/v1",
            api_key="",
            model="test-model",
            batch_chars=100_000,
        )

        self.assertEqual(len(result["annotations"]), 4)
        self.assertEqual(
            [item["chapter_id"] for item in result["annotations"]],
            [10, 10, 11, 11],
        )
        self.assertEqual(
            {item["name"]: item["frequency"] for item in result["characters"]},
            {"Gorcsev Iván": 2, "Bertinus": 1, "Vanek": 1},
        )
        chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
