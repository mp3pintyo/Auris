import unittest

import numpy as np

from core.tts_engine import TTSEngine


class _FakeModel:
    def __init__(self):
        self.kwargs = None

    def generate(self, **kwargs):
        self.kwargs = kwargs
        return [np.zeros(16, dtype=np.float32)]


class TtsLanguageTest(unittest.TestCase):
    def test_language_is_forwarded_to_omnivoice(self):
        engine = TTSEngine()
        engine.model = _FakeModel()
        engine._ready = True

        engine._synthesize_audio('Gyönyörű idő van.', language='hu')

        self.assertEqual(engine.model.kwargs['language'], 'hu')

    def test_language_is_part_of_cache_key(self):
        english = TTSEngine.cache_key('A test.', None, None, 1.0, language='en')
        hungarian = TTSEngine.cache_key('A test.', None, None, 1.0, language='hu')

        self.assertNotEqual(english, hungarian)
