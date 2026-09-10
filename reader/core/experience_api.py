"""HTTP boundaries for library tools; heavy model work stays in existing services."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, render_template, send_file, g

from core import experience, settings
from core import voice_preset_file
from core.database import get_conn

bp = Blueprint("experience", __name__)
_import_lock = threading.Lock()


@bp.errorhandler(ValueError)
def invalid_request(error):
    return jsonify(error=str(error)), 400


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("Érvényes JSON objektum szükséges.")
    return value


def book_id(value):
    if value in (None, ""):
        return None
    try:
        number = int(value)
        if number < 1:
            raise ValueError()
        return number
    except (TypeError, ValueError):
        raise ValueError("Érvényes könyvazonosító szükséges.") from None


@bp.route("/api/books/<int:bid>/metadata", methods=["PATCH"])
def metadata(bid):
    return jsonify(experience.update_metadata(bid, body()))


@bp.route("/api/pronunciation", methods=["GET", "POST"])
def pronunciation():
    if request.method == "GET":
        return jsonify(experience.list_rules(book_id(request.args.get("book_id"))))
    data = body()
    return jsonify(
        experience.save_rule(
            book_id(data.get("book_id")),
            data.get("source", ""),
            data.get("replacement", ""),
        )
    )


@bp.route("/api/pronunciation/<int:rule_id>", methods=["DELETE"])
def delete_pronunciation(rule_id):
    experience.delete_rule(rule_id)
    return jsonify(ok=True)


@bp.route("/api/pronunciation/preview", methods=["POST"])
def preview_pronunciation():
    data = body()
    text = str(data.get("text", ""))[:10000]
    return jsonify(
        original=text,
        spoken=experience.apply_pronunciation(text, book_id(data.get("book_id"))),
    )


@bp.route("/api/voice-profiles", methods=["GET", "POST"])
def profiles():
    if request.method == "GET":
        return jsonify(experience.list_profiles())
    data = body()
    return jsonify(
        experience.save_profile(
            data.get("name", ""),
            book_id(data.get("book_id")),
            book_id(data.get("char_id")),
        )
    )


@bp.route("/api/voice-profiles/<int:profile_id>", methods=["DELETE"])
def remove_profile(profile_id):
    experience.delete_profile(profile_id)
    return jsonify(ok=True)


@bp.route("/api/voice-profiles/<int:profile_id>/apply", methods=["POST"])
def use_profile(profile_id):
    data = body()
    experience.apply_profile(
        profile_id, book_id(data.get("book_id")), book_id(data.get("char_id"))
    )
    return jsonify(ok=True)


@bp.route("/api/voice-profiles/<int:profile_id>/export")
def export_profile(profile_id):
    with get_conn() as conn:
        profile = conn.execute(
            "SELECT * FROM voice_profiles WHERE id=?", (profile_id,)
        ).fetchone()
    if not profile:
        return jsonify(error="A hangprofil nem található."), 404
    if not profile["ref_audio_path"]:
        return jsonify(error="Csak referenciahangot tartalmazó profil exportálható."), 400
    try:
        archive = voice_preset_file.build_archive_from_path(
            profile["name"],
            profile["ref_audio_path"],
            ref_text=profile["ref_text"],
            source_filename=profile["ref_audio_name"],
            created_at=profile["created_at"],
            instruct=profile["instruct"],
        )
    except voice_preset_file.VoicePresetFileError as error:
        return jsonify(error=str(error)), 410
    return send_file(
        io.BytesIO(archive),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=voice_preset_file.safe_download_name(profile["name"]),
    )


@bp.route("/api/voice-profiles/import", methods=["POST"])
def import_profile():
    uploaded = request.files.get("file")
    if not uploaded or not str(uploaded.filename or "").lower().endswith(".aurisvoice"):
        raise ValueError("Válassz egy .aurisvoice hangprofilfájlt.")
    try:
        payload = voice_preset_file.read_archive_from_stream(uploaded.stream)
    except voice_preset_file.VoicePresetFileError as error:
        raise ValueError(str(error)) from error

    base_name = payload.name or Path(uploaded.filename).stem or "Importált hang"
    with get_conn() as conn:
        existing = {
            str(row["name"]).casefold()
            for row in conn.execute("SELECT name FROM voice_profiles")
        }
        name = base_name[:100]
        suffix = 2
        while name.casefold() in existing:
            tail = f" ({suffix})"
            name = base_name[:100 - len(tail)] + tail
            suffix += 1

        folder = Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent / "voice_profiles"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (uuid.uuid4().hex + ".wav")
        target.write_bytes(payload.audio_bytes)
        try:
            profile_id = conn.execute(
                "INSERT INTO voice_profiles(name,instruct,ref_audio_path,ref_audio_name,ref_text) "
                "VALUES(?,?,?,?,?)",
                (name, payload.instruct, str(target), payload.source_filename, payload.ref_text),
            ).lastrowid
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return jsonify(ok=True, id=profile_id, name=name, renamed=name != base_name)


@bp.route("/api/books/<int:bid>/search")
def search_book(bid):
    import app as application

    query = request.args.get("q", "").strip()
    if not 2 <= len(query) <= 200:
        return jsonify([])
    with get_conn() as conn:
        experience._book(conn, bid)
        chapters = [
            dict(r)
            for r in conn.execute(
                "SELECT id,title,content FROM chapters WHERE book_id=? ORDER BY order_num",
                (bid,),
            )
        ]
    found = []
    for chapter in chapters:
        if query.casefold() not in chapter["content"].casefold():
            continue
        application._ensure_chapter_segments(bid, chapter["id"])
        with get_conn() as conn:
            segments = conn.execute(
                "SELECT segment_index,text FROM tts_segments WHERE chapter_id=? ORDER BY segment_index",
                (chapter["id"],),
            ).fetchall()
        for segment in segments:
            pos = segment["text"].casefold().find(query.casefold())
            if pos >= 0:
                found.append(
                    {
                        "chapter_id": chapter["id"],
                        "chapter_title": chapter["title"],
                        "segment_index": segment["segment_index"],
                        "excerpt": segment["text"][
                            max(0, pos - 70) : pos + len(query) + 130
                        ],
                    }
                )
            if len(found) >= 100:
                return jsonify(found)
    return jsonify(found)


def _staging():
    import app as application

    path = Path(application.UPLOAD_DIR) / ".staging"
    path.mkdir(parents=True, exist_ok=True)
    # Only our UUID-named staging files expire; no user-specified paths.
    for old in path.iterdir():
        if (
            re.fullmatch(r"[0-9a-f]{32}\.(json|epub|pdf|docx|txt|prc|mobi)", old.name)
            and old.stat().st_mtime < time.time() - 86400
        ):
            old.unlink(missing_ok=True)
    return path


@bp.route("/api/import/preview", methods=["POST"])
def preview_import():
    from core import import_service

    token = uuid.uuid4().hex
    folder = _staging()
    uploaded = request.files.get("file")
    source_path = None
    try:
        if uploaded:
            ext = Path(uploaded.filename or "").suffix.lower()
            if ext not in {".epub", ".pdf", ".docx", ".txt", ".prc", ".mobi"}:
                raise ValueError("EPUB, PDF, DOCX, TXT, PRC vagy MOBI fájlt válassz.")
            source_path = folder / (token + ext)
            uploaded.save(source_path)
            parsed = import_service.prepare_file(str(source_path))
            parsed["file_type"] = ext[1:]
            parsed["original_name"] = Path(uploaded.filename).name
            if parsed.get("title") in {"Unknown Title", "Unknown"}:
                parsed["title"] = Path(uploaded.filename).stem
            if parsed.get("author") in {"Unknown Author", "Unknown"}:
                parsed["author"] = "Ismeretlen szerző"
        else:
            parsed = import_service.prepare_url(str(body().get("url", "")))
            parsed["file_type"] = "web"
            source_path = folder / (token + ".txt")
            source_path.write_text(
                "\n\n".join(c["content"] for c in parsed["chapters"]), encoding="utf-8"
            )
        parsed["staged_file"] = source_path.name
        parsed["content_hash"] = (
            parsed.get("content_hash")
            or hashlib.sha256(source_path.read_bytes()).hexdigest()
        )
        (folder / (token + ".json")).write_text(
            json.dumps(parsed, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as error:
        if source_path:
            try:
                source_path.unlink(missing_ok=True)
            except OSError:
                pass  # Expired staging cleanup retries files still held by a parser.
        if isinstance(error, ValueError):
            raise
        raise ValueError(
            "A dokumentum nem dolgozható fel. Ellenőrizd a fájlt vagy a webcímet. "
            + str(error)
        ) from error
    with get_conn() as conn:
        duplicate = conn.execute(
            "SELECT id,title FROM books WHERE content_hash=?", (parsed["content_hash"],)
        ).fetchone()
    return jsonify(
        token=token,
        title=parsed["title"],
        author=parsed["author"],
        language=parsed.get("language", "hu"),
        chapters=[
            {
                "title": c["title"],
                "word_count": c.get("word_count", len(c["content"].split())),
            }
            for c in parsed["chapters"]
        ],
        sample=parsed["chapters"][0]["content"][:1800],
        source_url=parsed.get("source_url", ""),
        duplicate=dict(duplicate) if duplicate else None,
    )


@bp.route("/api/import/confirm", methods=["POST"])
def confirm_import():
    import app as application
    from core import structure

    data = body()
    token = str(data.get("token", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Az import-előnézet azonosítója érvénytelen.")
    with _import_lock:
        folder = _staging()
        meta = folder / (token + ".json")
        if not meta.exists():
            raise ValueError(
                "Az előnézet lejárt vagy már importáltad. Készíts új előnézetet."
            )
        parsed = json.loads(meta.read_text(encoding="utf-8"))
        title = str(data.get("title", parsed["title"])).strip()
        author = str(data.get("author", parsed["author"])).strip()
        language = str(data.get("language", parsed.get("language", "hu"))).strip()
        if (
            not title
            or len(title) > 300
            or len(author) > 300
            or not re.fullmatch(r"[a-z]{2,3}", language)
        ):
            raise ValueError(
                "Adj címet (legfeljebb 300 karakter) és nyelvkódot (például hu)."
            )
        mode = data.get("narration_mode", "single")
        if mode not in {"single", "multi"}:
            raise ValueError("Válassz narrációs módot.")
        config = settings.load()
        llm = application._selected_llm_config(config)
        if mode == "multi" and (
            not llm["base_url"]
            or not llm["model"]
            or (llm["provider"] == "openai" and not llm["api_key"])
        ):
            raise ValueError(
                "A szereplőhangokhoz állíts be nyelvi modellt a Beállítások oldalon."
            )
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id,title FROM books WHERE content_hash=?",
                (parsed["content_hash"],),
            ).fetchone()
        if existing and not data.get("allow_duplicate", False):
            return jsonify(
                error="Ez a dokumentum már a könyvtárban van.", duplicate=dict(existing)
            ), 409
        staged = folder / parsed["staged_file"]
        dest = Path(application.UPLOAD_DIR) / (uuid.uuid4().hex + staged.suffix)
        shutil.copy2(staged, dest)
        try:
            chapters = structure.enrich_chapters(parsed["chapters"])
            with get_conn() as conn:
                bid = conn.execute(
                    """INSERT INTO books(title,author,file_path,file_type,cover_b64,language,
                    single_narrator_mode,total_chapters,character_analysis_status,character_analysis_provider,
                    character_analysis_model,source_url,content_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        title,
                        author,
                        str(dest),
                        parsed["file_type"],
                        parsed.get("cover_b64"),
                        language,
                        int(mode == "single"),
                        len(chapters),
                        "skipped" if mode == "single" else "queued",
                        "none" if mode == "single" else "llm",
                        "single narrator" if mode == "single" else llm["model"],
                        parsed.get("source_url", ""),
                        parsed["content_hash"],
                    ),
                ).lastrowid
                for ch in chapters:
                    conn.execute(
                        "INSERT INTO chapters(book_id,title,order_num,section_type,content,word_count) VALUES(?,?,?,?,?,?)",
                        (
                            bid,
                            ch["title"],
                            ch["order_num"],
                            ch.get("section_type", "chapter"),
                            ch["content"],
                            ch.get("word_count", len(ch["content"].split())),
                        ),
                    )
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        meta.unlink()
        staged.unlink(missing_ok=True)
    if mode == "multi":
        application._detect_characters(
            bid, {"title": title, "author": author, "chapters": chapters}, "llm", config
        )
    return jsonify(
        book_id=bid,
        title=title,
        chapters=len(chapters),
        analysis_status="skipped" if mode == "single" else "queued",
    )


