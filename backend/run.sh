#!/bin/bash
# Start Flax Assistant backend — auto-restarts on crash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt -q
else
  source venv/bin/activate
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  Add your GEMINI_API_KEY to backend/.env"
fi

echo "✦ Starting Flax Assistant backend on port 8747..."

# Auto-restart loop
while true; do
  uvicorn main:app --host 0.0.0.0 --port 8747 --reload
  echo "Backend crashed — restarting in 3s..."
  sleep 3
done
