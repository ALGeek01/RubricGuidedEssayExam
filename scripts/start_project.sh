#!/usr/bin/env bash
# Start the full RGEE stack: RGEE_Analysis_Agent (8010) then main app (8000).
# First run may install both venvs; the agent is started in the background and polled until ready.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

AGENT_HOST="${RGEE_ANALYSIS_AGENT_HOST:-127.0.0.1}"
AGENT_PORT="${RGEE_ANALYSIS_AGENT_PORT:-8010}"
MAIN_PORT="${PORT:-8000}"
AGENT_URL="http://${AGENT_HOST}:${AGENT_PORT}"
LOG_DIR="${RGEE_RUN_LOG_DIR:-$ROOT_DIR/.rgee-run}"
AGENT_LOG="$LOG_DIR/analysis-agent.log"
AGENT_PID=""

mkdir -p "$LOG_DIR"
chmod +x scripts/launch_project.sh scripts/launch_analysis_agent.sh run_dev.sh 2>/dev/null || true

free_port() {
  local port="$1" label="$2"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Port $port ($label) in use; stopping: $pids"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

ensure_env() {
  if [[ ! -f .env ]] && [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example"
  fi
  if [[ ! -f .env ]]; then
    return
  fi
  if grep -qE '^RGEE_ANALYSIS_AGENT_URL=https?://' .env 2>/dev/null; then
    return
  fi
  python3 - "$AGENT_URL" <<'PY'
import pathlib, re, sys
url = sys.argv[1]
p = pathlib.Path(".env")
text = p.read_text(encoding="utf-8")
if re.search(r"^RGEE_ANALYSIS_AGENT_URL=https?://", text, re.M):
    sys.exit(0)
if re.search(r"^#?\s*RGEE_ANALYSIS_AGENT_URL=", text, re.M):
    text = re.sub(
        r"^#?\s*RGEE_ANALYSIS_AGENT_URL=.*",
        f"RGEE_ANALYSIS_AGENT_URL={url}",
        text,
        count=1,
        flags=re.M,
    )
else:
    text = text.rstrip() + f"\nRGEE_ANALYSIS_AGENT_URL={url}\n"
p.write_text(text, encoding="utf-8")
PY
  echo "Set RGEE_ANALYSIS_AGENT_URL=${AGENT_URL} in .env"
}

load_dotenv_exports() {
  if [[ ! -f .env ]]; then
    return
  fi
  local line
  line="$(grep -E '^MOCK_LLM=' .env 2>/dev/null | tail -1 || true)"
  [[ -n "$line" ]] && export "$line"
  line="$(grep -E '^RGEE_ANALYSIS_AGENT_URL=' .env 2>/dev/null | tail -1 || true)"
  [[ -n "$line" ]] && export "$line"
}

stop_agent() {
  if [[ -n "${AGENT_PID:-}" ]] && kill -0 "$AGENT_PID" 2>/dev/null; then
    echo "Stopping RGEE_Analysis_Agent (pid $AGENT_PID) ..."
    kill "$AGENT_PID" 2>/dev/null || true
    wait "$AGENT_PID" 2>/dev/null || true
  fi
  AGENT_PID=""
}

cleanup() {
  stop_agent
}
trap cleanup EXIT INT TERM

wait_for_agent() {
  local url="${AGENT_URL}/openapi.json"
  local max_wait="${RGEE_AGENT_START_TIMEOUT_S:-300}"
  local i=0
  echo "Waiting for analysis agent at ${url} (timeout ${max_wait}s) ..."
  while (( i < max_wait )); do
    if curl -sf -o /dev/null "$url" 2>/dev/null; then
      echo "RGEE_Analysis_Agent is ready (${AGENT_URL})"
      return 0
    fi
    if [[ -n "${AGENT_PID:-}" ]] && ! kill -0 "$AGENT_PID" 2>/dev/null; then
      echo "RGEE_Analysis_Agent exited unexpectedly. Last log lines:"
      tail -30 "$AGENT_LOG" 2>/dev/null || true
      return 1
    fi
    if (( i > 0 && i % 15 == 0 )); then
      echo "  still starting (${i}s) — first run may install PyTorch; see ${AGENT_LOG}"
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "Timed out waiting for analysis agent. See ${AGENT_LOG}"
  tail -30 "$AGENT_LOG" 2>/dev/null || true
  return 1
}

echo "=== RGEE full stack startup ==="
free_port "$AGENT_PORT" "analysis agent"
free_port "$MAIN_PORT" "main app"
ensure_env
load_dotenv_exports
export RGEE_ANALYSIS_AGENT_URL="${RGEE_ANALYSIS_AGENT_URL:-$AGENT_URL}"
export PORT="$MAIN_PORT"

: >"$AGENT_LOG"
echo "Starting RGEE_Analysis_Agent in background (log: ${AGENT_LOG}) ..."
(
  export RGEE_ANALYSIS_AGENT_HOST="$AGENT_HOST"
  export RGEE_ANALYSIS_AGENT_PORT="$AGENT_PORT"
  exec "$ROOT_DIR/scripts/launch_analysis_agent.sh"
) >>"$AGENT_LOG" 2>&1 &
AGENT_PID=$!

wait_for_agent

echo ""
echo "Main app:     http://127.0.0.1:${MAIN_PORT}/"
echo "Instructor:   http://127.0.0.1:${MAIN_PORT}/professor"
echo "Analysis API: ${AGENT_URL}/docs"
echo "MOCK_LLM=${MOCK_LLM:-1} (export MOCK_LLM=0 for production Together when keyed)"
echo "Press Ctrl+C to stop both services."
echo ""

# Foreground main app; trap cleans up agent on exit.
trap cleanup EXIT INT TERM
export PORT="$MAIN_PORT"
exec "$ROOT_DIR/scripts/launch_project.sh"
