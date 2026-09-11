"""Compare previous array assembly with current M4B export's Python allocation peak.

Run from reader: .venv/Scripts/python.exe scripts/benchmark_m4b_memory.py --minutes 10
Uses synthetic audio and temporary files, never a personal book or TTS model.
The current measurement includes encoding; this is a memory comparison, not a
like-for-like speed benchmark. FFmpeg's separate process memory is excluded.
"""
import argparse
import json
import sys
import tempfile
import tracemalloc
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from core import exporter


def measure(operation):
    tracemalloc.start()
    operation()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return round(peak / 1024**2, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.minutes <= 60:
        parser.error('minutes must be 1–60')
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'tone.wav'
        sf.write(source, .05 * np.sin(2 * np.pi * 220 * np.arange(24000) / 24000), 24000)
        segments = [{'audio_path': str(source), 'duration_sec': 1, 'text': 'Test.'} for _ in range(args.minutes * 60)]
        # This is the old M4B path: merge a chapter, then concatenate chapters.
        old_peak = measure(lambda: np.concatenate([exporter._merge_wavs(segments)]))
        with patch.object(exporter, 'EXPORTS_DIR', directory):
            new_peak = measure(lambda: exporter.export_m4b('Memory benchmark',
                [{'chapter_title': 'Test', 'segments': segments}], mastering=False))
        print(json.dumps({'spoken_minutes': args.minutes, 'includes_segment_pauses': True,
                          'previous_assembly_peak_MiB': old_peak,
                          'current_export_peak_MiB': new_peak,
                          'metric': 'tracemalloc; FFmpeg subprocess excluded'}))


if __name__ == '__main__':
    main()
