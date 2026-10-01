@echo off
:: Auris - Windows setup wrapper
:: Usage: double-click or run from Command Prompt
::
:: The virtual environment is created with uv when it is available (for
:: example through mise), otherwise with a system Python 3.10+.
:: AURIS_PYTHON selects the Python version uv uses (default: 3.11).

cd /d "%~dp0"

if not defined AURIS_PYTHON set "AURIS_PYTHON=3.11"

if exist ".venv\Scripts\python.exe" goto :venv_ready

:: Probe by running each tool: a mise shim exists on PATH even when the
:: tool is not active, so `where` alone is not enough.
set "UV="
uv --version >nul 2>&1
if not errorlevel 1 set "UV=uv"
if not defined UV (
    mise exec uv -- uv --version >nul 2>&1
    if not errorlevel 1 set "UV=mise exec uv -- uv"
)

if defined UV (
    echo Creating virtual environment in .venv with uv ^(Python %AURIS_PYTHON%^)...
    call %UV% venv --seed --python %AURIS_PYTHON% .venv
    if errorlevel 1 (
        echo Failed to create virtual environment with uv.
        pause
        exit /b 1
    )
    goto :venv_ready
)

set "BOOTSTRAP="
python --version >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP=python"
if not defined BOOTSTRAP (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP=py -3"
)

if not defined BOOTSTRAP (
    echo Neither uv nor Python was found.
    echo Install uv ^(https://docs.astral.sh/uv/^) or Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo Creating virtual environment in .venv...
call %BOOTSTRAP% -m venv .venv
if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
)

:venv_ready
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo Adding pip to the virtual environment...
    ".venv\Scripts\python.exe" -m ensurepip --upgrade
    if errorlevel 1 (
        echo Failed to install pip into .venv.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" setup.py
if errorlevel 1 (
    echo.
    echo Setup failed. See output above for details.
    pause
    exit /b 1
)

pause
