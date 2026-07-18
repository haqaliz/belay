# Aspect spec — phase0-runner

**Parent PRD:** `../prd.md` · **Aspect:** the must-have Scope-A core (batch driver + ledger +
report). The minting driver is a separate aspect (`../minting-driver/spec.md`).

## Problem slice & user outcome

The founder points the runner at a directory of captured traces and gets back **the number** —
a reproducible violation rate with its denominator, its false-positive rate, and its
UNVERIFIED-by-cause breakdown — proven end-to-end by a deterministic offline test. No verdict
logic changes; this consumes the C1–C6 engine and produces the first C6 corpus input.

## In scope

- A batch driver: directory of `trace-*.jsonl` (+ `.manifests` siblings) → per-trace verify loop
  → per-turn `TurnVerdict` → flag FAILs → `add_case` each flagged turn → write a run ledger.
- An **injectable verifier seam** (`verify_turn` by default) so the driver's arithmetic is
  testable cross-platform without real replay.
- A run **ledger** (JSON, gitignored run output) recording instance dispositions, per-status turn
  counts, flagged/addable/unaddable counts, and UNVERIFIED turns bucketed by named cause.
- A **report** renderer: headline per-instance violation rate + denominator, per-turn FAIL rate,
  UNVERIFIED rate by cause, FP-rate (= 1 − precision via `corpus.metrics.score`), and the
  **instrument-failure guard** (empty/no-verifiable-turn-dominated mint ⇒ "instrument suspect",
  never a clean 0%).
- A `belay phase0` subcommand group (`run`, `report`) mirroring the existing argparse pattern.

## Out of scope

- The live LLM-driven mint (that's the minting driver + a manual gate).
- Any change to `verify_turn`, `add_case`, `score`, or verdict logic (reuse verbatim).
- New verdict axes; A3; Linux substrate.

## Acceptance criteria (testable — written first)

Cross-platform (fake verifier seam / synthetic flagged run, no Seatbelt):
1. Given canned per-turn verdicts, an instance with ≥1 FAIL turn ⇒ disposition `verified-flagged`;
   ≥1 verifiable turn and no FAIL ⇒ `verified-clean`; a trace whose turns are all UNVERIFIED ⇒
   `no-verifiable-turns`; a verify/mint crash ⇒ `errored`.
2. Violation rate = `verified-flagged` / (`verified-clean` + `verified-flagged`), with
   `no-verifiable-turns` and `errored` reported as separate counts, never in the denominator.
3. **Instrument-failure guard:** a run where `no-verifiable-turns` (or empty traces) dominates is
   reported as "instrument suspect / UNVERIFIED-of-the-experiment", explicitly NOT a 0% violation
   rate. (Teeth: a stubbed all-empty mint must NOT render as clean 0%.)
4. A FAIL turn with a restorable pre-state is ingested via `add_case` (synthetic flagged-run
   pattern from `test_corpus_add.py`); a FAIL turn whose pre-state is unrestorable is counted
   `flagged-unaddable`, stays in the violation numerator, and is NOT dropped.
5. UNVERIFIED is never counted as PASS or as a violation; every UNVERIFIED turn carries a named
   cause in the ledger (buckets from `canonical_cause`).
6. The report never prints a rate without its denominator; `_ratio`-style 0-denominator ⇒ "n/a",
   never 1.0 or 0%.
7. FP-rate is pulled from `corpus.metrics.score` over the ingested+labeled cases (UNVERIFIED
   excluded), consistent with `belay corpus score`.
8. Ledger + report are deterministic given fixed inputs (no clock/network/random in the arithmetic;
   any timestamp is read at the CLI boundary and injected).

Darwin-gated (reuses `test_launch_demo` gated capture helpers), one e2e:
9. A real gated capture of a cheating fixture server (weakens a `tests/` file) → runner → the
   turn flags as A1 FAIL at the exact turn, ingests as a corpus case, and the report shows a
   non-zero violation rate. Proves the seam matches real replay. `skipif(sys.platform != "darwin")`.

## Dependencies & sequencing

- Depends on merged C1–C6 (all present). Reuses `verify_turn`, `add_case`, `score`, `set_label`,
  `read_trace`/`derive_correlation`/`tool_calls`, `canonical_cause`.
- Sequenced before the minting driver — the runner must consume traces deterministically before
  we bother producing real ones.

## Open questions / risks (aspect-specific)

- Subcommand naming `belay phase0 run/report` vs `belay corpus batch` — settle at Phase 1 of the
  plan; PRD leaves it open. (Leaning `belay phase0` to keep the gate legible and not overload
  `corpus`.)
- Report output location for the published writeup — a `docs/technical/PHASE0_RESULTS.md` template
  filled at the live gate; the runner emits machine-readable ledger + human report to stdout.
