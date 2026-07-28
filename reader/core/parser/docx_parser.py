"""DOCX (Word 2007+) book import.

Word documents carry real paragraph styles, so when an author used Heading 1
the chapter boundaries are stated rather than guessed. Documents without any
heading styles fall back to the same text heuristics the TXT importer uses.

python-docx is imported lazily inside the functions that need it so the app
still starts when the dependency is missing.
"""


class DocxImportError(RuntimeError):
    """A .docx file could not be read, with a message meant for the user."""


# Word's built-in heading styles are "Heading 1" through "Heading 9". "Title"
# is the document title style and also marks a boundary.
_HEADING_STYLE_PREFIX = 'Heading'
_TITLE_STYLE = 'Title'


def _is_heading_style(style_name: str) -> bool:
    name = (style_name or '').strip()
    return name.startswith(_HEADING_STYLE_PREFIX) or name == _TITLE_STYLE


def extract_units(doc):
    """Return ordered (text, is_heading) pairs for a python-docx Document.

    Walks the document body rather than doc.paragraphs, because
    doc.paragraphs silently omits text inside tables.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    units = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'p':
            paragraph = Paragraph(child, doc)
            units.append((paragraph.text, _is_heading_style(paragraph.style.name)))
        elif tag == 'tbl':
            # Table text is body content. Cells are never chapter boundaries:
            # a heading-styled cell is a table header, not a chapter.
            for row in Table(child, doc).rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if paragraph.text.strip():
                            units.append((paragraph.text, False))
        # Anything else (sectPr, bookmarks) carries no book text.
    return units
