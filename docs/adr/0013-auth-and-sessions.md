# ADR-0013 · Authentication and sessions

- **Status:** Proposed — confirm the sign-in channel in S0
- **Date:** 2026-09-17

## Context

Users are students (mostly 16–18), teachers, school admins, content authors, subject
leads, research analysts and platform admins. Students sign in on shared or
low-end phones and in school labs, and often don't use email regularly. SMS costs
money per message and delivery in Nigeria is uneven between networks.

Under-18 accounts cannot store attempt data until guardian consent is recorded, so
consent is part of the account model, not a later feature.

Per-user pricing from hosted identity providers scales badly against a low price per
student.

## Decision (proposed)

- **Sessions:** opaque session IDs in Redis behind an httpOnly, Secure, SameSite=Lax
  cookie. No JWTs in the browser, so revocation is immediate.
- **Student sign-in:** school join code plus a one-time code. Channel (SMS or email)
  to be confirmed in S0 after checking delivery rates and cost with a Nigerian
  provider (Termii or Africa's Talking).
- **Staff sign-in:** email magic link, with optional password (Argon2id) for
  accounts that want one.
- **Authorisation:** roles in PostgreSQL, checked in a single policy layer, with
  every query scoped by organisation. Tenant isolation has its own automated tests.
- **Consent gate:** the API accepts attempts for in-session feedback but does not
  persist them until a guardian consent record exists.
- **Research group assignment** is readable only by the research role, and is
  immutable once written.
- **Rate limiting** on code requests and verification attempts, per phone or email
  and per IP.

## Consequences

- We operate our own authentication: lockout rules, code expiry, replay protection,
  device handling. This is deliberate and needs a security review before the v1.0
  release.
- No per-user identity-provider cost.
- Shared devices need explicit sign-out and short idle timeouts in school labs.

## Alternatives considered

- **Auth0, Clerk or similar.** Fast to start; per-user pricing works against the
  business model, and student data residency becomes a third-party question.
- **Passwords only.** Students forget them, and password resets need a channel
  anyway.
- **JWT access tokens without server-side sessions.** Cheap to verify, hard to
  revoke — wrong trade-off when a shared phone may need immediate sign-out.
