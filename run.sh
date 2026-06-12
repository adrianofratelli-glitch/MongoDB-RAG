#!/usr/bin/env bash
#
# Inicia a POC localmente:
#   - Backend  : API FastAPI  em http://localhost:8180
#   - Frontend : React + Vite em http://localhost:5180  (proxy /api -> :8180)
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

# Falha cedo, com diagnóstico, se as portas dedicadas já estiverem ocupadas
for port in 8180 5180; do
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
  if [ -n "$pid" ]; then
    echo "✗ Porta $port já está em uso pelo processo $pid:"
    ps -p "$pid" -o command= | cut -c1-100
    echo "  Para liberar:  kill $pid    (depois rode ./run.sh de novo)"
    exit 1
  fi
done

# Dependências do frontend na primeira execução
if [ ! -d "frontend/node_modules" ]; then
  echo "› Instalando dependências do frontend (primeira vez)…"
  (cd frontend && npm install)
fi

# Sobe o backend em segundo plano
echo "› Backend  : http://localhost:8180"
uvicorn backend.api:app --port 8180 &
BACKEND_PID=$!

# Encerra o backend ao sair (Ctrl+C)
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Sobe o frontend em primeiro plano
echo "› Frontend : http://localhost:5180"
npm --prefix frontend run dev
