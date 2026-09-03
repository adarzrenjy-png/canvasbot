#!/usr/bin/env bash
# Freeze the FastAPI backend into a standalone binary that the macOS app bundles.
# Output: release/backend/cadence-backend
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

if [[ ! -x .venv/bin/python ]]; then
  echo "==> Creating virtualenv"
  "$PYTHON_BIN" -m venv .venv
fi

echo "==> Installing backend requirements"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r backend/requirements.txt
.venv/bin/pip install --quiet pyinstaller

echo "==> Freezing backend"
rm -rf release/backend build/pyinstaller
.venv/bin/pyinstaller packaging/cadence-backend.spec \
  --noconfirm \
  --distpath release/backend \
  --workpath build/pyinstaller

BINARY="release/backend/cadence-backend"
if [[ ! -x "$BINARY" ]]; then
  echo "PyInstaller did not produce $BINARY" >&2
  exit 1
fi

echo "==> Smoke-testing the frozen backend"
# Bind a throwaway port, confirm the API answers, then shut it down.
PORT=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
CADENCE_API_PORT="$PORT" DATABASE_URL="sqlite:///$(mktemp -d)/smoke.db" "$BINARY" &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/v1/status" >/dev/null 2>&1; then
    echo "==> Frozen backend responded on port ${PORT}"
    echo "==> Built $BINARY"
    exit 0
  fi
  sleep 0.5
done

echo "The frozen backend did not answer on port ${PORT}" >&2
exit 1