@bp.route("/api/setup/status")
def setup_status():
    import app as application

    config = settings.load()
    hardware = {"device": "CPU", "vram_gb": 0}
    try:
        import torch

        if torch.cuda.is_available():
            hardware = {
                "device": torch.cuda.get_device_name(),
                "vram_gb": round(
                    torch.cuda.get_device_properties(0).total_memory / 1024**3, 1
                ),
            }
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            hardware = {"device": "Apple Metal (MPS)", "vram_gb": 0}
    except Exception:
        pass
    return jsonify(
        **hardware,
        tts=application.tts.status(),
        ffmpeg=bool(shutil.which("ffmpeg")),
        completed=bool(config.get("onboarding_complete")),
        profile=config.get("quality_profile", "balanced"),
    )


@bp.route("/api/setup/profile", methods=["POST"])
def setup_profile():
    data = body()
    profile = data.get("profile", "balanced")
    steps = {"fast": 8, "balanced": 16, "detailed": 32}
    if profile not in steps:
        raise ValueError("Ismeretlen minőségprofil.")
    changed = (
        settings.get("tts_num_step") != steps[profile]
        or settings.get("tts_batch_size") != 0
    )
    settings.save(
        {
            "quality_profile": profile,
            "tts_num_step": steps[profile],
            "tts_batch_size": 0,
            "onboarding_complete": bool(data.get("completed", False)),
        }
    )
    if changed:
        with get_conn() as conn:
            conn.execute("DELETE FROM tts_segments")
    return jsonify(ok=True, profile=profile)


