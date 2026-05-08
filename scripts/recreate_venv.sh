#!/usr/bin/env bash
# Recreate .venv with Python 3.12 (preferred), 3.11, or 3.13 — the versions PyTorch /
# sentence-transformers support well. Skips 3.14+ so you are not stuck without wheels.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

pick_python() {
  local c
  for c in python3.12 python3.11 python3.13; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info < (3, 14) else 1)' 2>/dev/null; then
        command -v "$c"
        return 0
      fi
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  cat <<'EOF' >&2
No Python 3.11–3.13 found on PATH (python3.12, python3.11, or python3.13).

macOS options:
  • Homebrew: brew install python@3.12
    then: export PATH="/opt/homebrew/opt/python@3.12/bin:$PATH"
    (Intel Homebrew often uses /usr/local/opt/python@3.12/bin)
  • https://www.python.org/downloads/ — install 3.12.x and re-run this script.

Fix Homebrew permission errors (if any) with:
  sudo chown -R "$(whoami)" /usr/local/Cellar /usr/local/Homebrew /usr/local/bin …
EOF
  exit 1
fi

echo "Using $PY — $($PY --version)"
rm -rf .venv
"$PY" -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -r requirements-analysis.txt
rm -f .venv/.deps_installed
touch .venv/.deps_installed

echo ""
echo "Done. Activate with: source .venv/bin/activate"
echo "Run app: ./run_dev.sh  or  ./scripts/launch_project.sh"
