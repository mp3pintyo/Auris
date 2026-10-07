"""Build a voice-training dataset from your own recordings. Run from the repository root.

reader/.venv/Scripts/python.exe scripts/voice_training/prepare_dataset.py \
    --audio felvetel1.wav --audio felvetel2.wav --out reader/data/voice_training/sajat

Every recording is cut into clips of whole sentences (2-16 s, cut in the
pauses). With a ``.txt`` of the same name beside a recording (the text you
read aloud) the clips get that exact text; otherwise the Hungarian Whisper
transcribes the recording. Clips that are too fast or slow for their text,
too quiet, clipped, cut off at the file edge, or misread (the recognizer hears
something else than the given text) are dropped. Validation holds
out whole recordings when there are at least three, otherwise every tenth
clip. Output: ``clips/*.wav`` (mono 24 kHz), ``manifest.jsonl`` and
``report.json``.

Only record and train voices you have the right to use. The OmniVoice weights
are CC-BY-NC: a trained voice is for non-commercial use.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'reader'))

SAMPLE_RATE = 24000
MIN_WPS, MAX_WPS = 1.0, 5.5
MIN_PEAK_DBFS = -35.0
MAX_CLIPPED = 0.001
MAX_TEXT_CER = 0.15  # a misread sentence: what was heard differs from the given text


def clip_problem(audio, text: str) -> str | None:
    import numpy as np

    seconds = len(audio) / SAMPLE_RATE
    words = len(text.split())
    if not words or not MIN_WPS <= words / seconds <= MAX_WPS:
        return f'tempó {words / seconds:.1f} szó/s'
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if 20 * np.log10(peak + 1e-9) < MIN_PEAK_DBFS:
        return 'túl halk'
    if float(np.mean(np.abs(audio) >= 0.999)) > MAX_CLIPPED:
        return 'túlvezérelt'
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--audio', type=Path, action='append', required=True, help='Recording (repeatable).')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--max-seconds', type=float, default=16.0)
    p.add_argument('--min-seconds', type=float, default=2.0)
    a = p.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    import soundfile as sf
    from core import qa, reference_candidates as rc
    from core.local_engines import resample

    transcriber = qa.Transcriber.whisper_for('hu')
    clips_dir = a.out / 'clips'
    clips_dir.mkdir(parents=True, exist_ok=True)
    rows, dropped, sources = [], [], []
    for source_index, path in enumerate(a.audio):
        audio, sr = sf.read(str(path), dtype='float32', always_2d=True)
        audio = resample(audio.mean(axis=1), sr, SAMPLE_RATE)
        heard = transcriber.transcribe(str(path), 'hu', word_timestamps=True)
        sidecar = path.with_suffix('.txt')
        text = sidecar.read_text(encoding='utf-8').strip() if sidecar.is_file() else heard['text']
        parts = rc.partition(audio, SAMPLE_RATE, text, heard['words'],
                             max_seconds=a.max_seconds, min_seconds=a.min_seconds)
        kept = 0
        for n, part in enumerate(parts):
            piece = rc.cut(audio, SAMPLE_RATE, part)
            problem = clip_problem(piece, part.text)
            if not problem and sidecar.is_file():
                heard_here = ' '.join(w['word'] for w in heard['words']
                                      if w.get('start') is not None and part.start <= w['start'] < part.end)
                cer = qa.score_transcript(part.text, heard_here, 'hu')['cer']
                if cer > MAX_TEXT_CER:
                    problem = f'eltérő szöveg ({cer:.0%})'
            clip_id = f's{source_index + 1:02d}_{n + 1:04d}'
            if problem:
                dropped.append({'id': clip_id, 'reason': problem, 'text': part.text})
                continue
            out = clips_dir / f'{clip_id}.wav'
            sf.write(str(out), piece, SAMPLE_RATE, subtype='PCM_16')
            rows.append({'id': clip_id, 'audio': str(out.resolve()), 'text': part.text,
                         'duration': round(part.duration, 3), 'source': path.name,
                         'text_source': 'file' if sidecar.is_file() else 'whisper'})
            kept += 1
        seconds = len(audio) / SAMPLE_RATE
        sources.append({'file': path.name, 'seconds': round(seconds, 1), 'clips': kept,
                        'text_source': 'file' if sidecar.is_file() else 'whisper'})
        print(f'{path.name}: {seconds / 60:.1f} perc → {kept} klip', flush=True)
    qa.Transcriber.unload_all()
    if not rows:
        sys.exit('Egyetlen használható klip sem maradt.')
    if len(sources) >= 3:
        held_out = sources[-1]['file']
        for row in rows:
            row['split'] = 'val' if row['source'] == held_out else 'train'
    else:
        for n, row in enumerate(rows):
            row['split'] = 'val' if n % 10 == 9 else 'train'
        if len(rows) >= 2 and not any(r['split'] == 'val' for r in rows):
            rows[-1]['split'] = 'val'
    with open(a.out / 'manifest.jsonl', 'w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    train_seconds = sum(r['duration'] for r in rows if r['split'] == 'train')
    report = {'sources': sources, 'clips': len(rows), 'dropped': dropped,
              'train_minutes': round(train_seconds / 60, 1),
              'val_clips': sum(r['split'] == 'val' for r in rows)}
    (a.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Kész: {len(rows)} klip, tanító anyag {train_seconds / 60:.1f} perc, '
          f'{report["val_clips"]} validációs klip, {len(dropped)} elvetve.', flush=True)


if __name__ == '__main__':
    main()
