# Spec — aspect `section-extension`

**Problem slice:** the named v0.36.0 follow-up — budgeted-mode verify `--json` omits
skipped turns' scores, so the future ledger cannot audit what the budget skipped.

**In scope**
- `triage_section` (`src/belay/verify/triage_surfaces.py:228-263`): in budgeted mode,
  the `scores` list gains one row per **scored** turn (non-None score) — replayed rows
  unchanged, skipped rows marked `"skipped": true`. Abstentions (None scores) stay
  absent. **Shadow mode byte-unchanged** (it has no skipped turns — no marker is added
  there, so the on/off identity pin stays byte-identical).
- The text line (`cli.py:1456-1488`): `scored` now counts all scored turns including
  skipped ones; `skipped` unchanged. One computation, two renderers.
- Re-pin the budgeted-mode tests (`tests/test_verify_triage_surfaces.py:281-316`); the
  shadow-mode tests and the refutation identity test must pass **unmodified**.

**Out of scope:** the calibration math, the ledger command, any shadow-mode change.

**Acceptance (test-first)**
- Budgeted mode: scores rows include skipped turns with `"skipped": true`; replayed
  rows carry no marker; abstentions absent.
- Shadow mode: section byte-identical to v0.36.0's shape (the refutation test and the
  snapshot fixture pass unmodified).
- Text line reflects the new `scored` count without changing `skipped`.

**Dependencies:** none (slice-1 surfaces shipped). **Sequencing:** first — the ledger
command consumes the extended section.