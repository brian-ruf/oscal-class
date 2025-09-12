#!/bin/bash
clear

# Function to determine the correct Python command
get_python_cmd() {
    # Check if python is Python 3.11
    if command -v python &>/dev/null; then
        PYTHON_VERSION=$(python --version 2>&1)
        if [[ $PYTHON_VERSION =~ Python\ 3\.([0-9]+) ]] && [ "${BASH_REMATCH[1]}" -ge "11" ]; then
            echo "python"
            return 0
        fi
    fi
    
    # Check if python3 is Python 3.11
    if command -v python3 &>/dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1)
        if [[ $PYTHON_VERSION =~ Python\ 3\.([0-9]+) ]] && [ "${BASH_REMATCH[1]}" -ge "11" ]; then
            echo "python3"
            return 0
        fi
    fi
    
    # Neither python nor python3 is 3.11+
    echo "none"
    return 1
}

# Get the correct Python command
PYTHON_CMD=$(get_python_cmd)
if [ "$PYTHON_CMD" == "none" ]; then
    echo "Error: Python 3.11 or 3.12 is required but not found."
    echo "Please install Python 3.11 or 3.12 and try again."
    exit 1
fi

echo "Using Python command: $PYTHON_CMD ($(${PYTHON_CMD} --version 2>&1))"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment"
    ${PYTHON_CMD} -m venv "venv"
else
    echo "Virtual environment already exists."
fi

echo "Activating virtual environment"
source venv/bin/activate

echo "Checking for PIP upgrade in virtual environment"
venv/bin/python -m pip install --upgrade pip

echo "Installing requirements.txt"
venv/bin/python -m pip install -r requirements.txt

echo ""
echo "Virtual environment setup complete!"
echo "To activate the environment in the future, run:"
echo "source venv/bin/activate"

