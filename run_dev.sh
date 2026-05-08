#!/usr/bin/env bash
cd "$(dirname "$0")"
# Uses .env for TOGETHER_API_KEY and MOCK_LLM; per-session Mock/Production is chosen on the home page.
PY=""
if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
fi
if [[ -n "$PY" ]]; then
  exec "$PY" -m uvicorn app.main:app --reload --reload-dir app --reload-dir templates --reload-dir static --reload-dir assets --host 127.0.0.1 --port 8000
fi
exec python3 -m uvicorn app.main:app --reload --reload-dir app --reload-dir templates --reload-dir static --reload-dir assets --host 127.0.0.1 --port 8000
