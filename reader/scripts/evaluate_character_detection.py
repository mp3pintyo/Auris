"""Run the configured local LLM character detector without importing a book.

Example (from the repository root):
  reader\.venv\Scripts\python.exe reader\scripts\evaluate_character_detection.py \
      test_docs\Rejto_Jeno-14-karatos-auto.pdf --output reader\data\llm_eval_hu.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

READER_DIR = Path(__file__).resolve().parents[1]
if str(READER_DIR) not in sys.path:
    sys.path.insert(0, str(READER_DIR))

from core import llm_characters, settings  # noqa: E402
from core.parser import pdf_parser, txt_parser, epub_parser  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    parsers = {
        ".pdf": pdf_parser.parse,
        ".txt": txt_parser.parse,
        ".epub": epub_parser.parse,
    }
    parse = parsers.get(args.document.suffix.lower())
    if parse is None:
        parser.error("Only PDF, TXT and EPUB are supported.")

    config = settings.load()
    data = parse(args.document)
    chapters = []
    for index, chapter in enumerate(data["chapters"], start=1):
        item = dict(chapter)
        item["id"] = index
        chapters.append(item)

    started = time.time()

    def progress(current: int, total: int, label: str):
        print(f"{args.document.name}: {current}/{total} {label}", flush=True)

    result = llm_characters.analyze_book(
        title=data["title"],
        author=data["author"],
        chapters=chapters,
        base_url=config.get("llm_base_url", ""),
        api_key=config.get("llm_api_key", ""),
        model=config.get("llm_model", ""),
        timeout=float(config.get("llm_timeout_sec", 600)),
        max_tokens=int(config.get("llm_max_output_tokens", 8192)),
        max_characters=int(config.get("llm_max_characters", 60)),
        batch_chars=int(config.get("llm_batch_chars", 10000)),
        progress=progress,
    )
    output = {
        "document": str(args.document),
        "title": data["title"],
        "author": data["author"],
        "language": data.get("language"),
        "model": config.get("llm_model"),
        "elapsed_seconds": round(time.time() - started, 2),
        **result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
    print(
        f"done: {len(result['characters'])} characters, "
        f"{len(result['annotations'])} dialogues, "
        f"{output['elapsed_seconds']}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
