import threading
import time
import unittest

from core.tts_batcher import InteractiveTTSBatcher


class InteractiveTTSBatcherTest(unittest.TestCase):
    def test_concurrent_requests_use_one_generate_many_call(self):
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
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(len(model_calls[0]), 5)
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
