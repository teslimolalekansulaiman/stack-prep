# ADR-0012 · Testing strategy and CI gates

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

Most bugs in this product are not crashes. They are wrong decisions: a student sent
to the wrong skill, a rating that moves too far after a lucky guess, an offline
ladder that disagrees with the server, a mock that loses an answer when the phone
sleeps. None of these show up as errors.

The product spec already defines the checks that matter: golden student profiles,
planner simulations, parity vectors, keyboard-only mock completion, loss-free
offline sync.

## Decision

| Layer | Tool | What it protects |
| --- | --- | --- |
| Python unit and integration | pytest, pytest-asyncio | API behaviour, SQL, jobs |
| Property tests | Hypothesis | Prerequisite graphs, form building, no-repeat rules |
| Golden students | pytest over JSON fixtures | The engine's decisions |
| Engine parity | Shared vectors run by pytest and Vitest | Python and TypeScript agreeing |
| Planner simulation | pytest, multi-week runs | Coverage floors, subject balance, review caps, success mix |
| API contract | Schemathesis against the OpenAPI schema | Responses matching their declared types |
| Frontend unit | Vitest + Testing Library | Client logic |
| End-to-end | Playwright | Keyboard-only mock, offline session, auto-submit |
| Load | k6 | Concurrency targets in the spec |
| Bundle size | size-limit | First-load budget |

**CI gates on every pull request:** ruff, mypy (strict on `packages/engine`), pytest,
Vitest, parity vectors, TypeScript type check, size-limit, and a migration check
that applies every migration to an empty database.

**Gates on the main branch additionally:** Playwright end-to-end and Schemathesis.

**Rules**
- An engine change that alters a golden expectation must change the fixture in the
  same pull request, with the reason in the description. Silent fixture edits are
  the thing reviewers watch for.
- Stale parity vectors fail the build; they are regenerated, never hand-edited.
- No test may depend on wall-clock time or unseeded randomness.

## Consequences

- Slower pull requests than a unit-test-only setup, in exchange for catching the
  failures that actually matter here.
- Fixtures and vectors are first-class artefacts with their own review standards.
- Playwright and k6 need maintenance as the UI changes; keep the end-to-end suite
  small and focused on the criteria in the spec.

## Alternatives considered

- **Coverage targets.** Easy to satisfy without testing a single decision the engine
  makes.
- **Manual QA before each release.** Cannot re-run months of simulated study on
  every change.
