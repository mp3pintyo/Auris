"""Structured chapter text, deterministic narration controls and edit validation."""

import json
import math
from difflib import SequenceMatcher

from core import enrichment


def initialize(conn):
    migrated_structure = False
    for table, fields in {
        'chapters': {'blocks_json': 'TEXT', 'text_revision': 'INTEGER DEFAULT 0',
                     'previous_text_json': 'TEXT'},
        'tts_segments': {'block_index': 'INTEGER', 'block_kind': 'TEXT', 'pause_ms': 'INTEGER'},
    }.items():
        existing = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
        for name, definition in fields.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
                migrated_structure |= table == 'chapters' and name == 'blocks_json'

    if migrated_structure:
        migrate_legacy_annotations(conn)


def migrate_legacy_annotations(conn, chapter_ids=None):
    # Earlier enrichment omitted headings. Align persisted speaker units by
    # their text before the new splitter includes those headings.
    for chapter in conn.execute('SELECT id,content FROM chapters').fetchall():
        if chapter_ids is not None and chapter['id'] not in chapter_ids:
            continue
        units = enrichment.build_speaker_units(chapter['content'])
        rows = conn.execute('SELECT * FROM speaker_annotations WHERE chapter_id=? ORDER BY unit_index',
                            (chapter['id'],)).fetchall()
        if not rows:
            continue
        kept = []
        cursor = -1
        for row in rows:
            old_index = row['unit_index']
            candidates = [u['index'] for u in units if u['index'] > cursor and u['text'] == row['unit_text']]
            if old_index in candidates:
                index = old_index
            elif len(candidates) == 1:
                index = candidates[0]
            else:
                continue  # Do not silently assign an ambiguous different passage.
            kept.append((index, row))
            cursor = index
        conn.execute('DELETE FROM speaker_annotations WHERE chapter_id=?', (chapter['id'],))
        for index, row in kept:
            conn.execute('INSERT INTO speaker_annotations '
                '(book_id,chapter_id,unit_index,unit_text,speaker_name,confidence,source) VALUES(?,?,?,?,?,?,?)',
                (row['book_id'],chapter['id'],index,row['unit_text'],row['speaker_name'],row['confidence'],row['source']))

def validate_blocks(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 10000:
        raise ValueError('A fejezet 1–10000 szövegblokkot tartalmazhat.')
    result = []
    total = 0
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise ValueError('Érvénytelen szövegblokk.')
        text = item['text'].replace('\r\n', '\n').replace('\r', '\n').strip()
        total += len(text)
        if not text or total > 2_000_000:
            raise ValueError('A szöveg nem lehet üres; a fejezet legfeljebb 2 millió karakter lehet.')
        kind = item.get('kind', 'paragraph')
        if kind not in ('paragraph', 'heading', 'subheading'):
            raise ValueError('Ismeretlen bekezdéstípus.')
        block = {'text': text, 'kind': kind}
        for key, low, high in (('speed', .5, 2), ('pause_ms', 0, 5000)):
            number = item.get(key)
            if number is not None and (
                isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not low <= number <= high
            ):
                raise ValueError('A tempó 0,5–2, a szünet 0–5000 ms lehet.')
            block[key] = number
        result.append(block)
    return result


def content_of(blocks):
    return '\n\n'.join(b['text'] for b in blocks)


def chapter_blocks(chapter):
    chapter = dict(chapter)
    if chapter.get('blocks_json'):
        return validate_blocks(json.loads(chapter['blocks_json']))
    paragraphs = enrichment._split_paragraphs(chapter['content'], chapter.get('title'))
    return [dict(text=p, kind='heading' if enrichment._is_heading_paragraph(
        p, chapter.get('title')) else 'paragraph', speed=None, pause_ms=None) for p in paragraphs]


def unit_mapping(old_text, new_text):
    old = [u['text'] for u in enrichment.build_speaker_units(old_text)]
    new = [u['text'] for u in enrichment.build_speaker_units(new_text)]
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    return {a + k: b + k for a, b, length in matcher.get_matching_blocks() for k in range(length)}


def position_mapping(old_segments, new_segments):
    """Preserve repeated passages by sequence, and edits by neighboring anchors."""
    old = [s['text'] for s in old_segments]
    new = [s['text'] for s in new_segments]
    mapped = {}
    for tag, a, end_a, b, end_b in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            mapped.update({i: b + i - a for i in range(a, end_a)})
        elif tag in ('replace', 'delete'):
            for i in range(a, end_a):
                mapped[i] = min(b + i - a, max(b, end_b - 1), max(0, len(new) - 1))
    return mapped


def enrich_blocks(blocks, characters, narrator, single, annotations):
    result = []
    offset = 0
    for block_index, block in enumerate(blocks):
        count = len(enrichment.build_speaker_units(block['text']))
        local_annotations = None if annotations is None else {
            i - offset: speaker for i, speaker in annotations.items() if offset <= i < offset + count
        }
        heading = block['kind'] in ('heading', 'subheading')
        segments = enrichment.enrich_chapter(
            block['text'], characters, narrator,
            single_narrator_mode=single or heading,
            speaker_annotations=local_annotations,
        )
        for i, seg in enumerate(segments):
            if seg.get('unit_index') is not None:
                seg['unit_index'] += offset
            seg['block_index'] = block_index
            seg['block_kind'] = block['kind']
            seg['pause_ms'] = block.get('pause_ms') if i == len(segments) - 1 else None
            if block.get('speed') is not None:
                seg['speed'] = block['speed']
            if heading:
                seg['is_dialogue'] = False
                seg['speaker_candidate'] = False
                if seg['enriched_text'][-1:] not in '.!?…:;':
                    seg['enriched_text'] += '.'
            result.append(seg)
        offset += count
    return result
