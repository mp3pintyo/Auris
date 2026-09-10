"""Real, cache-free OmniVoice benchmark. Run from the repository root.

reader/.venv/Scripts/python.exe scripts/benchmark_tts.py --output reader/data/performance/run.json
Optional: --ref-audio reference.wav --ref-text reference.txt (UTF-8 transcript).
No user settings are saved; generated WAVs live beside the report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reader'))

TEXTS = [
    'A reggeli napfény lassan betöltötte a szobát. Az asztalon egy nyitott könyv feküdt.',
    'Az utazó megállt a kapuban, és csendben körülnézett. A kertből madárdal hallatszott.',
    'Amikor a vonat elindult, Eszter még egyszer visszanézett az állomásra. '
    'A peronon álló emberek lassan eltűntek a kanyar mögött, és az ablak előtt '
    'feltűntek a folyópart magas fái. Elővette a jegyzetfüzetét, hogy leírja mindazt, '
    'amit ezen a különös reggelen látott.',
    'A könyvtáros gondosan visszatette a régi kötetet a polcra. A történet azonban '
    'tovább foglalkoztatta: vajon miért maradt üresen az utolsó oldal? '
    'Odakint esni kezdett, a cseppek egyenletesen kopogtak az ablakpárkányon. '
    'Úgy döntött, másnap újra megkeresi a levelet.',
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', type=Path, default=ROOT / 'model_backup/OmniVoice')
    p.add_argument('--modes', nargs='+', default=['off', 'eager', 'cuda_graph'])
    p.add_argument('--batches', nargs='+', type=int, default=[1, 4])
    p.add_argument('--repeats', type=int, default=5)
    p.add_argument('--steps', type=int, default=16)
    p.add_argument('--seed', type=int, default=123)
    p.add_argument('--cudnn-benchmark', action=argparse.BooleanOptionalAction, default=None,
                   help='Override convolution autotuning for controlled A/B measurements.')
    p.add_argument('--ref-audio', type=Path)
    p.add_argument('--ref-text', type=Path)
    a = p.parse_args()
    if a.repeats < 2 or not 1 <= a.steps <= 100 or any(b not in range(1, 5) for b in a.batches):
        p.error('Use repeats >=2, steps 1..100 and batches 1..4.')
    if bool(a.ref_audio) != bool(a.ref_text):
        p.error('Supply both --ref-audio and --ref-text.')

    import numpy as np
    import soundfile as sf
    import torch
    from core import settings
    from core.tts_accel import ACCEL_MODES, probe_accel
    from core.tts_engine import TTSEngine

    if any(m not in ACCEL_MODES for m in a.modes):
        p.error('Unknown acceleration mode.')
    probe = probe_accel()
    def sync():
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        elif probe.get('backend') == 'mps':
            torch.mps.synchronize()

    a.output.parent.mkdir(parents=True, exist_ok=True)
    wave_dir = a.output.with_suffix('')
    wave_dir.mkdir(parents=True, exist_ok=True)
    report = dict(platform=platform.platform(), python=sys.version,
                  probe=probe, steps=a.steps, seed=a.seed, texts=TEXTS,
                  voice_mode='clone' if a.ref_audio else 'design',
                  cache_bypassed=True, runs=[], summaries=[])
    def save():
        a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    ref_text = a.ref_text.read_text(encoding='utf-8').strip() if a.ref_text else None
    original_get = settings.get
    for mode in a.modes:
        engine = TTSEngine(str(a.model.resolve()))
        try:
            with patch.object(settings, 'get', side_effect=lambda k, d=None:
                              mode if k == 'tts_accel' else original_get(k, d)):
                t = time.perf_counter()
                engine.load_sync()
                if a.cudnn_benchmark is not None:
                    torch.backends.cudnn.benchmark = a.cudnn_benchmark
                sync()
                load_seconds = time.perf_counter() - t
            for batch in a.batches:
                # First invocation of each shape is kept, but excluded from
                # warm statistics. All timings include codec decode to CPU.
                for rep in range(a.repeats + 1):
                    torch.manual_seed(a.seed)
                    sync()
                    if torch.cuda.is_available():
                        torch.cuda.reset_peak_memory_stats()
                    t = time.perf_counter()
                    audio = engine._synthesize_batch(
                        TEXTS[:batch], instruct=None if a.ref_audio else 'male, moderate pitch',
                        ref_audio=str(a.ref_audio.resolve()) if a.ref_audio else None,
                        ref_text=ref_text, num_step=a.steps, language='hu', normalize_text=False,
                    )
                    sync()
                    elapsed = time.perf_counter() - t
                    valid = all(x.ndim == 1 and x.size and np.isfinite(x).all()
                                and np.max(np.abs(x)) > 1e-5 for x in audio)
                    if not valid:
                        raise RuntimeError('Invalid, empty, non-finite or silent audio')
                    seconds = sum(len(x) / 24000 for x in audio)
                    row = dict(mode=mode, batch=batch, repetition=rep, warm=rep > 0,
                               cudnn_benchmark=torch.backends.cudnn.benchmark,
                               seconds=elapsed, audio_seconds=seconds, rtf=elapsed/seconds,
                               load_seconds=load_seconds, status=engine.status(),
                               peak_allocated_gb=torch.cuda.max_memory_allocated()/2**30
                               if torch.cuda.is_available() else None,
                               reserved_gb=torch.cuda.memory_reserved()/2**30
                               if torch.cuda.is_available() else None,
                               hashes=[hashlib.sha256(x.tobytes()).hexdigest() for x in audio])
                    report['runs'].append(row)
                    if rep == 1:
                        for i, x in enumerate(audio):
                            sf.write(str(wave_dir / f'{mode}-b{batch}-{i}.wav'), x, 24000)
                    print(json.dumps({k: row[k] for k in ('mode','batch','repetition','seconds','rtf')}), flush=True)
                    save()
                warm = [r for r in report['runs'] if r['mode'] == mode and r['batch'] == batch and r['warm']]
                report['summaries'].append(dict(
                    mode=mode, batch=batch,
                    median_seconds=statistics.median(r['seconds'] for r in warm),
                    median_rtf=statistics.median(r['rtf'] for r in warm),
                    min_seconds=min(r['seconds'] for r in warm),
                    max_seconds=max(r['seconds'] for r in warm),
                ))
                save()
        except Exception as exc:
            report.setdefault('errors', []).append(dict(mode=mode, error=str(exc)))
            save()
            raise
        finally:
            engine.unload()
    print(json.dumps(report['summaries'], indent=2), flush=True)


if __name__ == '__main__':
    main()
