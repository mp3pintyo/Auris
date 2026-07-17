import unittest

from core.exporter import (
    DEFAULT_SEGMENT_PAUSE_SEC,
    DIALOGUE_TURN_PAUSE_SEC,
    ELLIPSIS_PAUSE_SEC,
    build_timeline,
    pause_after_segment,
)


class ExporterPauseTests(unittest.TestCase):
    def test_default_segment_pause(self):
        self.assertEqual(
            pause_after_segment({"text": "A sentence.", "is_dialogue": False}),
            DEFAULT_SEGMENT_PAUSE_SEC,
        )

    def test_consecutive_dialogue_gets_turn_taking_pause(self):
        current = {"text": '"First."', "is_dialogue": True}
        following = {"text": '"Second."', "is_dialogue": True}
        self.assertEqual(
            pause_after_segment(current, following),
            DIALOGUE_TURN_PAUSE_SEC,
        )

    def test_three_dots_at_end_get_at_least_one_and_a_half_seconds(self):
        following = {"text": "Next.", "is_dialogue": False}
        for text in ("De hát bolond ez, hiába!...", "Várj…", '„Talán...”'):
            with self.subTest(text=text):
                self.assertGreaterEqual(
                    pause_after_segment({"text": text}, following),
                    ELLIPSIS_PAUSE_SEC,
                )

    def test_timeline_uses_boundary_specific_pauses(self):
        segments = [
            {"text": '"First."', "is_dialogue": True, "duration_sec": 1.0},
            {"text": '"Wait..."', "is_dialogue": True, "duration_sec": 2.0},
            {"text": "Narration.", "is_dialogue": False, "duration_sec": 3.0},
        ]

        timeline = build_timeline(segments)

        self.assertAlmostEqual(timeline[0]["t_start"], 0.0)
        self.assertAlmostEqual(timeline[1]["t_start"], 1.0 + DIALOGUE_TURN_PAUSE_SEC)
        self.assertAlmostEqual(
            timeline[2]["t_start"],
            1.0 + DIALOGUE_TURN_PAUSE_SEC + 2.0 + ELLIPSIS_PAUSE_SEC,
        )


if __name__ == "__main__":
    unittest.main()
