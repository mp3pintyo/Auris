"""Fine-tune OmniVoice on one speaker's recordings (full fine-tune). Run from the repository root.

reader/.venv/Scripts/python.exe scripts/voice_training/train_omnivoice.py \
    --data reader/data/voice_training/sajat --out reader/data/voice_training/runs/sajat-1

Built on upstream OmniVoice's own Apache-2.0 training pieces (sample processor,
padding collator, masked-token loss); the loop is a small single-GPU trainer
that runs on Windows without Accelerate, WebDataset shards or worker processes.

* Audio tokens (Higgs audio tokenizer, 8 codebooks at 25 Hz) and texts are
  cached in ``<out>/tokens.pt``; the text gets the same Hungarian
  normalization Auris applies before speaking.
* Full fine-tune with FP32 master weights and BF16 autocast, AdamW, cosine
  schedule, gradient checkpointing; ``--batch-tokens`` 4096 with 2
  accumulation steps is about 4 minutes of speech per update.
* ``--prompt-ratio 0`` (default) teaches the voice to speak without a
  reference; 0.3 keeps cloning from a reference closer to the base model.
* Validation loss on held-out clips uses fixed masks every epoch; the best
  epoch is saved as a self-contained model folder in ``<out>/best`` (BF16
  weights, tokenizer, and the base audio tokenizer as hard links) that
  Auris and scripts/benchmark_quality.py --model can load.

A validation loss is not a quality guarantee: compare the result with
scripts/benchmark_quality.py against zero-shot cloning before using it.
"""

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'reader'))

SAMPLE_RATE = 24000
LANGUAGE = 'hu'


def auto_epochs(train_hours: float) -> int:
    """More passes over less audio: 25 epochs for 14 h, about 66 for 2 h, at most 100."""
    return max(10, min(100, round(25 * math.sqrt(14 / max(train_hours, 1e-3)))))


def batches_by_tokens(samples: list[dict], batch_tokens: int, rng: random.Random) -> list[list[dict]]:
    """Length-grouped batches whose padded size stays within ``batch_tokens``."""
    order = list(samples)
    rng.shuffle(order)
    groups = [sorted(order[i:i + 64], key=lambda s: s['length']) for i in range(0, len(order), 64)]
    batches = []
    for group in groups:
        batch, longest = [], 0
        for sample in group:
            longest_next = max(longest, sample['length'])
            if batch and longest_next * (len(batch) + 1) > batch_tokens:
                batches.append(batch)
                batch, longest_next = [], sample['length']
            batch.append(sample)
            longest = longest_next
        if batch:
            batches.append(batch)
    rng.shuffle(batches)
    return batches


