import unittest

from core.parser.pdf_parser import _join_line_spans


def _span(text, x0, x1, size=12):
    return {'text': text, 'bbox': (x0, 0, x1, size), 'size': size}


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


if __name__ == '__main__':
    unittest.main()
