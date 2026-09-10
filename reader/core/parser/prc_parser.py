"""Importer for Mobipocket/PalmDOC books (``.prc``, ``.mobi``).

The container is decoded by :mod:`core.parser.mobi`; this module turns the
result into the chapter structure the rest of the app expects, using the
book's own table of contents when it has one and falling back to the plain
text heading rules in :mod:`core.parser.txt_parser` when it does not.
"""

import base64
import re

from core.parser import mobi, txt_parser
from core.parser.language import detect_language
from core.parser.sections import (
    BACKMATTER_RE,
    should_skip_section,
    split_numbered_scenes,
)

MIN_CHAPTER_WORDS = 40
# A scene shorter than this is a fragment; it joins the scene before it.
MIN_SCENE_WORDS = 10
# Divider pages (Part I, Prologue, …) are kept even though they hold no body.
_DIVIDER_RE = re.compile(
    r'^(?:part|prologue|epilogue|foreword|preface|introduction|afterword|'
    r'appendix|interlude)\b',
    re.IGNORECASE,
)


def _normalize(line):
    return re.sub(r'[\s\W_]+', ' ', (line or '')).strip().lower()


def _scene_title(parent, marker):
    """'A matematikus · 3' — the part keeps its name, the scene its number."""
    number = marker.strip().rstrip('.)')
    return f'{parent} · {number}' if parent else number


def _add_chapter(chapters, title, content, order):
    chapters.append({
        'title': title,
        'order_num': order,
        'content': content,
        'word_count': len(content.split()),
    })
    return order + 1


def _append_to_previous(chapters, extra):
    if not chapters or not extra:
        return False
    previous = chapters[-1]
    previous['content'] = (previous['content'].rstrip() + '\n\n' + extra).strip()
    previous['word_count'] = len(previous['content'].split())
    return True


def _chapters_from_sections(sections):
    chapters = []
    order = 0
    started_story = False

    for section in sections:
        title = (section['title'] or '').strip()
        lines = list(section['lines'])

        # The TOC title and the chapter's own heading are usually the same
        # text; keep it once.
        if lines and title and _normalize(lines[0]) == _normalize(title):
            lines = lines[1:]

        first_line = lines[0] if lines else ''
        if BACKMATTER_RE.match(title) or BACKMATTER_RE.match(first_line):
            break

        content = '\n'.join(lines).strip()
        if not content:
            if not (title and _DIVIDER_RE.match(title)):
                continue
            content = title

        if should_skip_section(title, content, started_story):
            continue

        min_words = 1 if _DIVIDER_RE.match(title) else MIN_CHAPTER_WORDS
        if len(content.split()) < min_words and _append_to_previous(chapters, content):
            continue

        # A titled part is often only a container: the real chapters inside it
        # are marked by nothing but a number on its own line.
        scenes = split_numbered_scenes(lines)
        if scenes:
            for marker, body in scenes:
                scene_text = '\n'.join(body).strip()
                if not scene_text:
                    continue
                if (len(scene_text.split()) < MIN_SCENE_WORDS
                        and _append_to_previous(chapters, scene_text)):
                    continue
                order = _add_chapter(
                    chapters, _scene_title(title, marker), scene_text, order
                )
            started_story = True
            continue

        order = _add_chapter(
            chapters, title or f'Section {order + 1}', content, order
        )
        started_story = True

    return chapters


def parse(file_path):
    book = mobi.read(file_path)
    sections = book.sections()

    plain_text = '\n\n'.join(
        '\n'.join(section['lines']) for section in sections if section['lines']
    ).strip()

    chapters = _chapters_from_sections(sections)

    # No usable table of contents: fall back to the plain-text heading rules.
    if len(chapters) < 2 and plain_text:
        fallback = txt_parser.parse_text(
            plain_text,
            title=book.title,
            author=book.author if book.author != 'Unknown Author' else None,
        )
        if len(fallback['chapters']) > len(chapters):
            chapters = fallback['chapters']

    if not chapters and plain_text:
        chapters = [{
            'title': book.title,
            'order_num': 0,
            'content': plain_text,
            'word_count': len(plain_text.split()),
        }]

    cover_b64 = None
    if book.cover:
        cover_b64 = base64.b64encode(book.cover['data']).decode()

    # Most .prc files declare no language; fall back to guessing from the text.
    language = str(book.language or '').strip().lower().replace('_', '-').split('-', 1)[0]
    if not re.fullmatch(r'[a-z]{2,3}', language):
        language = ''
    if not language:
        language = detect_language(plain_text)

    return {
        'title': book.title,
        'author': book.author,
        'language': language,
        'cover_b64': cover_b64,
        'chapters': chapters,
    }
