#!/usr/bin/env bash
# Start RGEE_Analysis_Agent (FastAPI + Uvicorn on port 8010 by default).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="$ROOT_DIR/RGEE_Analysis_Agent"
cd "$AGENT_DIR"

PYTHON_FOR_VENV=""
for candidate in python3.12 python3.11 python3.13 python3.14 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_FOR_VENV="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_FOR_VENV" ]]; then
  echo "No Python interpreter found. Install Python 3.11+."
  exit 1
fi
if ! "$PYTHON_FOR_VENV" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "RGEE_Analysis_Agent requires Python 3.11 or newer."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  echo "Creating RGEE_Analysis_Agent .venv ..."
  "$PYTHON_FOR_VENV" -m venv .venv
fi
PYTHON_BIN=".venv/bin/python"
PIP_BIN=".venv/bin/pip"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing $PYTHON_BIN"
  exit 1
fi

NEED_INSTALL=0
if [[ ! -f ".venv/.deps_installed" ]]; then
  NEED_INSTALL=1
elif [[ "requirements.txt" -nt ".venv/.deps_installed" ]]; then
  echo "requirements.txt is newer than last install; reinstalling ..."
  NEED_INSTALL=1
fi

if [[ "$NEED_INSTALL" -eq 1 ]]; then
  echo "Installing RGEE_Analysis_Agent dependencies (includes PyTorch stack when not using mock analysis) ..."
  "$PIP_BIN" install -r requirements.txt
  touch .venv/.deps_installed
fi

if ! "$PYTHON_BIN" -m uvicorn --version >/dev/null 2>&1; then
  echo "uvicorn missing; reinstalling dependencies ..."
  "$PIP_BIN" install -r requirements.txt
  touch .venv/.deps_installed
fi

if ! "$PYTHON_BIN" -c "import fastapi" 2>/dev/null; then
  echo "fastapi import failed; reinstalling dependencies ..."
  "$PIP_BIN" install -r requirements.txt
  touch .venv/.deps_installed
fi

HOST="${RGEE_ANALYSIS_AGENT_HOST:-127.0.0.1}"
PORT="${RGEE_ANALYSIS_AGENT_PORT:-8010}"
IN_USE_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$IN_USE_PIDS" ]]; then
  echo "Port $PORT in use; stopping: $IN_USE_PIDS"
  kill $IN_USE_PIDS 2>/dev/null || true
  sleep 1
fi

echo "Starting RGEE_Analysis_Agent at http://${HOST}:${PORT}"
echo "In the main app .env, set RGEE_ANALYSIS_AGENT_URL=http://127.0.0.1:${PORT} (or this host) to delegate instructor question analysis."

exec "$PYTHON_BIN" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
