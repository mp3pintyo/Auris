# Auris 3.4.0 — structured text and optional editor verification

## Automated checks

- Full Python suite: 347 tests, one skipped, successful (30.725 seconds).
- Existing reader/voice studio Node suite: 13 passed.
- Final pause Node checks: explicit pause, zero/default completion and stale timer cancellation passed.
- JavaScript syntax, pip dependency consistency and release metadata checks passed.
- New regressions cover real EPUB/DOCX inputs, TOC-only titles, repeated text with different heading styles, PDF page continuations, validation, atomic edits, revision conflicts, speaker/bookmark/progress remapping, audio reuse, restoration and legacy backups.

## Local browser verification

Used local Playwright with installed Chrome and a Flask server on port 7877. The fixture database and settings were isolated in `C:/Temp/auris-text-qa`.

- Desktop 1440px and mobile 390px: real GET/PUT/restore, rendered headings and paragraph boundaries, collapsed advanced controls, dirty-close protection and zero-pause persistence passed.
- Mocked UI checks additionally covered unsupported Higgs raw speed controls, retained disabled values, annotation review notice and preview size limits.
- Documentation anchors resolve uniquely; documentation and reading views have no horizontal document overflow.
- Browser console and page-error lists were empty. Opening/editing did not generate speech automatically.
- Screenshots inspected for desktop/mobile editor, reader and documentation.

## Real audio verification

- RTX 3090 / OmniVoice preview with heading, 0.9 speed and 1200 ms pause: 2.79 seconds total, nonzero speech waveform and exactly silent final 1200 ms.
- Real four-block chapter export to WAV + SRT, including heading and subheading: successful durable export, 16.53 seconds total, matching the segment durations plus structural pauses. The requested final 1250 ms is silent even after audio mastering.
- Fixture text restored after edits. The temporary server is stopped at handoff.

## Limits documented in the product

Previously discarded source formatting requires reimport or manual correction. PDF/OCR structure remains heuristic. Higgs raw mode ignores speed controls; its editor speed input is disabled. No new per-block emotion controls or LLM auto-editing are claimed. Generated audio previews use the narrator voice.
