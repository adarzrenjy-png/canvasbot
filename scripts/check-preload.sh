#!/usr/bin/env bash
# The preload script must be CommonJS.
#
# This package is type=module, so a .js preload is treated as an ES module, and
# Electron cannot load an ES module into a sandboxed renderer. When that happens
# the preload fails silently: window.academicOS is simply undefined, and every
# feature behind the bridge — Canvas connect, API keys, the browser agent —
# reports "available in the desktop app" while running inside the desktop app.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRELOAD="$ROOT_DIR/apps/desktop/dist/preload/index.cjs"

if [[ ! -f "$PRELOAD" ]]; then
  echo "Preload missing at $PRELOAD." >&2
  echo "It is emitted from src/preload/index.cts; check tsconfig 'include' covers .cts." >&2
  exit 1
fi

if grep -qE '^\s*(import|export)\s' "$PRELOAD"; then
  echo "Preload at $PRELOAD is an ES module." >&2
  echo "A sandboxed Electron preload must be CommonJS. Keep the source as .cts." >&2
  exit 1
fi

if ! grep -q "require(" "$PRELOAD"; then
  echo "Preload at $PRELOAD does not look like CommonJS (no require call)." >&2
  exit 1
fi

# A stale ESM build left beside it would be loaded by an older main process path.
if [[ -f "$ROOT_DIR/apps/desktop/dist/preload/index.js" ]]; then
  echo "Stale ESM preload at dist/preload/index.js; remove dist and rebuild." >&2
  exit 1
fi

echo "Preload is CommonJS."
