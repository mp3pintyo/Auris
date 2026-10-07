"""Hungarian voice-cloning quality benchmark for OmniVoice. Run from the repository root.

reader/.venv/Scripts/python.exe scripts/benchmark_quality.py --ref voice.wav \
    --output reader/data/performance/quality.json

Every reference voice renders the sentences of scripts/data/benchmark_hu.txt
with each decoding profile and several seeds (takes). The TTS model is then
released, and every take is measured:

* word and character errors heard by the Hungarian Whisper (core.qa),
* speaker similarity to the reference clip (core.speaker_similarity),
* render speed (RTF).

From the same takes the report also simulates take-selection policies
(one take, fewest errors of 3, most similar of N with K Whisper checks), so
their gain and cost can be judged before they are built into export.

A reference transcript is read from --ref-text or a .txt beside the WAV; when
missing, the Hungarian Whisper transcribes the reference once. No settings are
changed and the audio cache is bypassed; WAVs are kept beside the report.
"""

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reader'))

TEXTS_FILE = ROOT / 'scripts' / 'data' / 'benchmark_hu.txt'
SAMPLE_RATE = 24000

# name: (num_step, speed, OmniVoice sampling overrides)
PROFILES = {
    's16': (16, 1.0, {}),                                 # current Auris default
    's32': (32, 1.0, {}),                                 # upstream default, guidance 2.0
    's16_pt05': (16, 1.0, {'position_temperature': 0.5}),
    's32_pt05': (32, 1.0, {'position_temperature': 0.5}),
    's32_pt05_r110': (32, 1.10, {'position_temperature': 0.5}),
    's32_g15': (32, 1.0, {'guidance_scale': 1.5}),
    's32_g30': (32, 1.0, {'guidance_scale': 3.0}),
}


def load_texts(path: Path, limit: int | None) -> list[str]:
    lines = [line.strip() for line in path.read_text(encoding='utf-8').splitlines()]
    texts = [line for line in lines if line and not line.startswith('#')]
    return texts[:limit] if limit else texts


def pick_one(takes: list[dict]) -> dict:
    return takes[0]


def pick_fewest_errors(takes: list[dict], n: int = 3) -> tuple[dict, int, int]:
    """Render until Whisper hears no error, at most n takes; else fewest errors."""
    checked = []
    for take in takes[:n]:
        checked.append(take)
        if take['wer'] == 0:
            return take, len(checked), len(checked)
    best = min(checked, key=lambda t: (t['wer'], t['cer']))
    return best, len(checked), len(checked)


def pick_most_similar(takes: list[dict], n: int, checks: int) -> tuple[dict, int, int]:
    """Rank n takes by likeness, Whisper-check the top ones; first clean wins."""
    ranked = sorted(takes[:n], key=lambda t: -t['similarity'])
    checked = ranked[:max(1, checks)]
    for take in checked:
        if take['wer'] == 0:
            return take, n, len(checked)
    best = min(range(len(checked)), key=lambda i: (checked[i]['wer'], checked[i]['cer'], i))
    return checked[best], n, len(checked)


def policies(seeds: int) -> list[tuple[str, callable]]:
    out = [('1 take', lambda t: (pick_one(t), 1, 0))]
    if seeds >= 2:
        out.append((f'fewest errors of {min(3, seeds)}', lambda t: pick_fewest_errors(t, 3)))
    for n, k in ((5, 3), (10, 5)):
        if seeds >= n:
            out.append((f'most similar of {n} ({k} checks)',
                        lambda t, n=n, k=k: pick_most_similar(t, n, k)))
    return out


def summarize(cells: dict, seeds: int) -> list[dict]:
    """cells[(ref, profile)][text_index] -> list of take dicts ordered by seed."""
    rows = []
    for (ref, profile), per_text in cells.items():
        texts = [per_text[i] for i in sorted(per_text)]
        all_takes = [t for takes in texts for t in takes]
        spread = [statistics.pstdev(t['similarity'] for t in takes) for takes in texts if len(takes) > 1]
        gen = sum(t['gen_seconds'] for t in all_takes)
        audio = sum(t['audio_seconds'] for t in all_takes)
        for name, policy in policies(seeds):
            chosen = [policy(takes) for takes in texts]
            picks = [c[0] for c in chosen]
            rows.append(dict(
                ref=ref, profile=profile, policy=name, lines=len(picks),
                wer=statistics.mean(p['wer'] for p in picks),
                cer=statistics.mean(p['cer'] for p in picks),
                clean_lines=sum(p['wer'] == 0 for p in picks),
                similarity=statistics.mean(p['similarity'] for p in picks),
                min_similarity=min(p['similarity'] for p in picks),
                renders_per_line=statistics.mean(c[1] for c in chosen),
                checks_per_line=statistics.mean(c[2] for c in chosen),
                take_similarity_spread=statistics.mean(spread) if spread else None,
                rtf=gen / audio if audio else None,
            ))
    return rows


