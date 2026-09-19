# Local syllabus database and PDF loader

The loader imports the existing curated extraction in
`seeds/neco_gce_mathematics.yaml` from `docs/Math-syllabus.pdf`. It checks the PDF's
SHA-256 before any database write. The PDF stays on disk; PostgreSQL stores its
metadata, topic/subtopic/skill rows, and a page-linked evidence row for each item.
It does **not** infer prerequisites, mastery levels, exclusions, official validity
dates, or verified grading rules from the PDF.

## Run locally

PostgreSQL 14+, `psql`, Ruby and Poppler are available in this workspace. No Ruby
gems are required.

```sh
bash database/local-db.sh start
ruby database/load_syllabus.rb --dry-run
ruby database/load_syllabus.rb
```

The loader applies `migrations/001_curriculum.sql` when the schema is absent. It
uses the local project database `scorepilot` on `127.0.0.1:55439`. The cluster
also accepts a Unix socket in `.local/run`, but everything here connects over TCP:
a socket path is capped at 103 bytes and `.local` belongs to the main checkout, so
the socket is out of reach from a git worktree on both counts.
`.local/postgres` contains persistent data and is ignored by Git. The same
`127.0.0.1:55439` is what DBeaver wants. Use database
`scorepilot`, username `teslimsulaiman`, and leave the password blank. This local
development cluster uses trust authentication for loopback connections. Tables
are in the `stackprep` schema. Stop it with:

```sh
bash database/local-db.sh stop
```

For another PostgreSQL instance, set `DATABASE_URL` or pass `--database-url URL`.
The URL may contain credentials, so avoid pasting it into shared terminals or logs.
Use `--pdf PATH` to validate another copy of the **same** PDF; a different hash is
rejected. Use `--seed PATH` only for a reviewed extraction with `format_version: 1`.

## Current imported state

| Entity | Rows | Review state |
| --- | ---: | --- |
| Examination and subject | 1 each | Draft |
| Source document | 1 | Rights and review pending |
| Syllabus version | 1 | Draft, not current |
| Topics | 9 | Draft |
| Subtopics | 39 | Draft; two are structural containers added for the schema |
| Candidate skills | 114 | Draft |
| Evidence links | 162 | Pending |
| Mastery levels, prerequisites, explicit exclusions | 0 | Not asserted by this PDF |

The PDF does not establish the exact NECO external track or an official effective
date. The loader therefore leaves the examination and version in draft and stores
all imported `syllabus_status` values as `uncertain`, with pilot support
`undecided`. It also leaves delivery and
AI-context permissions false. The grading table in the YAML remains a source claim
and is not loaded into `examinations.grading_system`.

Rerunning the loader is safe: its IDs are deterministic, duplicate rows are skipped,
and the transaction checks that existing content matches the curated extraction.
It never resets a reviewer-approved row to draft. A changed extraction should be
reviewed and imported under a new draft syllabus version instead of silently
altering the old one.

## Check the result

```sh
psql -h 127.0.0.1 -p 55439 -d scorepilot \
  -c "SELECT item_type, count(*) FROM stackprep.curriculum_items GROUP BY item_type ORDER BY item_type;"

psql -h 127.0.0.1 -p 55439 -d scorepilot \
  -c "SELECT count(*) FROM stackprep.published_curriculum_scope;"
```

The published count should remain **zero** until the applicable official source,
content, rights and reviewer decisions are confirmed. The code is a loader and a
review queue, not an approval or a student-facing release.
