"""Book organization, reusable voices and reversible pronunciation rules."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from core.database import get_conn, get_db_path


def initialize():
    with get_conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(books)")}
        for name, definition in {
            "source_url": "TEXT DEFAULT ''",
            "content_hash": "TEXT",
            "collection": "TEXT DEFAULT ''",
            "series": "TEXT DEFAULT ''",
            "reading_state": "TEXT DEFAULT 'new'",
        }.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE books ADD COLUMN {name} {definition}")
                if name == "reading_state":
                    conn.execute(
                        "UPDATE books SET reading_state='reading' WHERE last_read IS NOT NULL"
                    )
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pronunciation_rules (
                id INTEGER PRIMARY KEY, book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
                source TEXT NOT NULL, replacement TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS voice_profiles (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                instruct TEXT NOT NULL, ref_audio_path TEXT, ref_audio_name TEXT,
                ref_text TEXT, created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_segments_chapter ON tts_segments(chapter_id,segment_index);
            CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id,order_num);
        """)


def _book(conn, book_id):
    row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise ValueError("A könyv nem található.")
    return dict(row)


def update_metadata(book_id, values):
    allowed = {"title", "author", "language", "collection", "series", "reading_state"}
    updates = {}
    for key, value in values.items():
        if key not in allowed:
            continue
        if not isinstance(value, str):
            raise ValueError(f"A(z) {key} mezőnek szövegnek kell lennie.")
        updates[key] = value.strip()
    if "title" in updates and not updates["title"]:
        raise ValueError("A cím nem lehet üres.")
    if "author" in updates and not updates["author"]:
        updates["author"] = "Ismeretlen szerző"
    if any(len(v) > 300 for v in updates.values()):
        raise ValueError("Egy mező legfeljebb 300 karakter lehet.")
    if "language" in updates:
        updates["language"] = updates["language"].lower()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", updates["language"]):
            raise ValueError("Érvényes nyelvkód szükséges, például hu vagy en.")
    if updates.get("reading_state", "new") not in {"new", "reading", "finished"}:
        raise ValueError("Ismeretlen olvasási állapot.")
    with get_conn() as conn:
        previous = _book(conn, book_id)
        if updates:
            conn.execute(
                "UPDATE books SET "
                + ",".join(k + "=?" for k in updates)
                + " WHERE id=?",
                (*updates.values(), book_id),
            )
        language_changed = "language" in updates and updates["language"] != (
            previous.get("language") or ""
        ).strip().lower()
        if language_changed:
            conn.execute("DELETE FROM tts_segments WHERE book_id=?", (book_id,))
        result = _book(conn, book_id)
        result["segments_cleared"] = language_changed
        return result


def list_rules(book_id=None):
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM pronunciation_rules WHERE book_id IS NULL OR book_id=? ORDER BY book_id,id",
                (book_id,),
            )
        ]


def _invalidate(conn, book_id):
    if book_id is None:
        conn.execute("DELETE FROM tts_segments")
    else:
        conn.execute("DELETE FROM tts_segments WHERE book_id=?", (book_id,))


def save_rule(book_id, source, replacement):
    source, replacement = str(source).strip(), str(replacement).strip()
    if not source or not replacement or max(len(source), len(replacement)) > 200:
        raise ValueError("Mindkét kiejtési mező szükséges, legfeljebb 200 karakterrel.")
    if any(c in replacement for c in "[]\r\n"):
        raise ValueError(
            "A kiejtés egyszerű szöveg legyen, vezérlőcímkék és sortörés nélkül."
        )
    with get_conn() as conn:
        if book_id is not None:
            _book(conn, book_id)
        row = conn.execute(
            "SELECT id FROM pronunciation_rules WHERE book_id IS ? AND source=?",
            (book_id, source),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE pronunciation_rules SET replacement=? WHERE id=?",
                (replacement, row["id"]),
            )
            rule_id = row["id"]
        else:
            rule_id = conn.execute(
                "INSERT INTO pronunciation_rules(book_id,source,replacement) VALUES(?,?,?)",
                (book_id, source, replacement),
            ).lastrowid
        _invalidate(conn, book_id)
        return {
            "id": rule_id,
            "book_id": book_id,
            "source": source,
            "replacement": replacement,
        }


