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

# PyInstaller cannot cross-compile: the frozen backend is always built for the
# machine running the build. Packaging a different Electron architecture around
# it would produce a .dmg whose backend cannot execute, so the build is pinned
# to the host architecture unless explicitly overridden.
case "$(uname -m)" in
  arm64) HOST_ARCH=arm64 ;;
  x86_64) HOST_ARCH=x64 ;;
  *) echo "Unsupported host architecture: $(uname -m)" >&2; exit 1 ;;
esac

TARGET_ARCH=""
for argument in "$@"; do
  case "$argument" in
    --arm64) TARGET_ARCH=arm64 ;;
    --x64) TARGET_ARCH=x64 ;;
    *) echo "Unknown option: $argument" >&2; exit 1 ;;
  esac
done
TARGET_ARCH="${TARGET_ARCH:-$HOST_ARCH}"

if [[ "$TARGET_ARCH" != "$HOST_ARCH" && "${CADENCE_ALLOW_CROSS_ARCH:-}" != "1" ]]; then
  echo "Refusing to build $TARGET_ARCH on a $HOST_ARCH machine." >&2
  echo >&2
  echo "PyInstaller freezes the backend for the host architecture only, so the" >&2
  echo "resulting .dmg would carry a backend that cannot run on the target." >&2
  echo "Build each architecture on a matching machine — the GitHub Actions" >&2
  echo "workflow in .github/workflows/build-macos.yml does exactly that." >&2
  echo >&2
  echo "Set CADENCE_ALLOW_CROSS_ARCH=1 to override (the build will be broken)." >&2
  exit 1
fi

ARCH_ARGS=("--${TARGET_ARCH}")
echo "==> Building for ${TARGET_ARCH} (host: ${HOST_ARCH})"

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

# --publish never is required, not cosmetic: electron-builder auto-detects CI
# and tries to publish to GitHub Releases, failing the build on a missing
# GH_TOKEN even though the .dmg built fine. Releases are this repo's
# workflow job, not electron-builder's.
pnpm exec electron-builder --mac "${ARCH_ARGS[@]}" "${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"}" --publish never

echo
echo "==> Done. Artifacts in release/:"
ls -1 release/*.dmg release/*.zip 2>/dev/null || true
