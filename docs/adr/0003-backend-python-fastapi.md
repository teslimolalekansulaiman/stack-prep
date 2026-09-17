# ADR-0003 · Backend in Python with FastAPI

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

The backend serves the student app, the authoring and review tools, and the
scheduled jobs that update mastery, plans, reviews and metrics.

Two things pull hard in different directions:

1. The learning engine's rules must also run on the device, offline (ADR-0005).
   That favours TypeScript, which can run in both places.
2. Milestone M5 is statistical work — fitting item difficulty, session gain, score
   range widths, later IRT. That favours Python, where the libraries live.

The existing schema in `database/migrations` is SQL-first: nine tables, two views,
and roughly sixty check and foreign-key constraints written by hand, including
composite keys that keep a curriculum item inside one syllabus version.

## Decision

Python 3.12+ with FastAPI, using:

- **Pydantic v2** for request, response and settings models.
- **SQLAlchemy 2.0 Core** with **asyncpg** — connection handling and typed results
  over SQL we write ourselves, not the ORM.
- **OpenAPI output** generated from the route signatures, and used to generate the
  TypeScript API client in CI.

The offline requirement is met by a small TypeScript engine slice plus a parity
test suite (ADR-0005), not by moving the backend to TypeScript.

## Consequences

- Calibration, simulation and engine share one language and one repository, with no
  export boundary between the analysis and the code that runs in production.
- The item ladder, mastery update and help rules exist in two implementations. That
  cost is paid deliberately and controlled by generated parity vectors.
- The frontend's API types are generated, so an API change that breaks the client
  fails CI rather than production.
- Async all the way through: database driver, HTTP client, and the streaming AI
  endpoint.

## Alternatives considered

- **TypeScript (Fastify or NestJS).** One implementation of the engine and shared
  types, but the M5 statistics work becomes painful, and the fitted parameters have
  to cross a language boundary anyway.
- **Django + DRF.** The admin would shorten some content tooling, but its value is
  ORM-shaped, and our schema is deliberately hand-written SQL. The item editor
  (maths preview, distractor mapping, side-by-side review) is custom work either
  way.
- **Go or Elixir.** Good runtimes, wrong ecosystem for psychometrics, smaller local
  hiring pool.