@bp.route("/api/setup/preview", methods=["POST"])
def setup_preview():
    import app as application

    if application.tts.status().get("state") != "ready":
        return jsonify(
            error="Előbb töltsd be a beszédmotort. Az állapotát felül követheted."
        ), 409
    result = application.tts.generate(
        text="A délutáni fényben csendesen lapoztam a könyvet. Új történet kezdődik, tiszta, természetes magyar hangon.",
        instruct=settings.get("narrator_instruct"),
        language="hu",
        speed=1.0,
    )
    return jsonify(audio_url="/api/audio/" + result["cache_key"])


@bp.route("/jobs")
def jobs_page():
    return render_template("jobs.html")


def _assert_idle(bid=None, *, allow_interactive=False):
    import app as application

    if not allow_interactive and getattr(application, "_interactive_request_count", 0):
        raise ValueError(
            "Éppen hang készül. Állítsd le a lejátszást, majd próbáld újra."
        )

    if (
        application._active_durable_jobs(book_id=bid)
        or application._export_exclusive_active()
        or application._character_analysis_is_active()
    ):
        raise ValueError(
            "Előbb várd meg vagy állítsd le a futó generálást/elemzést a Feladatok oldalon."
        )
    for job in application._chapter_generation_jobs.values():
        if job.get("state") in {"pending", "running"}:
            raise ValueError(
                "A fejezethang készül. Előbb várd meg vagy állítsd le a feladatot."
            )


