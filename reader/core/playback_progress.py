"""Validated resume points tied to the exact generated audio variant."""
import math
import time
from core.database import get_conn


def save(book_id, values):
    try:
        chapter = int(values['chapter_id'])
        position = int(values.get('position', 0))
        offset = float(values.get('offset_sec', 0))
        event_time = int(values.get('event_time_ms', time.time() * 1000))
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('Érvénytelen lejátszási pozíció.')
    if position < 0 or not math.isfinite(offset) or offset < 0:
        raise ValueError('Érvénytelen lejátszási pozíció.')
    key = str(values.get('cache_key') or '')[:256]
    with get_conn() as conn:
        if not conn.execute('SELECT 1 FROM chapters WHERE id=? AND book_id=?', (chapter, book_id)).fetchone():
            raise ValueError('A fejezet nem ehhez a könyvhöz tartozik.')
        segment = conn.execute('SELECT cache_key,duration_sec FROM tts_segments WHERE book_id=? AND chapter_id=? AND segment_index=?',
                               (book_id, chapter, position)).fetchone()
        if not segment or not key or key != segment['cache_key']:
            key, offset = '', 0
        else:
            offset = min(offset, max(0, float(segment['duration_sec'] or 0)))
        conn.execute('''INSERT INTO reading_progress(book_id,chapter_id,position,offset_sec,cache_key,event_time_ms,updated_at)
            VALUES(?,?,?,?,?,?,datetime('now')) ON CONFLICT(book_id) DO UPDATE SET
            chapter_id=excluded.chapter_id,position=excluded.position,offset_sec=excluded.offset_sec,
            cache_key=excluded.cache_key,event_time_ms=excluded.event_time_ms,updated_at=excluded.updated_at
            WHERE excluded.event_time_ms >= reading_progress.event_time_ms''', (book_id, chapter, position, offset, key, event_time))
        conn.execute('''UPDATE books SET last_read=datetime('now'),
            reading_state=CASE WHEN reading_state='finished' THEN 'finished' ELSE 'reading' END WHERE id=?''', (book_id,))


def load(book_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM reading_progress WHERE book_id=?', (book_id,)).fetchone()
        if not row:
            return {}
        result = dict(row)
        segment = conn.execute('SELECT cache_key FROM tts_segments WHERE book_id=? AND chapter_id=? AND segment_index=?',
                               (book_id, result['chapter_id'], result['position'])).fetchone()
        if not segment or not result['cache_key'] or segment['cache_key'] != result['cache_key']:
            result.update(offset_sec=0, cache_key='')
        return result
