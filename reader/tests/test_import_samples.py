import re
import unittest
from pathlib import Path

from core.parser import pdf_parser, txt_parser


SAMPLES = Path(__file__).resolve().parents[2] / 'test_docs'


class ImportSampleTest(unittest.TestCase):
    def test_hungarian_pdf_preserves_double_accented_letters(self):
        book = pdf_parser.parse(SAMPLES / 'Rejto_Jeno-14-karatos-auto.pdf')
        text = '\n'.join(chapter['content'] for chapter in book['chapters'])

        self.assertEqual(book['language'], 'hu')
        for word in ('Rejtő', 'Jenő', 'midőn', 'jelentőségű', 'nagyszerű', 'tűnik', 'szőlője'):
            self.assertIn(word, text)
        self.assertIsNone(re.search(r'\b(?:mid|jelent|nagyszer|t)\s+[őű]\s*', text))

    def test_english_txt_remains_english(self):
        book = txt_parser.parse(SAMPLES / '14Carat.txt')

        self.assertEqual(book['language'], 'en')
        self.assertTrue(book['chapters'])
