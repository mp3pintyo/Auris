"""Best-of-N takes for export: render several versions, keep the best one.

Measured on Hungarian OmniVoice cloning (40 sentences, RTX 3090;
docs/superpowers/specs/2026-10-07-indextts2-premium-atvetel.md):

* one take: 2.7 % word errors, 31/40 lines without an error;
* the most similar of 10 takes with 5 Whisper checks: 0.16 % word errors,
  39/40 clean lines, likeness to the voice 0.855 -> 0.877 and the weakest
  line 0.766 -> 0.827.

Rule ("most similar, no word errors"): rank the takes by speaker similarity
to the voice's reference clip, let Whisper check the most similar ones in
order, and keep the first one heard without a word error; when none is clean,
keep the checked take with the fewest errors (ties: the more similar one).
Without a reference to compare against (a voice designed from a description
without an anchor clip) the rule falls back to "fewest errors": takes are
checked in render order and the first clean one wins.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Export modes offered in the export dialog: (takes rendered, Whisper checks).
TAKE_MODES = {
    "normal": None,
    "similar5": (5, 3),
    "similar10": (10, 5),
}
SELECTION_CHUNK = 32  # segments rendered, judged and cleaned up together


@dataclass
class Choice:
    take: dict
    checks: int
    reason: str


def most_similar_clean(takes: list[dict], checks: int) -> Choice:
    """``takes`` carry ``similarity`` and a ``judge()`` returning (wer, cer)."""
    ranked = sorted(takes, key=lambda t: -t["similarity"])
    checked = []
    for take in ranked[:max(1, checks)]:
        take["wer"], take["cer"] = take["judge"]()
        checked.append(take)
        if take["wer"] == 0:
            return Choice(take, len(checked), "similar-clean")
    best = min(range(len(checked)), key=lambda i: (checked[i]["wer"], checked[i]["cer"], i))
    return Choice(checked[best], len(checked), "similar-fewest-errors")


def fewest_errors(takes: list[dict], checks: int) -> Choice:
    checked = []
    for take in takes[:max(1, checks)]:
        take["wer"], take["cer"] = take["judge"]()
        checked.append(take)
        if take["wer"] == 0:
            return Choice(take, len(checked), "first-clean")
    best = min(range(len(checked)), key=lambda i: (checked[i]["wer"], checked[i]["cer"], i))
    return Choice(checked[best], len(checked), "fewest-errors")


def policy_name(mode: str) -> str | None:
    spec = TAKE_MODES.get(mode)
    return f"similar:{spec[0]}:{spec[1]}" if spec else None


# ── Export integration ──────────────────────────────────────────────────────

def _segment_voices(application, book_id: int) -> tuple[dict, str | None, str | None, str | None]:
    from core.database import get_conn

    with get_conn() as conn:
        book = conn.execute('SELECT language FROM books WHERE id=?', (book_id,)).fetchone()
        chars = {r['name']: dict(r) for r in conn.execute(
            'SELECT * FROM characters WHERE book_id=?', (book_id,)).fetchall()}
    narrator_ref, narrator_text = application._book_narrator_reference(book_id)
    language = book['language'] if book and book['language'] else None
    return chars, narrator_ref, narrator_text, language


def _voice_for(seg: dict, chars: dict, narrator_ref, narrator_text) -> tuple[str | None, str | None]:
    char = chars.get(seg['character_name']) if seg.get('character_name') else None
    if char:
        ref = char.get('ref_audio_path') or None
        return ref, ((char.get('ref_text') or None) if ref else None)
    return narrator_ref, narrator_text


def _similarity_target(engine, item: dict) -> str | None:
    """The clip a take should sound like: the reference, or a design anchor."""
    if item.get('ref_audio'):
        return item['ref_audio']
    resolve = getattr(engine, '_resolve_voice', None)
    if resolve is None:
        return None
    try:
        _, anchor, _ = resolve(item.get('instruct'), None, None, item.get('language'))
    except Exception as exc:
        log.warning('Voice anchor unavailable for take selection: %s', exc)
        return None
    return anchor if anchor and os.path.exists(anchor) else None


def select_export_takes(application, book_id: int, segs: list[dict], job: dict | None,
                        mode: str, export_pool=None) -> int:
    """Replace each segment's audio with its best of N takes; returns how many changed.

    Runs after the normal export pass, so take 0 is the audio already made.
    Segments chosen under the same mode earlier are skipped; losing takes
    (take 0 included) are deleted unless a segment still uses the file.
    """
    from core import qa, settings, speaker_similarity
    from core.database import get_conn
    from core.local_engines import ENGINE_INFO

    spec = TAKE_MODES.get(mode)
    engine = application.tts
    engine_name = getattr(engine, 'engine_name', 'omnivoice')
    if not spec or not ENGINE_INFO.get(engine_name, {}).get('takes'):
        return 0
    count, checks = spec
    policy = policy_name(mode)
    todo = [s for s in segs if s.get('id') and s.get('enriched_text') and s.get('audio_path')
            and os.path.exists(s['audio_path']) and s.get('take_policy') != policy]
    if not todo:
        return 0
    chars, narrator_ref, narrator_text, language = _segment_voices(application, book_id)
    embedder = speaker_similarity.get_embedder()
    transcriber = qa.Transcriber.whisper_for(language or 'hu')
    targets: dict[str, object] = {}
    if job is not None:
        job['total'] = int(job.get('total') or 0) + len(todo)
    changed = 0
    try:
        for start in range(0, len(todo), SELECTION_CHUNK):
            chunk = todo[start:start + SELECTION_CHUNK]
            application._check_job_cancelled(job)
            if job is not None:
                job['message'] = (f'Take-ek készítése ({start + 1}–{start + len(chunk)}/{len(todo)}, '
                                  f'szegmensenként {count})…')
            items, owners = [], []
            for n, seg in enumerate(chunk):
                ref, ref_text = _voice_for(seg, chars, narrator_ref, narrator_text)
                base = {'text': seg['enriched_text'], 'instruct': seg.get('instruct'), 'ref_audio': ref,
                        'ref_text': ref_text, 'speed': seg.get('speed') or 1.0, 'language': language}
                seg['_take_item'] = base
                for take in range(1, count):
                    items.append({**base, 'take': take})
                    owners.append((n, take))
            num_step = None
            try:
                from core.tts_engine import _tts_num_step_from_settings
                num_step = _tts_num_step_from_settings()
            except Exception:
                pass
            renders: dict[tuple[int, int], dict] = {}

            def on_item(i, result):
                renders[owners[i]] = result
                application._check_job_cancelled(job, throttle=True)

            runner = export_pool if export_pool is not None else engine
            runner.generate_many(items, num_step=num_step, on_item=on_item)
            application._check_job_cancelled(job)
            if job is not None:
                job['message'] = f'A legjobb take kiválasztása ({start + 1}–{start + len(chunk)}/{len(todo)})…'
            updates, losers = [], set()
            for n, seg in enumerate(chunk):
                item = seg.pop('_take_item')
                takes = [{'take': 0, 'audio_path': seg['audio_path'], 'cache_key': seg.get('cache_key'),
                          'duration_sec': seg.get('duration_sec')}]
                takes += [{'take': t, **renders[(n, t)]} for t in range(1, count) if (n, t) in renders]
                for take in takes:
                    take['judge'] = (lambda path=take['audio_path'], text=seg['enriched_text']: _judge(
                        transcriber, path, text, language))
                target_path = _similarity_target(engine, item)
                if target_path:
                    if target_path not in targets:
                        targets[target_path] = embedder.embed_file(target_path)
                    for take in takes:
                        take['similarity'] = speaker_similarity.similarity(
                            embedder.embed_file(take['audio_path']), targets[target_path])
                    choice = most_similar_clean(takes, checks)
                else:
                    choice = fewest_errors(takes, checks)
                best = choice.take
                losers.update(take['audio_path'] for take in takes if take is not best)
                seg.update(audio_path=best['audio_path'], duration_sec=best['duration_sec'],
                           cache_key=best['cache_key'], take_policy=policy)
                updates.append((best['audio_path'], best['duration_sec'], best['cache_key'], policy, seg['id']))
                changed += best['take'] != 0
                application._bump_export_progress(job, 1, synthesized=True)
            with get_conn() as conn:
                conn.executemany('UPDATE tts_segments SET audio_path=?, duration_sec=?, cache_key=?, '
                                 'take_policy=? WHERE id=?', updates)
                used = {row[0] for row in conn.execute(
                    'SELECT audio_path FROM tts_segments WHERE audio_path IS NOT NULL')}
            for path in losers - used:
                try:
                    os.remove(path)
                except OSError:
                    pass
    finally:
        for seg in segs:
            seg.pop('_take_item', None)
        if not settings.get('asr_keep_loaded', False):
            qa.Transcriber.unload_all()
    log.info('Take selection (%s): %d segments, %d replaced', policy, len(todo), changed)
    return changed


def _judge(transcriber, path: str, text: str, language: str | None) -> tuple[float, float]:
    from core.qa import score_transcript

    heard = transcriber.transcribe(path, language or 'hu')['text']
    score = score_transcript(text, heard, language or 'hu')
    return score['wer'], score['cer']
