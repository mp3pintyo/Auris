"""Reference audition: which stretch of a recording clones the voice best.

Different stretches of the same speaker clone differently, and neither length
nor pitch predicts which one wins (own measurement: the best of 5 takes per
sentence reached 0.871-0.897 likeness depending on the stretch). So each
candidate clip is tried: it reads a few fixed Hungarian test sentences (two
takes each), and every render is scored against the whole recording, the
speaker's own voice, with CAM++ likeness and the Hungarian Whisper. The most
similar candidate within a word-error guard of the most accurate one is
recommended.
"""

from __future__ import annotations

import logging
import os
import statistics
import tempfile

log = logging.getLogger(__name__)

TEST_SENTENCES = (
    "A reggeli napfény lassan betöltötte a csendes szobát, az asztalon nyitott könyv feküdt.",
    "– Hová mész ilyen későn? – kérdezte az anyja a konyhából, de választ már nem kapott.",
    "A vonat pontosan negyed kilenckor indult, és a peronon álló emberek lassan eltűntek a kanyar mögött.",
    "Különös, fémes csörömpölés hallatszott a pincéből, aztán minden elcsendesedett.",
)
TAKES = (0, 1)
WER_GUARD = 0.05
MAX_CANDIDATES = 6


def audition(engine, source_path: str, candidates: list[dict], language: str | None = "hu",
             *, embedder=None, transcriber=None, takes: tuple[int, ...] = TAKES) -> dict:
    """Render the test sentences with every candidate and rank them.

    ``candidates`` are ``{"start", "end", "text"}`` stretches of ``source_path``.
    Returns ``{"results": [...per candidate...], "recommended": index}``.
    """
    from core import qa, reference_audio, speaker_similarity

    if not candidates:
        raise ValueError("Nincs meghallgatható szakasz.")
    candidates = candidates[:MAX_CANDIDATES]
    language = (language or "hu").lower()[:2]
    embedder = embedder or speaker_similarity.get_embedder()
    transcriber = transcriber or qa.Transcriber.whisper_for(language)
    target = embedder.embed_file(source_path)
    rendered: list[str] = []
    with tempfile.TemporaryDirectory(prefix="auris-audition-") as workdir:
        clips, items, owners = [], [], []
        for index, cand in enumerate(candidates):
            clip = os.path.join(workdir, f"jelolt{index + 1}.wav")
            reference_audio.cut_reference(source_path, clip, float(cand["start"]), float(cand["end"]))
            clips.append((clip, cand["text"]))
            for sentence_index, sentence in enumerate(TEST_SENTENCES):
                for take in takes:
                    items.append({"text": sentence, "instruct": None, "ref_audio": clip,
                                  "ref_text": cand["text"], "speed": 1.0, "language": language,
                                  "take": take})
                    owners.append((index, sentence_index))
        try:
            results = engine.generate_many(items)
            rendered = [r["audio_path"] for r in results]
            scores: dict[int, list[tuple[float, float]]] = {}
            for (index, sentence_index), result in zip(owners, results):
                heard = transcriber.transcribe(result["audio_path"], language)["text"]
                wer = qa.score_transcript(TEST_SENTENCES[sentence_index], heard, language)["wer"]
                likeness = speaker_similarity.similarity(embedder.embed_file(result["audio_path"]), target)
                scores.setdefault(index, []).append((likeness, wer))
        finally:
            for path in rendered:
                try:
                    os.remove(path)
                except OSError:
                    pass
            invalidate = getattr(engine, "invalidate_voice_prompt", None)
            for clip, text in clips:
                if invalidate is not None:
                    try:
                        invalidate(clip, text)
                    except Exception:
                        pass
    rows = []
    for index, cand in enumerate(candidates):
        values = scores.get(index, [])
        rows.append({
            "index": index, "start": cand["start"], "end": cand["end"], "text": cand["text"],
            "similarity": round(statistics.mean(v[0] for v in values), 4) if values else 0.0,
            "wer": round(statistics.mean(v[1] for v in values), 4) if values else 1.0,
            "renders": len(values),
        })
    best_wer = min(r["wer"] for r in rows)
    eligible = [r for r in rows if r["wer"] <= best_wer + WER_GUARD]
    recommended = max(eligible, key=lambda r: (r["similarity"], -r["wer"]))["index"]
    for row in rows:
        row["recommended"] = row["index"] == recommended
    log.info("Reference audition: %s", [(r["index"], r["similarity"], r["wer"]) for r in rows])
    return {"results": rows, "recommended": recommended,
            "sentences": len(TEST_SENTENCES), "takes": len(takes)}
