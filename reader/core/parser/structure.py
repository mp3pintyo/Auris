"""Source structure shared by importers; narration controls remain optional."""
import re


def attach_blocks(chapters, kinds=None):
    kinds = kinds or {}
    for chapter in chapters:
        if 'blocks' in chapter:
            chapter['content'] = '\n\n'.join(block['text'] for block in chapter['blocks'])
            chapter['word_count'] = len(chapter['content'].split())
            continue
        blocks = []
        for part in re.split(r'\n\s*\n', chapter.get('content', '')):
            text = part.strip()
            if text:
                kind = kinds.get(text, 'paragraph')
                if text == chapter.get('title'):
                    kind = 'heading'
                blocks.append({'text': text, 'kind': kind, 'speed': None, 'pause_ms': None})
        chapter['blocks'] = blocks
        chapter['content'] = '\n\n'.join(block['text'] for block in blocks)
        chapter['word_count'] = len(chapter['content'].split())
    return chapters


class StructuredText(str):
    """A source block retaining its own kind even when its wording repeats."""
    def __new__(cls, text, kind='paragraph'):
        value = super().__new__(cls, text)
        value.kind = kind
        return value


def blocks_from_lines(lines):
    blocks = []
    for line in lines:
        for part in re.split(r'\n\s*\n', str(line)):
            if part.strip():
                blocks.append(dict(text=part.strip(), kind=getattr(line, 'kind', 'paragraph'),
                                   speed=None, pause_ms=None))
    return blocks
