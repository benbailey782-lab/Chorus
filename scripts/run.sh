#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q -r requirements.txt

if [ ! -d frontend/node_modules ]; then
    (cd frontend && npm install)
fi

(cd frontend && npm run dev -- --host 0.0.0.0) &
FRONTEND_PID=$!

uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload &
BACKEND_PID=$!

sleep 2
if command -v open >/dev/null; then
    open "http://localhost:5173"
elif command -v xdg-open >/dev/null; then
    xdg-open "http://localhost:5173"
fi

trap 'kill $FRONTEND_PID $BACKEND_PID 2>/dev/null || true' EXIT INT TERM
wait
