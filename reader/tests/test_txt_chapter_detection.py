"""Unit tests for plain-text chapter / section detection."""
import tempfile
import unittest
from pathlib import Path

from core.parser import txt_parser
from core.parser.txt_parser import (
    _is_all_caps_heading,
    _is_explicit_section,
    _looks_like_heading,
)
from core import structure


class ExplicitSectionTests(unittest.TestCase):
    def test_english_chapter_forms(self):
        for line in (
            'Chapter One',
            'Chapter 1',
            'CHAPTER XII',
            'Ch. 3',
            'Chapter Twenty-one',
            'Part II',
            'Prologue',
            'Epilogue',
        ):
            self.assertTrue(_is_explicit_section(line), line)

    def test_hungarian_chapter_forms(self):
        for line in (
            '1. fejezet',
            'Fejezet 3',
            'II. fejezet',
            '3. rész',
            'Rész 2',
        ):
            self.assertTrue(_is_explicit_section(line), line)

    def test_non_sections_rejected(self):
        for line in (
            'III',
            'II.',
            'I',
            'TEXAS RESTAURANT',
            'VERDIER:',
            'B. L.',
            'Ivan Gorchev boarded ship',
            '',
        ):
            self.assertFalse(_is_explicit_section(line), line)


class AllCapsHeadingTests(unittest.TestCase):
    def test_accepts_scene_titles(self):
        self.assertTrue(_is_all_caps_heading('THE LONG ROAD HOME'))
        self.assertTrue(_is_all_caps_heading('TEXAS RESTAURANT'))

    def test_rejects_speakers_and_romans(self):
        for line in ('VERDIER:', 'BALUKHIN:', 'III', 'II.', 'B. L.', 'I'):
            self.assertFalse(_is_all_caps_heading(line), line)


class HeadingPolicyTests(unittest.TestCase):
    def test_all_caps_disabled_when_requested(self):
        self.assertTrue(_looks_like_heading('Chapter One', allow_all_caps=False))
        self.assertFalse(_looks_like_heading('TEXAS RESTAURANT', allow_all_caps=False))
        self.assertTrue(_looks_like_heading('TEXAS RESTAURANT', allow_all_caps=True))


class ParseIntegrationTests(unittest.TestCase):
    def _parse_text(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.txt'
            path.write_text(text, encoding='utf-8')
            return txt_parser.parse(str(path))

    def test_prefers_explicit_markers_over_all_caps(self):
        body = (
            'Once upon a time there was a long story that keeps going for many words '
            'so each section is long enough to keep. More text here. '
        ) * 5
        text = (
            f'My Novel\n\n'
            f'Chapter One\n{body}\n'
            f'TEXAS RESTAURANT\n{body}\n'
            f'Chapter Two\n{body}\n'
            f'III\n{body}\n'
        )
        book = self._parse_text(text)
        titles = [ch['title'] for ch in book['chapters']]
        self.assertEqual(titles, ['Chapter One', 'Chapter Two'])
        self.assertNotIn('TEXAS RESTAURANT', titles)
        self.assertNotIn('III', titles)

    def test_falls_back_to_all_caps_without_explicit_markers(self):
        body = (
            'Once upon a time there was a long story that keeps going for many words '
            'so each section is long enough to keep. More filler text here. '
        ) * 8
        text = (
            f'My Novel\n\n'
            f'THE BEGINNING\n{body}\n'
            f'THE MIDDLE\n{body}\n'
            f'THE END\n{body}\n'
        )
        book = self._parse_text(text)
        titles = [ch['title'] for ch in book['chapters']]
        self.assertEqual(titles, ['THE BEGINNING', 'THE MIDDLE', 'THE END'])

    def test_form_feed_before_chapter_is_handled(self):
        body1 = 'Body of chapter one with plenty of words. ' * 20
        body2 = 'Body of chapter two with plenty of words. ' * 20
        text = f'Title\n\n\x0cChapter One\n{body1}\n\x0cChapter Two\n{body2}\n'
        book = self._parse_text(text)
        titles = [ch['title'] for ch in book['chapters']]
        self.assertEqual(titles, ['Chapter One', 'Chapter Two'])

    def test_hungarian_fejezet_split(self):
        body1 = 'Egyszer volt hol nem volt, hosszú történet szövege. ' * 15
        body2 = 'Aztán máskor is történt valami a történetben. ' * 15
        text = f'Regény\n\n1. fejezet\n{body1}\n2. fejezet\n{body2}\n'
        book = self._parse_text(text)
        titles = [ch['title'] for ch in book['chapters']]
        self.assertEqual(titles, ['1. fejezet', '2. fejezet'])
        self.assertEqual(
            [structure.classify_section(t) for t in titles],
            ['chapter', 'chapter'],
        )


if __name__ == '__main__':
    unittest.main()
