#!/usr/bin/env bash
#
# Start the POC locally:
#   - Backend  : FastAPI    at http://localhost:8180
#   - Frontend : React+Vite at http://localhost:5180  (proxies /api -> :8180)
#
# Usage:  ./run.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Activate the Python virtual environment, if present
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Fail fast, with diagnostics, if a dedicated port is already in use
for port in 8180 5180; do
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
  if [ -n "$pid" ]; then
    echo "Port $port is already in use by process $pid:"
    ps -p "$pid" -o command= | cut -c1-100
    echo "  To free it:  kill $pid    (then run ./run.sh again)"
    exit 1
  fi
done

# Install frontend dependencies on first run
if [ ! -d "frontend/node_modules" ]; then
  echo "Installing frontend dependencies (first run)..."
  (cd frontend && npm install)
fi

# Start the backend in the background
echo "Backend  : http://localhost:8180"
uvicorn backend.api:app --port 8180 &
BACKEND_PID=$!

# Stop the backend on exit (Ctrl+C)
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Start the frontend in the foreground
echo "Frontend : http://localhost:5180"
npm --prefix frontend run dev
