#!/bin/bash
# Start both backend and desktop app for development

echo "✦ Starting Flax Assistant..."

# Start backend in background
cd "$(dirname "$0")/backend"
if [ ! -d "venv" ]; then
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt -q
else
  source venv/bin/activate
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  Created .env — add your GEMINI_API_KEY before the AI features work"
fi

uvicorn main:app --host 0.0.0.0 --port 8747 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..10}; do
  if curl -s http://127.0.0.1:8747/health > /dev/null 2>&1; then
    echo "Backend ready ✓"
    break
  fi
  sleep 1
done

# Start desktop app
cd "$(dirname "$0")/desktop"
npm run dev &
DESKTOP_PID=$!
echo "Desktop PID: $DESKTOP_PID"

echo ""
echo "✦ Flax Assistant running"
echo "  Backend: http://127.0.0.1:8747"
echo "  Desktop: dev mode (Electron)"
echo ""
echo "Press Ctrl+C to stop both"

# Wait and cleanup
trap "kill $BACKEND_PID $DESKTOP_PID 2>/dev/null; echo 'Stopped.'" INT TERM
wait
