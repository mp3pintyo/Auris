#!/usr/bin/env bash
# Auris - Linux / macOS setup wrapper
# Usage: bash setup.sh

set -e
cd "$(dirname "$0")"

PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "Python not found. Please install Python 3.10+ first."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtual environment in .venv..."
    "$PYTHON" -m venv .venv
fi

".venv/bin/python" setup.py
