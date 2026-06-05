#!/bin/bash
# Set up the local virtual environment and install the package in editable mode.
# Safe to run more than once — skips venv creation if .venv already exists.
# Can be sourced interactively or executed as a subprocess by run_unit_tests.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in tests/.venv..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment."
        exit 1
    fi
fi

source "${SCRIPT_DIR}/.venv/bin/activate"

cd "${SCRIPT_DIR}/.."
pip install -e ".[dev]"
cd "$SCRIPT_DIR"
