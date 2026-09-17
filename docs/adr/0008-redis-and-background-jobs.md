# ADR-0008 · Redis for cache, sessions and background jobs

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

Work that must not happen inside a request: nightly item statistics, metrics
rollups, mock repair after a submission, review scheduling, batch generation of
alternative explanations, digest sending, sync reconciliation.

Sessions need a server-side store that can be revoked. Some endpoints need rate
limiting — especially the AI ones, which cost money per call.

## Decision

**Redis** for cache, sessions, rate limits and the job queue, with **arq** as the
worker framework (async-native, same event loop model as FastAPI, small surface).

- Jobs are defined in `apps/api`, run by a separate worker process, and are
  idempotent: re-running a day's metrics produces identical rows.
- Scheduled jobs use arq's cron support.
- Sessions are opaque IDs in Redis referenced by an httpOnly cookie, so revoking a
  session is a delete.
- Cached values (plans, opportunities) carry `engine_version` in the key, so a
  version bump invalidates them.

Redis is a cache and a queue, never a source of truth. Everything durable lives in
PostgreSQL, and losing Redis costs a re-run and re-login, not data.

## Consequences

- One more service to run and monitor; it is already installed locally.
- Job failures need alerting and a retry policy, plus a dead-letter list for
  inspection.
- A second process type (worker) in every environment, sized separately from the API.

## Alternatives considered

- **Celery.** More mature tooling, heavier configuration, and a synchronous model
  that fits an async codebase less neatly. Reconsider if arq's operational tooling
  becomes limiting.
- **PostgreSQL-backed queues.** One fewer service, at the cost of queue load on the
  primary database during exam-season peaks.
- **Managed queues (SQS and friends).** Cloud lock-in and latency for a workload
  that fits comfortably in Redis.
