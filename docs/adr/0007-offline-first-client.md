# ADR-0007 · Offline-first client storage and sync

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

Students study on mobile data that drops out, in school halls with weak signal, and
in computer labs sharing one connection. The product spec requires a student to
complete a practice session offline and lose nothing, and a mock to survive
backgrounding and a dropped connection.

Attempts are append-only and never edited, so there are no conflicting writes to
merge — the hard part is delivery, not conflict resolution.

## Decision

- **Service worker (Workbox)** caches the application shell and static assets;
  the app opens offline.
- **IndexedDB via Dexie** stores the prefetched item bundle (the next 40 practice
  items with solutions and hints), the current plan, local ratings and the outbox.
- **Attempts are queued in an outbox**, each with a client-generated UUID and a
  client timestamp, and posted in order when the connection returns. The API is
  idempotent on that UUID, so retries are safe.
- **Mocks** fetch the whole form before the timer starts, keep answers locally, and
  submit on reconnect. The server holds authoritative start and end times; a late
  submission is recorded and flagged, never silently accepted.
- **Local ratings** are updated by the TypeScript engine slice (ADR-0005) so the
  ladder keeps adapting offline. The server recomputes on sync and its result wins.
- **No sensitive data at rest:** the item bundle and attempts only. No guardian
  contact details, no result slips.

## Consequences

- The client carries real logic and real state, so it needs its own tests, including
  a "network off mid-session" end-to-end case.
- Server ratings can briefly disagree with the device's. The server is the source of
  truth and reconciles on sync; the student sees no conflict.
- A nightly reconciliation job compares client-reported attempt counts with stored
  attempts and alerts on any gap.

## Alternatives considered

- **Online only.** Simplest, and unusable for a large share of the target students.
- **CRDTs or a sync framework.** Built for concurrent edits to shared documents;
  an append-only outbox is far simpler and sufficient.
- **Local SQLite through WebAssembly.** More capable querying, heavier download, and
  the queries the client runs are trivial.
