# Auris 3.3.0 validation

Checked on Windows on 2026-09-11 using `reader/.venv`.

- Full Python suite: 320 tests, successful, one skipped.
- Node playback/voice tests: 13 passed.
- `pip check`: no broken requirements.
- Local Chrome/Playwright: book metadata edit/persistence, import options,
  Hungarian OCR preview, precise resume after reload, scheduled backup creation
  and download, mobile layout, documentation IDs and table-of-contents links.
  Screenshots inspected; no browser console errors.
- Real FFmpeg/ffprobe: chapter titles and timing, Hungarian metadata including
  series index, publisher/date/language, cover art, mastering and subtitle timing.
- Real Tesseract 5.4.0 with official `tessdata_best/hun.traineddata`: Hungarian
  accented image text and a mixed PDF with a scanned page and native text.
- Calibre adapter: subprocess contract, real generated-EPUB parsing, original
  source hash, temporary cleanup and missing-tool errors tested. A real Calibre
  conversion was not run on this machine; Calibre remains an optional external
  prerequisite.

Memory comparison:

```powershell
cd reader
.venv/Scripts/python.exe scripts/benchmark_m4b_memory.py --minutes 10
```

Ten minutes of synthetic audio plus inter-sentence pauses: previous array
assembly peaked at **296.66 MiB**, current export at **0.59 MiB** in `tracemalloc`.
This measures Python/NumPy allocations, not total system memory; the external
FFmpeg process is excluded. The current path includes encoding, whereas the
baseline measures the old array assembly. These numbers are not a speed or TTS
quality benchmark.

No personal library was modified by browser tests; they used an isolated fixture
database and synthetic audio. Optional imports do not bundle or automatically
download Tesseract, its language data, or Calibre.
