# Engineering Decisions

## ADR-001: Keep the tested Python domain core

**Decision:** Retain FastAPI/SQLModel for canonical state and deterministic scheduling while replacing Tauri with Electron.

**Why:** Phase 1 already has migrations, tests, reconciliation-ready models, and a working scheduler. Rewriting those rules in Node would create two sources of truth and delay the Canvas-to-plan slice. Electron still supplies the browser, background, keychain, and packaging capabilities requested by the revised brief.

## ADR-002: Stable LMS URLs are identity evidence

Courses and assignments reconcile primarily by normalized Canvas URL plus source. Visible titles are mutable attributes. Hashes detect semantic changes; a second observation updates rather than duplicates a record.

## ADR-003: Persistent events, not timer coupling

Scans record durable events and jobs. Expensive analysis is triggered only by meaningful state changes. A no-change scan updates health state without invoking the Brain or moving calendar blocks.

## ADR-004: Mock providers are first-class

Demo mode exercises the full pipeline without Canvas access or paid tokens. Live provider adapters share the same validated schemas and are opt-in integration tests.

## ADR-005: Local MCP first; remote is opt-in

Local stdio and loopback Streamable HTTP are safe defaults. ChatGPT does not directly connect to arbitrary localhost MCP servers, so remote connectivity will use a supported secure tunnel or an authenticated relay—never an automatically exposed port.

## ADR-006: User overrides outrank inference

Explicit duration, completion, availability, and lock choices are stored separately and are not overwritten by later model output.

## ADR-007: Do not invent a GLM computer-use protocol

The Playwright action executor and provider interface are implemented, while the Z.AI network adapter remains configurable and pending a verified provider-specific computer-use contract. Demo mode uses the exact validated scan boundary, so replacing the mock worker does not alter reconciliation, Brain triggering, or scheduling.
