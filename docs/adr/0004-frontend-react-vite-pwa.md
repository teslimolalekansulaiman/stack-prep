# ADR-0004 · Frontend as a React + Vite installable web app

- **Status:** Accepted
- **Date:** 2026-09-17

## Context

The client must run on a 2 GB Android phone over a patchy mobile connection, and in
desktop Chrome in school computer labs during mock exams. Nearly every screen is
behind authentication, so search engine indexing is irrelevant. Practice must work
offline (ADR-0007). The product spec sets a first-load budget the app has to hold.

Maths and, later, chemistry notation appear in authoring, practice and mocks, and
must render identically in all three.

## Decision

A single-page application: **React 18 + TypeScript, built with Vite**, installable
as a progressive web app.

- **Routing:** React Router.
- **Server state:** TanStack Query (retries, cache, offline-aware refetching).
- **Local state:** Zustand.
- **Styling:** Tailwind CSS with Radix primitives for accessible components.
- **Forms:** React Hook Form with Zod schemas.
- **Notation:** KaTeX with the mhchem extension, in one shared component used by
  authoring, practice and mocks.
- **Charts:** uPlot for series, hand-written SVG for the class heatmap.
- **Budget:** ≤ 200 KB of JavaScript gzipped on first load, enforced in CI.

A Capacitor wrapper is the path to an app store listing if one is ever needed. No
second codebase.

## Consequences

- One client for phones and lab desktops, one deployment, instant updates.
- Discipline required on dependencies: every added library is measured against the
  bundle budget, and the CI check fails the build rather than warning.
- The marketing site stays separate and static, so its needs never inflate the app.

## Alternatives considered

- **Next.js.** Server rendering buys nothing behind a login, and adds a server
  runtime, bundle weight and complexity to the offline story.
- **React Native or Flutter.** A second codebase, and no help with lab desktops.
- **Svelte.** Smaller output, but a smaller hiring pool locally; the bundle budget
  is reachable with React and discipline.
