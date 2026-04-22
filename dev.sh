#!/usr/bin/env bash
# Convenience launcher: starts the FastAPI backend and the Vite dev server
# side-by-side. `Ctrl-C` terminates both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() {
  echo ""
  echo "── shutting down ──"
  if [[ -n "${UV_PID:-}" ]]; then kill "$UV_PID" 2>/dev/null || true; fi
  if [[ -n "${VITE_PID:-}" ]]; then kill "$VITE_PID" 2>/dev/null || true; fi
}
trap cleanup INT TERM EXIT

export PATH="$HOME/.local/bin:$PATH"

# Warm a staged demo fixture if none exists (first-boot friendly).
if [[ ! -d /tmp/muchlinski-demo ]]; then
  echo "── staging primary demo fixture ──"
  "$ROOT/demo/primary/stage.sh" > /dev/null
fi

echo "── starting FastAPI on :8080 ──"
# Invoke uvicorn via `python -m` so we always use the project's interpreter
# (Python 3.11 from .venv). A bare `uv run uvicorn` can hit a different
# `uvicorn` on PATH (e.g. system Python 3.14's) that lacks our deps.
(cd "$ROOT" && uv run python -m uvicorn server.main:app --host 127.0.0.1 --port 8080 --reload) &
UV_PID=$!

sleep 2

echo "── starting Vite on :5173 ──"
(cd "$ROOT/web" && npm run dev) &
VITE_PID=$!

echo ""
echo "──────────────────────────────────────────"
echo "  Backend:  http://127.0.0.1:8080"
echo "  Frontend: http://127.0.0.1:5173"
echo "  Press Ctrl-C to stop both."
echo "──────────────────────────────────────────"
echo ""

wait
