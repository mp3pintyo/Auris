@echo off
:: Auris - Windows launcher
:: The TTS model loads in the background; the app opens immediately.
:: Model must be present at: ..\model_backup\OmniVoice\

cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

echo Starting OmniReader...
echo Open your browser at: http://127.0.0.1:7860
echo.
echo Model status will appear in the top-right corner of the app.
echo (Model loads in the background; you can browse and read while it loads.)
echo.
echo Press Ctrl+C to stop.

"%PYTHON%" app.py
