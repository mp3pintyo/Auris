"""Portable library archives. Never deserialize code or extract arbitrary paths."""

from __future__ import annotations
import hashlib
import json
import shutil
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path
from core import settings
from core.database import get_conn, get_db_path

TABLES = (
    "books",
    "chapters",
    "characters",
    "speaker_annotations",
    "reading_progress",
    "tts_segments",
    "bookmarks",
    "pronunciation_rules",
    "voice_profiles",
)
PATH_FIELDS = {
    "books": ("file_path", "narrator_ref_audio_path"),
    "characters": ("ref_audio_path",),
    "tts_segments": ("audio_path",),
    "voice_profiles": ("ref_audio_path",),
}
MAX_EXPANDED = 4 * 1024**3
PORTABLE_SETTINGS = {
    "default_speed",
    "normalize_text",
    "tts_num_step",
    "tts_batch_size",
    "audio_mastering",
    "theme",
    "font_size",
    "font_family",
    "line_height",
    "quality_profile",
    "audio_format",
    "subtitle_format",
    "narrator_instruct",
}


def create_backup(destination, include_audio=False):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = {}
    known = {}
    manifest = {
        "version": 1,
        "tables": {},
        "files": {},
        "settings": {},
        "audio": include_audio,
    }
    with get_conn() as conn:
        conn.execute("BEGIN")
        for table in TABLES:
            rows = [dict(r) for r in conn.execute("SELECT * FROM " + table)]
            for row in rows:
                for field in PATH_FIELDS.get(table, ()):
                    value = row.get(field)
                    if table == "tts_segments" and not include_audio:
                        row[field] = None
                        continue
                    if not value:
                        continue
                    source = Path(value)
                    if not source.is_file():
                        row[field] = None if field != "file_path" else ""
                        continue
                    key = str(source.resolve())
                    if key not in known:
                        archive_name = "files/" + uuid.uuid4().hex + source.suffix[:12]
                        known[key] = archive_name
                        files[archive_name] = source
                    row[field] = known[key]
            manifest["tables"][table] = rows
    manifest["settings"] = {
        k: v for k, v in settings.load().items() if k in PORTABLE_SETTINGS
    }
    try:
        with zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as z:
            for name, source in files.items():
                digest = hashlib.sha256()
                with (
                    source.open("rb") as inp,
                    z.open(name, "w", force_zip64=True) as out,
                ):
                    while chunk := inp.read(1024 * 1024):
                        digest.update(chunk)
                        out.write(chunk)
                manifest["files"][name] = digest.hexdigest()
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def restore_backup(archive, destination, *, confirm=False):
    if not confirm:
        raise ValueError("A visszaállításhoz kifejezett megerősítés szükséges.")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    created = []
    committed = False
    try:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if (
                len(infos) > 30000
                or len(set(names)) != len(names)
                or sum(i.file_size for i in infos) > MAX_EXPANDED
            ):
                raise ValueError("A mentés túl nagy vagy ismétlődő fájlokat tartalmaz.")
            if (
                "manifest.json" not in names
                or z.getinfo("manifest.json").file_size > 100 * 1024**2
            ):
                raise ValueError("Nem érvényes Auris-mentés.")
            manifest = json.loads(z.read("manifest.json"))
            if not isinstance(manifest, dict) or not isinstance(
                manifest.get("settings", {}), dict
            ):
                raise ValueError("A mentés leíróadatai érvénytelenek.")
            if not isinstance(manifest.get("tables"), dict) or not isinstance(
                manifest.get("files"), dict
            ):
                raise ValueError("A mentés táblái vagy fájladatai érvénytelenek.")
            if manifest.get("version") != 1 or set(manifest.get("tables", {})) != set(
                TABLES
            ):
                raise ValueError(
                    "A mentés verziója vagy adatbázisszerkezete nem támogatott."
                )
            file_map = manifest.get("files", {})
            if set(names) != {"manifest.json", *file_map}:
                raise ValueError("A mentés nem várt fájlokat tartalmaz.")
            for name in file_map:
                parts = Path(name).parts
                if (
                    len(parts) != 2
                    or parts[0] != "files"
                    or ".." in name
                    or ":" in name
                    or "\\" in name
                ):
                    raise ValueError("Érvénytelen fájlútvonal a mentésben.")
            with get_conn() as conn:
                for table, rows in manifest["tables"].items():
                    columns = {
                        r["name"]
                        for r in conn.execute("PRAGMA table_info(" + table + ")")
                    }
                    if not isinstance(rows, list) or any(
                        not isinstance(row, dict) or not set(row) <= columns
                        for row in rows
                    ):
                        raise ValueError(
                            "A mentés érvénytelen adatbázismezőket tartalmaz."
                        )
            if (
                shutil.disk_usage(destination).free
                < sum(i.file_size for i in infos) + 100 * 1024**2
            ):
                raise ValueError("Nincs elég szabad hely a visszaállításhoz.")
            resolved = {}
            for name, expected in file_map.items():
                target = destination / (uuid.uuid4().hex + Path(name).suffix)
                created.append(target)
                digest = hashlib.sha256()
                with z.open(name) as inp, target.open("wb") as out:
                    while chunk := inp.read(1024 * 1024):
                        digest.update(chunk)
                        out.write(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError("A mentés egyik fájlja sérült.")
                resolved[name] = str(target.resolve())
            for table, rows in manifest["tables"].items():
                for row in rows:
                    for field in PATH_FIELDS.get(table, ()):
                        value = row.get(field)
                        if value:
                            if value not in resolved:
                                raise ValueError("Hiányzó fájlhivatkozás a mentésben.")
                            row[field] = resolved[value]
            # Before any database replacement, create a recovery copy of today's library.
            recovery = (
                Path(get_db_path()).parent
                / "backups"
                / ("before-restore-" + str(time.time_ns()) + ".zip")
            )
            create_backup(recovery, include_audio=False)
            with get_conn() as conn:
                # Historical jobs reference IDs from the replaced library and must not be resumed.
                tables = {
                    r["name"]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                for operational in ("jobs", "chapter_analysis_state"):
                    if operational in tables:
                        conn.execute("DELETE FROM " + operational)
                for table in reversed(TABLES):
                    conn.execute("DELETE FROM " + table)
                for table in TABLES:
                    for row in manifest["tables"][table]:
                        conn.execute(
                            "INSERT INTO "
                            + table
                            + " ("
                            + ",".join('"' + k + '"' for k in row)
                            + ") VALUES ("
                            + ",".join("?" for _ in row)
                            + ")",
                            tuple(row.values()),
                        )
            committed = True
            # Machine-specific model paths and secrets remain from the current machine.
            allowed = PORTABLE_SETTINGS
            warning = None
            try:
                settings.save(
                    {
                        k: v
                        for k, v in manifest.get("settings", {}).items()
                        if k in allowed
                    }
                )
            except OSError:
                warning = "A könyvtár visszaállt, a megjelenési beállítások mentése nem sikerült."
            return {
                "books": len(manifest["tables"]["books"]),
                "recovery_path": str(recovery),
                "warning": warning,
            }
    except (
        zipfile.BadZipFile,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        sqlite3.DatabaseError,
    ) as error:
        if not committed:
            for p in created:
                p.unlink(missing_ok=True)
        raise ValueError("A mentés sérült vagy nem Auris-formátumú.") from error
    except Exception:
        if not committed:
            for p in created:
                p.unlink(missing_ok=True)
        raise
