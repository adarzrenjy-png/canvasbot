# Academic OS Architecture

Cadence is a local-first academic operating system with three deliberately separate layers.

```text
Rutgers Canvas (managed Electron session)
                 │ screenshots + constrained actions
                 ▼
       Canvas computer-use worker
                 │ validated scan result
                 ▼
   FastAPI service + SQLite canonical state
                 │ typed domain events
        ┌────────┴─────────┐
        ▼                  ▼
 Brain provider       Deterministic scheduler
 (semantic only)      (timestamps and constraints)
        └────────┬─────────┘
                 ▼
        React desktop interface
                 │
        semantic service layer
                 ▼
      MCP stdio / Streamable HTTP
```

## Process boundaries

- **Electron main process** owns desktop lifecycle, the persistent Canvas browser partition, navigation restrictions, encrypted credential storage, and native notifications.
- **React renderer** is an unprivileged presentation layer. It receives a narrow preload API and talks to the local service over REST.
- **Python service** remains authoritative for SQLite, reconciliation, scheduling, mastery, activity history, and API/MCP tools. The existing tested Python core made replacing it with a second TypeScript implementation a higher-risk duplication.
- **Canvas worker** accepts only configured academic origins and a constrained action vocabulary. It never receives or types a Rutgers password and cannot submit, message, enroll, or mutate Canvas state.
- **Brain providers** receive task-specific context and return validated structured recommendations. They do not write to SQLite or place timestamps.
- **MCP** is an optional interface over the same service functions used by REST and the desktop. The app never depends on an external AI client.

## Vertical slice

The first slice is credential-free and reproducible:

1. A mock or validated Canvas scan is ingested.
2. Stable Canvas URLs reconcile courses and assignments without duplication.
3. Meaningful changes emit durable domain events.
4. New work is analyzed by the configured Brain or deterministic demo provider.
5. A three-question calibration is created when confidence is insufficient.
6. A completed calibration updates the assignment proficiency estimate and duration. Concept-level mastery evidence updates are the next depth pass.
7. The deterministic scheduler places feasible blocks and records its decisions.
8. The UI and MCP server read the resulting canonical state.

Live GLM execution is kept behind `ComputerUseProvider`; current public Z.AI documentation confirms a bearer-authenticated general API and function calling, but does not document a stable model-specific computer-use wire protocol. The adapter therefore keeps endpoint, model, and protocol mapping configurable rather than inventing a proprietary contract.

## MCP modes

- **Local:** stdio for desktop clients and Streamable HTTP bound to loopback.
- **Remote:** architecture only. Disabled by default until an authenticated TLS relay or OpenAI Secure MCP Tunnel is configured. Raw port forwarding is not supported.

The implementation targets the current official MCP SDK and Streamable HTTP transport. HTTP deployment must use OAuth-compatible authorization and DNS-rebinding/origin controls. Write tools are separate from read tools and require an explicit write capability.

## Data and secrets

SQLite stores academic state, evidence, jobs, usage, and encrypted-credential references. Electron `safeStorage` protects provider keys at rest using the OS facility available to Electron. The renderer sends a newly entered key across a narrow preload method; Electron's main process stores it and calls the provider's model-catalog endpoint without returning the key. Passwords, browser cookies, raw keys, and credential references are never returned by REST or MCP. Canvas cookies remain in Electron's dedicated persistent profile. In demo mode, the persisted job runner exercises the same scan schema and reconciliation pipeline without a network or paid model call; live jobs are left for the desktop computer-use worker to claim.
