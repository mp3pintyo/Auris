import re

from core.parser.language import detect_language
from core.parser.sections import (
    BACKMATTER_RE as _BACKMATTER_RE,
    COPYRIGHT_RE as _COPYRIGHT_RE,
    EXPLICIT_MARKER_THRESHOLD as _EXPLICIT_MARKER_THRESHOLD,
    INITIALS_RE as _INITIALS_RE,
    NUMBER_WORDS as _NUMBER_WORDS,
    ROMAN_ONLY_RE as _ROMAN_ONLY_RE,
    SKIP_SECTION_RE as _SKIP_SECTION_RE,
    SPEAKER_LABEL_RE as _SPEAKER_LABEL_RE,
    TOC_CHAPTER_RE as _TOC_CHAPTER_RE,
    build_chapters as _build_chapters,
    is_all_caps_heading as _is_all_caps_heading,
    is_explicit_section as _is_explicit_section,
    looks_like_heading as _looks_like_heading,
    should_skip_section as _should_skip_section,
)

# The private aliases above keep the historical import surface of this module.
# tests/test_txt_chapter_detection.py imports _is_all_caps_heading,
# _is_explicit_section and _looks_like_heading from here.


def parse(file_path):
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read()

    # Form-feed page breaks are common in plain-text book dumps.
    raw = raw.replace('\x0c', '\n')
    lines = raw.splitlines()

    # Try to extract title from first non-empty lines
    title = 'Unknown Title'
    author = 'Unknown Author'
    for line in lines[:20]:
        line = line.strip()
        if line and len(line) < 120:
            title = line
            break

    # Detect "by Author" pattern
    by_match = re.search(r'\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', raw[:500])
    if by_match:
        author = by_match.group(1)

    # If the document already has several explicit Chapter/Fejezet markers,
    # ignore all-caps scene titles so they don't pollute the TOC.
    explicit_count = sum(1 for line in lines if _is_explicit_section(line))
    allow_all_caps = explicit_count < _EXPLICIT_MARKER_THRESHOLD

    chapters = _build_chapters(
        [(line, False) for line in lines],
        title,
        allow_all_caps=allow_all_caps,
        text_headings=True,
    )

    if not chapters:
        chapters = [{
            'title': title,
            'order_num': 0,
            'content': raw.strip(),
            'word_count': len(raw.split()),
        }]

    return {
        'title': title,
        'author': author,
        'language': detect_language(raw),
        'cover_b64': None,
        'chapters': chapters,
    }
