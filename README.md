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

A new install starts **empty** and fills from Canvas: there is no sample
coursework standing in for yours. Set `DEMO_MODE=true` to seed the sample
courses used by the walkthrough; demo mode runs the whole path above without
network calls or API credits. Live Rutgers access uses a dedicated Playwright browser profile in Electron: the user signs in and completes MFA manually, the app retains the browser session, and the worker never handles a Rutgers password.

## What works

- Electron desktop shell with a narrow, sandboxed preload bridge
- Persistent Playwright Canvas session, configurable Rutgers-only origins, and explicit password-field protection
- Encrypted provider-secret vault backed by Electron `safeStorage`; raw keys never enter SQLite
- Live Academic Brain: OpenAI, Anthropic, Z.AI (GLM), and any OpenAI-compatible
  endpoint (OpenRouter, Ollama, vLLM, LM Studio) drive assignment analysis,
  calibration questions, and answer grading
- Settings model picker that loads the models available to the entered API key,
  and states plainly whether the Brain is live or falling back to built-in logic
- FastAPI/SQLModel service, SQLite migrations, durable jobs, domain events, and worker health
- Stable Canvas URL identity, duplicate prevention, change detection, and scan failure/auth states
- Credential-free demo Brain for assignment analysis, three-question calibration, and explainable time estimates
- Deterministic scheduling with conflicts, protected blocks, split limits, and deadline safety buffers
- First-run setup collecting your name, study hours, focus block length, and
  deadline buffer, with Settings writing through to the same values
- Today, Calendar, Assignments, Mastery, Activity, Settings, Canvas status, and calibration UI
- Inter-based interface with light, dark, and system themes; fonts are bundled, so the app renders correctly offline
- macOS installer build producing a .dmg with the Python backend frozen into the bundle
- Model-agnostic browser agent: any JSON-capable model drives the managed
  Canvas browser through a constrained action vocabulary
- MCP 2.x server over stdio or loopback Streamable HTTP, with safe read tools and token-gated scan requests
- 23 unit/integration tests plus TypeScript compilation and frontend linting

The Canvas browser agent now runs on a model-agnostic Playwright harness (see
**Browser agent** below) rather than a vendor-specific computer-use protocol.
Upstream's reasoning for not faking the latter still stands: the live Z.AI computer-use network adapter is intentionally not faked: public provider documentation does not currently define a stable GLM-5.3-Flash computer-use wire contract. The provider interface, constrained action executor, prompt, managed browser, scan schema, and downstream pipeline are ready for that adapter once a verified account/API contract is available. Remote MCP, native notifications, and study timers remain on the task ledger. Installer packaging now ships (see **Building the macOS installer**); Apple code signing and notarization are wired but require your own Developer ID.

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

Use **Settings → Academic Brain** to pick a provider, enter an API key, load the
models that key can reach, and choose the one Cadence routes semantic tasks to.

| Provider | Endpoint | Notes |
| --- | --- | --- |
| OpenAI | `api.openai.com` | Chat models only; speech, image, and embedding models are filtered out |
| Anthropic | `api.anthropic.com` | Uses the Messages API |
| Z.AI | `api.z.ai` | GLM models, via the OpenAI-compatible surface |
| Custom | you supply it | Anything speaking OpenAI's `/chat/completions`: OpenRouter, Ollama, vLLM, LM Studio |

Remote custom endpoints must use https so the key is never sent in the clear;
loopback URLs may use http.

The panel shows whether the Brain is **live**. When no provider is configured,
its key is missing, or a call fails, Cadence falls back to deterministic
built-in logic rather than erroring — so a provider outage never blocks
scheduling. Keys are encrypted by Electron in the OS-backed vault and pushed to
the local service in memory only; they are **never written to SQLite**, which is
enforced by a test.

## Building the macOS installer

The installer must be built **on macOS**: creating a `.dmg` and signing a bundle
both require Apple tooling that exists nowhere else. You can build it on your own
Mac, or let GitHub Actions do it.

### On your Mac

```bash
pnpm install
pnpm dist:mac
```

Artifacts land in `release/` as `Cadence-<version>-<arch>.dmg` alongside a `.zip`.

`pnpm dist:mac` builds for **the architecture of the machine you run it on**.
That is a hard constraint rather than a default: PyInstaller freezes the backend
for the host machine and cannot cross-compile, so packaging the other
architecture would produce a `.dmg` whose backend cannot execute. The build
script refuses a mismatched `--arm64`/`--x64` rather than emitting a broken
installer.

