#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_FOR_VENV=""
# Prefer 3.12 / 3.11 / 3.13 before 3.14 so PyTorch + sentence-transformers wheels exist.
for candidate in python3.12 python3.11 python3.13 python3.14 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_FOR_VENV="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_FOR_VENV" ]]; then
  echo "No Python interpreter found. Please install Python 3.11+."
  exit 1
fi

PYTHON_VERSION="$("$PYTHON_FOR_VENV" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if "$PYTHON_FOR_VENV" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null; then
  echo "Note: Python 3.14+ often lacks PyTorch wheels. For question-analysis embeddings install 3.12 and run:" >&2
  echo "  chmod +x scripts/recreate_venv.sh && ./scripts/recreate_venv.sh" >&2
fi
if ! "$PYTHON_FOR_VENV" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Detected Python $PYTHON_VERSION at $(command -v "$PYTHON_FOR_VENV")."
  echo "RGEE requires Python 3.11 or newer."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  echo "Creating virtual environment in .venv ..."
  "$PYTHON_FOR_VENV" -m venv .venv
fi

PYTHON_BIN=".venv/bin/python"
PIP_BIN=".venv/bin/pip"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Virtual environment python was not found at $PYTHON_BIN"
  exit 1
fi

if [[ ! -f ".venv/.deps_installed" ]]; then
  echo "Installing project dependencies ..."
  "$PIP_BIN" install -r requirements.txt
  touch .venv/.deps_installed
fi

if ! "$PYTHON_BIN" -m uvicorn --version >/dev/null 2>&1; then
  echo "uvicorn is missing in .venv, reinstalling dependencies ..."
  "$PIP_BIN" install -r requirements.txt
  touch .venv/.deps_installed
fi

PORT=8000
IN_USE_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"
if [[ -n "$IN_USE_PIDS" ]]; then
  echo "Port $PORT is already in use. Stopping existing process(es): $IN_USE_PIDS"
  kill $IN_USE_PIDS || true
  sleep 1
fi

echo "Starting RGEE at http://127.0.0.1:8000"
exec "$PYTHON_BIN" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
