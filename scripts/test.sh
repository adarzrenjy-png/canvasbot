#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
.venv/bin/pytest
pnpm --filter frontend build
pnpm --filter @cadence/desktop build
./scripts/check-preload.sh