@bp.before_request
def protect_running_work():
    mutation = request.method in {
        "POST",
        "PATCH",
        "DELETE",
    } and request.endpoint not in {
        "experience.preview_import",
        "experience.preview_pronunciation",
    }
    if mutation or request.endpoint == "experience.search_book":
        import app as application

        application._work_dispatch_lock.acquire()
        g.experience_work_lock = True
        if mutation:
            _assert_idle(
                allow_interactive=request.endpoint in {
                    "experience.profiles",
                    "experience.remove_profile",
                    "experience.use_profile",
                }
            )


@bp.teardown_request
def release_work_gate(error=None):
    if g.pop("experience_work_lock", False):
        import app as application

        application._work_dispatch_lock.release()


@bp.route("/api/storage")
def storage_status():
    import app as application
    from core.database import get_db_path
    from core.tts_engine import AUDIO_CACHE_DIR
    from core.exporter import EXPORTS_DIR

    paths = {
        "Könyvtáradatok": Path(get_db_path()).parent,
        "Forrásfájlok": Path(application.UPLOAD_DIR),
        "Generált hangok": Path(AUDIO_CACHE_DIR),
        "Exportok": Path(EXPORTS_DIR),
    }
    result = []
    for name, path in paths.items():
        files = (
            [p for p in path.rglob("*") if p.is_file() and not p.is_symlink()]
            if path.exists()
            else []
        )
        result.append(
            {
                "name": name,
                "bytes": sum(p.stat().st_size for p in files),
                "files": len(files),
            }
        )
    cache = _audio_cache_scan()
    cache.pop("orphan_paths", None)
    return jsonify(
        areas=result,
        free_bytes=shutil.disk_usage(Path(get_db_path()).parent).free,
        audio_cache=cache,
    )


def _audio_cache_scan():
    from core.tts_engine import AUDIO_CACHE_DIR

    with get_conn() as conn:
        referenced = {
            Path(row["audio_path"]).name
            for row in conn.execute(
                "SELECT DISTINCT audio_path FROM tts_segments WHERE audio_path IS NOT NULL"
            )
            if row["audio_path"]
        }
    total_files = total_bytes = orphan_files = orphan_bytes = 0
    orphan_paths = []
    folder = Path(AUDIO_CACHE_DIR)
    for entry in folder.iterdir() if folder.exists() else ():
        if not entry.is_file() or entry.suffix.lower() != ".wav":
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        total_files += 1
        total_bytes += size
        if entry.name not in referenced:
            orphan_files += 1
            orphan_bytes += size
            orphan_paths.append(entry)
    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "orphan_files": orphan_files,
        "orphan_bytes": orphan_bytes,
        "orphan_paths": orphan_paths,
    }


