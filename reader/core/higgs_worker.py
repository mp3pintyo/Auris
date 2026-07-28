"""Persistent Higgs inference worker.

This process intentionally runs with a private Transformers package path.
OmniVoice is pinned to Transformers 5.3, while the Higgs community adapter
requires 5.5 or newer; keeping them in separate processes prevents module and
model-class conflicts when users switch engines.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback


PREFIX = "AURIS_HIGGS_JSON:"
_REPLY_LOCK = threading.Lock()
_PROTOCOL_STDOUT = sys.stdout


def reply(payload: dict) -> None:
    with _REPLY_LOCK:
        # ASCII-only JSON keeps the protocol safe even if a redirected Windows
        # stream is recreated with a legacy locale encoding.
        print(
            PREFIX + json.dumps(payload, ensure_ascii=True),
            file=_PROTOCOL_STDOUT,
            flush=True,
        )


def audio_array(output):
    import numpy as np

    if hasattr(output, "detach"):
        output = output.detach().float().cpu().numpy()
    audio = np.asarray(output, dtype=np.float32).squeeze()
    if audio.ndim > 1:
        audio = audio.mean(axis=0)
    if audio.ndim != 1:
        raise RuntimeError(f"Unexpected Higgs output shape: {audio.shape}")
    return audio


def reference_array(output):
    import numpy as np

    audio = np.asarray(output, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if audio.ndim != 1:
        raise RuntimeError(f"Unexpected Higgs reference shape: {audio.shape}")
    return audio


def main() -> None:
    # Parent Popen writes UTF-8. Windows redirected stdio otherwise inherits a
    # locale encoding (often cp1250), corrupting Hungarian prompts before they
    # reach the tokenizer.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # Reserve the original stdout pipe for framed RPC replies. Libraries such
    # as Transformers/tqdm may use carriage-return progress rendering, which
    # can otherwise become interleaved with a JSON response on Windows.
    sys.stdout = sys.stderr
    import soundfile as sf
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    major, minor = (int(part) for part in transformers.__version__.split(".")[:2])
    if (major, minor) < (5, 5):
        raise RuntimeError(
            f"Higgs needs Transformers >=5.5, worker loaded {transformers.__version__}"
        )

    init = json.loads(sys.stdin.readline())
    source = init["source"]
    local_only = bool(init.get("local_only"))
    model_seed = int(init.get("model_seed", 123))
    common = {"trust_remote_code": True, "local_files_only": local_only}
    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.bfloat16
    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        # Apple Silicon (Metal). float32 by default: bfloat16 audibly clips
        # sentence onsets on MPS (verified on M-series hardware).
        # Set AURIS_MPS_DTYPE=bf16 to trade quality for speed.
        device = "mps"
        dtype = (
            torch.bfloat16
            if os.environ.get("AURIS_MPS_DTYPE", "").lower() in {"bf16", "bfloat16"}
            else torch.float32
        )
    else:
        device = "cpu"
        dtype = torch.float32
    # The adapter reports audio_head.weight as missing and initializes it while
    # from_pretrained() constructs the model. Set a stable initialization seed
    # before loading so repeated worker starts remain reproducible.
    torch.manual_seed(model_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(model_seed)
    tokenizer = AutoTokenizer.from_pretrained(source, **common)
    model = AutoModelForCausalLM.from_pretrained(
        source, dtype=dtype, **common
    ).eval()
    if device != "cpu":
        model = model.to(device)
    # Keep the same loading sequence as source/higgs-tts-3-4b/app.py. The
    # Transformers loader applies the model's own weight-tying rules, so an
    # additional generic tie_weights() call is not needed.
    audio_embedding = getattr(getattr(model, "audio_embedding", None), "weight", None)
    audio_head = getattr(getattr(model, "audio_head", None), "weight", None)
    audio_head_shared = bool(
        audio_embedding is not None
        and audio_head is not None
        and audio_embedding.shape == audio_head.shape
        and audio_embedding.data_ptr() == audio_head.data_ptr()
    )
    head_probe = (
        audio_head.detach().reshape(-1)[:8].float().cpu().tolist()
        if audio_head is not None
        else []
    )
    embedding_probe = (
        audio_embedding.detach().reshape(-1)[:8].float().cpu().tolist()
        if audio_embedding is not None
        else []
    )
    if not callable(getattr(model, "generate_speech", None)):
        raise RuntimeError("Selected model has no generate_speech() method")
    sample_rate = int(getattr(model.config, "sample_rate", 24000))
    reply(
        {
            "ok": True,
            "event": "ready",
            "source": source,
            "device": device,
            "dtype": str(dtype),
            "sample_rate": sample_rate,
            "transformers": transformers.__version__,
            "audio_head_shared": audio_head_shared,
            "audio_head_probe": head_probe,
            "audio_embedding_probe": embedding_probe,
            "model_seed": model_seed,
        }
    )

    for line in sys.stdin:
        try:
            request = json.loads(line)
            command = request.get("command")
            if command == "shutdown":
                reply({"ok": True, "event": "shutdown"})
                return
            if command != "generate":
                raise ValueError("Unknown worker command")

            seed = int(request.get("seed", -1))
            if seed >= 0:
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)

            kwargs = dict(request["generation"])
            ref_path = request.get("reference_audio")
            if ref_path:
                audio, sr = sf.read(ref_path, always_2d=False)
                kwargs.update(
                    {
                        "reference_audio": torch.from_numpy(reference_array(audio)),
                        "reference_sample_rate": int(sr),
                        "reference_text": request.get("reference_text") or None,
                    }
                )
            # Match the known-good direct_speech() path. Cancellation is handled
            # by terminating this isolated process from the parent.
            output = model.generate_speech(
                request["prompt"], tokenizer, **kwargs
            )
            audio = audio_array(output)
            sf.write(request["output_path"], audio, sample_rate)
            reply(
                {
                    "ok": True,
                    "event": "generated",
                    "output_path": request["output_path"],
                    "samples": len(audio),
                    "sample_rate": sample_rate,
                }
            )
        except Exception as exc:
            reply(
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        reply(
            {
                "ok": False,
                "event": "startup_error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
