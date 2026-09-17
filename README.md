# Score Pilot

Adaptive exam preparation for Nigerian UTME candidates. The product decides what a
student should study next to gain the most exam marks from the time they have.

- **What we're building:** [docs/product-spec.md](docs/product-spec.md)
- **How and when:** [docs/roadmap.md](docs/roadmap.md)
- **Why it's built this way:** [docs/adr/](docs/adr/README.md)
- **Both documents as one page:** `node docs/_build/build.mjs`

## Layout

```
apps/api            FastAPI service and background worker (ADR-0003)
apps/web            React client, offline-capable (ADR-0004)
packages/engine     Learning engine: pure rules, no I/O (ADR-0005)
packages/engine-ts  Offline slice of the engine, kept in parity
packages/fixtures   Generated parity vectors shared by both test suites
packages/api-client Types generated from the API's OpenAPI schema
database/           SQL migrations, syllabus seed, loader (ADR-0006)
analysis/           Calibration scripts and notebooks
docs/               Spec, roadmap, ADRs
```

## Getting started

Prerequisites: PostgreSQL 18, Redis 8, Node 20+, [uv](https://docs.astral.sh/uv/).
Docker is **not** needed for local development (ADR-0010).

```sh
make setup        # uv sync + npm install
make db-start     # project-local PostgreSQL on port 55439
make migrate      # apply database/migrations
make seed         # load the reviewed syllabus extraction
make test         # Python and JavaScript suites
```

Then, in two terminals:

```sh
make api          # http://127.0.0.1:8000  (docs at /docs)
make web          # http://127.0.0.1:5173
```

If either port is busy, override it: `make api API_PORT=8001`, and start the client with
`PORT=5179 API_PROXY=http://127.0.0.1:8001 npm run dev`.

`make help` lists every target.

## Content review

The app opens on the review queue, because until questions are verified there is nothing to
show a student. Imported past-paper questions arrive with a **proposed** answer, difficulty
level and skill; a subject expert turns those into decisions.

Built for speed, since a paper is 100 questions:

| Key | Action |
| --- | --- |
| A–D | Verify the answer |
| 1–5 | Verify the difficulty level |
| S | Approve the skill mapping |
| ⏎ | Approve the question |
| J / K | Move through the queue |

The database, not the screen, enforces the rules. A question cannot be approved until its
answer and level are human-verified (`answer_source`, `level_source`), its primary skill is
approved, and it has a worked solution and a hint. Approved content is then immutable:
corrections open a new version, so a marked response always reflects what the candidate saw.

Two views drive the queue: `questions_awaiting_answer_check` and `question_readiness`.

## Database

The local cluster lives in `.local/postgres` and is never committed. Connect with
psql or DBeaver:

| Setting | Value |
| --- | --- |
| Host | 127.0.0.1 |
| Port | 55439 |
| Database | scorepilot |
| User | your macOS username |
| Password | none (trust auth on loopback) |
| Schema | `stackprep` |

If PostgreSQL 18 refuses to start on macOS with "postmaster became multithreaded",
set a locale: `LC_ALL=en_US.UTF-8 make db-start`. The Makefile does this for you.

## Working on the engine

The engine decides what each student does next, so it carries the heaviest rules:

1. Change the rule in `packages/engine`.
2. Mirror it in `packages/engine-ts` if it is one of the offline rules (mastery
   update, item ladder, help ladder).
3. Run `make fixtures` to regenerate `packages/fixtures/vectors.json`.
4. Run `make test`. The parity test fails if the two implementations disagree, and
   the fixtures test fails if the vectors are stale.
5. Bump `ENGINE_VERSION` in both packages when behaviour changes, and explain the
   diff in the pull request.

Never hand-edit generated vectors, and never make a test pass by loosening an
expectation without saying why in the pull request description.

## Conventions

- Events (`attempts` and friends) are append-only and are the source of truth.
  Ratings, plans and metrics are derived and can be rebuilt by replay.
- Constraints belong in the database; application checks are for error messages.
- Every derived record carries `engine_version`.
- No test may depend on wall-clock time or unseeded randomness.
