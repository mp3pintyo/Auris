@echo off
REM Optional GPU acceleration extras for Auris on Windows.
REM CUDA Graph (main speedup) needs NO extra packages — enabled via Settings.
REM This script tries community Triton wheels for Hybrid mode (NVIDIA only).

cd /d "%~dp0"

echo.
echo === Auris optional Triton acceleration (Windows) ===
echo CUDA Graph works without this. Triton is extra and may fail on some setups.
echo.

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: The Auris virtual environment is missing: reader\.venv
  echo Run reader\setup.bat first.
  goto :end
)
set "PYTHON=.venv\Scripts\python.exe"

"%PYTHON%" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'hip', torch.version.hip)" || (
  echo ERROR: PyTorch is not installed in reader\.venv. Run reader\setup.bat first.
  goto :end
)

"%PYTHON%" -c "import sys, torch; sys.exit(0 if torch.version.cuda and torch.cuda.is_available() else 1)" || (
  echo.
  echo Triton kernels need an NVIDIA CUDA GPU; nothing to install here.
  echo AMD ROCm and CPU builds use the standard mode in Settings.
  goto :end
)

echo.
echo [1/3] Trying triton-windows (community build)...
"%PYTHON%" -m pip install -U "triton-windows" || (
  echo WARNING: triton-windows install failed. CUDA Graph mode still works.
  echo See: https://github.com/woct0rdho/triton-windows
  goto :end
)

echo.
echo [2/3] Installing omnivoice-triton (may pull Linux-only triton; --no-deps if needed)...
"%PYTHON%" -m pip install "omnivoice-triton" || (
  echo Retrying with --no-deps ...
  "%PYTHON%" -m pip install "omnivoice-triton" --no-deps
  "%PYTHON%" -m pip install soundfile numpy huggingface-hub
)

echo.
echo [3/3] Probe
"%PYTHON%" -c "from core.tts_accel import probe_accel; import json; print(json.dumps(probe_accel(), indent=2))"

echo.
echo Done. In Auris Settings set GPU acceleration to Auto or Hybrid, then Reload TTS model.
:end
pause
