#!/bin/bash
# Run unit tests from the tests/ directory.
# Ensures a virtual environment is active before running pytest.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

clear

if [ -z "$VIRTUAL_ENV" ]; then
    if [ ! -d ".venv" ]; then
        echo "No virtual environment found. Running local_venv.sh to set it up..."
        source "${SCRIPT_DIR}/local_venv.sh"
        if [ $? -ne 0 ]; then
            echo "ERROR: local_venv.sh failed. Cannot run tests."
            exit 1
        fi
    fi

    echo "Activating virtual environment..."
    source "${SCRIPT_DIR}/.venv/bin/activate"

    if [ -z "$VIRTUAL_ENV" ]; then
        echo "ERROR: Failed to activate virtual environment."
        exit 1
    fi
fi

echo "Using: $(python --version) at $(which python)"
python -m pytest unit/ -v
