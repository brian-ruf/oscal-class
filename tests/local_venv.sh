#!/bin/bash
# Set up the local virtual environment and install the package in editable mode.
# Safe to run more than once — skips venv creation if .venv already exists.
# Source this file to activate the current shell. If executed directly, it will
# install dependencies and, in an interactive terminal, hand you a new shell
# with the virtual environment active.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SOURCED=0
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    SOURCED=1
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in tests/.venv..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment."
        exit 1
    fi
fi

source "${SCRIPT_DIR}/.venv/bin/activate"

if [ "${VIRTUAL_ENV:-}" != "${SCRIPT_DIR}/.venv" ]; then
    echo "ERROR: Virtual environment activation failed."
    exit 1
fi

if [ "$(command -v pip)" != "${SCRIPT_DIR}/.venv/bin/pip" ]; then
    echo "ERROR: pip is not resolving from the virtual environment."
    exit 1
fi

unset VIRTUAL_ENV_DISABLE_PROMPT

cd "${SCRIPT_DIR}/.."
"${SCRIPT_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${SCRIPT_DIR}/.venv/bin/python" -m pip install -e ".[dev]"
cd "$SCRIPT_DIR"

if [ "$SOURCED" -eq 0 ]; then
    if [ -t 0 ] && [ -t 1 ]; then
        echo "Starting a shell with the virtual environment active..."
        exec "${SHELL:-/bin/bash}" --rcfile <(
            if [ -f "$HOME/.bashrc" ]; then
                printf 'source "%s"\n' "$HOME/.bashrc"
            fi
            printf 'source "%s"\n' "${SCRIPT_DIR}/.venv/bin/activate"
        ) -i
    fi

    echo "NOTE: local_venv.sh was executed, so the activated environment cannot persist in the parent shell."
    echo "Use: source ${SCRIPT_DIR}/local_venv.sh"
fi

