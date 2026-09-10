import threading
import time
import unittest

from core.tts_batcher import InteractiveTTSBatcher


class InteractiveTTSBatcherTest(unittest.TestCase):
    def test_multiple_priority_requests_finish_before_slow_lookahead_batch(self):
        lookahead_started = threading.Event()
        release_lookahead = threading.Event()

        def generate_many(items, on_item=None):
            if len(items) > 1:
                lookahead_started.set()
                release_lookahead.wait(timeout=2)
            results = [
                {"cache_key": f"k{item['index']}", "audio_path": "test.wav"}
                for item in items
            ]
            for index, result in enumerate(results):
                on_item(index, result)
            return results

        batcher = InteractiveTTSBatcher(generate_many, collect_ms=40)
        results = [None] * 4

        def submit(index, priority):
            results[index] = batcher.submit(
                ("segment", index),
                {"index": index, "text": f"Sentence {index}."},
                priority=priority,
            )

        threads = [
            threading.Thread(target=submit, args=(0, True)),
            threading.Thread(target=submit, args=(1, True)),
            threading.Thread(target=submit, args=(2, False)),
            threading.Thread(target=submit, args=(3, False)),
        ]
        for thread in threads:
            thread.start()

        try:
            self.assertTrue(lookahead_started.wait(timeout=1))
            for thread in threads[:2]:
                thread.join(timeout=0.2)
            self.assertTrue(all(not thread.is_alive() for thread in threads[:2]))
            self.assertEqual([result["cache_key"] for result in results[:2]], ["k0", "k1"])
            self.assertTrue(threads[2].is_alive())
            self.assertTrue(threads[3].is_alive())
        finally:
            release_lookahead.set()
            for thread in threads:
                thread.join(timeout=2)

    def test_first_request_finishes_before_slow_lookahead_batch(self):
        lookahead_started = threading.Event()
        release_lookahead = threading.Event()

        def generate_many(items, on_item=None):
            if len(items) > 1:
                lookahead_started.set()
                release_lookahead.wait(timeout=2)
            results = [
                {"cache_key": f"k{item['index']}", "audio_path": "test.wav"}
                for item in items
            ]
            for index, result in enumerate(results):
                on_item(index, result)
            return results

        batcher = InteractiveTTSBatcher(generate_many, collect_ms=40)
        results = [None] * 3

        def submit(index):
            results[index] = batcher.submit(
                ("segment", index),
                {"index": index, "text": f"Sentence {index}."},
            )

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(3)]
        for thread in threads:
            thread.start()

        try:
            self.assertTrue(lookahead_started.wait(timeout=1))
            threads[0].join(timeout=0.2)
            self.assertFalse(
                threads[0].is_alive(),
                "the playback-critical first request waited for lookahead synthesis",
            )
            self.assertEqual(results[0]["cache_key"], "k0")
            self.assertTrue(threads[1].is_alive())
            self.assertTrue(threads[2].is_alive())
        finally:
            release_lookahead.set()
            for thread in threads:
                thread.join(timeout=2)

    def test_concurrent_requests_prioritize_first_and_batch_remaining_calls(self):
        model_calls = []

        def generate_many(items, on_item=None):
            model_calls.append(list(items))
            results = [
                {"cache_key": f"k{item['index']}", "audio_path": "test.wav"}
                for item in items
            ]
            for index, result in enumerate(results):
                on_item(index, result)
            return results

        batcher = InteractiveTTSBatcher(generate_many, collect_ms=40)
        results = [None] * 5

        def submit(index):
            results[index] = batcher.submit(
                ("segment", index),
                {"index": index, "text": f"Sentence {index}."},
            )

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(
            [[item["index"] for item in call] for call in model_calls],
            [[0], [1, 2, 3, 4]],
        )
        self.assertEqual([result["cache_key"] for result in results], [f"k{i}" for i in range(5)])

    def test_duplicate_inflight_key_is_synthesized_once(self):
        model_calls = []

        def generate_many(items, on_item=None):
            model_calls.append(list(items))
            time.sleep(0.03)
            result = {"cache_key": "shared", "audio_path": "test.wav"}
            on_item(0, result)
            return [result]

        batcher = InteractiveTTSBatcher(generate_many, collect_ms=30)
        results = []

        def submit():
            results.append(
                batcher.submit("same-segment", {"index": 1, "text": "Same."})
            )

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(len(model_calls), 1)
        self.assertEqual(len(model_calls[0]), 1)
        self.assertEqual([result["cache_key"] for result in results], ["shared", "shared"])


if __name__ == "__main__":
    unittest.main()
