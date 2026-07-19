import unittest

from core.enrichment import _inject_tags, enrich_chapter


class ExpressionTagTest(unittest.TestCase):
    def test_exclamation_does_not_inject_literal_oh_vocalization(self):
        enriched, tag = _inject_tags("Az is van!", "Az is van!", False)

        self.assertEqual(enriched, "Az is van!")
        self.assertIsNone(tag)

    def test_shocked_question_does_not_inject_literal_oh_vocalization(self):
        enriched, tag = _inject_tags('"What?!"', '"What?!"', True)

        self.assertEqual(enriched, '"What?!"')
        self.assertIsNone(tag)

    def test_exact_reported_passage_reaches_tts_without_surprise_tag(self):
        segments = enrich_chapter(
            "De mi a másik lehetőség? Az is van! Ezek nem tudják,",
            character_map={},
        )

        by_text = {segment["text"]: segment["enriched_text"] for segment in segments}
        self.assertEqual(by_text["Az is van!"], "Az is van!")
        self.assertNotIn("[surprise-oh]", " ".join(by_text.values()))

    def test_explicit_laughter_remains_available(self):
        enriched, tag = _inject_tags(
            '"That was funny," he laughed.',
            '"That was funny," he laughed.',
            True,
        )

        self.assertEqual(tag, "[laughter]")
        self.assertIn("[laughter]", enriched)


if __name__ == "__main__":
    unittest.main()
