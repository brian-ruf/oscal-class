#!/bin/bash
clear

export DEBUG=False

if [ -d "venv" ]; then
    echo "Virtual environment found."
else
    echo "Virtual environment not found. Installing ..."
    bash install_venv.sh
fi

echo "Running application"
source venv/bin/activate
python word-to-OSCAL.py
