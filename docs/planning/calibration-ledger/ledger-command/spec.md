# Spec — aspect `ledger-command`

**Problem slice:** `belay triage-ledger` — the pure re-render command that turns a
stored `verify --json` document into the calibration measurement.

**In scope**
- `src/belay/cli.py`: the `triage-ledger` leaf subcommand (insertion point near
  `cli.py:4486-4488`) + `_cmd_triage_ledger` (the `_cmd_phase0_report` load shape,
  `cli.py:3007-3022`: fail-closed exit 2 on missing/malformed input).
- `src/belay/verify/triage_ledger.py` (new): document → rows mapping and the text +
  `--json` renderers (deterministic, byte-stable; "one computation, two renderers").
  Mapping: `triage.scores` rows joined to `turns` by `ordinal`; FAIL → violated=True,
  PASS/WARN → False; **UNVERIFIED turns excluded with the count stated**; skipped rows
  (the `"skipped": true` marker) excluded from the calibration column (no verdict) and
  counted; abstentions absent.
- Refusals: a document with **no `triage` section** ⇒ exit 2 named (never a ledger
  over a document that ran no triage); a document with **zero decided rows** ⇒ the
  named refusal rendered, no rates, **exit 0** (the INSTRUMENT SUSPECT shape —
  `phase0/report.py:65-75`; a measurement, not a gate).
- `--json` output flag; widen the flag-parity `--json` row
  (`tests/test_cli_flag_parity.py:114`) in the same commit.
- Docs: README quickstart line + ROADMAP/CAPABILITY_ROADMAP C10 slice-2 lines; the
  STATUS/CLAUDE/CHANGELOG entries land at merge.

**Out of scope:** multi-document aggregation, budget auto-tuning, the mint re-run.

**Acceptance (test-first)**
- Demo capture + stub triage author (shadow mode) → `belay triage-ledger` renders:
  0 violations, denominator stated (7 turns, 7 decided, 0 excluded), exit 0 — the
  mechanics proven on real data.
- A synthetic document with known rows pins the rendered reliability bins, ECE, and
  sweep table exactly (`--json` byte-stable).
- UNVERIFIED and skipped rows: excluded from the column, counted in the report.
- 100%-UNVERIFIED document ⇒ named refusal, no rates, exit 0.
- No `triage` section ⇒ exit 2 named.
- Same document twice ⇒ byte-identical output (the re-render discipline, pinned).
- Flag-parity guard green with the widened `--json` row.

**Dependencies:** `section-extension` (the skipped rows) + `calibration-math`.
**Sequencing:** third.