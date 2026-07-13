@echo off
:: Auris - Windows setup wrapper
:: Usage: double-click or run from Command Prompt

cd /d "%~dp0"

set "BOOTSTRAP="
where python >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP=python"
if not defined BOOTSTRAP (
    where py >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP=py -3"
)

if not defined BOOTSTRAP (
    echo Python not found. Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv...
    call %BOOTSTRAP% -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
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
