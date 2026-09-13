# Structured text and narration implementation plan

**Goal:** Preserve source paragraphs and headings, provide an optional reversible editor, and carry explicit pauses and speed into playback and export.

**Architecture:** Chapters retain plain content for search and attribution and store ordered JSON blocks for structure and narration controls. Existing chapters derive blocks from their current text. The editor uses revision checks and the existing work gate; segment rebuilding preserves matching audio and remaps annotations and reading anchors.

**Tech Stack:** Flask, SQLite, existing enrichment and TTS engines, vanilla JavaScript, local Playwright.

**Spec:** User-approved design in the conversation, 2026-09-13.

## Global constraints
- Use reader/.venv for Python and local Playwright for rendered validation.
- Keep controls optional and collapsed; do not introduce unverified emotion controls.
- Complete bilingual documentation, minor version and verified GitHub release.

## Tasks
- [x] Preserve actual source headings and paragraphs in parsers; test EPUB, DOCX, PDF and TXT import.
- [x] Add blocks, revision and previous-state chapter columns plus segment structure metadata. Validate finite speed 0.5–2 and pauses 0–5000 ms, reject malformed/empty input and stale revisions.
- [x] Apply block structure to enrichment without changing spoken source text; retain unit indexes for speaker attribution. Test title narration, block boundaries and explicit zero pause.
- [x] Add editor GET/PUT/restore/preview endpoints under work coordination. Test reversible edits, annotation remapping, matching audio retention, bookmarks, conflict handling and cross-book access.
- [x] Add separate accessible editor with find/replace, block types, split/add/delete, collapsed narration controls and preview. Verify save/discard/restore on desktop and mobile, screenshot and console errors.
- [x] Update Hungarian docs and bilingual changelog; run full Python and Node suites, pip check and release checks. Publication follows the Auris release workflow; its result is reported in the final handoff.