def file_key(path: str) -> str:
    stat = os.stat(path)
    return hashlib.sha256(f'{os.path.abspath(path)}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()[:20]


def encode_tokens(rows: list[dict], base: Path, cache_path: Path) -> dict:
    """Audio tokens and normalized text per clip, cached across runs of the same data."""
    import soundfile as sf
    import torch
    from transformers import AutoFeatureExtractor, HiggsAudioV2TokenizerModel
    from core.local_engines import resample
    from core.tts_engine import apply_text_normalization

    cache = torch.load(cache_path) if cache_path.is_file() else {}
    missing = [r for r in rows if cache.get(r['id'], {}).get('key') != file_key(r['audio'])]
    if missing:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        extractor = AutoFeatureExtractor.from_pretrained(str(base / 'audio_tokenizer'))
        tokenizer = HiggsAudioV2TokenizerModel.from_pretrained(str(base / 'audio_tokenizer'), device_map=device)
        for n, row in enumerate(missing):
            audio, sr = sf.read(row['audio'], dtype='float32', always_2d=True)
            audio = resample(audio.mean(axis=1), sr, SAMPLE_RATE)
            with torch.inference_mode():
                inputs = extractor(raw_audio=audio, sampling_rate=SAMPLE_RATE, return_tensors='pt').to(device)
                codes = tokenizer.encode(inputs['input_values']).audio_codes.squeeze(0)
            cache[row['id']] = {'key': file_key(row['audio']), 'tokens': codes.to(torch.int16).cpu(),
                                'text': apply_text_normalization(row['text'], LANGUAGE)}
            if (n + 1) % 50 == 0:
                print(f'tokenizálva {n + 1}/{len(missing)}', flush=True)
        del tokenizer
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        torch.save(cache, cache_path)
    return cache


def save_model(model, tokenizer, base: Path, folder: Path, info: dict) -> None:
    """Self-contained OmniVoice folder: BF16 weights, tokenizer, linked audio tokenizer."""
    import torch

    tmp = folder.with_name(folder.name + '.tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    state = {k: (v.detach().to(torch.bfloat16) if v.is_floating_point() else v.detach())
             for k, v in model.state_dict().items()}
    model.save_pretrained(str(tmp), state_dict=state, safe_serialization=True)
    tokenizer.save_pretrained(str(tmp))
    for name in ('chat_template.jinja',):
        if (base / name).is_file():
            shutil.copy2(base / name, tmp / name)
    source = base / 'audio_tokenizer'
    for path in source.rglob('*'):
        target = tmp / 'audio_tokenizer' / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, target)
        except OSError:
            shutil.copy2(path, target)
    (tmp / 'auris_training.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.rmtree(folder, ignore_errors=True)
    os.replace(tmp, folder)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data', type=Path, required=True, help='Folder with manifest.jsonl (prepare_dataset.py).')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--base', type=Path, default=None, help='Base OmniVoice folder.')
    p.add_argument('--epochs', type=int, default=0, help='0: from the amount of training audio.')
    p.add_argument('--max-steps', type=int, default=0, help='Stop after this many updates (smoke tests).')
    p.add_argument('--lr', type=float, default=2e-5)
    p.add_argument('--batch-tokens', type=int, default=4096)
    p.add_argument('--accum', type=int, default=2)
    p.add_argument('--prompt-ratio', type=float, default=0.0)
    p.add_argument('--patience', type=int, default=8, help='Epochs without a better validation loss.')
    p.add_argument('--no-grad-checkpointing', action='store_true')
    p.add_argument('--seed', type=int, default=1234)
    a = p.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    import torch
    from transformers import AutoTokenizer, get_cosine_schedule_with_warmup
    from omnivoice.data.collator import PaddingDataCollator
    from omnivoice.data.processor import OmniVoiceSampleProcessor
    from omnivoice.models.omnivoice import OmniVoice
    from core.paths import omnivoice_model

    base = (a.base or omnivoice_model()).resolve()
    rows = [json.loads(line) for line in (a.data / 'manifest.jsonl').read_text(encoding='utf-8').splitlines() if line]
    train_rows = [r for r in rows if r.get('split') != 'val']
    val_rows = [r for r in rows if r.get('split') == 'val']
    if not train_rows or not val_rows:
        sys.exit('A manifest tanító és validációs klipeket is igényel.')
    a.out.mkdir(parents=True, exist_ok=True)
    random.seed(a.seed)
    torch.manual_seed(a.seed)
    cache = encode_tokens(rows, base, a.out / 'tokens.pt')
    train_hours = sum(r['duration'] for r in train_rows) / 3600
    epochs = a.epochs or auto_epochs(train_hours)

    device = 'cuda'
    model = OmniVoice.from_pretrained(str(base), train=True, dtype=torch.float32, attn_implementation='sdpa').to(device)
    tokenizer = AutoTokenizer.from_pretrained(str(base))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if not a.no_grad_checkpointing:
        model.llm.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        model.llm.config.use_cache = False
    processor = OmniVoiceSampleProcessor(
        text_tokenizer=tokenizer, num_channels=8, audio_mask_id=1024,
        prompt_ratio_range=(0.0, a.prompt_ratio), mask_ratio_range=(0.0, 1.0), drop_cond_ratio=0.1,
        language_ratio=0.8, use_pinyin_ratio=0.0, instruct_ratio=0.0, only_instruct_ratio=0.0)
    collate = PaddingDataCollator(processor, a.batch_tokens)

    def processed(rows_):
        out = []
        for r in rows_:
            item = cache[r['id']]
            sample = processor({'label': {'text': item['text'], 'language_id': LANGUAGE},
                                'audio_tokens': item['tokens']})
            out.append(sample)
        return out

    # Validation: masks drawn once with a fixed seed, so epochs compare.
    state = random.getstate(), torch.get_rng_state()
    random.seed(0)
    torch.manual_seed(0)
    val_batches = [collate(b) for b in batches_by_tokens(processed(val_rows), a.batch_tokens, random.Random(0))]
    random.setstate(state[0])
    torch.set_rng_state(state[1])

    rng = random.Random(a.seed)
    steps_per_epoch = math.ceil(len(batches_by_tokens(processed(train_rows), a.batch_tokens, random.Random(0))) / a.accum)
    total_steps = steps_per_epoch * epochs
    if a.max_steps:
        total_steps = min(total_steps, a.max_steps)
    optimizer = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01, fused=True)
    scheduler = get_cosine_schedule_with_warmup(optimizer, max(1, int(0.03 * total_steps)), total_steps)

    def to_device(batch):
        return {k: v.to(device, non_blocking=True) for k, v in batch.items()}

    def validate() -> float:
        model.eval()
        losses = []
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            for batch in val_batches:
                losses.append(float(model(**to_device(batch)).loss))
        model.train()
        return sum(losses) / len(losses)

    info = {'base': str(base), 'data': str(a.data.resolve()), 'train_clips': len(train_rows),
            'val_clips': len(val_rows), 'train_minutes': round(train_hours * 60, 1), 'epochs': epochs,
            'total_steps': total_steps, 'lr': a.lr, 'batch_tokens': a.batch_tokens, 'accum': a.accum,
            'prompt_ratio': a.prompt_ratio, 'language': LANGUAGE}
    print(json.dumps(info, ensure_ascii=False), flush=True)
    log = open(a.out / 'metrics.jsonl', 'a', encoding='utf-8')
    base_loss = validate()
    print(f'alap validációs veszteség: {base_loss:.4f}', flush=True)
    log.write(json.dumps({'epoch': 0, 'val_loss': base_loss}) + '\n')
    best, stale, step, t0 = base_loss, 0, 0, time.time()
    torch.cuda.reset_peak_memory_stats()
    model.train()
    for epoch in range(1, epochs + 1):
        batches = batches_by_tokens(processed(train_rows), a.batch_tokens, rng)
        running = []
        for n, batch in enumerate(batches):
            with torch.autocast('cuda', dtype=torch.bfloat16):
                loss = model(**to_device(collate(batch))).loss
            if not torch.isfinite(loss):
                optimizer.zero_grad(set_to_none=True)
                continue
            (loss / a.accum).backward()
            running.append(float(loss.detach()))
            if (n + 1) % a.accum == 0 or n + 1 == len(batches):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                if a.max_steps and step >= a.max_steps:
                    break
        val = validate()
        peak = torch.cuda.max_memory_allocated() / 2**30
        row = {'epoch': epoch, 'step': step, 'train_loss': sum(running) / max(1, len(running)), 'val_loss': val,
               'lr': scheduler.get_last_lr()[0], 'peak_gb': round(peak, 2), 'minutes': round((time.time() - t0) / 60, 1)}
        log.write(json.dumps(row) + '\n')
        log.flush()
        print(json.dumps(row), flush=True)
        if val < best - 0.005:
            best, stale = val, 0
            save_model(model, tokenizer, base, a.out / 'best', {**info, 'epoch': epoch, 'step': step, 'val_loss': val,
                                                                 'base_val_loss': base_loss})
        else:
            stale += 1
        if (a.max_steps and step >= a.max_steps) or stale >= a.patience:
            break
    save_model(model, tokenizer, base, a.out / 'last', {**info, 'epoch': epoch, 'step': step, 'val_loss': val,
                                                        'base_val_loss': base_loss})
    log.close()
    print(f'Kész. Legjobb validációs veszteség {best:.4f} (alap {base_loss:.4f}); '
          f'modell: {(a.out / "best") if best < base_loss else "nem lett jobb az alapnál"}', flush=True)


if __name__ == '__main__':
    main()
