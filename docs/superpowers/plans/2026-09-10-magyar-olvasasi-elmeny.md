# Magyar olvasási élmény – megvalósítási terv

> Agentic workers: use superpowers:subagent-driven-development. Shared workspace, strictly separate file ownership; root integrates and verifies.

**Goal:** A jóváhagyott magyar olvasási élmény és Trafilatura-import elkészítése.
**Architecture:** Flask/SQLite marad; új core szolgáltatások és Blueprint, meglévő TTS/cache adapterekkel.
**Tech Stack:** Python projekt-venv, Flask, SQLite, vanilla JS, Trafilatura, meglévő ffmpeg.
**Spec:** ../specs/2026-09-10-magyar-olvasasi-elmeny-design.md

## Global Constraints
- OmniVoice elsődleges magyar motor, nincs modell- vagy Transformers-frissítés.
- Külső integráció: csak Trafilatura. OCR hiányát érthetően jelezzük.
- Python: D:/AI/Auris/reader/.venv/Scripts/python.exe. Browser: local Playwright.
- Közös feature ág; agentek csak kijelölt fájlokat írnak; root kezeli sémát és összekötést.

## Feladatok

- [x] 1. Import szolgáltatás: core/import_service.py, parser/pdf_parser.py, tests/test_import_service.py. API: prepare_file(path)->dict, prepare_url(url)->dict; a dict meglévő parser séma + source_url/content_hash. Magyar szövegtisztítás és kontrollált URL-letöltés. Tesztek: üres PDF, azonos nevű fájlok, privát URL tiltás, HTML metadata/bekezdések.
- [x] 2. Tartós jobok és export: core/jobs.py, app.py, core/exporter.py, tests/test_durable_jobs.py. Interfész: init_jobs(), list_jobs(), cancel_job(id), resume_job(id); Flask route-ok /api/jobs és /api/jobs/<id>/cancel|resume. Meglévő export/generálás integráció, reanalysis /api/books/<id>/reanalyze {chapter_ids?,failed_only?}; M4B és opcionális felirat.
- [x] 3. Olvasó: templates/reader.html, static/js/reader.js, static/js/listening.js, static/css/reader-experience.css. Nyugodt nézet, mobil/keyboard, keresés API /api/books/<id>/search?q=, időzítő/időugrás, exportpreset. A kereső találat: chapter_id, chapter_title, segment_index, excerpt. Teszt: helyi Playwright/Node viselkedési ellenőrzés.
- [x] 4. Közös szolgáltatások: core/experience.py, core/experience_api.py, core/database.py. Kiejtési szabályok /api/pronunciation?book_id=; POST {book_id?,source,replacement}, DELETE /<id>, POST /preview. Profile API /api/voice-profiles {name,instruct,book_id,char_id?}, apply /<id>/apply {book_id,char_id?}. TTS _compute_segments... kiejtés alkalmazása root integrációval. Metaadat PATCH /api/books/<id>/metadata. Kereső és tárhely/backup.
- [x] 5. Könyvtár és import UI: templates/library.html, static/js/library.js. Keresés/szűrés/metaadatok, URL/file preview /api/import/preview (multipart file vagy JSON url), POST /api/import/confirm {token,title,author,language,narration_mode}. Backend preview token csak app által létrehozott staged fájlt nyithat.
- [x] 6. Hangok/beállítások: voice_studio.html/js, settings.html/js, új experience.js/css. Hangprofil, szótár UI, első indítás/diagnosztika, magyar copy. Diagnosztika GET /api/setup/status; POST /api/setup/profile {profile}; próbahang meglévő preview API.
- [x] 7. Feladatoldal és dokumentáció: templates/jobs.html, static/js/jobs.js, base.html, docs.html, README.md. Új működés, korlátok, kezelőfeliratok, magyar példa.
- [x] 8. Integrációs kapu: összes célzott + teljes unittest; JS/Python szintaxis; Playwright import→olvasó→hangprofil→feladatok→export hibakezelés és 390px mobil; képernyők és konzolnapló; önálló kódreview és javítás.

## Végrehajtási szabály
Tesztelőbb ciklus a logikához: célzott teszt írása → hiányzó viselkedés miatti hiba → implementáció → célzott zöld. UI-nál valós DOM/state teszt. A kész feladatokat e tervben jelöljük, az eltéréseket a progress.md-ben indokoljuk. A teljes csomag végén egy összefüggő ellenőrzés, a regressziók célzott javításával.
