#!/bin/bash
# Main function: prepare the project environment and start the FastAPI server.

# Stop immediately if setup or server startup fails.
set -e

# Always run from the project root so relative configuration paths stay stable.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
APP_PORT="${APP_PORT:-8000}"

if ! [[ "$APP_PORT" =~ ^[0-9]{1,5}$ ]] || (( APP_PORT < 1 || APP_PORT > 65535 )); then
    echo "Invalid APP_PORT '$APP_PORT'. Choose a port between 1 and 65535."
    exit 2
fi

echo "=========================================================="
echo "    ENCHANTED INK — AI-Powered Infinite Whiteboard        "
echo "=========================================================="
echo "Directory: $PROJECT_DIR"

# Create the application's virtual environment only on a fresh checkout.
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
fi

# Launch the API and static whiteboard UI.
set +e
./venv/bin/python - "$APP_PORT" >/dev/null <<'PY'
import json
import socket
import sys
from urllib.request import urlopen

port = int(sys.argv[1])
try:
    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
        pass
except OSError:
    sys.exit(1)

try:
    with urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=1) as response:
        title = json.load(response).get("info", {}).get("title")
    if title == "Enchanted Ink — AI Whiteboard API":
        print("running")
        sys.exit(0)
except Exception:
    pass

print("busy")
sys.exit(2)
PY
PORT_CHECK=$?
set -e

if [ "$PORT_CHECK" -eq 0 ]; then
    echo "Enchanted Ink is already running at http://localhost:$APP_PORT."
    exit 0
elif [ "$PORT_CHECK" -eq 2 ]; then
    echo "Port $APP_PORT is already in use by another service."
    echo "Stop that service or start Enchanted Ink on another port with APP_PORT=8001 ./run_prototype.sh."
    exit 1
fi

echo "Starting FastAPI server on http://localhost:$APP_PORT..."
echo "Press Ctrl+C to stop."
echo "=========================================================="

./venv/bin/python backend/app.py
