import re
import unittest
from pathlib import Path

from core.parser import pdf_parser, txt_parser


SAMPLES = Path(__file__).resolve().parents[2] / 'test_docs'


class ImportSampleTest(unittest.TestCase):
    def test_hungarian_pdf_preserves_double_accented_letters(self):
        book = pdf_parser.parse(SAMPLES / 'Rejto_Jeno-14-karatos-auto.pdf')
        text = '\n'.join(chapter['content'] for chapter in book['chapters'])
        # Author/title sit on the front page and are not always inside chapter bodies
        # once chapters are split on "I. FEJEZET" markers.
        identity = f"{book.get('author', '')} {book.get('title', '')}"

        self.assertEqual(book['language'], 'hu')
        for word in ('Rejtő', 'Jenő'):
            self.assertIn(word, identity)
        for word in ('midőn', 'jelentőségű', 'nagyszerű', 'tűnik', 'szőlője'):
            self.assertIn(word, text)
        self.assertIsNone(re.search(r'\b(?:mid|jelent|nagyszer|t)\s+[őű]\s*', text))

    def test_english_txt_remains_english(self):
        book = txt_parser.parse(SAMPLES / '14Carat.txt')

        self.assertEqual(book['language'], 'en')
        self.assertTrue(book['chapters'])

    def test_english_txt_splits_on_chapter_markers(self):
        """14Carat uses 'Chapter One'..'Chapter Twenty-one' plus all-caps scene
        titles and roman sub-sections. Only the Chapter markers should split."""
        book = txt_parser.parse(SAMPLES / '14Carat.txt')
        titles = [ch['title'] for ch in book['chapters']]

        self.assertEqual(len(book['chapters']), 21)
        self.assertEqual(titles[0], 'Chapter One')
        self.assertEqual(titles[-1], 'Chapter Twenty-one')
        self.assertTrue(all(t.startswith('Chapter ') for t in titles))
        # False positives that used to appear as separate chapters
        for bad in ('III', 'TEXAS RESTAURANT', 'VERDIER:', 'CHARACTERS:'):
            self.assertNotIn(bad, titles)
        # Each real chapter should carry substantial body text
        self.assertTrue(all(ch['word_count'] > 100 for ch in book['chapters']))

    def test_hungarian_pdf_splits_on_fejezet_markers(self):
        """Hungarian PDF uses 'I. FEJEZET' at near-body font size — must not
        require the title-page mega font threshold to detect chapters."""
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest('PyMuPDF not installed')

        book = pdf_parser.parse(SAMPLES / 'Rejto_Jeno-14-karatos-auto.pdf')
        titles = [ch['title'] for ch in book['chapters']]

        self.assertEqual(book['language'], 'hu')
        self.assertEqual(len(book['chapters']), 21)
        self.assertEqual(titles[0], 'I. FEJEZET')
        self.assertEqual(titles[-1].upper(), 'XXI. FEJEZET')
        self.assertTrue(all('FEJEZET' in t.upper() for t in titles))
        # Must not collapse the whole novel into a single chapter
        self.assertLess(max(ch['word_count'] for ch in book['chapters']), 10_000)
        self.assertTrue(all(ch['word_count'] > 50 for ch in book['chapters']))

    def test_hungarian_pdf_removes_centered_page_numbers(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF not installed')

        doc = fitz.open(SAMPLES / 'Rejto_Jeno-14-karatos-auto.pdf')
        try:
            blocks = pdf_parser._collect_blocks(doc)
        finally:
            doc.close()

        page_numbers = [
            block['text'] for block in blocks
            if pdf_parser._is_centered_page_number(block)
        ]
        filtered = pdf_parser._without_page_numbers(blocks)

        self.assertGreater(len(page_numbers), 100)
        self.assertFalse(any(pdf_parser._is_centered_page_number(block) for block in filtered))
