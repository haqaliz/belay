# Spec — aspect `calibration-math`

**Problem slice:** the pure measurement — reliability curve, ECE, and the
violations-skipped × budget-saved sweep, with the house rate discipline (None for
0-denominator, never 1.0).

**In scope**
- `src/belay/verify/calibration.py` (new, stdlib only — the zero-LLM guard auto-scans
  `verify/`): pure functions over typed rows, no JSON/document concerns:
  - `reliability_curve(rows)` — **equal-width decile bins** on confidence [0,1]
    (pinned at the review gate): per bin, n, mean confidence, observed violation
    rate; an empty bin renders `"no data"` (rate None, never 0).
  - `ece(rows)` — expected calibration error over non-empty bins:
    Σ(n_bin/N × |rate_bin − conf_bin|); 0 for an empty set is a *named* refusal, not
    a number (the caller refuses before this is reached).
  - `threshold_sweep(rows, candidates)` — per candidate threshold: violations-skipped
    (violated rows with score < threshold), budget-saved (skipped rows / total);
    plus a top-N sweep over the same rows.
  - `LedgerRow` dataclass: `ordinal, score, confidence, violated` — the document
    mapping (turns with a decided verdict only) is the ledger-command aspect's job.
- Rate discipline copied from `corpus/metrics.py:149-155`: None for 0-denominator.

**Out of scope:** document parsing, rendering, the CLI, the section extension.

**Acceptance (test-first)**
- Known sets pin the decile bins, the ECE value, and the sweep table **exactly**
  (byte-pinned fixture values, computed by hand in the test).
- Empty bins render `"no data"`, never 0; 0-denominator rates are None, never 1.0.
- Deterministic: no clock, no randomness, no filesystem — the same input yields the
  same output (asserted structurally and by re-run).

**Dependencies:** none. **Sequencing:** second (parallel-safe with
`section-extension`).