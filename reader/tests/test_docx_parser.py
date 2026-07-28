"""Tests for DOCX import.

Fixtures are built with python-docx in a temp directory so no binary
artifact is committed and the tests exercise a real round trip.
"""
import tempfile
import unittest
from pathlib import Path

from core.parser.docx_parser import DocxImportError, extract_units


def _docx(build, name='book.docx'):
    """Build a .docx via a callback and return its path."""
    from docx import Document

    document = Document()
    build(document)
    path = Path(tempfile.mkdtemp()) / name
    document.save(path)
    return path


def _open(path):
    from docx import Document

    return Document(path)


class ExtractUnitsTests(unittest.TestCase):
    def test_heading_styles_are_flagged(self):
        def build(d):
            d.add_heading('Chapter One', level=1)
            d.add_paragraph('Body text.')

        units = extract_units(_open(_docx(build)))
        self.assertEqual(units[0], ('Chapter One', True))
        self.assertEqual(units[1], ('Body text.', False))

    def test_title_style_is_a_heading(self):
        def build(d):
            d.add_paragraph('The Book', style='Title')
            d.add_paragraph('Body text.')

        units = extract_units(_open(_docx(build)))
        self.assertEqual(units[0], ('The Book', True))

    def test_table_text_is_included_in_document_order(self):
        """doc.paragraphs silently omits table cells, which would drop part of
        the book with no warning."""
        def build(d):
            d.add_paragraph('Before the table.')
            table = d.add_table(rows=1, cols=2)
            table.cell(0, 0).text = 'Cell A'
            table.cell(0, 1).text = 'Cell B'
            d.add_paragraph('After the table.')

        texts = [text for text, _ in extract_units(_open(_docx(build)))]
        self.assertEqual(
            texts, ['Before the table.', 'Cell A', 'Cell B', 'After the table.']
        )

    def test_table_cells_are_never_headings(self):
        def build(d):
            table = d.add_table(rows=1, cols=1)
            table.cell(0, 0).text = 'CHAPTER ONE'

        units = extract_units(_open(_docx(build)))
        self.assertEqual(units, [('CHAPTER ONE', False)])

    def test_empty_paragraphs_are_kept_as_blank_units(self):
        """Blank lines separate paragraphs for downstream narration, so they
        must survive extraction rather than being dropped."""
        def build(d):
            d.add_paragraph('First.')
            d.add_paragraph('')
            d.add_paragraph('Second.')

        texts = [text for text, _ in extract_units(_open(_docx(build)))]
        self.assertEqual(texts, ['First.', '', 'Second.'])

    def test_docx_import_error_is_a_runtime_error(self):
        self.assertTrue(issubclass(DocxImportError, RuntimeError))


if __name__ == '__main__':
    unittest.main()