@bp.route("/api/storage/audio-cache/cleanup", methods=["POST"])
def cleanup_audio_cache():
    scan = _audio_cache_scan()
    removed_files = removed_bytes = 0
    cutoff = time.time() - 3600
    for path in scan["orphan_paths"]:
        try:
            stat = path.stat()
            if stat.st_mtime > cutoff:
                continue
            path.unlink()
            removed_files += 1
            removed_bytes += stat.st_size
        except OSError:
            continue
    return jsonify(ok=True, removed_files=removed_files, removed_bytes=removed_bytes)


@bp.route("/api/backup", methods=["POST"])
def backup_library():
    from core.database import get_db_path
    from core.library_backup import create_backup

    data = body()
    dest = (
        Path(get_db_path()).parent / "backups" / ("auris-" + uuid.uuid4().hex + ".zip")
    )
    create_backup(dest, bool(data.get("include_audio", False)))
    return send_file(dest, as_attachment=True, download_name="auris-konyvtar.zip")


@bp.route("/api/backup/restore", methods=["POST"])
def restore_library():
    import app as application
    from core.library_backup import restore_backup

    if request.form.get("confirm") != "VISSZAÁLLÍTÁS":
        raise ValueError("A visszaállítás megerősítéséhez írd be: VISSZAÁLLÍTÁS")
    file = request.files.get("file")
    if not file:
        raise ValueError("Válaszd ki az Auris ZIP-mentést.")
    temporary = _staging() / (uuid.uuid4().hex + ".zip")
    try:
        file.save(temporary)
        result = restore_backup(
            temporary, Path(application.UPLOAD_DIR) / "restored", confirm=True
        )
        return jsonify(result)
    finally:
        temporary.unlink(missing_ok=True)


@bp.route("/api/books/<int:bid>/remove", methods=["POST"])
def remove_book(bid):
    import app as application
    from core.tts_engine import AUDIO_CACHE_DIR

    data = body() if request.method == "POST" else {}
    candidates = []
    with get_conn() as conn:
        book = experience._book(conn, bid)
        if data.get("source"):
            path = Path(book["file_path"]).resolve()
            if path.is_relative_to(Path(application.UPLOAD_DIR).resolve()):
                other = conn.execute(
                    "SELECT 1 FROM books WHERE id<>? AND file_path=?",
                    (bid, book["file_path"]),
                ).fetchone()
                if not other:
                    candidates.append(path)
        if data.get("audio"):
            for row in conn.execute(
                "SELECT DISTINCT audio_path FROM tts_segments WHERE book_id=? AND audio_path IS NOT NULL",
                (bid,),
            ):
                path = Path(row["audio_path"]).resolve()
                shared = conn.execute(
                    "SELECT 1 FROM tts_segments WHERE book_id<>? AND audio_path=?",
                    (bid, row["audio_path"]),
                ).fetchone()
                reference = conn.execute(
                    "SELECT 1 FROM voice_profiles WHERE ref_audio_path=? UNION SELECT 1 FROM characters WHERE ref_audio_path=? UNION SELECT 1 FROM books WHERE narrator_ref_audio_path=?",
                    (row["audio_path"],) * 3,
                ).fetchone()
                if (
                    not shared
                    and not reference
                    and path.is_relative_to(Path(AUDIO_CACHE_DIR).resolve())
                ):
                    candidates.append(path)
        conn.execute("DELETE FROM books WHERE id=?", (bid,))
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "jobs" in tables:
            for job in conn.execute(
                "SELECT id,result_json FROM jobs WHERE book_id=? AND state='complete' AND type IN ('export_book','export_chapter')",
                (bid,),
            ).fetchall():
                result = json.loads(job["result_json"] or "{}")
                result["book_title"] = book["title"]
                conn.execute(
                    "UPDATE jobs SET book_id=NULL,chapter_id=NULL,result_json=? WHERE id=?",
                    (json.dumps(result, ensure_ascii=False), job["id"]),
                )
            conn.execute("DELETE FROM jobs WHERE book_id=?", (bid,))
        if "chapter_analysis_state" in tables:
            conn.execute("DELETE FROM chapter_analysis_state WHERE book_id=?", (bid,))
    warnings = []
    for path in candidates:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            warnings.append("Egy lemezfájlt nem sikerült törölni: " + path.name)
    return jsonify(ok=True, warnings=warnings)
