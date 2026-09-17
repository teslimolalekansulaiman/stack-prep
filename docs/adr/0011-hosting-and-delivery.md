# ADR-0011 · Hosting and content delivery

- **Status:** Proposed — decide in S0 after a latency test from Lagos
- **Date:** 2026-09-17

## Context

Students are in Nigeria, on mobile data and in school labs. Traffic is seasonal:
quiet from June to December, peaking January to April, with sharp spikes when a
school runs a mock for a whole class at once.

No major cloud provider has a Nigerian region. The realistic options are South
Africa (AWS `af-south-1`, Azure South Africa North, GCP `africa-south1`) or Europe
(Ireland, London, Frankfurt). Routing from Lagos to Europe is often better provisioned
than intra-African routes, so this must be measured, not assumed.

The client is offline-first, which makes steady-state latency less critical than
the size and cacheability of what it downloads.

## Decision (proposed)

- **Application and worker:** containers on a platform with straightforward scaling.
  Fly.io (which has a Johannesburg region) for speed of setup, or AWS ECS Fargate
  in `af-south-1` if we want everything in one cloud.
- **Database:** managed PostgreSQL with point-in-time recovery, in the same region
  as the application.
- **Redis:** managed, same region.
- **Static assets and item bundles:** behind Cloudflare, which has a Lagos presence.
  Item bundles are immutable and content-hashed, so they cache at the edge.
- **Object storage:** S3 or Cloudflare R2 for item images and uploaded result slips.
- **Scaling:** scale the API and worker by schedule as well as load, since mock
  windows are known in advance.

**Before accepting this ADR:** measure round-trip time and download speed from a
Lagos mobile connection to candidate regions, and confirm current region
availability for each managed service.

## Consequences

- One region to start; no multi-region complexity.
- Cloudflare in front gives caching, TLS and basic protection in one step.
- Seasonal cost: size for the January–April peak, scale down afterwards.

## Alternatives considered

- **A VPS and manual setup.** Cheapest, and turns backups, failover and scaling into
  our problem during the exam season.
- **Serverless functions.** Cold starts and connection-pool pressure on PostgreSQL,
  for a workload that is steady while students are studying.
- **Hosting in Nigeria (local providers).** Lowest latency in principle; weaker
  managed-service and backup guarantees. Worth revisiting at scale.
