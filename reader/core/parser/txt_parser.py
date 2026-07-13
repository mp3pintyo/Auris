import re

from core.parser.language import detect_language

_SECTION_RE = re.compile(
    r'^(?:'
    r'(?:chapter|ch\.?)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten'
    r'|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty'
    r'|twenty.one|twenty.two|twenty.three|thirty|forty|fifty|sixty|seventy|eighty|ninety'
    r'|hundred)'
    r'|part\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five)'
    r'|prologue|epilogue|foreword|preface|introduction|afterword|appendix|interlude'
    r'|chapter\s+\w+'
    r')\b.*$',
    re.IGNORECASE
)
_SKIP_SECTION_RE = re.compile(
    r'^(?:table\s+of\s+contents|contents|copyright\b|other\s+books\s+by\b)$',
    re.IGNORECASE
)
_BACKMATTER_RE = re.compile(
    r'^(?:you\s+have\s+just\s+finished\s+reading\b|about\s+the\s+author\b|acknowledgements?\b)',
    re.IGNORECASE
)
_COPYRIGHT_RE = re.compile(
    r'\bcopyright\b|all rights reserved|licensed for your enjoyment only|'
    r'please buy an additional copy',
    re.IGNORECASE
)
_TOC_CHAPTER_RE = re.compile(
    r'\bchapter\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten'
    r'|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen'
    r'|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b',
    re.IGNORECASE
)


def _looks_like_heading(line):
    line = line.strip()
    if not line:
        return False
    if len(line) > 150:
        return False
    if _SECTION_RE.match(line):
        return True
    # All-caps short line
    if line.isupper() and 2 < len(line) < 80:
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
    if not started_story and len(content.split()) < 120 and not _looks_like_heading(title):
        return True
    return False


def parse(file_path):
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read()

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

    chapters = []
    current_title = title
    current_lines = []
    order = 0
    started_story = False

    for line in lines:
        stripped = line.strip()
        if _BACKMATTER_RE.match(stripped):
            break
        if _looks_like_heading(stripped):
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
