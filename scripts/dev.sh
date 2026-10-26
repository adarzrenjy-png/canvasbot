#!/usr/bin/env sh
# Start Jig in development mode (macOS/Linux). Same as: python3 scripts/jig.py dev
set -e
cd "$(dirname "$0")/.."
PY="$(command -v python3 || command -v python)"
exec "$PY" scripts/jig.py dev "$@"
