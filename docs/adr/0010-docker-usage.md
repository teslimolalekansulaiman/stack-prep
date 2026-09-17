# ADR-0010 · Docker for production images and CI, not for local development

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

Developers work on macOS. PostgreSQL 18 and Redis 8 are installed natively, and
`database/local-db.sh` already runs a project-local PostgreSQL cluster on port
55439 with its data in `.local/postgres`.

Docker on macOS runs in a virtual machine: slower filesystem access, a few
gigabytes of RAM, and an extra layer between the developer and a debugger.

Production and CI have the opposite need — the image that runs must be identical
everywhere, and CI needs a database that is created and destroyed per run.

## Decision

- **Local development: native.** Postgres via `database/local-db.sh`, Redis via
  Homebrew, Python via uv, Node via the system install. No Docker required to run
  the app or its tests.
- **A `docker-compose.yml` is provided but optional**, for anyone who prefers
  containers or needs to reproduce a version mismatch. It must stay in step with the
  native versions.
- **CI: containers.** PostgreSQL and Redis run as service containers, pinned to the
  production versions.
- **Production: containers.** `apps/api/Dockerfile` builds the API and worker image.
  The web client is static files behind a CDN and needs no image.
- Images are multi-stage and run as a non-root user. The image tag is the git SHA;
  no `latest` in deployment.

## Consequences

- Fast local iteration and straightforward debugging.
- A local–CI difference exists (host OS), which CI catches because it runs the same
  pinned service versions as production.
- The compose file needs occasional upkeep to avoid drifting from reality.

## Alternatives considered

- **Docker for everything, including local dev.** Identical environments everywhere,
  paid for daily in speed on developer machines that are already set up natively.
- **Devcontainers.** Good for onboarding new contributors; revisit if the team grows
  past a handful of people.
- **No containers at all.** Shifts deployment onto host configuration, which drifts.