def markdown(report: dict) -> str:
    target = (f"célfelvétel: {Path(report['similarity_target']).name}" if report.get('similarity_target')
              else 'az adott referenciaklipre')
    out = ['# Auris magyar minőségmérés', '',
           f"Dátum: {report['started']} · GPU: {report.get('gpu') or 'n/a'} · "
           f"{report['lines']} mondat × {report['seeds']} seed", '']
    for ref in report['references']:
        out += [f"## {ref['name']}", '', f"Referencia-átirat ({ref['text_source']}): {ref['text']}", '',
                '| Profil | Take-választás | WER % | CER % | Hibátlan sor | Hasonlóság | Legrosszabb | '
                'Szórás (take) | Render/sor | Whisper/sor | RTF |',
                '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for r in report['summary']:
            if r['ref'] != ref['name']:
                continue
            spread = '' if r['take_similarity_spread'] is None else f"{r['take_similarity_spread']:.3f}"
            out.append(
                f"| {r['profile']} | {r['policy']} | {100 * r['wer']:.2f} | {100 * r['cer']:.2f} | "
                f"{r['clean_lines']}/{r['lines']} | {r['similarity']:.3f} | {r['min_similarity']:.3f} | "
                f"{spread} | {r['renders_per_line']:.1f} | {r['checks_per_line']:.1f} | "
                f"{r['rtf']:.3f} |")
        out.append('')
    out += ['A WER/CER a magyar Whisper hallása, nem emberi ítélet; a Whisper saját hibája is benne van. '
            f'A hasonlóság a CAM++ hangvektor koszinusza: {target}. Az RTF a generálás ideje '
            'osztva a hang hosszával (a take-választás ezt a render/sor értékkel szorozza).', '']
    return '\n'.join(out)


def finish(report: dict, output: Path) -> None:
    """Score every measured take, summarize, and write the JSON and Markdown reports."""
    from core import qa

    for row in report['takes']:
        if 'heard' in row:
            score = qa.score_transcript(report['texts'][row['index']], row['heard'], 'hu')
            row.update(wer=score['wer'], cer=score['cer'])
    cells: dict = {}
    for row in report['takes']:
        cells.setdefault((row['ref'], row['profile']), {}).setdefault(row['index'], []).append(row)
    for per_text in cells.values():
        for takes in per_text.values():
            takes.sort(key=lambda t: t['take'])
    report['summary'] = summarize(cells, report['seeds'])
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_suffix('.md').write_text(markdown(report), encoding='utf-8')
    print(markdown(report), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ref', type=Path, action='append', default=[],
                   help='Reference WAV (repeatable).')
    p.add_argument('--rescore', action='store_true',
                   help='Re-score an existing --output report from its saved transcripts.')
    p.add_argument('--ref-text', type=Path, action='append', default=[],
                   help='UTF-8 transcript for the --ref with the same position.')
    p.add_argument('--target', type=Path, default=None,
                   help='Measure likeness to this recording (e.g. the full voice sample) '
                        'instead of each reference clip, so different references compare fairly.')
    p.add_argument('--model', type=Path, default=None)
    p.add_argument('--profiles', nargs='+', default=['s16', 's32', 's32_pt05'],
                   choices=sorted(PROFILES))
    p.add_argument('--seeds', type=int, default=5, help='Takes per sentence and profile.')
    p.add_argument('--seed', type=int, default=1000)
    p.add_argument('--batch', type=int, default=8)
    p.add_argument('--texts', type=Path, default=TEXTS_FILE)
    p.add_argument('--limit', type=int, default=None, help='Use only the first N sentences.')
    a = p.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if a.rescore:
        finish(json.loads(a.output.read_text(encoding='utf-8')), a.output)
        return
    if not a.ref:
        p.error('At least one --ref is required.')
    if not 1 <= a.seeds <= 20 or not 1 <= a.batch <= 16:
        p.error('Use 1..20 seeds and batch 1..16.')
    if len(a.ref_text) > len(a.ref):
        p.error('More --ref-text than --ref.')

    import numpy as np
    import soundfile as sf
    import torch
    from core import qa, speaker_similarity
    from core.paths import omnivoice_model
    from core.tts_engine import TTSEngine

    texts = load_texts(a.texts, a.limit)
    out_dir = a.output.with_suffix('')
    out_dir.mkdir(parents=True, exist_ok=True)
    report = dict(started=time.strftime('%Y-%m-%d %H:%M'), platform=platform.platform(),
                  gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                  lines=len(texts), seeds=a.seeds, base_seed=a.seed, texts=texts,
                  profiles={name: dict(num_step=PROFILES[name][0], speed=PROFILES[name][1],
                                       sampling=PROFILES[name][2]) for name in a.profiles},
                  speaker_model=speaker_similarity.MODEL_FILE, references=[], takes=[], summary=[])

    def save():
        a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    # 1. Reference transcripts: given, sidecar, or Hungarian Whisper.
    transcriber = qa.Transcriber.whisper_for('hu')
    for i, ref in enumerate(a.ref):
        if not ref.is_file():
            p.error(f'Missing reference: {ref}')
        sidecar = a.ref_text[i] if i < len(a.ref_text) else ref.with_suffix('.txt')
        if sidecar.is_file():
            text, source = sidecar.read_text(encoding='utf-8').strip(), 'fájl'
        else:
            text, source = transcriber.transcribe(str(ref), 'hu')['text'], 'Whisper'
        name = f'{i + 1}-{ref.stem[:24]}'
        report['references'].append(dict(name=name, path=str(ref.resolve()), text=text, text_source=source))
    qa.Transcriber.unload_all()
    save()

    # 2. Render every reference × profile × seed.
    engine = TTSEngine(str((a.model or omnivoice_model()).resolve()))
    engine.load_sync()
    try:
        for ref in report['references']:
            for profile in a.profiles:
                num_step, speed, sampling = PROFILES[profile]
                for take in range(a.seeds):
                    folder = out_dir / ref['name'] / profile / f'take{take}'
                    folder.mkdir(parents=True, exist_ok=True)
                    torch.manual_seed(a.seed + take)
                    for start in range(0, len(texts), a.batch):
                        chunk = texts[start:start + a.batch]
                        if torch.cuda.is_available():
                            torch.cuda.synchronize()
                        t = time.perf_counter()
                        audio = engine._synthesize_batch(
                            chunk, ref_audio=ref['path'], ref_text=ref['text'],
                            speeds=[speed] * len(chunk), num_step=num_step, language='hu',
                            normalize_text=True, sampling=sampling)
                        if torch.cuda.is_available():
                            torch.cuda.synchronize()
                        elapsed = time.perf_counter() - t
                        total = sum(len(x) for x in audio) / SAMPLE_RATE
                        for j, x in enumerate(audio):
                            index = start + j
                            path = folder / f'{index:03d}.wav'
                            sf.write(str(path), np.asarray(x, dtype=np.float32), SAMPLE_RATE)
                            seconds = len(x) / SAMPLE_RATE
                            report['takes'].append(dict(
                                ref=ref['name'], profile=profile, take=take, index=index,
                                path=str(path), audio_seconds=seconds,
                                gen_seconds=elapsed * seconds / total if total else 0.0))
                    print(json.dumps(dict(ref=ref['name'], profile=profile, take=take)), flush=True)
                    save()
    finally:
        engine.unload()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # 3. Measure: Whisper errors and likeness to the reference clip.
    embedder = speaker_similarity.get_embedder()
    if a.target:
        shared = embedder.embed_file(a.target)
        report['similarity_target'] = str(a.target.resolve())
    targets = {r['name']: shared if a.target else embedder.embed_file(r['path'])
               for r in report['references']}
    for n, row in enumerate(report['takes']):
        row.update(heard=transcriber.transcribe(row['path'], 'hu')['text'],
                   similarity=round(speaker_similarity.similarity(
                       embedder.embed_file(row['path']), targets[row['ref']]), 4))
        if n % 50 == 0:
            print(f'measured {n + 1}/{len(report["takes"])}', flush=True)
            save()
    qa.Transcriber.unload_all()
    finish(report, a.output)


if __name__ == '__main__':
    main()
