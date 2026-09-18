# ADR-0016 · A shared Hetzner VPS for the dev deployment

- **Status:** Accepted
- **Date:** 2026-09-17
- **Relates to:** [ADR-0011](0011-hosting-and-delivery.md), which remains *Proposed*
  and governs production hosting. This decision does not settle that one.

## Context

Content review is the work in front of us: imported past-paper questions arrive
proposed, and a subject expert has to verify each answer, level and skill before a
student can see anything. The tool for that is built, but it only runs on a
developer's laptop, which makes a reviewer dependent on a developer.

A deployed instance removes that dependency. What it needs is modest — one API,
one worker, PostgreSQL, Redis, and a static client — and the audience is a handful
of people, not students.

An existing Hetzner VPS is available. It is not ours alone: it runs another
project ("AI Engineer Platform") as systemd services behind Caddy, on a 4 GB,
2-core machine. That project is understood to be abandoned but is still running.

ADR-0011 proposed managed hosting and explicitly set aside "a VPS and manual
setup" because it makes backups, failover and scaling our problem during exam
season. That reasoning holds — for production.

## Decision

Deploy the **dev** branch to the existing Hetzner box, as a guest on it.

- **Containers, not system packages.** The repository already has a Dockerfile and
  ADR-0010. Containers also keep PostgreSQL 18 off a machine whose system packages
  belong to someone else.
- **Nothing published to the internet.** The API binds to `127.0.0.1:8010`;
  PostgreSQL and Redis publish no ports at all. Caddy, already running for the
  other project, is the only process facing outward.
- **An explicit Caddy site block on our own domain**, `stackprep.stackjunior.com`.

  A subdomain of the neighbour's `binaax.app` was tried first and does not work.
  Their config issues a certificate on demand for any `<digits>.binaax.app`
  hostname, and an internet scanner probing random numeric subdomains for leaked
  cloud credentials triggers one per probe — fifteen certificates in a single
  observed hour. Let's Encrypt allows fifty per registered domain per week, so
  `binaax.app` sits permanently at its limit and new names silently never get a
  certificate. Caddy reports this as nothing at all: the domain appears in its
  managed list, no certificate is ever obtained, and the handshake fails with
  `tlsv1 alert internal error`.

  Waiting does not help; the scanner consumes each reset. Our own domain has its
  own quota, and the deployment stops depending on another project's TLS
  configuration. Worth telling that project's owner regardless — it is their
  quota being burned, and it will affect them again.
- **HTTP basic auth in front of everything.** The review API has no authentication
  of its own until ADR-0013 lands, and it can rewrite the question bank. A password
  is not real access control, but it is the difference between "colleagues" and
  "the internet".
- **No `sudo` in the pipeline.** `sudo` on that box requires a password, and a sudo
  password in a CI secret is worse than the problem it solves. The deploy user is
  in the `docker` group; installing Docker and editing Caddy are one-time human
  steps.
- **Every container memory-capped**, following the convention the box already uses
  for its other tenant. An unbounded PostgreSQL on a shared 4 GB machine is how you
  take down someone else's service.
- **`main` is never deployed automatically.**

## Consequences

- A reviewer can work from a URL. That is the point, and it arrives now rather than
  after a hosting decision.
- We inherit a neighbour. Our resource limits protect them; their Caddy config is a
  dependency of ours. Neither project can be redeployed carelessly.
- Backups do not exist yet. Reviewed questions are real human effort and are not
  reproducible from this repository — see `deploy/README.md`. This is the most
  likely way to lose something that matters.
- No failover, no scaling, and a shared machine. When students depend on this,
  ADR-0011 has to be decided properly; this is not a substitute for it.
- If the other project is switched off, the box becomes ours and these constraints
  loosen. That is not assumed here.

## Alternatives considered

- **Managed hosting now (ADR-0011's proposal).** Correct for production, premature
  for a review tool used by a few people. It also needs the Lagos latency
  measurement ADR-0011 asks for, which has not happened.
- **Matching the neighbour's pattern: systemd units, no Docker.** Consistent with
  the box, but every deploy would need `sudo systemctl restart`, which means either
  a password in CI or a NOPASSWD sudoers rule — more privilege, not less. It also
  needs PostgreSQL 18 from a third-party apt repository on a shared machine.
- **A numeric sandbox subdomain.** The neighbour's Caddy config maps
  `<port>.binaax.app` straight to `localhost:<port>`, so this would have needed no
  configuration at all. Rejected: that wildcard carries no basic auth, so it would
  put an unauthenticated question-bank API on the public internet, and its
  certificate would depend on the other project's approval endpoint.
