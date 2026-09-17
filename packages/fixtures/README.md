# Engine fixtures

`vectors.json` is generated from the Python engine and read by both test suites
(ADR-0005):

```sh
make fixtures      # uv run python -m engine.fixtures packages/fixtures/vectors.json
```

Each case is `state + input → expected result` for one rule: a mastery update, a
retention calculation, a ladder step or a help decision.

**Never hand-edit this file.** If a rule changes, change it in `packages/engine`,
regenerate here, and review the diff in the same pull request — the diff is the
record of how student-facing behaviour changed. `packages/engine/tests/test_fixtures.py`
fails when the checked-in file is stale, and the TypeScript parity test fails when
the two implementations disagree.
