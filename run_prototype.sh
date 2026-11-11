#!/bin/bash
# Enchanted Ink — Prototype Startup Script

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================================="
echo "    ENCHANTED INK — AI-Powered Infinite Whiteboard        "
echo "=========================================================="
echo "Directory: $PROJECT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install openpyxl pandas fastapi uvicorn pydantic requests python-multipart pillow
fi

echo "Starting FastAPI server on http://localhost:8000..."
echo "Press Ctrl+C to stop."
echo "=========================================================="

./venv/bin/python backend/app.py