def delete_rule(rule_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pronunciation_rules WHERE id=?", (rule_id,)
        ).fetchone()
        if not row:
            raise ValueError("A szabály nem található.")
        conn.execute("DELETE FROM pronunciation_rules WHERE id=?", (rule_id,))
        _invalidate(conn, row["book_id"])


def apply_pronunciation(text, book_id=None, rules=None):
    mapping = {}
    for rule in list_rules(book_id) if rules is None else rules:
        mapping[rule["source"]] = rule["replacement"]
    if not mapping:
        return text
    pattern = re.compile(
        r"(?<!\w)(?:"
        + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True))
        + r")(?!\w)"
    )
    # One pass: replacements are never interpreted as new dictionary input.
    return pattern.sub(lambda m: mapping[m.group(0)], text)


def save_profile(name, book_id, char_id=None):
    name = str(name).strip()
    if not name or len(name) > 100:
        raise ValueError("Adj nevet a hangnak (legfeljebb 100 karakter).")
    with get_conn() as conn:
        book = _book(conn, book_id)
        if char_id is not None:
            row = conn.execute(
                "SELECT * FROM characters WHERE book_id=? AND id=?", (book_id, char_id)
            ).fetchone()
            if not row:
                raise ValueError("A szereplő nem található.")
            voice = dict(row)
        else:
            from core.settings import DEFAULT_NARRATOR_INSTRUCT, get

            voice = {
                "instruct": book["narrator_instruct"]
                or get("narrator_instruct")
                or DEFAULT_NARRATOR_INSTRUCT,
                "ref_audio_path": book["narrator_ref_audio_path"],
                "ref_audio_name": book["narrator_ref_audio_name"],
                "ref_text": book["narrator_ref_text"],
            }
    ref = voice.get("ref_audio_path")
    if ref:
        source = Path(ref)
        if not source.is_file():
            raise ValueError(
                "A referenciahang hiányzik. Töltsd fel újra a profil mentése előtt."
            )
        folder = Path(get_db_path()).parent / "voice_profiles"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (uuid.uuid4().hex + ".wav")
        shutil.copy2(source, target)
        ref = str(target)
    with get_conn() as conn:
        profile_id = conn.execute(
            "INSERT INTO voice_profiles(name,instruct,ref_audio_path,ref_audio_name,ref_text) VALUES(?,?,?,?,?)",
            (
                name,
                voice.get("instruct") or "",
                ref,
                voice.get("ref_audio_name"),
                voice.get("ref_text"),
            ),
        ).lastrowid
        return dict(
            conn.execute(
                "SELECT * FROM voice_profiles WHERE id=?", (profile_id,)
            ).fetchone()
        )


def apply_profile(profile_id, book_id, char_id=None):
    with get_conn() as conn:
        _book(conn, book_id)
        p = conn.execute(
            "SELECT * FROM voice_profiles WHERE id=?", (profile_id,)
        ).fetchone()
        if not p:
            raise ValueError("A hangprofil nem található.")
        if p["ref_audio_path"] and not Path(p["ref_audio_path"]).is_file():
            raise ValueError("A hangprofil referenciafájlja hiányzik.")
        values = (
            p["instruct"],
            p["ref_audio_path"],
            p["ref_audio_name"],
            p["ref_text"],
        )
        if char_id is not None:
            result = conn.execute(
                "UPDATE characters SET instruct=?,ref_audio_path=?,ref_audio_name=?,ref_text=? WHERE book_id=? AND id=?",
                (*values, book_id, char_id),
            )
        else:
            result = conn.execute(
                "UPDATE books SET narrator_instruct=?,narrator_ref_audio_path=?,narrator_ref_audio_name=?,narrator_ref_text=? WHERE id=?",
                (*values, book_id),
            )
        if result.rowcount == 0:
            raise ValueError("A szereplő nem található.")
        _invalidate(conn, book_id)


def list_profiles():
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute("SELECT * FROM voice_profiles ORDER BY name,id")
        ]


def delete_profile(profile_id):
    with get_conn() as conn:
        # Keep the reference: already applied books may still use it.
        conn.execute("DELETE FROM voice_profiles WHERE id=?", (profile_id,))
