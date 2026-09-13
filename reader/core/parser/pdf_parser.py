import re
import base64
import unicodedata

from core.parser.language import detect_language
from core.parser.structure import attach_blocks
from core.parser.sections import EXPLICIT_MARKER_THRESHOLD, is_explicit_section

try:
    import pymupdf
    FITZ_OK = True
except ImportError:
    FITZ_OK = False


# Fallback keyword search when the document has no explicit Chapter/Fejezet lines
# (used together with font-size heuristics).
_HEADING_KEYWORD_RE = re.compile(
    r'\b(chapter|prologue|epilogue|part|section|preface|'
    r'foreword|introduction|afterword|appendix|fejezet|r[eé]sz)\b',
    re.IGNORECASE,
)


def _span_needs_leading_space(previous, current):
    """Return whether two adjacent PDF spans have a visible word gap."""
    previous_bbox = previous.get('bbox') or ()
    current_bbox = current.get('bbox') or ()
    if len(previous_bbox) < 4 or len(current_bbox) < 4:
        return False

    gap = current_bbox[0] - previous_bbox[2]
    font_size = min(previous.get('size', 12), current.get('size', 12))
    return gap > max(1.0, font_size * 0.18)


def _join_line_spans(spans):
    """Rebuild a PDF line without adding spaces at every font span boundary.

    Some embedded fonts put Hungarian double-accented glyphs (ő/ű) in a
    separate span. Joining every span with a space therefore breaks a single
    word. Span text normally carries real spaces; when it does not, bounding
    boxes let us distinguish a word gap from a font/glyph boundary.
    """
    parts = []
    previous = None

    for span in spans:
        text = span.get('text', '')
        if not text:
            continue

        if (
            previous is not None
            and parts
            and not parts[-1][-1].isspace()
            and not text[0].isspace()
            and _span_needs_leading_space(previous, span)
        ):
            parts.append(' ')

        parts.append(text)
        previous = span

    return unicodedata.normalize('NFC', ''.join(parts)).strip()


def _collect_blocks(doc):
    """Flatten PDF text into ordered line dicts with font size and page."""
    all_blocks = []
    for page_num, page in enumerate(doc):
        blocks = page.get_text('dict')['blocks']
        for block_index, block in enumerate(blocks):
            if block.get('type') != 0:
                continue
            for line_index, line in enumerate(block.get('lines', [])):
                spans = line.get('spans', [])
                text = _join_line_spans(spans)
                if text:
                    size = max((span.get('size', 12) for span in spans), default=12)
                    all_blocks.append({
                        'text': text,
                        'size': size,
                        'page': page_num,
                        'bbox': tuple(line.get('bbox', ())),
                        'page_width': page.rect.width,
                        'paragraph_start': line_index == 0 and block_index > 0,
                    })
    return all_blocks


def _is_centered_page_number(block):
    """Return whether a line is a centred, standalone Arabic page number."""
    text = block.get('text', '').strip()
    bbox = block.get('bbox') or ()
    page_width = block.get('page_width')
    if not re.fullmatch(r'\d{1,4}', text) or len(bbox) < 4 or not page_width:
        return False

    line_center = (bbox[0] + bbox[2]) / 2
    # Page numbers are conventionally centered; keeping this geometric check
    # avoids deleting numeric content from ordinary paragraph or table cells.
    return abs(line_center - page_width / 2) <= page_width * 0.08


def _without_page_numbers(blocks):
    """Remove PDF page-number lines before language and chapter processing."""
    return [block for block in blocks if not _is_centered_page_number(block)]


def _merge_pdf_blocks(blocks):
    """Join PDF lines while preserving meaningful layout boundaries."""
    output = ''
    previous_kind = None
    previous_page = None
    for block in blocks:
        text = unicodedata.normalize('NFC', block.get('text', '')).strip()
        if not text:
            continue
        if not output:
            output = text
            previous_kind = block.get('kind')
            previous_page = block.get('page')
            continue

        if (
            not block.get('kind') and not previous_kind
            and re.search(r"[^\W\d_][-\u00ad]$", output, re.UNICODE)
            and re.match(r"[a-záéíóöőúüű]", text)
        ):
            output = output[:-1] + text
        elif block.get('kind') or previous_kind or (block.get('paragraph_start') and not (
            previous_page is not None and block.get('page') != previous_page
            and re.match(r'[a-záéíóöőúüű]', text)
            and not re.search(r'[.!?…][\"”’]?$', output)
        )):
            output += '\n\n' + text
        else:
            output += ' ' + text
        previous_kind = block.get('kind')
        previous_page = block.get('page')
    return output.strip()