To build for the architecture you are not on, use CI.

### On GitHub Actions

`.github/workflows/build-macos.yml` builds on GitHub's macOS runners, so no local
Mac is needed. Because of the cross-compilation constraint above, each
architecture is built on a runner of that architecture.

- **Manually** — Actions tab → *Build macOS installer* → *Run workflow*. The
  `.dmg` is attached to the run as a downloadable artifact. Tick *Also build for
  Intel Macs* if you need an Intel build; it is off by default, since every Mac
  released since late 2020 is Apple silicon.
- **On a tag** — `git tag v0.2.0 && git push origin v0.2.0` builds both
  architectures and publishes a GitHub Release with the installers attached.

The workflow verifies that the frozen backend inside each bundle actually matches
its target architecture, and fails the build if it does not.

Runner images: `macos-latest` is Apple silicon; the Intel job uses
`macos-15-intel`, which GitHub retires in August 2027.

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

An ad-hoc signed build still trips Gatekeeper, because it is not notarized.
macOS reports this as *“Cadence” Not Opened — Apple could not verify “Cadence” is
free of malware*, offering only **Move to Trash** and **Done**. That wording is
about the missing notarization ticket, not about anything found in the app.
Choose **Done**, never *Move to Trash*, then allow it one of two ways.

**Terminal — one command.** Remove the quarantine flag macOS attaches to
downloaded files:

```bash
xattr -dr com.apple.quarantine /Applications/Cadence.app
```

`-r` matters: an app is a directory, and the flag sits on files inside it. After
this the app opens normally, for good.

**System Settings — no Terminal.** Try to open Cadence, dismiss the warning, then
go to **System Settings → Privacy & Security** and scroll to the bottom. A line
about Cadence being blocked appears with an **Open Anyway** button; the button
only shows up after a launch attempt, and only for about an hour afterwards. On
**macOS 14 and earlier** you can instead right-click the app and choose **Open**;
that shortcut was removed in macOS 15.

Only a **signed and notarized** build launches on a plain double-click with no
warning at all. That needs a paid Apple Developer account.

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

## Browser agent

The Canvas agent is driven by **any model that can emit JSON**, not by a
vendor-specific computer-use API. Screenshot-and-pixel-coordinate protocols
differ per provider and lock you to one vendor; this harness works with
everything in the provider table above, including local models.

Each step:

1. **Observe** — the page is described as text: URL, title, trimmed body copy,
   and every visible interactive element. Each element is tagged in the DOM with
   a `data-cadence-ref` attribute.
2. **Plan** — the observation, the goal, and the steps so far go to the
   configured Brain, which returns exactly one action as JSON.
3. **Execute** — the action is validated against the schema in *both* Python and
   TypeScript, then run through the constrained executor.

Because elements are tagged before being described, the model chooses targets
from a list it was shown rather than inventing CSS selectors that match nothing.

The action vocabulary is fixed: `click`, `double_click`, `type_text`,
`press_key`, `scroll`, `navigate`, `go_back`, `wait`, `read_page`, `finish`,
`fail`. Anything else is rejected before it reaches the browser.

Guard rails:

- **Passwords are never typed.** The executor refuses `type_text` on a password
  field, and password values are never read back into an observation. The agent
  is told to stop and report if a page demands sign-in.
- **Navigation is confined** to `CANVAS_ALLOWED_ORIGINS`.
- **Runs are bounded** by a step budget (25 by default, 50 maximum).
- **Actions time out in 10 seconds**, so a stale selector costs one step rather
  than stalling the run on Playwright's 30-second default.
- **Failures are fed back, not thrown** — a rejected action becomes history the
  model can react to, so it can pick a different element.
- **A live model is required.** The deterministic demo Brain cannot drive a
  browser, and the agent says so rather than inventing actions.

## First run

The app opens on a four-step setup: your name and term, the hours study blocks
may occupy, how long a focus block may run and how far ahead of a deadline to
finish, then an optional Canvas connection.

Everything it collects is a real scheduling constraint — the planner reads the
same `UserPreferences` row when it places blocks — and every value stays
editable in **Settings**, where each control writes through immediately and
replans the calendar.

Until Canvas is connected the planner is genuinely empty rather than populated
with samples. Preferences live in SQLite under Electron's user-data directory,
never in the app bundle.

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
backend/app/agent/   Browser agent planning and the shared action schema
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
