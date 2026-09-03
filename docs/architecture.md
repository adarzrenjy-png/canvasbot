# Architecture

Cadence is split into an authoritative local service and a replaceable client.

```text
React + TypeScript UI (apps/frontend)
             │ REST / OpenAPI
             ▼
FastAPI boundary (backend/app/api.py)
             │
   ┌─────────┼──────────┐
   ▼         ▼          ▼
Scheduler  Domain    Connectors
   │       services   / LLM ports
   └─────────┼──────────┘
             ▼
       SQLite / SQLModel
```

The database owns assignments, calendar events, blocks, decisions, and history. The scheduler is deterministic and receives plain task and busy-window inputs. The UI never asks an LLM to place calendar events. Future Canvas, Google Calendar, and model providers plug into interfaces around the same services.

## Scheduling objective

Phase 1 uses a deterministic urgency-first greedy planner. It sorts by deadline and priority, places work in 30-minute increments, caps focus blocks at 90 minutes, rejects calendar overlap, and targets a 12-hour safety buffer. Each run and placement explanation is persisted. Calibration-gated assignments are excluded until they reach `CALIBRATED`.

## Security boundary

Assignment text is untrusted data. Live connector tokens must never enter model prompts or SQLite. Later provider credentials are represented by keychain lookup identifiers only. API logs must redact `Authorization` and provider-specific token headers.
