"""Shared section / chapter heading detection for text and PDF parsers."""

import re

# Shared number words for English chapter/part labels.
NUMBER_WORDS = (
    r'one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
    r'twenty(?:\s*-\s*\w+)?|thirty|forty|fifty|sixty|seventy|eighty|'
    r'ninety|hundred'
)

# Hungarian ordinal headings from 1 to 99. Accent-tolerant variants also
# recognize text extracted from older PDFs with damaged Hungarian glyphs.
HU_ORDINAL = (
    r'(?:tizen|huszon|harminc|negyven|[öo]tven|hatvan|hetven|nyolcvan|kilencven)'
    r'(?:egyedik|kettedik|harmadik|negyedik|[öo]t[öo]dik|hatodik|hetedik|nyolcadik|kilencedik)'
    r'|els[őo]|m[áa]sodik|harmadik|negyedik|[öo]t[öo]dik|hatodik|hetedik|nyolcadik|kilencedik'
    r'|tizedik|huszadik|harmincadik|negyvenedik|[öo]tvenedik|hatvanadik|hetvenedik'
    r'|nyolcvanadik|kilencvenedik|sz[áa]zadik'
)

HU_NAMED_SECTIONS = (
    r'el[őo]sz[óo]|ut[óo]sz[óo]|bevezet[ée]s|bevezet[őo]|pr[óo]l[óo]gus|'
    r'epil[óo]gus|f[üu]ggel[ée]k|k[öo]sz[öo]netnyilv[áa]n[íi]t[áa]s|'
    r'a\s+szerz[őo]r[őo]l'
)

# Explicit section markers (English + Hungarian). High-confidence chapter boundaries.
SECTION_RE = re.compile(
    r'^(?:'
    # English: Chapter 1 / Ch. I / Chapter Twenty-one
    rf'(?:chapter|ch\.?)\s+(?:\d+|[ivxlcdm]+|{NUMBER_WORDS})\b'
    # English: Part 1 / Part II
    rf'|part\s+(?:\d+|[ivxlcdm]+|{NUMBER_WORDS})\b'
    # Named front/back matter
    r'|prologue|epilogue|foreword|preface|introduction|afterword|appendix|interlude'
    rf'|(?:{HU_NAMED_SECTIONS})\b'
    # Hungarian: "1. fejezet", "Fejezet 1", "I. FEJEZET"
    r'|(?:\d+|[ivxlcdm]+)\.?\s*fejezet\b'
    r'|fejezet\s+(?:\d+|[ivxlcdm]+)\b'
    rf'|(?:{HU_ORDINAL})\s+fejezet\b'
    # Hungarian: "1. rész", "II. rész", "Rész 3"
    r'|(?:\d+|[ivxlcdm]+)\.?\s*r[eé]sz\b'
    r'|r[eé]sz\s+(?:\d+|[ivxlcdm]+)\b'
    rf'|(?:{HU_ORDINAL})\s+r[eé]sz\b'
    r').*$',
    re.IGNORECASE,
)

# Prefer explicit markers once we see this many in the whole document.
EXPLICIT_MARKER_THRESHOLD = 2


def is_explicit_section(line: str, max_len: int = 150) -> bool:
    """True when a line is a high-confidence chapter/section heading."""
    line = (line or '').strip()
    if not line or len(line) > max_len:
        return False
    return bool(SECTION_RE.match(line))


def looks_like_lead_in_prose(content: str) -> bool:
    """Recognize a real opening paragraph before the first chapter heading."""
    content = (content or '').strip()
    if len(content.split()) < 15:
        return False
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    longest_line_words = max((len(line.split()) for line in lines), default=0)
    sentence_marks = len(re.findall(r'[.!?…]', content))
    return longest_line_words >= 12 or sentence_marks >= 2


NUMBERED_MARKER_RE = re.compile(r'^\s*(\d{1,3})\s*[.)]?\s*$')
MIN_NUMBERED_MARKERS = 3
MIN_MEDIAN_SCENE_WORDS = 50


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def split_numbered_scenes(
    lines,
    min_markers=MIN_NUMBERED_MARKERS,
    min_median_words=MIN_MEDIAN_SCENE_WORDS,
):
    """Split a substantial consecutive run of bare numbered scenes."""
    marks = []
    for index, line in enumerate(lines):
        match = NUMBERED_MARKER_RE.match(line)
        if match:
            marks.append((index, int(match.group(1))))
    if len(marks) < min_markers:
        return None
    numbers = [number for _, number in marks]
    if any(second - first != 1 for first, second in zip(numbers, numbers[1:])):
        return None

    bounds = [index for index, _ in marks] + [len(lines)]
    scenes = [
        (lines[start].strip(), lines[start + 1:end])
        for (start, _), end in zip(marks, bounds[1:])
    ]
    preamble = lines[:marks[0][0]]
    if preamble:
        scenes[0] = (scenes[0][0], preamble + scenes[0][1])
    sizes = [sum(len(line.split()) for line in body) for _, body in scenes]
    if not sizes or sizes[-1] == 0 or _median(sizes) < min_median_words:
        return None
    return scenes


