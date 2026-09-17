# Architecture decision records

One file per decision, numbered in order. Each records the context at the time, the
decision, its consequences and the alternatives that were rejected.

A decision is never edited to say something different later. To change one, write a
new ADR that supersedes it and update the old file's status line.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-monorepo-layout.md) | Single repository, npm and uv workspaces | Accepted |
| [0003](0003-backend-python-fastapi.md) | Backend in Python with FastAPI | Accepted |
| [0004](0004-frontend-react-vite-pwa.md) | Frontend as a React + Vite installable web app | Accepted |
| [0005](0005-engine-python-with-typescript-parity.md) | Engine in Python, with a TypeScript slice for offline use | Accepted |
| [0006](0006-sql-first-schema.md) | SQL-first schema with raw SQL migrations | Accepted |
| [0007](0007-offline-first-client.md) | Offline-first client storage and sync | Accepted |
| [0008](0008-redis-and-background-jobs.md) | Redis for cache, sessions and background jobs | Accepted |
| [0009](0009-ai-grounding-and-cost.md) | AI explanations grounded in stored solutions, precomputed in batch | Accepted |
| [0010](0010-docker-usage.md) | Docker for production images and CI, not for local development | Accepted |
| [0011](0011-hosting-and-delivery.md) | Hosting and content delivery | Proposed |
| [0012](0012-testing-strategy.md) | Testing strategy and CI gates | Accepted |
| [0013](0013-auth-and-sessions.md) | Authentication and sessions | Proposed |
| [0014](0014-neco-objective-poc.md) | Objective papers for the POC, marks out of 100 per subject | Partly superseded by 0015 |
| [0015](0015-waec-wassce-replaces-neco.md) | WAEC WASSCE replaces NECO as the POC exam | Accepted |

Statuses: Proposed · Accepted · Superseded by ADR-XXXX · Rejected.
