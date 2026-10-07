import unittest

import numpy as np

from core import reference_candidates as rc

SR = 1000
TEXT = ("Az első mondat itt van. A második mondat kicsit hosszabb ennél. "
        "Dr. Kovács a harmadikat mondja. Végül jön a negyedik.")


def timed_words():
    """Each sentence lasts 4 s with a 1 s pause; word times spread evenly."""
    words, t = [], 0.5
    for sentence in rc.split_sentences(TEXT):
        tokens = sentence.split()
        step = 4.0 / len(tokens)
        for k, token in enumerate(tokens):
            words.append({"word": token, "start": t + k * step, "end": t + (k + 1) * step})
        t += 5.0
    return words


def speech_with_pauses(seconds=20.0, trailing_quiet=True):
    """Speech 0.5-19.5 s with 1 s pauses; quiet edges unless cut off."""
    audio = 0.2 * np.ones(int(seconds * SR), dtype=np.float32)
    audio[:int(0.5 * SR)] = 0.0
    for k in range(4):
        audio[int((4.5 + 5 * k) * SR):int((5.5 + 5 * k) * SR)] = 0.0
    if not trailing_quiet:
        audio = audio[:int(19.5 * SR)]
    return audio


class ReferenceCandidatesTest(unittest.TestCase):
    def test_hungarian_abbreviation_does_not_split(self):
        self.assertEqual(len(rc.split_sentences(TEXT)), 4)

    def test_sentence_times_follow_matched_words(self):
        times = rc.sentence_times(rc.split_sentences(TEXT), timed_words())
        self.assertAlmostEqual(times[0][0], 0.5)
        self.assertAlmostEqual(times[3][1], 19.5)

    def test_missing_recognition_marks_sentence_untimed(self):
        words = [w for w in timed_words() if w["start"] < 10]
        times = rc.sentence_times(rc.split_sentences(TEXT), words)
        self.assertIsNotNone(times[1])
        self.assertIsNone(times[3])

    def test_candidates_cut_in_pauses_within_length_range(self):
        found = rc.candidates(speech_with_pauses(), SR, TEXT, timed_words(),
                              min_seconds=8, max_seconds=12, target_seconds=10)
        self.assertTrue(found)
        for cand in found:
            self.assertGreaterEqual(cand.duration, 8)
            self.assertLessEqual(cand.duration, 12)
            self.assertEqual(cand.last_sentence - cand.first_sentence, 1)
            for edge in (cand.start, cand.end):
                if 0.5 < edge < 19.5:
                    # Inside a pause, never inside a word.
                    self.assertTrue(any(4.5 <= edge - 5 * k <= 5.5 for k in range(4)), edge)
        self.assertIn("Dr. Kovács", " ".join(c.text for c in found))

    def test_touching_word_times_still_cut_in_the_pause(self):
        words = timed_words()
        for word, nxt in zip(words, words[1:]):
            word["end"] = nxt["start"]  # recognizer leaves no gap between words
        found = rc.candidates(speech_with_pauses(), SR, TEXT, words,
                              min_seconds=3, max_seconds=6, target_seconds=5)
        singles = sorted((c for c in found if c.first_sentence == c.last_sentence),
                         key=lambda c: c.first_sentence)
        self.assertEqual(len(singles), 4)
        for left, right in zip(singles, singles[1:]):
            self.assertEqual(left.end, right.start)
            self.assertTrue(any(4.5 <= left.end - 5 * k <= 5.5 for k in range(4)), left.end)

    def test_recording_edges_follow_the_sound(self):
        found = rc.candidates(speech_with_pauses(), SR, TEXT, timed_words(),
                              min_seconds=3, max_seconds=6, target_seconds=5)
        first = min(found, key=lambda c: c.start)
        last = max(found, key=lambda c: c.end)
        self.assertTrue(0.3 <= first.start <= 0.5, first.start)
        self.assertTrue(19.5 <= last.end <= 19.7, last.end)

    def test_speech_cut_off_by_the_file_end_is_not_offered(self):
        found = rc.candidates(speech_with_pauses(trailing_quiet=False), SR, TEXT, timed_words(),
                              min_seconds=3, max_seconds=6, target_seconds=5)
        self.assertTrue(found)
        self.assertTrue(all(c.last_sentence < 3 for c in found))

    def test_cut_fades_edges(self):
        cand = rc.Candidate(1.0, 3.0, "x", 0, 0)
        piece = rc.cut(np.ones(5 * SR, dtype=np.float32), SR, cand)
        self.assertEqual(len(piece), 2 * SR)
        self.assertEqual(piece[0], 0.0)
        self.assertEqual(piece[len(piece) // 2], 1.0)


if __name__ == "__main__":
    unittest.main()
