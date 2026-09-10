"""Durable background-job state stored in the Auris SQLite database."""

from __future__ import annotations

import json
import uuid
from typing import Any

from core import database


_JSON_COLUMNS = {"input_json": "input", "result_json": "result"}
_UPDATABLE = {
    "state",
    "message",
    "done",
    "total",
    "error",
    "result_json",
    "cancel_requested",
    "started_at",
    "finished_at",
}


def ensure_jobs() -> None:
    """Create job-owned tables without changing any existing job state."""
    with database.get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id               TEXT PRIMARY KEY,
                type             TEXT NOT NULL,
                book_id          INTEGER,
                chapter_id       INTEGER,
                input_json       TEXT NOT NULL DEFAULT '{}',
                state            TEXT NOT NULL DEFAULT 'pending',
                message          TEXT NOT NULL DEFAULT '',
                done             INTEGER NOT NULL DEFAULT 0,
                total            INTEGER NOT NULL DEFAULT 0,
                error            TEXT,
                result_json      TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                attempt          INTEGER NOT NULL DEFAULT 1,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
                started_at       TEXT,
                finished_at      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
            CREATE INDEX IF NOT EXISTS idx_jobs_book ON jobs(book_id, created_at);

            CREATE TABLE IF NOT EXISTS chapter_analysis_state (
                book_id       INTEGER NOT NULL,
                chapter_id    INTEGER NOT NULL,
                state         TEXT NOT NULL,
                error         TEXT,
                updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY(book_id, chapter_id)
            );
            """
        )


def init_jobs() -> None:
    """Create job-owned tables and mark work abandoned by a restart."""
    ensure_jobs()
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET state='interrupted', "
            "message='Az alkalmazás újraindításakor megszakadt', "
            "error=COALESCE(error, 'Az alkalmazás a feladat befejezése előtt újraindult.'), "
            "cancel_requested=0, finished_at=datetime('now'), "
            "updated_at=datetime('now') WHERE state IN ('pending', 'running')"
        )


def _decode(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for column, public_name in _JSON_COLUMNS.items():
        raw = item.pop(column, None)
        if raw in (None, ""):
            item[public_name] = None if public_name == "result" else {}
        else:
            try:
                item[public_name] = json.loads(raw)
            except (TypeError, ValueError):
                item[public_name] = None
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    item["job_id"] = item["id"]
    done = int(item.get("done") or 0)
    total = int(item.get("total") or 0)
    item["percent"] = round(done / total * 100) if total else 0
    return item


def create_job(
    job_type: str,
    input_data: dict | None = None,
    *,
    book_id: int | None = None,
    chapter_id: int | None = None,
    message: str = "Starting...",
    done: int = 0,
    total: int = 0,
    job_id: str | None = None,
) -> dict:
    job_id = job_id or str(uuid.uuid4())
    payload = json.dumps(input_data or {}, ensure_ascii=False, separators=(",", ":"))
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO jobs "
            "(id, type, book_id, chapter_id, input_json, state, message, done, total) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (job_id, job_type, book_id, chapter_id, payload, message, done, total),
        )
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT j.*, b.title AS book_title, c.title AS chapter_title "
            "FROM jobs j LEFT JOIN books b ON b.id=j.book_id "
            "LEFT JOIN chapters c ON c.id=j.chapter_id AND c.book_id=j.book_id "
            "WHERE j.id=?",
            (job_id,),
        ).fetchone()
    return _decode(row)


def list_jobs(*, book_id: int | None = None) -> list[dict]:
    sql = (
        "SELECT j.*, b.title AS book_title, c.title AS chapter_title "
        "FROM jobs j LEFT JOIN books b ON b.id=j.book_id "
        "LEFT JOIN chapters c ON c.id=j.chapter_id AND c.book_id=j.book_id"
    )
    params: tuple[Any, ...] = ()
    if book_id is not None:
        sql += " WHERE j.book_id=?"
        params = (book_id,)
    sql += " ORDER BY j.created_at DESC, j.rowid DESC"
    with database.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_decode(row) for row in rows]


def update_job(job_id: str, **changes) -> dict:
    if "result" in changes:
        changes["result_json"] = json.dumps(
            changes.pop("result"), ensure_ascii=False, separators=(",", ":")
        )
    state = changes.get("state")
    if state == "running" and "started_at" not in changes:
        changes["started_at"] = _sqlite_now()
    if state in {"complete", "failed", "cancelled", "interrupted"} and "finished_at" not in changes:
        changes["finished_at"] = _sqlite_now()
    unknown = set(changes) - _UPDATABLE
    if unknown:
        raise ValueError(f"Unsupported job fields: {', '.join(sorted(unknown))}")
    if not changes:
        job = get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job
    if "cancel_requested" in changes:
        changes["cancel_requested"] = int(bool(changes["cancel_requested"]))
    assignments = [
        "started_at=COALESCE(started_at, ?)" if name == "started_at" else f"{name}=?"
        for name in changes
    ]
    assignments.append("updated_at=datetime('now')")
    values = list(changes.values()) + [job_id]
    with database.get_conn() as conn:
        cur = conn.execute(
            f"UPDATE jobs SET {', '.join(assignments)} WHERE id=?",
            values,
        )
        if cur.rowcount == 0:
            raise KeyError(job_id)
    return get_job(job_id)


def cancel_job(job_id: str) -> dict | None:
    job = get_job(job_id)
    if job is None:
        return None
    if job["state"] not in {"pending", "running"}:
        return job
    with database.get_conn() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET "
            "state=CASE WHEN state='pending' THEN 'cancelled' ELSE state END, "
            "cancel_requested=1, "
            "message=CASE WHEN state='pending' THEN 'Indítás előtt leállítva' "
            "ELSE 'Leállítás kérve; az aktuális köteg még befejeződhet' END, "
            "finished_at=CASE WHEN state='pending' THEN datetime('now') ELSE finished_at END, "
            "updated_at=datetime('now') "
            "WHERE id=? AND state IN ('pending', 'running')",
            (job_id,),
        )
        if cursor.rowcount == 0:
            row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
    return get_job(job_id)


def is_cancel_requested(job_id: str) -> bool:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    return bool(row and row["cancel_requested"])


def mark_cancelled(job_id: str, message: str = "Leállítva") -> dict:
    return update_job(
        job_id,
        state="cancelled",
        cancel_requested=True,
        message=message,
        finished_at=_sqlite_now(),
    )


def resume_job(job_id: str) -> dict | None:
    with database.get_conn() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET state='pending', message='Folytatásra vár a gyorsítótárból', "
            "error=NULL, result_json=NULL, cancel_requested=0, attempt=attempt+1, "
            "started_at=NULL, finished_at=NULL, updated_at=datetime('now') "
            "WHERE id=? AND state IN ('interrupted', 'cancelled', 'failed')",
            (job_id,),
        )
        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT state FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            raise ValueError(f"Job in state {row['state']} cannot be resumed.")
    return get_job(job_id)


def _sqlite_now() -> str:
    with database.get_conn() as conn:
        row = conn.execute("SELECT datetime('now') AS value").fetchone()
    return row["value"]


def set_chapter_analysis_state(
    book_id: int,
    chapter_id: int,
    state: str,
    error: str | None,
) -> None:
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO chapter_analysis_state (book_id, chapter_id, state, error) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(book_id, chapter_id) DO UPDATE SET "
            "state=excluded.state, error=excluded.error, updated_at=datetime('now')",
            (book_id, chapter_id, state, error),
        )


def list_chapter_analysis_states(book_id: int) -> dict[int, dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chapter_analysis_state WHERE book_id=? ORDER BY chapter_id",
            (book_id,),
        ).fetchall()
    return {int(row["chapter_id"]): dict(row) for row in rows}


def failed_chapter_ids(book_id: int) -> list[int]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT chapter_id FROM chapter_analysis_state "
            "WHERE book_id=? AND state='failed' ORDER BY chapter_id",
            (book_id,),
        ).fetchall()
    return [int(row["chapter_id"]) for row in rows]
