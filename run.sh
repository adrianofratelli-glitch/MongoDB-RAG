#!/usr/bin/env bash
#
# Inicia a POC localmente:
#   - Backend  : API FastAPI  em http://localhost:8000
#   - Frontend : React + Vite em http://localhost:5180  (proxy /api -> :8000)
#
# Uso:  ./run.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Ambiente virtual Python (se existir)
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Dependências do frontend na primeira execução
if [ ! -d "frontend/node_modules" ]; then
  echo "› Instalando dependências do frontend (primeira vez)…"
  (cd frontend && npm install)
fi

# Sobe o backend em segundo plano
echo "› Backend  : http://localhost:8000"
uvicorn backend.api:app --port 8000 &
BACKEND_PID=$!

# Encerra o backend ao sair (Ctrl+C)
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Sobe o frontend em primeiro plano
echo "› Frontend : http://localhost:5180"
npm --prefix frontend run dev
