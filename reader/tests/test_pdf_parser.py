import unittest

from core.parser.pdf_parser import _join_line_spans, _split_chapters
from core.parser.sections import is_explicit_section


def _span(text, x0, x1, size=12):
    return {'text': text, 'bbox': (x0, 0, x1, size), 'size': size}


def _block(text, size=12, page=0):
    return {'text': text, 'size': size, 'page': page}


class JoinPdfLineSpansTest(unittest.TestCase):
    def test_hungarian_glyph_in_separate_span_stays_inside_word(self):
        spans = [
            _span('gy', 0, 12),
            _span('ő', 12, 18),
            _span('z', 18, 24),
            _span('tes', 24, 42),
        ]

        self.assertEqual(_join_line_spans(spans), 'győztes')

    def test_hungarian_double_accent_is_normalized_to_nfc(self):
        spans = [_span('jöv', 0, 18), _span('o\u030b', 18, 24), _span('nk', 24, 36)]

        self.assertEqual(_join_line_spans(spans), 'jövőnk')

    def test_real_geometric_word_gap_is_preserved(self):
        spans = [_span('első', 0, 22), _span('könyv', 26, 54)]

        self.assertEqual(_join_line_spans(spans), 'első könyv')

    def test_existing_space_is_not_duplicated(self):
        spans = [_span('első ', 0, 25), _span('könyv', 25, 53)]

        self.assertEqual(_join_line_spans(spans), 'első könyv')


class PdfChapterSplitTest(unittest.TestCase):
    def test_roman_fejezet_is_explicit_section(self):
        for title in ('I. FEJEZET', 'II. Fejezet', 'XII. FEJEZET', '1. fejezet'):
            self.assertTrue(is_explicit_section(title), title)

    def test_splits_on_fejezet_even_when_font_near_body(self):
        """Rejtő PDF: body ~12pt, chapter headings ~14pt, title ~24pt.

        The old top-10%-of-sizes threshold only kept 24pt and missed FEJEZET.
        """
        body = 'Gorcsev Iván a Rangoon teherhajó matróza még huszonegy éves sem volt. ' * 8
        blocks = [
            _block('Rejtő Jenő', size=18),
            _block('A tizennégy karátos autó', size=24),
            _block('I. FEJEZET', size=13.9),
            _block(body, size=12),
            _block('II. FEJEZET', size=13.9),
            _block(body, size=12),
            _block('III. FEJEZET', size=13.9),
            _block(body, size=12),
        ]
        chapters = _split_chapters(blocks, default_title='A tizennégy karátos autó')
        titles = [ch['title'] for ch in chapters]
        self.assertEqual(titles, ['I. FEJEZET', 'II. FEJEZET', 'III. FEJEZET'])
        self.assertTrue(all(ch['word_count'] > 50 for ch in chapters))

    def test_body_mentions_of_resz_do_not_split(self):
        body = (
            'Az áruház teljes személyzete, valamint a vásárlóközönség egy része '
            'gyönyörködve körülállja a jelenetet a kirakat előtt. '
        ) * 10
        blocks = [
            _block('I. FEJEZET', size=14),
            _block(body, size=12),
            _block('II. FEJEZET', size=14),
            _block(body, size=12),
        ]
        chapters = _split_chapters(blocks, default_title='Regény')
        self.assertEqual([c['title'] for c in chapters], ['I. FEJEZET', 'II. FEJEZET'])


if __name__ == '__main__':
    unittest.main()
