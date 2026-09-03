#!/usr/bin/env bash
# Build the macOS installer end to end: frontend, Electron main, frozen backend,
# then the .dmg. Pass --arm64 or --x64 to build a single architecture.
# Output: release/Cadence-<version>-<arch>.dmg
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "A macOS installer can only be built on macOS: .dmg creation and code" >&2
  echo "signing both require Apple tooling that exists nowhere else." >&2
  exit 1
fi

ARCH_ARGS=()
for argument in "$@"; do
  case "$argument" in
    --arm64) ARCH_ARGS+=(--arm64) ;;
    --x64) ARCH_ARGS+=(--x64) ;;
    *) echo "Unknown option: $argument" >&2; exit 1 ;;
  esac
done

echo "==> Installing node dependencies"
pnpm install --frozen-lockfile

echo "==> Building renderer and Electron main"
pnpm build

echo "==> Building the backend binary"
./scripts/build-backend.sh

echo "==> Packaging the app"
SIGN_ARGS=()
if [[ -n "${CSC_LINK:-}${CSC_NAME:-}" ]]; then
  echo "    Signing identity detected; the bundle will be signed."
  if [[ -n "${APPLE_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" && -n "${APPLE_TEAM_ID:-}" ]]; then
    echo "    Notarization credentials detected; the bundle will be notarized."
  else
    echo "    No notarization credentials; skipping notarization."
    echo "    Gatekeeper will still warn on first launch."
  fi
else
  echo "    No signing identity in the environment; ad-hoc signing instead."
  echo "    Apple silicon refuses to launch unsigned arm64 code, and"
  echo "    electron-builder does not fall back to ad-hoc on its own, so the"
  echo "    identity is set explicitly. Gatekeeper will still warn on first launch."
  # hardenedRuntime with an ad-hoc signature enforces library validation, which
  # would reject Electron's pre-signed framework. build/entitlements.mac.plist
  # carries com.apple.security.cs.disable-library-validation for exactly this.
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  SIGN_ARGS+=(-c.mac.identity=-)
fi

pnpm exec electron-builder --mac "${ARCH_ARGS[@]+"${ARCH_ARGS[@]}"}" "${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"}"

echo
echo "==> Done. Artifacts in release/:"
ls -1 release/*.dmg release/*.zip 2>/dev/null || true
