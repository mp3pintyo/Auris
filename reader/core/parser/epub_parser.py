import base64
import re
from html.parser import HTMLParser

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
    rf")\b.*$",
    re.IGNORECASE,
)
_FRONTMATTER_RE = re.compile(
    r"^(?:table\s+of\s+contents|contents|copyright\b|other\s+books\s+by\b)",
    re.IGNORECASE,
)
_BACKMATTER_RE = re.compile(
    r"^(?:you\s+have\s+just\s+finished\s+reading\b|about\s+the\s+author\b|acknowledgements?\b)",
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
    r"^(?:part|prologue|epilogue|foreword|preface|introduction|afterword|appendix|interlude)\b",
    re.IGNORECASE,
)


class _HTMLLineExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_tags = {"script", "style"}
        self._block_tags = {
            "p",
            "div",
            "section",
            "article",
            "header",
            "footer",
            "li",
            "ul",
            "ol",
            "tr",
            "td",
            "th",
            "blockquote",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "br",
            "hr",
        }
        self._current_skip = 0

    def _line_break(self):
        if not self.parts or self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._skip_tags:
            self._current_skip += 1
            return
        if tag in self._block_tags:
            self._line_break()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._skip_tags:
            self._current_skip = max(0, self._current_skip - 1)
            return
        if tag in self._block_tags:
            self._line_break()

    def handle_data(self, data):
        if self._current_skip == 0 and data:
            self.parts.append(data)

    def get_lines(self):
        raw = "".join(self.parts).replace("\xa0", " ")
        raw = raw.replace("\r", "\n")
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        lines = []
        for line in raw.splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if normalized:
                lines.append(normalized)
        return lines


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
                content = "\n".join(current_lines).strip()
                sections.append({"title": current_title.strip(), "content": content})
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title is None:
        return prefix_lines or current_lines, []

    content = "\n".join(current_lines).strip()
    sections.append({"title": current_title.strip(), "content": content})

    return prefix_lines, sections


def _append_to_previous(chapters, extra_lines):
    if not chapters or not extra_lines:
        return

    extra = "\n".join(extra_lines).strip()
    if not extra:
        return

    previous = chapters[-1]
    previous["content"] = (previous["content"].rstrip() + "\n\n" + extra).strip()
    previous["word_count"] = len(previous["content"].split())


def _add_section(chapters, title, content, order_num, min_words=None):
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

    book = epub.read_epub(file_path, options={"ignore_ncx": False})

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
        lines = _extract_lines(html)
        text = "\n".join(lines).strip()
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
                order = _add_section(chapters, section["title"], section["content"], order)
            continue

        # No headings recognised in the HTML — use the TOC-provided title if
        # available.  This handles EPUBs where each chapter is a separate file
        # but the heading text is only in the NCX/NAV, not in the HTML body.
        if toc_title:
            chapter_content = "\n".join(prefix_lines).strip()
            order = _add_section(chapters, toc_title, chapter_content, order, min_words=1)
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
            order,
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

    return {
        "title": title,
        "author": author,
        "language": language,
        "cover_b64": cover_b64,
        "chapters": chapters,
    }
