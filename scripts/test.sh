#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_BIN="/Users/advaith/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
FALLBACK_BIN="/Users/advaith/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback"
export PATH="$NODE_BIN:$FALLBACK_BIN:$PATH"

cd "$ROOT_DIR"
.venv/bin/pytest
cd apps/frontend
pnpm build
