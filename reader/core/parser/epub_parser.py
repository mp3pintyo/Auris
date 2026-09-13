import base64
import re
from html.parser import HTMLParser

from core.parser.structure import attach_blocks, StructuredText, blocks_from_lines
from core.parser.sections import HU_NAMED_SECTIONS, HU_ORDINAL

try:
    import ebooklib
    from ebooklib import epub

    EBOOKLIB_OK = True
except ImportError:
    EBOOKLIB_OK = False


_NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty(?:\s*-\s*\w+)?|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety|hundred"
)
_SECTION_HEADING_RE = re.compile(
    rf"^\s*(?:"
    rf"(?:chapter|ch\.?)\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})"
    rf"|part\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})"
    rf"|prologue|epilogue|foreword|preface|introduction|afterword|appendix|interlude"
    rf"|(?:\d+|[ivxlcdm]+)\.?\s*fejezet|fejezet\s+(?:\d+|[ivxlcdm]+)"
    rf"|(?:{HU_ORDINAL})\s+fejezet"
    rf"|(?:\d+|[ivxlcdm]+)\.?\s*r[eé]sz|r[eé]sz\s+(?:\d+|[ivxlcdm]+)"
    rf"|(?:{HU_ORDINAL})\s+r[eé]sz|(?:{HU_NAMED_SECTIONS})"
    rf")\b.*$",
    re.IGNORECASE,
)
_FRONTMATTER_RE = re.compile(
    r"^(?:table\s+of\s+contents|contents|copyright\b|other\s+books\s+by\b|tartalomjegyz[ée]k|tartalom\b|impresszum\b)",
    re.IGNORECASE,
)
_BACKMATTER_RE = re.compile(
    r"^(?:you\s+have\s+just\s+finished\s+reading\b|about\s+the\s+author\b|acknowledgements?\b|a\s+szerz[őo]r[őo]l\b|k[öo]sz[öo]netnyilv[áa]n[íi]t[áa]s\b)",
    re.IGNORECASE,
)
_COPYRIGHT_RE = re.compile(
    r"\bcopyright\b|all rights reserved|licensed for your enjoyment only|"
    r"please buy an additional copy",
    re.IGNORECASE,
)
_TOC_HINT_RE = re.compile(
    rf"\btable\s+of\s+contents\b|\bcontents\b|"
    rf"\bchapter\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b",
    re.IGNORECASE,
)
_DIVIDER_RE = re.compile(
    rf"^(?:part|prologue|epilogue|foreword|preface|introduction|afterword|appendix|interlude|r[eé]sz|{HU_NAMED_SECTIONS})\b",
    re.IGNORECASE,
)


class _HTMLLineExtractor(HTMLParser):
    """Collect semantic blocks, ignoring source indentation inside paragraphs."""
    def __init__(self):
        super().__init__()
        self.lines = []
        self.kinds = {}
        self.parts = []
        self.skip = 0
        self.kind = 'paragraph'
        self.tags = {'p', 'div', 'section', 'article', 'header', 'footer',
                     'li', 'ul', 'ol', 'tr', 'td', 'th', 'blockquote',
                     'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr'}

    def flush(self):
        text = '\n'.join(re.sub(r'\s+', ' ', part).strip()
                         for part in ''.join(self.parts).split('\x00')).strip()
        if text:
            self.lines.append(StructuredText(text, self.kind))
            if self.kind != 'paragraph' or text not in self.kinds:
                self.kinds[text] = self.kind
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1
        if self.skip:
            return
        if tag in self.tags:
            self.flush()
            self.kind = 'heading' if tag == 'h1' else 'subheading' if re.fullmatch('h[2-6]', tag) else 'paragraph'
        elif tag == 'br':
            # A line break inside a paragraph is not a new paragraph.
            self.parts.append('\x00')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag in self.tags:
            self.flush()
            self.kind = 'paragraph'

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def get_lines(self):
        self.flush()
        return self.lines


def _decode_item(item):
    try:
        content = item.get_content()
        return content.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_lines(html_content):
    parser = _HTMLLineExtractor()
    parser.feed(html_content)
    parser.close()
    return parser.get_lines()


def _looks_like_section_heading(line):
    line = line.strip()
    if not line or len(line) > 160:
        return False
    return bool(_SECTION_HEADING_RE.match(line))


