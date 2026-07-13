import unittest

from core.parser.language import detect_language


class DetectLanguageTest(unittest.TestCase):
    def test_detects_hungarian(self):
        text = (
            'A különös történet főhőse még nem tudta, hogy ő lesz az, '
            'aki egy gyönyörű napon visszatér a régi házba.'
        )
        self.assertEqual(detect_language(text), 'hu')

    def test_keeps_english_as_default(self):
        text = 'The story was about a man who had not seen the house before.'
        self.assertEqual(detect_language(text), 'en')
