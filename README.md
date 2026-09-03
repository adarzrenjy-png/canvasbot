# Cadence — Adaptive Academic OS

Cadence is a local-first desktop academic planner. It turns Canvas observations, assignment analysis, short calibrations, and calendar constraints into an explainable study plan. SQLite and deterministic application code remain authoritative; model providers are narrow, replaceable helpers.

This repository now contains a working first vertical slice:

```text
persisted Canvas scan job
→ validated observation schema
→ stable-URL reconciliation
→ assignment analysis
→ three-question calibration
→ adaptive duration estimate
→ deterministic study blocks
→ React UI + activity trail + MCP
```

Demo mode runs that path without network calls or API credits. Live Rutgers access uses a dedicated Playwright browser profile in Electron: the user signs in and completes MFA manually, the app retains the browser session, and the worker never handles a Rutgers password.

## What works

- Electron desktop shell with a narrow, sandboxed preload bridge
- Persistent Playwright Canvas session, configurable Rutgers-only origins, and explicit password-field protection
- Encrypted provider-secret vault backed by Electron `safeStorage`; raw keys never enter SQLite
- Settings-based OpenAI/Anthropic model picker that loads the models available to the entered API key
- FastAPI/SQLModel service, SQLite migrations, durable jobs, domain events, and worker health
- Stable Canvas URL identity, duplicate prevention, change detection, and scan failure/auth states
- Credential-free demo Brain for assignment analysis, three-question calibration, and explainable time estimates
- Deterministic scheduling with conflicts, protected blocks, split limits, and deadline safety buffers
- Today, Calendar, Assignments, Mastery, Activity, Settings, Canvas status, and calibration UI
- Inter-based interface with light, dark, and system themes; fonts are bundled, so the app renders correctly offline
- macOS installer build producing a .dmg with the Python backend frozen into the bundle
- MCP 2.x server over stdio or loopback Streamable HTTP, with safe read tools and token-gated scan requests
- 23 unit/integration tests plus TypeScript compilation and frontend linting

The live Z.AI computer-use network adapter is intentionally not faked: public provider documentation does not currently define a stable GLM-5.3-Flash computer-use wire contract. The provider interface, constrained action executor, prompt, managed browser, scan schema, and downstream pipeline are ready for that adapter once a verified account/API contract is available. Remote MCP, provider-backed Brain grading, native notifications, and study timers remain on the task ledger. Installer packaging now ships (see **Building the macOS installer**); Apple code signing and notarization are wired but require your own Developer ID.

## Quick start

Requirements: Python 3.10+, Node.js 20+, pnpm, and Chrome (or a Playwright Chromium channel).

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
pnpm install
.venv/bin/alembic upgrade head
pnpm dev
```

`pnpm dev` starts the Electron app, the React dev server, and the local Python service. For browser-only UI development, run `./scripts/dev.sh` and open `http://127.0.0.1:5173`.

Use **Connect Canvas** inside the desktop app. A managed browser opens for manual Rutgers authentication. Configure allowed authentication redirects through `CANVAS_ALLOWED_ORIGINS`; autonomous actions outside that list are rejected.

Use **Settings → Academic Brain** to choose OpenAI or Anthropic, enter an API key, load the models available to that key, and select the model Cadence should route semantic tasks to. The key is encrypted by Electron in the operating-system-backed vault; only the provider and model selection are stored in SQLite.

## Building the macOS installer

The installer must be built **on macOS**: creating a `.dmg` and signing a bundle
both require Apple tooling that exists nowhere else.

```bash
pnpm install
pnpm dist:mac            # both architectures
pnpm dist:mac:arm64      # Apple silicon only
pnpm dist:mac:x64        # Intel only
```

Artifacts land in `release/` as `Cadence-<version>-<arch>.dmg` alongside a `.zip`.

The build runs three stages: Vite compiles the renderer, `tsc` compiles the
Electron main process, and PyInstaller freezes the FastAPI service into a single
`cadence-backend` binary. That binary ships inside
`Cadence.app/Contents/Resources/backend/`, so an installed copy needs **no
Python, virtualenv, or pip** on the user's machine. The backend build
smoke-tests the frozen binary — starting it, calling the API, shutting it
down — and fails the build if it does not answer.

At launch the app reserves a free loopback port, starts the backend with SQLite
pointed at `~/Library/Application Support/Cadence/planner.db`, waits for the API
to respond, and only then shows the window. If the service never answers, an
error window reports the captured output instead of hanging on a blank screen.