def _is_toc_document(lines, text):
    if not lines:
        return False
    first = lines[0]
    if _FRONTMATTER_RE.match(first) and "contents" in first.lower():
        return True
    chapter_mentions = len(
        re.findall(
            rf"\bchapter\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    return "table of contents" in text.lower() and chapter_mentions >= 3


def _should_skip_document(lines, text, started_story):
    if not lines or not text:
        return True

    first = lines[0]
    lowered = text.lower()

    if _is_toc_document(lines, text):
        return True
    if _COPYRIGHT_RE.search(text):
        return True
    if _FRONTMATTER_RE.match(first):
        return True
    if _BACKMATTER_RE.match(first):
        return True

    if not started_story:
        # Skip title pages and promotional lead-in until the first real section.
        if len(lines) <= 3 and len(text.split()) < 40:
            return True
        if len(text.split()) < 120 and not any(_looks_like_section_heading(line) for line in lines):
            return True

    if started_story and re.search(
        r"\bfeel free to tweet\b|"
        r"\bevery writer likes to receive a review\b|"
        r"\bother books by\b",
        lowered,
    ):
        return True

    return False


def _split_document(lines):
    prefix_lines = []
    sections = []
    current_title = None
    current_lines = []

    for line in lines:
        if _looks_like_section_heading(line):
            if current_title is None and current_lines:
                prefix_lines = current_lines[:]
            elif current_title is not None:
                content = "\n\n".join(current_lines).strip()
                sections.append({"title": current_title.strip(), "content": content, "lines": current_lines[:]})
            current_title = line.strip()
            current_lines = [StructuredText(line, "heading")]
        else:
            current_lines.append(line)

    if current_title is None:
        return prefix_lines or current_lines, []

    content = "\n\n".join(current_lines).strip()
    sections.append({"title": current_title.strip(), "content": content, "lines": current_lines[:]})

    return prefix_lines, sections


def _append_to_previous(chapters, extra_lines):
    if not chapters or not extra_lines:
        return

    extra = "\n\n".join(extra_lines).strip()
    if not extra:
        return

    previous = chapters[-1]
    previous["content"] = (previous["content"].rstrip() + "\n\n" + extra).strip()
    previous["word_count"] = len(previous["content"].split())
    if "blocks" in previous:
        previous["blocks"].extend(blocks_from_lines(extra_lines))


def _add_section(chapters, title, content, order_num, min_words=None, lines=None):
    title = (title or "").strip()
    content = content.strip()
    if not content:
        content = title  # divider pages (Part I, Prologue, …) carry their title as content
    if min_words is None:
        min_words = 1 if _DIVIDER_RE.match(title) else 40
    if len(content.split()) < min_words:
        return order_num
    chapters.append(
        {
            "title": title or f"Section {order_num + 1}",
            "order_num": order_num,
            "content": content,
            "word_count": len(content.split()),
        }
    )
    if lines is not None:
        chapters[-1]["blocks"] = blocks_from_lines(lines)
    return order_num + 1


def _fallback_title(lines, order_num):
    for line in lines[:5]:
        if line and len(line) <= 120:
            return line
    return f"Section {order_num + 1}"


def _flatten_toc(toc_items):
    """Flatten the nested EPUB TOC into [(title, bare_filename)] preserving order."""
    entries = []
    for item in toc_items:
        if isinstance(item, tuple):
            section, children = item
            href = getattr(section, "href", "") or ""
            fname = href.split("#")[0].rsplit("/", 1)[-1]
            if fname:
                entries.append((getattr(section, "title", "") or "", fname))
            entries.extend(_flatten_toc(children))
        else:
            href = getattr(item, "href", "") or ""
            fname = href.split("#")[0].rsplit("/", 1)[-1]
            if fname:
                entries.append((getattr(item, "title", "") or "", fname))
    return entries


def parse(file_path):
    if not EBOOKLIB_OK:
        raise ImportError("ebooklib is not installed. Run: pip install ebooklib")

    # Close even if ebooklib rejects a malformed book halfway through loading.
    # Otherwise Windows cannot remove the optional converter's temporary file.
    with open(file_path, 'rb') as source:
        book = epub.read_epub(source, options={"ignore_ncx": False})

    title = book.get_metadata("DC", "title")
    title = title[0][0] if title else "Unknown Title"

    author = book.get_metadata("DC", "creator")
    author = author[0][0] if author else "Unknown Author"

    language = book.get_metadata("DC", "language")
    language = language[0][0][:2] if language else "en"

    cover_b64 = None
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        try:
            cover_b64 = base64.b64encode(item.get_content()).decode()
            break
        except Exception:
            pass
    if not cover_b64:
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            name = item.get_name().lower()
            if "cover" in name:
                try:
                    cover_b64 = base64.b64encode(item.get_content()).decode()
                    break
                except Exception:
                    pass

    spine_ids = [spine_ref[0] for spine_ref in book.spine]
    spine_items = []
    for sid in spine_ids:
        item = book.get_item_with_id(sid)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            spine_items.append(item)

    # Build filename → TOC title map from the EPUB navigation document.
    # First occurrence wins so that anchored sub-entries (#anchor) don't override
    # the file-level entry.
    toc_entries = _flatten_toc(book.toc)
    toc_map: dict = {}
    for toc_title_val, fname in toc_entries:
        if fname and fname not in toc_map:
            toc_map[fname] = toc_title_val

    chapters = []
    order = 0
    started_story = False
    in_backmatter = False
    fallback_docs = []

    for item in spine_items:
        html = _decode_item(item)
        extractor = _HTMLLineExtractor()
        extractor.feed(html)
        extractor.close()
        lines = extractor.get_lines()
        text = "\n\n".join(lines).strip()
        if not text:
            continue

        item_basename = (item.get_name() or "").rsplit("/", 1)[-1]
        toc_title = toc_map.get(item_basename, "")

        first_line = lines[0] if lines else ""
        if in_backmatter:
            continue
        if _BACKMATTER_RE.match(first_line):
            in_backmatter = True
            continue

        # TOC-identified items bypass the front-matter skip heuristic; they are
        # always real content.  We still skip genuine TOC HTML pages regardless.
        if _is_toc_document(lines, text):
            continue
        if not toc_title and _should_skip_document(lines, text, started_story):
            continue

        prefix_lines, sections = _split_document(lines)
        if sections:
            started_story = True
            _append_to_previous(chapters, prefix_lines)
            for section in sections:
                order = _add_section(chapters, section["title"], section["content"], order, lines=section["lines"])
            continue

        # No headings recognised in the HTML — use the TOC-provided title if
        # available.  This handles EPUBs where each chapter is a separate file
        # but the heading text is only in the NCX/NAV, not in the HTML body.
        if toc_title:
            prefix_lines = list(prefix_lines)
            if prefix_lines and str(prefix_lines[0]).strip() == toc_title.strip():
                prefix_lines[0] = StructuredText(prefix_lines[0], "heading")
            else:
                prefix_lines.insert(0, StructuredText(toc_title.strip(), "heading"))
            chapter_content = "\n\n".join(prefix_lines).strip()
            order = _add_section(chapters, toc_title, chapter_content, order, min_words=1, lines=prefix_lines)
            started_story = True
            continue

        # Headingless spine item with no TOC entry: append to previous chapter
        # only if the content is small (genuine continuation), otherwise treat
        # it as its own chapter to avoid swallowing large orphan documents.
        if chapters and len(text.split()) < 300:
            _append_to_previous(chapters, lines)
            started_story = True
            continue

        fallback_docs.append({"lines": lines, "text": text})

    # Always drain fallback_docs — large headingless spine items without TOC
    # entries are better as individual chapters than silently merged.
    for doc in fallback_docs:
        order = _add_section(
            chapters,
            _fallback_title(doc["lines"], order),
            doc["text"],
            order, lines=doc["lines"],
        )

    if not chapters and fallback_docs:
        combined = "\n\n".join(doc["text"] for doc in fallback_docs).strip()
        if combined:
            chapters = [
                {
                    "title": title,
                    "order_num": 0,
                    "content": combined,
                    "word_count": len(combined.split()),
                }
            ]

    attach_blocks(chapters)
    return {
        "title": title,
        "author": author,
        "language": language,
        "cover_b64": cover_b64,
        "description": next((v for v, _ in book.get_metadata('DC', 'description')), ''),
        "publisher": next((v for v, _ in book.get_metadata('DC', 'publisher')), ''),
        "published": next((v for v, _ in book.get_metadata('DC', 'date')), ''),
        "series": next((attrs.get('content', '') for _, attrs in book.get_metadata('OPF', 'meta') if attrs.get('name') == 'calibre:series'), ''),
        "series_index": next((attrs.get('content', '') for _, attrs in book.get_metadata('OPF', 'meta') if attrs.get('name') == 'calibre:series_index'), ''),
        "chapters": chapters,
    }
