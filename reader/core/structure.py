import re

_NUMBER_WORDS = (
    r'one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
    r'twenty(?:\s*-?\s*\w+)?|thirty|forty|fifty|sixty|seventy|eighty|'
    r'ninety|hundred'
)

SECTION_PATTERNS = [
    ('prologue',     re.compile(r'^\s*prologue\b', re.IGNORECASE)),
    ('epilogue',     re.compile(r'^\s*epilogue\b', re.IGNORECASE)),
    ('foreword',     re.compile(r'^\s*foreword\b', re.IGNORECASE)),
    ('preface',      re.compile(r'^\s*preface\b', re.IGNORECASE)),
    ('introduction', re.compile(r'^\s*introduction\b', re.IGNORECASE)),
    ('afterword',    re.compile(r'^\s*afterword\b', re.IGNORECASE)),
    ('appendix',     re.compile(r'^\s*appendix\b', re.IGNORECASE)),
    ('interlude',    re.compile(r'^\s*interlude\b', re.IGNORECASE)),
    ('part',         re.compile(
        rf'^\s*(?:part\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b|'
        r'(?:\d+|[ivxlcdm]+)\.?\s*r[eé]sz\b|r[eé]sz\s+(?:\d+|[ivxlcdm]+)\b)',
        re.IGNORECASE,
    )),
    ('chapter',      re.compile(
        rf'^\s*(?:'
        rf'(?:chapter|ch\.?)\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b|'
        r'(?:\d+|[ivxlcdm]+)\.?\s*fejezet\b|fejezet\s+(?:\d+|[ivxlcdm]+)\b'
        r')',
        re.IGNORECASE,
    )),
]


def classify_section(title: str) -> str:
    for section_type, pattern in SECTION_PATTERNS:
        if pattern.match(title.strip()):
            return section_type
    return 'chapter'


def enrich_chapters(chapters: list) -> list:
    for ch in chapters:
        ch['section_type'] = classify_section(ch['title'])
    return chapters


def build_toc(chapters: list) -> list:
    toc = []
    for ch in chapters:
        toc.append({
            'id': ch.get('id'),
            'title': ch['title'],
            'order_num': ch['order_num'],
            'section_type': ch.get('section_type', 'chapter'),
            'word_count': ch.get('word_count', 0),
        })
    return toc
