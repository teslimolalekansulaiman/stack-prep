# ADR-0001 · Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

Sprint S0 of the engineering plan requires architecture decision records for the
stack, hosting, offline strategy and maths rendering. The team is small, and the
product runs for a year before its first real exam outcome. Decisions made now
(how mastery is stored, where the engine runs, what a question row looks like) are
expensive to reverse once student data exists.

Without a written record, a decision's reasoning lives in one person's memory, and
six months later nobody can tell a deliberate choice from an accident.

## Decision

Every significant technical decision gets an ADR in `docs/adr/`, numbered
sequentially, using this structure: Context, Decision, Consequences, Alternatives
considered.

Significant means: it constrains other decisions, is costly to reverse, or a new
engineer would otherwise ask "why is it like this?".

ADRs are immutable. A changed decision becomes a new ADR that supersedes the old
one; the old file keeps its content and gains a superseded status line.

## Consequences

- Reviewers can challenge a decision's reasoning, not just its code.
- The S0 acceptance criterion ("ADRs for the five decisions are merged") is met by
  files in the repository, not by a discussion.
- A small ongoing cost: roughly 30 minutes per decision.

## Alternatives considered

- **A page in the product spec.** Mixes what we build with how we build it, and
  loses the record of rejected options.
- **Nothing written down.** Cheapest today, most expensive in month six.