SKIP_SECTION_RE = re.compile(
    r'^(?:table\s+of\s+contents|contents|copyright\b|other\s+books\s+by\b|'
    r'tartalom(?:jegyzék)?\b)$',
    re.IGNORECASE,
)
BACKMATTER_RE = re.compile(
    r'^(?:you\s+have\s+just\s+finished\s+reading\b|about\s+the\s+author\b|'
    r'acknowledgements?\b|a\s+szerzőről\b)',
    re.IGNORECASE,
)
COPYRIGHT_RE = re.compile(
    r'\bcopyright\b|all rights reserved|licensed for your enjoyment only|'
    r'please buy an additional copy|'
    r'minden\s+jog\s+fenntartva',
    re.IGNORECASE,
)
TOC_CHAPTER_RE = re.compile(
    rf'\b(?:chapter|fejezet)\s+(?:\d+|[ivxlcdm]+|{NUMBER_WORDS})\b|'
    rf'\b(?:\d+|[ivxlcdm]+)\.?\s*fejezet\b|'
    rf'\b(?:{HU_ORDINAL})\s+fejezet\b',
    re.IGNORECASE,
)
# Pure roman-numeral sub-section markers: I, II, III., XIV
ROMAN_ONLY_RE = re.compile(r'^[IVXLCDM]+\.?$', re.IGNORECASE)
# Initials like "B. L." / "A. B. C."
INITIALS_RE = re.compile(r'^(?:[A-Z]\.\s*)+[A-Z]\.?$')
# Dialogue / script speaker labels: "VERDIER:", "BALUKHIN :"
SPEAKER_LABEL_RE = re.compile(r'^[A-Z][A-Z0-9 .\'-]{0,40}:\s*$')


def is_all_caps_heading(line: str) -> bool:
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
    if SPEAKER_LABEL_RE.match(line):
        return False
    if ROMAN_ONLY_RE.match(line):
        return False
    if INITIALS_RE.match(line):
        return False
    # Need at least one real word (2+ letters), not just punctuation/digits.
    if not re.search(r'[A-ZÁÉÍÓÖŐÚÜŰ]{2,}', line):
        return False
    return True


def looks_like_heading(line: str, allow_all_caps: bool = True) -> bool:
    if is_explicit_section(line):
        return True
    if allow_all_caps and is_all_caps_heading(line):
        return True
    return False


def should_skip_section(title, content, started_story, *, title_is_declared_heading=False):
    """title_is_declared_heading: the title came from a source-declared heading
    (e.g. a DOCX Heading style), not a guessed boundary. When true, the
    front-matter word-count guard below is skipped, since the boundary was
    stated by the author rather than inferred from text. Defaults to False so
    TXT (which never declares headings) is unaffected."""
    title = (title or '').strip()
    content = (content or '').strip()
    lowered = content.lower()

    if not content:
        return True
    if SKIP_SECTION_RE.match(title):
        return True
    if BACKMATTER_RE.match(title):
        return True
    if COPYRIGHT_RE.search(content):
        return True
    if 'table of contents' in lowered and len(TOC_CHAPTER_RE.findall(content)) >= 3:
        return True
    if 'tartalom' in lowered and len(TOC_CHAPTER_RE.findall(content)) >= 3:
        return True
    if (
        not title_is_declared_heading
        and not started_story
        and len(content.split()) < 120
        and not is_explicit_section(title)
        and not looks_like_lead_in_prose(content)
    ):
        return True
    return False


def build_chapters(
    units,
    fallback_title,
    *,
    allow_all_caps: bool = True,
    text_headings: bool = True,
):
    """Group (text, is_heading) units into chapters.

    units: ordered (text, is_heading) pairs. is_heading marks a boundary the
        source declared explicitly, such as a DOCX Heading style.
    fallback_title: title for content appearing before the first heading.
    allow_all_caps: let the all-caps heuristic mark headings.
    text_headings: run text-based heading detection at all. DOCX turns this
        off when the document has real heading styles, so an author's declared
        structure is never second-guessed by a regex.

    Returns chapter dicts. An empty list means nothing met the length and
    skip rules; each caller supplies its own single-chapter fallback.
    """
    chapters = []
    current_title = fallback_title
    current_title_is_heading = False
    current_lines = []
    order = 0
    started_story = False

    for text, is_heading in units:
        stripped = (text or '').strip()
        if BACKMATTER_RE.match(stripped):
            break
        heading = is_heading or (
            text_headings and looks_like_heading(stripped, allow_all_caps=allow_all_caps)
        )
        if heading:
            content = '\n'.join(current_lines).strip()
            if len(content) > 100 and not should_skip_section(
                current_title,
                content,
                started_story,
                title_is_declared_heading=current_title_is_heading,
            ):
                chapters.append({
                    'title': current_title,
                    'order_num': order,
                    'content': content,
                    'word_count': len(content.split()),
                })
                order += 1
                started_story = True
            current_title = stripped
            current_title_is_heading = is_heading
            current_lines = []
        else:
            current_lines.append(text)

    if current_lines:
        content = '\n'.join(current_lines).strip()
        if len(content) > 50 and not should_skip_section(
            current_title,
            content,
            started_story,
            title_is_declared_heading=current_title_is_heading,
        ):
            chapters.append({
                'title': current_title,
                'order_num': order,
                'content': content,
                'word_count': len(content.split()),
            })

    return chapters
