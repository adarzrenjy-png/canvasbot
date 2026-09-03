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
- MCP 2.x server over stdio or loopback Streamable HTTP, with safe read tools and token-gated scan requests
- 23 unit/integration tests plus TypeScript compilation and frontend linting

The live Z.AI computer-use network adapter is intentionally not faked: public provider documentation does not currently define a stable GLM-5.3-Flash computer-use wire contract. The provider interface, constrained action executor, prompt, managed browser, scan schema, and downstream pipeline are ready for that adapter once a verified account/API contract is available. Remote MCP, provider-backed Brain grading, native notifications, study timers, and signed installers remain on the task ledger.

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

## Local services

API documentation is available at `http://127.0.0.1:8000/docs` while the app is running.

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
./scripts/test.sh
pnpm lint
pnpm build
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
