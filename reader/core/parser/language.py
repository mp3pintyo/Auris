import re


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_HUNGARIAN_WORDS = {
    'a', 'az', 'és', 'hogy', 'nem', 'is', 'egy', 'de', 'meg', 'mint', 'aki',
    'ami', 'már', 'még', 'volt', 'van', 'csak', 'majd', 'után', 'előtt',
}
_ENGLISH_WORDS = {
    'a', 'an', 'the', 'and', 'that', 'not', 'is', 'was', 'of', 'to', 'in',
    'he', 'she', 'it', 'with', 'for', 'as', 'but', 'had', 'his', 'her',
}


def detect_language(text: str, default: str = 'en') -> str:
    """Distinguish Hungarian from English without an online dependency."""
    sample = str(text or '')[:100_000].lower()
    words = _WORD_RE.findall(sample)
    if not words:
        return default

    hungarian_score = sum(word in _HUNGARIAN_WORDS for word in words)
    english_score = sum(word in _ENGLISH_WORDS for word in words)

    # The double-accented letters are distinctive Hungarian evidence.
    hungarian_score += (sample.count('ő') + sample.count('ű')) * 2

    if hungarian_score >= 5 and hungarian_score > english_score * 1.2:
        return 'hu'
    return default