def _body_font_size(all_blocks):
    """Estimate body font size as the most common line size."""
    if not all_blocks:
        return 12.0
    from collections import Counter
    counts = Counter(round(b['size'], 2) for b in all_blocks)
    return counts.most_common(1)[0][0]


def _is_size_keyword_heading(block, body_size):
    """Fallback: larger-than-body font + section keyword (no explicit markers)."""
    text = block['text']
    if len(text) >= 120:
        return False
    if block['size'] <= body_size + 0.5:
        return False
    return bool(_HEADING_KEYWORD_RE.search(text))


def _split_chapters(all_blocks, default_title):
    """Split line blocks into chapters using explicit markers first."""
    explicit_count = sum(1 for b in all_blocks if is_explicit_section(b['text']))
    use_explicit_only = explicit_count >= EXPLICIT_MARKER_THRESHOLD

    body_size = _body_font_size(all_blocks)

    chapters = []
    current_title = default_title
    current_lines = []
    order = 0

    for block in all_blocks:
        text = block['text']
        if use_explicit_only:
            is_heading = is_explicit_section(text)
        else:
            is_heading = is_explicit_section(text) or _is_size_keyword_heading(
                block, body_size
            )

        if is_heading and current_lines:
            content = _merge_pdf_blocks(current_lines)
            if len(content) > 100:
                chapters.append({
                    'title': current_title,
                    'order_num': order,
                    'content': content,
                    'word_count': len(content.split()),
                })
                order += 1
            current_title = text.strip()
            current_lines = [dict(block, kind="heading")]
        elif is_heading and not current_lines:
            # Heading at the very start (or right after a discarded frontmatter).
            current_title = text.strip()
            current_lines = [dict(block, kind="heading")]
        else:
            if block['size'] > body_size + 1 and len(text) < 120:
                block = dict(block, kind='subheading')
            current_lines.append(block)

    if current_lines:
        content = _merge_pdf_blocks(current_lines)
        if len(content) > 100:
            chapters.append({
                'title': current_title,
                'order_num': order,
                'content': content,
                'word_count': len(content.split()),
            })

    kinds = {b['text']: 'subheading' for b in all_blocks if b['size'] > body_size + 1}
    kinds.update({c['title']: 'heading' for c in chapters})
    attach_blocks(chapters, kinds)
    return chapters


def parse(file_path):
    if not FITZ_OK:
        raise ImportError("PyMuPDF is not installed. Run: pip install pymupdf")

    # A failed native open can retain a Windows file handle in its traceback.
    # Own and close the source handle before parsing, including corrupt PDFs.
    with open(file_path, 'rb') as source:
        doc = pymupdf.open(stream=source.read(), filetype='pdf')

    title = doc.metadata.get('title', '') or 'Unknown Title'
    author = doc.metadata.get('author', '') or 'Unknown Author'

    # Try to extract cover from first page
    cover_b64 = None
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5))
        cover_b64 = base64.b64encode(pix.tobytes('png')).decode()
    except Exception:
        pass

    all_blocks = _without_page_numbers(_collect_blocks(doc))

    if not all_blocks:
        doc.close()
        return {'title': title, 'author': author, 'language': 'en',
                'cover_b64': cover_b64, 'chapters': []}

    language = detect_language(' '.join(block['text'] for block in all_blocks))
    chapters = _split_chapters(all_blocks, default_title=title)

    if not chapters:
        full_text = _merge_pdf_blocks(all_blocks)
        chapters = [{
            'title': title,
            'order_num': 0,
            'content': full_text,
            'word_count': len(full_text.split()),
        }]

    attach_blocks(chapters)
    doc.close()

    return {
        'title': title,
        'author': author,
        'language': language,
        'cover_b64': cover_b64,
        'chapters': chapters,
    }
