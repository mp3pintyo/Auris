"""Cut reference-clip candidates from a long voice recording. Run from the repository root.

reader/.venv/Scripts/python.exe scripts/reference_candidates.py \
    --audio voice.wav --text voice.txt --out reader/data/performance/candidates

The Hungarian Whisper times the words of the known transcript; every run of
whole sentences lasting 8-16 seconds is written as a mono 24 kHz WAV with its
exact text beside it (``.txt``), plus ``candidates.json``. Feed the WAVs to
scripts/benchmark_quality.py (with --target set to the full recording) to hear
which stretch clones the voice best.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reader'))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--audio', type=Path, required=True)
    p.add_argument('--text', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--min-seconds', type=float, default=8.0)
    p.add_argument('--max-seconds', type=float, default=16.0)
    p.add_argument('--target-seconds', type=float, default=12.0)
    p.add_argument('--limit', type=int, default=8, help='Keep the N candidates nearest the target length.')
    a = p.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    import soundfile as sf
    from core import qa, reference_candidates as rc
    from core.local_engines import resample

    text = a.text.read_text(encoding='utf-8').strip()
    audio, sr = sf.read(str(a.audio), dtype='float32', always_2d=True)
    audio = resample(audio.mean(axis=1), sr, 24000)
    words = qa.Transcriber.whisper_for('hu').transcribe(str(a.audio), 'hu', word_timestamps=True)['words']
    qa.Transcriber.unload_all()
    found = rc.candidates(audio, 24000, text, words, min_seconds=a.min_seconds,
                          max_seconds=a.max_seconds, target_seconds=a.target_seconds)[:a.limit]
    if not found:
        sys.exit('Nem találtam megfelelő hosszú, mondathatáron vágható szakaszt.')
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, cand in enumerate(sorted(found, key=lambda c: c.start), 1):
        stem = f'cand{n:02d}_{cand.start:05.1f}-{cand.end:05.1f}s'
        sf.write(str(a.out / f'{stem}.wav'), rc.cut(audio, 24000, cand), 24000, subtype='PCM_16')
        (a.out / f'{stem}.txt').write_text(cand.text, encoding='utf-8')
        rows.append(dict(file=f'{stem}.wav', start=round(cand.start, 2), end=round(cand.end, 2),
                         duration=round(cand.duration, 2), sentences=[cand.first_sentence, cand.last_sentence],
                         text=cand.text))
        print(f'{stem}  {cand.duration:4.1f}s  {cand.text[:70]}…', flush=True)
    (a.out / 'candidates.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
