import re

from core.parser.language import detect_language
from core.parser.sections import (
    EXPLICIT_MARKER_THRESHOLD as _EXPLICIT_MARKER_THRESHOLD,
    NUMBER_WORDS as _NUMBER_WORDS,
    is_explicit_section as _is_explicit_section,
)
_SKIP_SECTION_RE = re.compile(
    r'^(?:table\s+of\s+contents|contents|copyright\b|other\s+books\s+by\b|'
    r'tartalom(?:jegyzék)?\b)$',
    re.IGNORECASE,
)
_BACKMATTER_RE = re.compile(
    r'^(?:you\s+have\s+just\s+finished\s+reading\b|about\s+the\s+author\b|'
    r'acknowledgements?\b|a\s+szerzőről\b)',
    re.IGNORECASE,
)
_COPYRIGHT_RE = re.compile(
    r'\bcopyright\b|all rights reserved|licensed for your enjoyment only|'
    r'please buy an additional copy|'
    r'minden\s+jog\s+fenntartva',
    re.IGNORECASE,
)
_TOC_CHAPTER_RE = re.compile(
    rf'\b(?:chapter|fejezet)\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b|'
    rf'\b(?:\d+|[ivxlcdm]+)\.?\s*fejezet\b',
    re.IGNORECASE,
)
# Pure roman-numeral sub-section markers: I, II, III., XIV
_ROMAN_ONLY_RE = re.compile(r'^[IVXLCDM]+\.?$', re.IGNORECASE)
# Initials like "B. L." / "A. B. C."
_INITIALS_RE = re.compile(r'^(?:[A-Z]\.\s*)+[A-Z]\.?$')
# Dialogue / script speaker labels: "VERDIER:", "BALUKHIN :"
_SPEAKER_LABEL_RE = re.compile(r'^[A-Z][A-Z0-9 .\'-]{0,40}:\s*$')

def _is_all_caps_heading(line: str) -> bool:
    """Conservative all-caps heading heuristic for books without Chapter N labels."""
    line = (line or '').strip()
    if not line:
        return False
    if not (3 < len(line) < 80):
        return False
    if not line.isupper():
        return False
    # Speaker labels and short roman-numeral scene markers are not chapters.
    if line.endswith(':'):
        return False
    if _SPEAKER_LABEL_RE.match(line):
        return False
    if _ROMAN_ONLY_RE.match(line):
        return False
    if _INITIALS_RE.match(line):
        return False
    # Need at least one real word (2+ letters), not just punctuation/digits.
    if not re.search(r'[A-ZÁÉÍÓÖŐÚÜŰ]{2,}', line):
        return False
    return True


def _looks_like_heading(line: str, allow_all_caps: bool = True) -> bool:
    if _is_explicit_section(line):
        return True
    if allow_all_caps and _is_all_caps_heading(line):
        return True
    return False


def _should_skip_section(title, content, started_story):
    title = (title or '').strip()
    content = (content or '').strip()
    lowered = content.lower()

    if not content:
        return True
    if _SKIP_SECTION_RE.match(title):
        return True
    if _BACKMATTER_RE.match(title):
        return True
    if _COPYRIGHT_RE.search(content):
        return True
    if 'table of contents' in lowered and len(_TOC_CHAPTER_RE.findall(content)) >= 3:
        return True
    if 'tartalom' in lowered and len(_TOC_CHAPTER_RE.findall(content)) >= 3:
        return True
    if not started_story and len(content.split()) < 120 and not _is_explicit_section(title):
        return True
    return False


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

    chapters = []
    current_title = title
    current_lines = []
    order = 0
    started_story = False

    for line in lines:
        stripped = line.strip()
        if _BACKMATTER_RE.match(stripped):
            break
        if _looks_like_heading(stripped, allow_all_caps=allow_all_caps):
            content = '\n'.join(current_lines).strip()
            if len(content) > 100 and not _should_skip_section(current_title, content, started_story):
                chapters.append({
                    'title': current_title,
                    'order_num': order,
                    'content': content,
                    'word_count': len(content.split()),
                })
                order += 1
                started_story = True
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        content = '\n'.join(current_lines).strip()
        if len(content) > 50 and not _should_skip_section(current_title, content, started_story):
            chapters.append({
                'title': current_title,
                'order_num': order,
                'content': content,
                'word_count': len(content.split()),
            })

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
