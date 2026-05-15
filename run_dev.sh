#!/usr/bin/env bash
# Quick dev server: requires an existing .venv (use scripts/launch_project.sh for full setup).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export MOCK_LLM="${MOCK_LLM:-1}"

if [[ ! -x .venv/bin/python ]]; then
  echo "No .venv found. Run first:"
  echo "  chmod +x scripts/launch_project.sh && ./scripts/launch_project.sh"
  exit 1
fi

if ! .venv/bin/python -m uvicorn --version >/dev/null 2>&1; then
  echo "uvicorn missing; installing requirements.txt into .venv ..."
  .venv/bin/pip install -r requirements.txt
fi

if [[ ! -f .env ]] && [[ -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit as needed)."
fi

PORT="${PORT:-8000}"
IN_USE_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$IN_USE_PIDS" ]]; then
  echo "Port $PORT in use; stopping: $IN_USE_PIDS"
  kill $IN_USE_PIDS 2>/dev/null || true
  sleep 1
fi

echo "Starting RGEE (dev) at http://127.0.0.1:${PORT} · MOCK_LLM=${MOCK_LLM}"
if [[ -n "${RGEE_ANALYSIS_AGENT_URL:-}" ]]; then
  echo "Question analysis will call RGEE_Analysis_Agent at ${RGEE_ANALYSIS_AGENT_URL}"
fi

exec .venv/bin/python -m uvicorn app.main:app \
  --reload --reload-dir app --reload-dir templates --reload-dir static --reload-dir assets \
  --host 127.0.0.1 --port "$PORT"
