import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import app as app_module
from core import database, jobs


class DurableJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_restart_marks_unfinished_jobs_interrupted_without_running_them(self):
        jobs.init_jobs()
        pending = jobs.create_job(
            "export_book",
            {"book_id": 7, "audio_fmt": "wav", "sub_fmt": "none"},
            book_id=7,
        )
        running = jobs.create_job(
            "generate_chapter",
            {"book_id": 7, "chapter_id": 11},
            book_id=7,
            chapter_id=11,
        )
        jobs.update_job(running["id"], state="running", done=2, total=5)

        jobs.init_jobs()

        self.assertEqual(jobs.get_job(pending["id"])["state"], "interrupted")
        restored = jobs.get_job(running["id"])
        self.assertEqual(restored["state"], "interrupted")
        self.assertEqual((restored["done"], restored["total"]), (2, 5))
        self.assertEqual(restored["input"]["chapter_id"], 11)

    def test_job_result_and_progress_round_trip_as_api_ready_values(self):
        jobs.init_jobs()
        created = jobs.create_job(
            "export_chapter",
            {"book_id": 3, "chapter_id": 4},
            book_id=3,
            chapter_id=4,
        )

        jobs.update_job(
            created["id"],
            state="complete",
            done=9,
            total=9,
            message="Done",
            result={"audio_download": "/api/jobs/result/example"},
        )

        restored = jobs.list_jobs()[0]
        self.assertEqual(restored["job_id"], created["id"])
        self.assertEqual(restored["percent"], 100)
        self.assertEqual(restored["result"]["audio_download"], "/api/jobs/result/example")
        self.assertFalse(restored["cancel_requested"])
        self.assertIsNotNone(restored["finished_at"])

    def test_running_job_cancels_cooperatively_and_can_be_resumed_explicitly(self):
        jobs.init_jobs()
        created = jobs.create_job("export_book", {"book_id": 5}, book_id=5)
        jobs.update_job(created["id"], state="running", done=3, total=8)

        cancelling = jobs.cancel_job(created["id"])
        self.assertEqual(cancelling["state"], "running")
        self.assertTrue(jobs.is_cancel_requested(created["id"]))
        jobs.mark_cancelled(created["id"], "Cancelled after current batch")
        cancelled = jobs.get_job(created["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["done"], 3)

        resumed = jobs.resume_job(created["id"])
        self.assertEqual(resumed["state"], "pending")
        self.assertFalse(resumed["cancel_requested"])
        self.assertEqual(resumed["attempt"], 2)
        self.assertEqual(resumed["done"], 3)

    def test_only_one_concurrent_resume_can_claim_a_terminal_job(self):
        jobs.init_jobs()
        created = jobs.create_job("export_book", {"book_id": 5}, book_id=5)
        jobs.update_job(created["id"], state="interrupted")
        barrier = threading.Barrier(2)

        def resume():
            barrier.wait()
            try:
                return jobs.resume_job(created["id"])
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: resume(), range(2)))

        claimed = [result for result in results if result is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["attempt"], 2)
        self.assertEqual(jobs.get_job(created["id"])["attempt"], 2)

    def test_pending_job_is_cancelled_without_starting_work(self):
        jobs.init_jobs()
        created = jobs.create_job("reanalyze", {"book_id": 2}, book_id=2)

        cancelled = jobs.cancel_job(created["id"])

        self.assertEqual(cancelled["state"], "cancelled")
        self.assertTrue(cancelled["cancel_requested"])

    def test_cancel_does_not_overwrite_a_job_that_completed_after_a_stale_read(self):
        jobs.init_jobs()
        created = jobs.create_job("export_book", {"book_id": 2}, book_id=2)
        stale_pending = jobs.get_job(created["id"])
        original_get_job = jobs.get_job
        stale_returned = False

        def stale_once(job_id):
            nonlocal stale_returned
            if not stale_returned:
                stale_returned = True
                jobs.update_job(
                    job_id, state="complete", done=1, total=1,
                    result={"download_path": "finished.wav"},
                )
                return stale_pending
            return original_get_job(job_id)

        with patch.object(jobs, "get_job", side_effect=stale_once):
            cancelled = jobs.cancel_job(created["id"])

        final = original_get_job(created["id"])
        self.assertEqual(cancelled["state"], "complete")
        self.assertEqual(final["state"], "complete")
        self.assertEqual(final["result"]["download_path"], "finished.wav")

    def test_chapter_reanalysis_state_tracks_success_and_failure_separately(self):
        jobs.init_jobs()
        jobs.set_chapter_analysis_state(9, 21, "complete", None)
        jobs.set_chapter_analysis_state(9, 22, "failed", "model timeout")

        states = jobs.list_chapter_analysis_states(9)

        self.assertEqual(states[21]["state"], "complete")
        self.assertEqual(states[22]["state"], "failed")
        self.assertEqual(states[22]["error"], "model timeout")
        self.assertEqual(jobs.failed_chapter_ids(9), [22])


