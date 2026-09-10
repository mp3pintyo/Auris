import os
import tempfile
import unittest
from pathlib import Path

import app as app_module
from core import database


class SpeakerCorrectionsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_startup = app_module._startup_complete
        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        app_module._startup_complete = True
        database.init_db()
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books "
                "(id, title, file_path, file_type, character_analysis_status, "
                "character_analysis_provider) "
                "VALUES (1, 'Test', 'test.txt', 'txt', 'complete', 'llm')"
            )
            conn.execute(
                "INSERT INTO chapters "
                "(id, book_id, title, order_num, content, word_count) "
                "VALUES (2, 1, 'Chapter', 0, "
                "'The room was quiet. - Who are you? - I am Alice.', 10)"
            )
            conn.execute(
                "INSERT INTO characters "
                "(id, book_id, name, frequency, instruct) "
                "VALUES (3, 1, 'Alice', 1, 'female voice')"
            )
            conn.execute(
                "INSERT INTO speaker_annotations "
                "(book_id, chapter_id, unit_index, unit_text, speaker_name, "
                "confidence, source) "
                "VALUES (1, 2, 2, '- I am Alice.', 'Alice', 0.8, 'automatic')"
            )
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        app_module._startup_complete = self.original_startup
        self.tmp.cleanup()

    def test_assigns_existing_character_to_missed_dialogue(self):
        before = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertTrue(before[1]["speaker_candidate"])
        self.assertIsNone(before[1]["character_name"])
        self.assertEqual(before[2]["speaker_source"], "automatic")

        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={"unit_index": 1, "speaker_name": "alice"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["speaker_name"], "Alice")

        after = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertEqual(after[1]["character_name"], "Alice")
        self.assertEqual(after[1]["speaker_source"], "manual")
        with database.get_conn() as conn:
            character = conn.execute(
                "SELECT frequency FROM characters WHERE id=3"
            ).fetchone()
        self.assertEqual(character["frequency"], 2)

    def test_creates_new_character_and_can_remove_assignment(self):
        created = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={"unit_index": 1, "speaker_name": "Bob"},
        )
        self.assertEqual(created.status_code, 200)
        self.assertIsNotNone(created.get_json()["character_id"])

        characters = self.client.get("/api/books/1/characters").get_json()
        bob = next(character for character in characters if character["name"] == "Bob")
        self.assertEqual(bob["frequency"], 1)
        self.assertTrue(bob["instruct"])
        chapter_characters = self.client.get(
            "/api/books/1/characters?chapter_id=2"
        ).get_json()
        self.assertIn("Bob", {
            character["name"] for character in chapter_characters
        })

        removed = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={"unit_index": 1, "speaker_name": None},
        )
        self.assertEqual(removed.status_code, 200)
        segments = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertIsNone(segments[1]["character_name"])
        self.assertTrue(segments[1]["speaker_candidate"])
        self.assertEqual(segments[1]["speaker_source"], "manual")
        chapter_characters = self.client.get(
            "/api/books/1/characters?chapter_id=2"
        ).get_json()
        chapter_character_names = {
            character["name"] for character in chapter_characters
        }
        self.assertNotIn("Bob", chapter_character_names)
        self.assertIn("Alice", chapter_character_names)

    def test_manual_override_survives_automatic_reanalysis(self):
        self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={"unit_index": 1, "speaker_name": "Bob"},
        )

        app_module._store_character_analysis(
            1,
            chars=[
                {
                    "name": "Alice",
                    "gender": "female",
                    "frequency": 2,
                    "instruct": "new automatic voice",
                    "color_hex": "#000000",
                }
            ],
            annotations=[
                {
                    "chapter_id": 2,
                    "unit_index": 1,
                    "unit_text": "- Who are you?",
                    "speaker_name": "Alice",
                    "confidence": 0.9,
                }
            ],
            status="complete",
            message="reanalyzed",
        )

        segments = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertEqual(segments[1]["character_name"], "Bob")
        self.assertEqual(segments[1]["speaker_source"], "manual")

    def test_rejects_unknown_speaker_unit(self):
        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={"unit_index": 999, "speaker_name": "Alice"},
        )
        self.assertEqual(response.status_code, 404)

    def test_can_assign_an_entire_multi_sentence_dialogue_turn(self):
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE chapters SET content=? WHERE id=2",
                (
                    "- First sentence. Second sentence from the same speaker. "
                    "- Another speaker replies.",
                ),
            )
            conn.execute(
                "DELETE FROM speaker_annotations WHERE chapter_id=2"
            )

        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={
                "unit_index": 0,
                "speaker_name": "Alice",
                "apply_to_turn": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated_units"], 2)
        segments = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertEqual(
            [segment["character_name"] for segment in segments[:2]],
            ["Alice", "Alice"],
        )
        self.assertTrue(segments[1]["speaker_continuation"])

    def test_can_correct_from_sentence_to_end_of_dialogue_turn(self):
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE chapters SET content=? WHERE id=2",
                (
                    "- Spoken first. Narration starts here. "
                    "Narration continues here. - Another speaker replies.",
                ),
            )
            conn.execute(
                "DELETE FROM speaker_annotations WHERE chapter_id=2"
            )

        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={
                "unit_index": 1,
                "speaker_name": None,
                "scope": "turn_tail",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated_units"], 2)
        segments = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertNotEqual(segments[0]["speaker_source"], "manual")
        self.assertEqual(
            [segment["speaker_source"] for segment in segments[1:3]],
            ["manual", "manual"],
        )
        self.assertEqual(
            [segment["character_name"] for segment in segments[1:3]],
            [None, None],
        )

    def test_can_assign_explicit_range_including_missed_narration(self):
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE chapters SET content=? WHERE id=2",
                (
                    "Narration before. Missed spoken sentence. "
                    "A few more spoken words. Narration after.",
                ),
            )
            conn.execute(
                "DELETE FROM speaker_annotations WHERE chapter_id=2"
            )

        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={
                "unit_index": 1,
                "range_end_unit_index": 2,
                "speaker_name": "Alice",
                "scope": "range",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated_units"], 2)
        self.assertEqual(response.get_json()["range_end_unit_index"], 2)
        segments = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertEqual(
            [segment["character_name"] for segment in segments],
            [None, "Alice", "Alice", None],
        )
        self.assertEqual(
            [segment["speaker_source"] for segment in segments[1:3]],
            ["manual", "manual"],
        )

    def test_explicit_range_clears_old_contiguous_speaker_tail(self):
        content = (
            "First spoken sentence. Second spoken sentence. "
            "Old extra sentence. A different speaker follows."
        )
        units = app_module.enrichment.build_speaker_units(content)
        self.assertEqual(len(units), 4)
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE chapters SET content=? WHERE id=2",
                (content,),
            )
            conn.execute(
                "INSERT INTO characters "
                "(book_id, name, frequency, instruct) "
                "VALUES (1, 'Bob', 1, 'male voice')"
            )
            conn.execute(
                "DELETE FROM speaker_annotations WHERE chapter_id=2"
            )
            for unit_index, speaker_name in enumerate(
                ("Alice", "Alice", "Alice", "Bob")
            ):
                conn.execute(
                    "INSERT INTO speaker_annotations "
                    "(book_id, chapter_id, unit_index, unit_text, "
                    "speaker_name, confidence, source) "
                    "VALUES (1, 2, ?, ?, ?, 0.8, 'automatic')",
                    (unit_index, units[unit_index]["text"], speaker_name),
                )

        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={
                "unit_index": 0,
                "range_end_unit_index": 1,
                "speaker_name": "Alice",
                "scope": "range",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["range_end_unit_index"], 1)
        self.assertEqual(payload["assigned_units"], 2)
        self.assertEqual(payload["boundary_cleared_units"], 1)
        segments = self.client.get("/api/tts/segments/1/2").get_json()
        self.assertEqual(
            [segment["character_name"] for segment in segments],
            ["Alice", "Alice", None, "Bob"],
        )
        self.assertEqual(segments[2]["speaker_source"], "manual")
        self.assertEqual(segments[3]["speaker_source"], "automatic")

    def test_rejects_reversed_explicit_speaker_range(self):
        response = self.client.put(
            "/api/books/1/chapters/2/speaker-annotations",
            json={
                "unit_index": 1,
                "range_end_unit_index": 0,
                "speaker_name": "Alice",
                "scope": "range",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("range", response.get_json()["error"].lower())

    def test_reader_contains_speaker_editor(self):
        response = self.client.get("/reader/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="speaker-editor-overlay"', response.data)
        self.assertIn(b'id="speaker-range-end"', response.data)

        reader_script = (
            Path(__file__).resolve().parents[1] / "static" / "js" / "reader.js"
        ).read_text(encoding="utf-8")
        self.assertIn("range_end_unit_index", reader_script)
        self.assertIn("previewStoredSpeakerRange", reader_script)
        self.assertIn("getStoredSpeakerRangeEnd", reader_script)
        self.assertIn("continuesSameAssignedSpeaker", reader_script)
        self.assertIn(
            "previousSegment?.character_name === seg.character_name",
            reader_script,
        )
        self.assertIn("isManualNarration", reader_script)
        self.assertIn("startsNarrationRange", reader_script)
        self.assertIn(
            "showNarrationLabel = isManualNarration || startsNarrationRange",
            reader_script,
        )
        # The exact visible Narráció label is covered by the Playwright test;
        # keep this API test focused on the editor being wired into the page.
        self.assertNotIn("speaker-editor-turn-scope", reader_script)
        self.assertIn("Ki mondja ezt?".encode('utf-8'), response.data)


if __name__ == "__main__":
    unittest.main()
