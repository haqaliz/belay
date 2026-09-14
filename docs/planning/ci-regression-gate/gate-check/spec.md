# Aspect: gate-check

## Problem slice

The core capability: given a baseline (banked, replayable) and a new capture of the same
run, decide — deterministically, with named causes — whether the new run regressed, and
exit non-zero when it did.

## User outcome

`belay gate check <trace> [--server -- CMD…] [--json]` answers "did the new agent version
break a previously-passing trajectory?" in CI, grounded in re-execution, with the exact
divergences named.

## In scope

- CLI: `belay gate check <trace>` (replay-bearing) with `--server` (override; default is the
  baseline's stored command), `--replays`, `--timeout`, `--shell-server`, `--json` (S1),
  `--run-id` fallback (S2), `--no-ingest` (see `divergence-banking`).
- Resolve baseline by run id; missing ⇒ exit 2, `BASELINE_NOT_FOUND`; identity mismatch ⇒
  exit 2, `IDENTITY_MISMATCH`.
- **Re-verify the baseline with the current engine** (replay) and verify the new capture;
  both sides use the same engine in the same run, so engine drift cancels.
- Diff verdicts per dimension, reusing the `corpus/run.py` model generalized from
  case-vs-expected to capture-vs-baseline:
  - SKIP-first: baseline not runnable / capability mismatch ⇒ named-cause abstention
    (`BASELINE_UNRESTORABLE`, `BASELINE_CAPABILITY_MISMATCH`), never a regression.
  - Exact equality per dimension on the recomputed verdict set; any new FAIL or worse
    status ⇒ `REGRESSION` with named `(axis, kind)` rows (expected vs observed).
  - New UNVERIFIED turns: named and reported, never fail alone.
  - Trajectory (`status`/`cause`/`evidence_count`) and claim dimensions compared when
    declared in the baseline.
  - Shape (turn count, tool sequence) reported as named `shape` divergences (S4),
    report-only.
- Exit contract: 0 no regression · 1 regression · 2 preflight, outcome rendered
  `UNVERIFIED` + named cause.
- `--json` report: run id, per-dimension divergences, coverage, exit-relevant summary;
  text renderer byte-identical in content.
- Flag parity declared in `tests/test_cli_flag_parity.py`; README/`--help` coverage line
  states what the gate checked (and that UNVERIFIED never renders as PASS).

## Out of scope

- Banking (baseline-bank) and corpus ingest (divergence-banking).
- Structural trajectory diffing as a hard fail (`--strict-shape` is N1).
- GitHub Action wiring / UI.
- Multi-baseline aggregation or trending.

## Acceptance criteria (written first)

1. **Regression:** a baseline re-verified against an injected trajectory change (new failing
   turn / changed tool sequence) yields `REGRESSION`, exit 1, named `(axis, kind)`
   divergences — never a silent pass.
2. **Clean:** an unchanged re-run yields exit 0 with a report byte-stable against the
   baseline's expected set.
3. **Abstention:** a missing baseline (exit 2, `BASELINE_NOT_FOUND`) and an unrestorable /
   cross-substrate baseline (`BASELINE_UNRESTORABLE` / `BASELINE_CAPABILITY_MISMATCH`)
   render `UNVERIFIED` + named cause — never a false clean, never a false regression.
4. **No false regression on nondeterminism:** a nondeterministic tool's turn is `UNVERIFIED`
   (named) and does not fail the gate alone.
5. **Parity guard green:** the flag-parity tests pass with the new surface declared.
6. Deterministic, no network, runs in the standard suite.

## Dependencies & sequencing

Depends on `baseline-bank`. Blocks `divergence-banking` (the bank hook) and `surface-docs`.

## Open questions

- Whether `gate check` verifies the new capture with the baseline's server command by
  default or requires `--server` when the capture's boundary differs. Default: stored
  command, override available; a boundary mismatch surfaces as a named UNVERIFIED, never a
  guessed replay.
- Report schema: reuse `verify/json.py` shape wrapped with a gate envelope, or a new
  `gate` schema. Default: gate envelope referencing the verify records — one computation,
  one renderer per contract.
