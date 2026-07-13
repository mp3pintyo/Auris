import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'reader.db')


def get_db_path():
    return os.path.abspath(DB_PATH)


@contextmanager
def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(get_db_path()), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            author      TEXT DEFAULT 'Unknown',
            file_path   TEXT NOT NULL,
            file_type   TEXT NOT NULL,
            cover_b64   TEXT,
            language    TEXT DEFAULT 'en',
            narrator_instruct TEXT,
            single_narrator_mode INTEGER DEFAULT 0,
            narrator_ref_audio_path TEXT,
            narrator_ref_audio_name TEXT,
            narrator_ref_text TEXT,
            added_at    TEXT DEFAULT (datetime('now')),
            last_read   TEXT,
            total_chapters INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id      INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            title        TEXT NOT NULL,
            order_num    INTEGER NOT NULL,
            section_type TEXT DEFAULT 'chapter',
            content      TEXT NOT NULL,
            word_count   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS characters (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            gender        TEXT DEFAULT 'unknown',
            frequency     INTEGER DEFAULT 1,
            instruct      TEXT,
            ref_audio_path TEXT,
            ref_audio_name TEXT,
            ref_text       TEXT,
            color_hex     TEXT DEFAULT '#FFFFFF',
            UNIQUE(book_id, name)
        );

        CREATE TABLE IF NOT EXISTS reading_progress (
            book_id    INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
            chapter_id INTEGER,
            position   INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tts_segments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            segment_index INTEGER NOT NULL,
            text          TEXT NOT NULL,
            enriched_text TEXT NOT NULL,
            character_name TEXT,
            instruct      TEXT,
            speed         REAL DEFAULT 1.0,
            is_dialogue   INTEGER DEFAULT 0,
            audio_path    TEXT,
            duration_sec  REAL,
            cache_key     TEXT UNIQUE
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            segment_index INTEGER DEFAULT 0,
            text_excerpt  TEXT,
            label         TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        );
        """)

        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(books)").fetchall()
        }
        if "narrator_instruct" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN narrator_instruct TEXT")
        if "single_narrator_mode" not in cols:
            conn.execute(
                "ALTER TABLE books ADD COLUMN single_narrator_mode INTEGER DEFAULT 0"
            )
        if "narrator_ref_audio_path" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN narrator_ref_audio_path TEXT")
        if "narrator_ref_audio_name" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN narrator_ref_audio_name TEXT")
        if "narrator_ref_text" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN narrator_ref_text TEXT")

        char_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(characters)").fetchall()
        }
        if "ref_audio_name" not in char_cols:
            conn.execute("ALTER TABLE characters ADD COLUMN ref_audio_name TEXT")
        if "ref_text" not in char_cols:
            conn.execute("ALTER TABLE characters ADD COLUMN ref_text TEXT")

    # Remove UNIQUE constraint from tts_segments.cache_key so identical sentences
    # in different chapters don't cause INSERT OR IGNORE to silently drop segments.
    import sqlite3 as _sqlite3
    import logging as _logging
    _mc = _sqlite3.connect(get_db_path())
    _mc.row_factory = _sqlite3.Row
    try:
        tbl = _mc.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tts_segments'"
        ).fetchone()
        if tbl and 'UNIQUE' in (tbl['sql'] or '').upper():
            _mc.executescript("""
                PRAGMA foreign_keys=OFF;
                DROP TABLE IF EXISTS tts_segments_new;
                CREATE TABLE tts_segments_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                    segment_index INTEGER NOT NULL,
                    text          TEXT NOT NULL,
                    enriched_text TEXT NOT NULL,
                    character_name TEXT,
                    instruct      TEXT,
                    speed         REAL DEFAULT 1.0,
                    is_dialogue   INTEGER DEFAULT 0,
                    audio_path    TEXT,
                    duration_sec  REAL,
                    cache_key     TEXT
                );
                INSERT INTO tts_segments_new SELECT * FROM tts_segments;
                DROP TABLE tts_segments;
                ALTER TABLE tts_segments_new RENAME TO tts_segments;
                PRAGMA foreign_keys=ON;
            """)
    except Exception as _e:
        _logging.getLogger(__name__).warning(
            "cache_key UNIQUE migration failed (non-fatal): %s", _e
        )
    finally:
        _mc.close()
