# Analysis

Calibration scripts and notebooks. This is where milestone M5 work lives: fitting
item difficulty, the session gain `g`, session minutes and score-range widths from
pilot data.

Rules that keep analysis and production honest:

- Read from pseudonymised exports, never from production tables directly.
- Every figure quoted in a report must be reproducible from a script or notebook
  committed here, with the data snapshot it used.
- Fitted parameters are written out as a versioned JSON file and loaded by
  `packages/engine`. Analysis never changes engine code directly.
- Notebooks are run with papermill so a report can be regenerated end to end.
