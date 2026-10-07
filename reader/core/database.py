import sqlite3
import os
from contextlib import contextmanager

from core.paths import user_path

DB_PATH = str(user_path('data', 'reader.db'))


def get_db_path():
    return os.path.abspath(DB_PATH)


# Bumped when init_db gains a migration; stored in PRAGMA user_version.
SCHEMA_VERSION = 2
# Writers (export progress, playback progress, backups) overlap; wait instead
# of failing with "database is locked".
BUSY_TIMEOUT_SEC = 30


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=BUSY_TIMEOUT_SEC)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def get_conn():
    conn = connect()
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
    wal = sqlite3.connect(get_db_path(), timeout=BUSY_TIMEOUT_SEC)
    try:
        # WAL lets readers proceed while a job writes; the mode is persistent.
        wal.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    finally:
        wal.close()
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
            total_chapters INTEGER DEFAULT 0,
            character_analysis_status TEXT DEFAULT 'pending',
            character_analysis_message TEXT DEFAULT '',
            character_analysis_provider TEXT,
            character_analysis_model TEXT,
            character_analysis_updated_at TEXT
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

        CREATE TABLE IF NOT EXISTS speaker_annotations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            unit_index    INTEGER NOT NULL,
            unit_text     TEXT NOT NULL,
            speaker_name  TEXT NOT NULL,
            confidence    REAL DEFAULT 0,
            source        TEXT DEFAULT 'automatic',
            UNIQUE(chapter_id, unit_index)
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
            cache_key     TEXT,
            unit_index    INTEGER,
            speaker_candidate INTEGER DEFAULT 0,
            ends_paragraph INTEGER DEFAULT 0
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

        progress_cols = {r['name'] for r in conn.execute('PRAGMA table_info(reading_progress)')}
        if 'offset_sec' not in progress_cols:
            conn.execute('ALTER TABLE reading_progress ADD COLUMN offset_sec REAL DEFAULT 0')
        if 'cache_key' not in progress_cols:
            conn.execute("ALTER TABLE reading_progress ADD COLUMN cache_key TEXT DEFAULT ''")
        if 'event_time_ms' not in progress_cols:
            conn.execute('ALTER TABLE reading_progress ADD COLUMN event_time_ms INTEGER DEFAULT 0')

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
        if "character_analysis_status" not in cols:
            conn.execute(
                "ALTER TABLE books ADD COLUMN character_analysis_status TEXT DEFAULT 'pending'"
            )
        if "character_analysis_message" not in cols:
            conn.execute(
                "ALTER TABLE books ADD COLUMN character_analysis_message TEXT DEFAULT ''"
            )
        if "character_analysis_provider" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN character_analysis_provider TEXT")
        if "character_analysis_model" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN character_analysis_model TEXT")
        if "character_analysis_updated_at" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN character_analysis_updated_at TEXT")
        # Publishing: optional music bed and narrator credit for intro/outro.
        if "bg_music_path" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN bg_music_path TEXT")
        if "bg_music_name" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN bg_music_name TEXT")
        if "bg_music_db" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN bg_music_db REAL DEFAULT -22")
        if "narrator_credit" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN narrator_credit TEXT")

        char_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(characters)").fetchall()
        }
        if "ref_audio_name" not in char_cols:
            conn.execute("ALTER TABLE characters ADD COLUMN ref_audio_name TEXT")
        if "ref_text" not in char_cols:
            conn.execute("ALTER TABLE characters ADD COLUMN ref_text TEXT")

        annotation_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(speaker_annotations)").fetchall()
        }
        if "source" not in annotation_cols:
            conn.execute(
                "ALTER TABLE speaker_annotations "
                "ADD COLUMN source TEXT DEFAULT 'automatic'"
            )

    # Remove UNIQUE constraint from tts_segments.cache_key so identical sentences
    # in different chapters don't cause INSERT OR IGNORE to silently drop segments.
    import logging as _logging
    _mc = connect()
    try:
        tbl = _mc.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tts_segments'"
        ).fetchone()
        if tbl and 'UNIQUE' in (tbl['sql'] or '').upper():
            existing = [
                row['name'] for row in _mc.execute('PRAGMA table_info(tts_segments)')
            ]
            target = [
                'id', 'book_id', 'chapter_id', 'segment_index', 'text', 'enriched_text',
                'character_name', 'instruct', 'speed', 'is_dialogue', 'audio_path',
                'duration_sec', 'cache_key', 'unit_index', 'speaker_candidate',
                'ends_paragraph',
            ]
            # Copy every column both tables share; a fixed list silently
            # dropped speaker units and paragraph ends on older databases.
            shared = ', '.join(c for c in target if c in existing)
            _mc.executescript(f"""
                PRAGMA foreign_keys=OFF;
                BEGIN;
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
                    cache_key     TEXT,
                    unit_index    INTEGER,
                    speaker_candidate INTEGER DEFAULT 0,
                    ends_paragraph INTEGER DEFAULT 0
                );
                INSERT INTO tts_segments_new ({shared})
                SELECT {shared} FROM tts_segments;
                DROP TABLE tts_segments;
                ALTER TABLE tts_segments_new RENAME TO tts_segments;
                COMMIT;
                PRAGMA foreign_keys=ON;
            """)
    except Exception as _e:
        try:
            _mc.execute('ROLLBACK')
        except Exception:
            pass
        _logging.getLogger(__name__).warning(
            "cache_key UNIQUE migration failed (non-fatal): %s", _e
        )
    finally:
        _mc.close()

    with get_conn() as conn:
        segment_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tts_segments)").fetchall()
        }
        if "unit_index" not in segment_cols:
            conn.execute("ALTER TABLE tts_segments ADD COLUMN unit_index INTEGER")
        if "speaker_candidate" not in segment_cols:
            conn.execute(
                "ALTER TABLE tts_segments "
                "ADD COLUMN speaker_candidate INTEGER DEFAULT 0"
            )
        if "ends_paragraph" not in segment_cols:
            conn.execute(
                "ALTER TABLE tts_segments "
                "ADD COLUMN ends_paragraph INTEGER DEFAULT 0"
            )
        if "take_policy" not in segment_cols:
            # Which export take selection chose the current audio (NULL: one take).
            conn.execute("ALTER TABLE tts_segments ADD COLUMN take_policy TEXT")

    from core import text_editor
    with get_conn() as conn:
        text_editor.initialize(conn)

    from core.experience import initialize
    initialize()

    with get_conn() as conn:
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_segments_cache_key ON tts_segments(cache_key)'
        )
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')

    from core.qa_api import ensure_tables
    ensure_tables()
