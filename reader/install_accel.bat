@echo off
REM Optional GPU acceleration extras for Auris on Windows.
REM CUDA Graph (main speedup) needs NO extra packages — enabled via Settings.
REM This script tries community Triton wheels for Hybrid mode.

echo.
echo === Auris optional Triton acceleration (Windows) ===
echo CUDA Graph works without this. Triton is extra and may fail on some setups.
echo.

python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" || (
  echo ERROR: Activate the same Python env you use for Auris first.
  exit /b 1
)

echo.
echo [1/3] Trying triton-windows (community build)...
python -m pip install -U "triton-windows" || (
  echo WARNING: triton-windows install failed. CUDA Graph mode still works.
  echo See: https://github.com/woct0rdho/triton-windows
  goto :end
)

echo.
echo [2/3] Installing omnivoice-triton (may pull Linux-only triton; --no-deps if needed)...
python -m pip install "omnivoice-triton" || (
  echo Retrying with --no-deps ...
  python -m pip install "omnivoice-triton" --no-deps
  python -m pip install soundfile numpy huggingface-hub
)

echo.
echo [3/3] Probe
python -c "from core.tts_accel import probe_accel; import json; print(json.dumps(probe_accel(), indent=2))"

echo.
echo Done. In Auris Settings set GPU acceleration to Auto or Hybrid, then Reload TTS model.
:end
pause
