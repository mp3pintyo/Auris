"""Shared section / chapter heading detection for text and PDF parsers."""

import re

# Shared number words for English chapter/part labels.
NUMBER_WORDS = (
    r'one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
    r'twenty(?:\s*-\s*\w+)?|thirty|forty|fifty|sixty|seventy|eighty|'
    r'ninety|hundred'
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
    # Hungarian: "1. fejezet", "Fejezet 1", "I. FEJEZET"
    r'|(?:\d+|[ivxlcdm]+)\.?\s*fejezet\b'
    r'|fejezet\s+(?:\d+|[ivxlcdm]+)\b'
    # Hungarian: "1. rész", "II. rész", "Rész 3"
    r'|(?:\d+|[ivxlcdm]+)\.?\s*r[eé]sz\b'
    r'|r[eé]sz\s+(?:\d+|[ivxlcdm]+)\b'
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
