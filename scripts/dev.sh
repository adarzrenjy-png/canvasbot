#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ -n "${CADENCE_PYTHON:-}" ]]; then
  PYTHON_BIN="$CADENCE_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo "Cadence requires Python 3.10 or newer. Set CADENCE_PYTHON to a compatible interpreter." >&2
  exit 1
fi
if [[ ! -x .venv/bin/uvicorn ]]; then
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi

.venv/bin/uvicorn backend.app.main:app --reload --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

cd apps/frontend
pnpm install
pnpm dev