### Signing and notarization

Installing is drag-and-drop: open the `.dmg` and drag **Cadence** to
**Applications**. What happens on *first launch* depends on how it was built.

Without credentials the build is **ad-hoc signed but not notarized**. Ad-hoc
signing matters: Apple silicon refuses to launch unsigned arm64 code at all, and
electron-builder does not fall back to ad-hoc on its own, so the build script
sets the identity explicitly.

An ad-hoc signed build still trips Gatekeeper, because it is not notarized. The
first launch takes a detour:

- **macOS 14 Sonoma and earlier** — right-click the app, choose **Open**, then
  **Open** again in the dialog.
- **macOS 15 Sequoia and later** — the right-click shortcut no longer works. Try
  to open the app, dismiss the warning, then go to **System Settings → Privacy &
  Security**, scroll to the message about Cadence, and click **Open Anyway**.

Only a **signed and notarized** build launches on a plain double-click with no
warning. That needs a paid Apple Developer account.

To produce a distributable build, export your own credentials before building —
they are read from the environment and never stored in this repository:

```bash
export CSC_LINK=/path/to/DeveloperID.p12   # or CSC_NAME="Developer ID Application: ..."
export CSC_KEY_PASSWORD=...

# Optional, for notarization:
export APPLE_ID=you@example.com
export APPLE_APP_SPECIFIC_PASSWORD=abcd-efgh-ijkl-mnop
export APPLE_TEAM_ID=XXXXXXXXXX

pnpm dist:mac
```

The build script reports which of signing and notarization it detected, and
falls back to ad-hoc signing when neither is present.

### Known limitation

**Connect Canvas** drives a managed browser through Playwright using your
installed **Google Chrome** (`channel: 'chrome'`); Chromium is deliberately not
bundled, which keeps the installer small but means Chrome must be present for
Canvas sign-in. Everything else, including demo mode, runs without it.

## Local services

`./scripts/dev.sh` serves the API on a fixed port, with documentation at
`http://127.0.0.1:8000/docs`. The Electron app instead reserves a free port at
launch to avoid collisions, so its API base is printed in the main-process log
and exposed to the renderer as `window.academicOS.apiBaseUrl`.

Local MCP over stdio:

```bash
pnpm mcp:stdio
```

Loopback Streamable HTTP (`http://127.0.0.1:8001/mcp`):

```bash
pnpm mcp:http
```

Read tools expose courses, upcoming assignments, the week plan, recent changes, and planner health. `request_canvas_scan` requires `MCP_WRITE_TOKEN`. Passwords, cookies, keys, raw SQL, filesystem access, and arbitrary browser control are never exposed. Non-loopback HTTP binding is rejected unless remote mode is explicitly enabled; an authenticated secure tunnel/relay still needs to be configured before remote use.

## Verification

```bash
./scripts/test.sh          # pytest, then the frontend production build
pnpm lint                  # frontend lint and desktop typecheck
pnpm build                 # renderer and Electron main
pnpm build:backend         # freeze the backend and smoke-test the binary
```

Database models are in `backend/app/models.py`, with Alembic migrations in `backend/migrations/versions`:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "describe change"
```

## Repository map

```text
apps/desktop/        Electron lifecycle, managed browser, action executor, secret vault
apps/frontend/       React + TypeScript + Vite desktop interface
backend/app/         Canonical data, REST/MCP, reconciliation, jobs, Brain pipeline, scheduler
backend/migrations/  Alembic history
prompts/             Versioned model instructions
tests/               Domain, scheduler, Canvas, worker, API, and MCP tests
packaging/           PyInstaller entry point and spec for the backend binary
build/               electron-builder resources: app icon and entitlements
scripts/             Development, test, and macOS packaging scripts
ARCHITECTURE.md      Process boundaries and data flow
DECISIONS.md         Engineering decisions and constraints
TASKS.md             Completed slice and next depth passes
```

## Security and privacy

- Canvas passwords are never stored or typed by the worker.
- Browser cookies remain in Electron's dedicated local Canvas profile.
- API keys are accepted only through the desktop vault and encrypted with the OS-backed facility.
- Academic text is sent to a configured Brain only for a specific semantic task.
- Telemetry and remote MCP are off by default.
- Demo mode makes no paid model calls.