if __name__ == "__main__":
    unittest.main()


class DurableJobsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_startup = app_module._startup_complete
        database.DB_PATH = os.path.join(self.tmp.name, "reader.db")
        database.init_db()
        jobs.init_jobs()
        app_module._startup_complete = True
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO books (id, title, author, file_path, file_type, language) "
                "VALUES (1, 'Book', 'Writer', 'book.txt', 'txt', 'hu')"
            )
            conn.execute(
                "INSERT INTO chapters (id, book_id, title, order_num, content, word_count) "
                "VALUES (10, 1, 'One', 0, 'First line. Second line.', 4)"
            )
            conn.execute(
                "INSERT INTO chapters (id, book_id, title, order_num, content, word_count) "
                "VALUES (11, 1, 'Two', 1, 'Third line.', 2)"
            )

    def tearDown(self):
        app_module._interactive_request_count = 0
        database.DB_PATH = self.original_db_path
        app_module._startup_complete = self.original_startup
        self.tmp.cleanup()

    def test_jobs_api_lists_and_cancels_persisted_job(self):
        created = jobs.create_job("export_book", {"book_id": 1}, book_id=1)

        listed = self.client.get("/api/jobs")
        cancelled = self.client.post(f"/api/jobs/{created['id']}/cancel")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()[0]["id"], created["id"])
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["state"], "cancelled")
        self.assertEqual(listed.get_json()[0]["book_title"], "Book")

    def test_resume_is_explicit_and_dispatches_saved_input(self):
        created = jobs.create_job(
            "generate_chapter",
            {"book_id": 1, "chapter_id": 10},
            book_id=1,
            chapter_id=10,
        )
        jobs.update_job(created["id"], state="interrupted")

        with patch.object(app_module, "_launch_durable_job", return_value=True):
            response = self.client.post(f"/api/jobs/{created['id']}/resume")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"], "pending")
        self.assertEqual(response.get_json()["input"]["chapter_id"], 10)

    def test_concurrent_resume_dispatches_interrupted_job_exactly_once(self):
        created = jobs.create_job(
            "generate_chapter",
            {"book_id": 1, "chapter_id": 10},
            book_id=1,
            chapter_id=10,
        )
        jobs.update_job(created["id"], state="interrupted")
        request_barrier = threading.Barrier(2)
        active_barrier = threading.Barrier(2)
        active_call_lock = threading.Lock()
        active_calls = 0
        max_active_calls = 0
        launches = []
        original_active = app_module._active_durable_jobs

        def synchronized_active_jobs(*args, **kwargs):
            nonlocal active_calls, max_active_calls
            with active_call_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                try:
                    active_barrier.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
                return original_active(*args, **kwargs)
            finally:
                with active_call_lock:
                    active_calls -= 1

        def post_resume():
            with app_module.app.test_client() as client:
                request_barrier.wait()
                return client.post(f"/api/jobs/{created['id']}/resume").status_code

        with (
            patch.object(app_module, "_active_durable_jobs", side_effect=synchronized_active_jobs),
            patch.object(app_module, "_launch_durable_job", side_effect=lambda stored: launches.append(stored) or True),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            statuses = list(pool.map(lambda _index: post_resume(), range(2)))

        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0]["attempt"], 2)
        self.assertEqual(jobs.get_job(created["id"])["attempt"], 2)
        self.assertEqual(max_active_calls, 1)

    def test_reanalyze_validates_chapters_and_creates_durable_job(self):
        configured = {
            "provider": "local", "base_url": "http://localhost:1234/v1",
            "api_key": "", "model": "test-model",
        }
        with (
            patch.object(app_module, "_launch_durable_job", return_value=True),
            patch.object(app_module, "_selected_llm_config", return_value=configured),
        ):
            response = self.client.post(
                "/api/books/1/reanalyze", json={"chapter_ids": [11]}
            )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["type"], "reanalyze")
        self.assertEqual(payload["input"]["chapter_ids"], [11])
        self.assertEqual(payload["book_id"], 1)

        with patch.object(app_module, "_selected_llm_config", return_value=configured):
            invalid = self.client.post(
                "/api/books/1/reanalyze", json={"chapter_ids": [999]}
            )
        self.assertEqual(invalid.status_code, 400)

    def test_interactive_preview_blocks_bulk_work_but_allows_voice_switches(self):
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO characters "
                "(id, book_id, name, gender, frequency, instruct, color_hex) "
                "VALUES (20, 1, 'Anna', 'female', 1, 'voice', '#123456')"
            )
        profile = self.client.post(
            "/api/voice-profiles",
            json={"name": "Anna másik hangja", "book_id": 1, "char_id": 20},
        ).get_json()
        started = threading.Event()
        release = threading.Event()

        class BlockingPreviewTTS:
            def status(self):
                return {"state": "ready"}

            def generate_preview(self, **_kwargs):
                started.set()
                self.assert_released = release.wait(timeout=3)
                return {"cache_key": "preview-cache"}

        fake_tts = BlockingPreviewTTS()

        def request_preview():
            with app_module.app.test_client() as client:
                return client.post(
                    "/api/books/1/characters/20/preview",
                    json={"text": "Próba."},
                ).status_code

        configured = {
            "provider": "local", "base_url": "http://localhost:1234/v1",
            "api_key": "", "model": "test-model",
        }
        with (
            patch.object(app_module, "tts", fake_tts),
            patch.object(app_module, "_selected_llm_config", return_value=configured),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(request_preview)
            self.assertTrue(started.wait(timeout=2))
            self.assertEqual(app_module._interactive_request_count, 1)
            self.assertTrue(app_module._work_dispatch_lock.acquire(blocking=False))
            app_module._work_dispatch_lock.release()

            reanalyze = self.client.post(
                "/api/books/1/reanalyze", json={"chapter_ids": [10]}
            )
            mutate = self.client.put(
                "/api/books/1/characters/20", json={"instruct": "new voice"}
            )
            switch_profile = self.client.post(
                f"/api/voice-profiles/{profile['id']}/apply",
                json={"book_id": 1, "char_id": 20},
            )
            self.assertEqual(reanalyze.status_code, 409)
            self.assertEqual(mutate.status_code, 200)
            self.assertEqual(switch_profile.status_code, 200)
            release.set()
            self.assertEqual(future.result(timeout=3), 200)
        self.assertEqual(app_module._interactive_request_count, 0)

    def test_cached_interactive_audio_remains_available_during_background_job(self):
        audio_path = os.path.join(self.tmp.name, "cached.wav")
        with open(audio_path, "wb") as audio_file:
            audio_file.write(b"RIFF")
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO tts_segments "
                "(book_id, chapter_id, segment_index, text, enriched_text, cache_key, "
                "audio_path, duration_sec) VALUES (1, 10, 0, 'First line.', "
                "'First line.', 'cached-key', ?, 1.25)",
                (audio_path,),
            )
        jobs.create_job("reanalyze", {"book_id": 1}, book_id=1)

        with patch.object(app_module.tts, "status", return_value={"state": "ready"}):
            response = self.client.post(
                "/api/tts/generate",
                json={"book_id": 1, "chapter_id": 10, "segment_index": 0},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["cached"])

    def test_segment_read_holds_shared_gate_while_ensuring_rows(self):
        ownership = []

        def ensure(_book_id, _chapter_id):
            ownership.append(app_module._work_dispatch_lock._is_owned())
            return []

        with patch.object(app_module, "_ensure_chapter_segments", side_effect=ensure):
            response = self.client.get("/api/tts/segments/1/10")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ownership, [True])

    def test_book_delete_is_rejected_while_durable_work_is_active(self):
        jobs.create_job("export_book", {"book_id": 1}, book_id=1)

        response = self.client.delete("/api/books/1")

        self.assertEqual(response.status_code, 409)
        with database.get_conn() as conn:
            self.assertIsNotNone(
                conn.execute("SELECT id FROM books WHERE id=1").fetchone()
            )

    def test_reanalysis_store_preserves_manual_annotation_and_voice(self):
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO characters "
                "(book_id, name, gender, frequency, instruct, color_hex, ref_audio_path) "
                "VALUES (1, 'Anna', 'female', 1, 'custom voice', '#123456', 'anna.wav')"
            )
            conn.execute(
                "INSERT INTO speaker_annotations "
                "(book_id, chapter_id, unit_index, unit_text, speaker_name, confidence, source) "
                "VALUES (1, 10, 0, 'First line.', 'Anna', 1.0, 'manual')"
            )

        app_module._store_reanalysis_chapter(
            1,
            10,
            [{
                "name": "Anna", "gender": "female", "frequency": 2,
                "instruct": "generated voice", "color_hex": "#ffffff",
            }],
            [{
                "chapter_id": 10, "unit_index": 0, "unit_text": "First line.",
                "speaker_name": "Narrator", "confidence": 0.8,
            }, {
                "chapter_id": 10, "unit_index": 1, "unit_text": "Second line.",
                "speaker_name": "Anna", "confidence": 0.8,
            }],
        )

        with database.get_conn() as conn:
            anna = conn.execute(
                "SELECT instruct, color_hex, ref_audio_path FROM characters "
                "WHERE book_id=1 AND name='Anna'"
            ).fetchone()
            annotations = conn.execute(
                "SELECT unit_index, speaker_name, source FROM speaker_annotations "
                "WHERE chapter_id=10 ORDER BY unit_index"
            ).fetchall()
        self.assertEqual(dict(anna), {
            "instruct": "custom voice", "color_hex": "#123456",
            "ref_audio_path": "anna.wav",
        })
        self.assertEqual(
            [(row["unit_index"], row["speaker_name"], row["source"]) for row in annotations],
            [(0, "Anna", "manual"), (1, "Anna", "automatic")],
        )

    def test_cancellation_after_batch_result_keeps_cache_and_skips_fallback(self):
        class CancellingTTS:
            def __init__(self, audio_path):
                self.audio_path = audio_path
                self.fallback_calls = 0

            def generate_many(self, items, **kwargs):
                result = {
                    "audio_path": self.audio_path,
                    "duration_sec": 1.0,
                    "cache_key": "kept-cache",
                    "cache_hit": False,
                }
                kwargs["on_item"](0, result)
                return [result]

            def generate(self, **kwargs):
                self.fallback_calls += 1
                raise AssertionError("fallback must not run for cancellation")

        audio_path = os.path.join(self.tmp.name, "cached.wav")
        with open(audio_path, "wb") as audio_file:
            audio_file.write(b"RIFF")
        fake = CancellingTTS(audio_path)
        created = jobs.create_job(
            "generate_chapter", {"book_id": 1, "chapter_id": 10},
            book_id=1, chapter_id=10,
        )
        jobs.update_job(created["id"], state="running")
        with database.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO tts_segments "
                "(book_id, chapter_id, segment_index, text, enriched_text, instruct, cache_key) "
                "VALUES (1, 10, 0, 'First line.', 'First line.', 'voice', 'pending')"
            )
            segment_id = cur.lastrowid
        legacy_job = app_module._legacy_job(jobs.get_job(created["id"]))

        def request_cancel(index, result):
            app_module._persist_job(legacy_job)
            jobs.cancel_job(created["id"])

        with (
            patch.object(app_module, "tts", fake),
            patch.object(app_module, "_bump_export_progress", side_effect=lambda job, n=1, synthesized=False: request_cancel(0, None)),
        ):
            with self.assertRaises(app_module.JobCancelled):
                app_module._ensure_audio_for_chapter(
                    1, 10,
                    [{
                        "id": segment_id, "audio_path": None,
                        "character_name": None, "enriched_text": "First line.",
                        "instruct": "voice", "speed": 1.0,
                    }],
                    legacy_job,
                )

        with database.get_conn() as conn:
            stored = conn.execute(
                "SELECT audio_path, cache_key FROM tts_segments WHERE id=?",
                (segment_id,),
            ).fetchone()
        self.assertEqual(fake.fallback_calls, 0)
        self.assertEqual(stored["audio_path"], audio_path)
        self.assertEqual(stored["cache_key"], "kept-cache")

    def test_reanalysis_keeps_successful_chapter_when_another_chapter_fails(self):
        created = jobs.create_job(
            "reanalyze", {"book_id": 1, "chapter_ids": [10, 11]},
            book_id=1, total=2,
        )

        def analyze(**kwargs):
            chapter = kwargs["chapters"][0]
            if chapter["id"] == 11:
                return {
                    "characters": [], "annotations": [],
                    "errors": [{"chapters": ["Two"], "message": "timeout"}],
                }
            return {
                "characters": [{
                    "name": "Anna", "gender": "female", "frequency": 1,
                    "instruct": "voice", "color_hex": "#111111",
                }],
                "annotations": [{
                    "chapter_id": 10, "unit_index": 0,
                    "unit_text": "First line.", "speaker_name": "Anna",
                    "confidence": 1.0,
                }],
                "errors": [],
            }

        config = {"llm_timeout_sec": 30, "llm_max_output_tokens": 1000}
        selected = {
            "provider": "openai", "base_url": "https://example.test/v1",
            "api_key": "test", "model": "model",
        }
        with (
            patch.object(app_module.app_settings, "load", return_value=config),
            patch.object(app_module, "_selected_llm_config", return_value=selected),
            patch.object(app_module.llm_characters, "analyze_book", side_effect=analyze),
        ):
            app_module._run_reanalysis_job(created["id"], 1, [10, 11])

        final = jobs.get_job(created["id"])
        states = jobs.list_chapter_analysis_states(1)
        with database.get_conn() as conn:
            annotation = conn.execute(
                "SELECT speaker_name FROM speaker_annotations "
                "WHERE chapter_id=10 AND unit_index=0"
            ).fetchone()
        self.assertEqual(final["state"], "complete")
        self.assertEqual(final["result"]["failed_chapters"][0]["chapter_id"], 11)
        self.assertEqual(states[10]["state"], "complete")
        self.assertEqual(states[11]["state"], "failed")
        self.assertEqual(annotation["speaker_name"], "Anna")

    def test_reanalysis_remaps_bookmark_to_matching_text_after_segment_split(self):
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO tts_segments "
                "(book_id, chapter_id, segment_index, text, enriched_text, cache_key) "
                "VALUES (1, 10, 0, 'Alpha Beta', 'Alpha Beta', 'old')"
            )
            conn.execute(
                "INSERT INTO reading_progress (book_id, chapter_id, position) "
                "VALUES (1, 10, 0)"
            )
            conn.execute(
                "INSERT INTO bookmarks "
                "(book_id, chapter_id, segment_index, text_excerpt) "
                "VALUES (1, 10, 0, 'Beta')"
            )
        rebuilt = [
            {
                "text": text, "enriched_text": text, "character_name": None,
                "instruct": "voice", "speed": 1.0, "is_dialogue": False,
                "unit_index": index, "speaker_candidate": False,
                "ends_paragraph": index == 1,
            }
            for index, text in enumerate(("Alpha", "Beta"))
        ]

        with patch.object(app_module, "_compute_segments_for_chapter", return_value=rebuilt):
            app_module._store_reanalysis_chapter(1, 10, [], [])

        with database.get_conn() as conn:
            progress = conn.execute(
                "SELECT position FROM reading_progress WHERE book_id=1"
            ).fetchone()[0]
            bookmark = conn.execute(
                "SELECT segment_index FROM bookmarks WHERE book_id=1"
            ).fetchone()[0]
        self.assertEqual(progress, 0)
        self.assertEqual(bookmark, 1)
