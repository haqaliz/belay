# Spec — surfaces (`--no-claim-axis` + wiring)

> Part of `claim-re-derivation-a3` (C8). PRD: `../prd.md`.

## Problem slice

Wire the A3 evaluator into every surface where it can run, gate it behind `--no-claim-axis`, and
make the refutation a test. The deterministic spine's outputs must be byte-identical with the
axis on or off.

## In-scope

- **`--no-claim-axis`** on `belay verify`, `belay phase0 run`, `belay corpus run` — precedent:
  `--no-default-invariants` (`src/belay/cli.py:2248-2255`). Declared in the CLI parity guard
  (`tests/test_cli_flag_parity.py:45-75, 111-125`). With the flag, A3 is absent everywhere.
- **Instance-level evaluation** at trace close, gated: the same three call sites as the
  trajectory rule — `belay verify` (`src/belay/cli.py:738-750`), `phase0 run`
  (`src/belay/phase0/runner.py:369-384`), `corpus run` recompute (`src/belay/corpus/run.py:479-543`).
  `--turn N` never evaluates A3 (partial facts would be fabricated — same rule as the
  trajectory seam, `cli.py:738-742`).
- **Rendering**:
  - Text: instance-level A3 line beside `_emit_trajectory` (`cli.py:979-1018`); A3 sub-verdicts
    already render per-axis (`cli.py:789-791`). The check's source + real exit code in the
    message. Coverage line names the axis when absent (no author configured) — absent, not
    UNVERIFIED, never PASS.
  - JSON: an A3 record following `trajectory_record` (`src/belay/verify/json.py:192-214`),
    with check source + exit code fields (pattern: `_subverdict_record` special case,
    `json.py:123-130`).
- **Cause bucketing**: `A3/...` prefix labels in `canonical_cause._PREFIX_LABELS`
  (`src/belay/replay/report.py:140-158`), ahead of the `REPLAYED_SUB_VERDICT` catch-all — else
  A3 UNVERIFIEDs bucket blandly.
- **Phase0 disposition**: A3 FAIL → `VERIFIED_FLAGGED` (same bucket as trajectory FAIL,
  `src/belay/phase0/runner.py:501-511`); A3 UNVERIFIED never flags. Ledger/report surfaces carry
  the A3 summary **absent-never-zero** (`src/belay/phase0/ledger.py:163-184, 257-278`,
  `report.py:291-366` pattern).
- **The refutation test** (acceptance 1, `CAPABILITY_ROADMAP.md:792-795`): run the corpus with
  and without `--no-claim-axis`; assert every PASS and every FAIL verdict is identical — turns
  and instance-level alike. Must include at least one A3-bearing case (from aspect `corpus`).
- **Zero-LLM guard update** (`tests/test_verify_zero_llm.py:124-153`): deliberate, visible
  decision — the A3 author import is behind the seam and exempted only where execution decides.

## Out-of-scope

- The evaluator itself (aspect `evaluator`), the author (aspect `author`), corpus case schema
  (aspect `corpus`), demo fixtures (aspect `demo-acceptance`).
- Console changes: the console renders `--json`; no console code exists that needs editing
  unless the JSON contract change demands it (check at plan time; prefer none).

## Acceptance criteria (test-first)

1. `--no-claim-axis` accepted by all three commands; parity guard declares it; unknown flag on
   any command fails cleanly.
2. Refutation test over the corpus: identical PASS/FAIL with and without the flag — this test
   "must never be weakened" (its docstring says so).
3. `--turn N` runs never emit an A3 verdict (asserted).
4. A3 verdict renders in text and JSON with check source + real exit code; absent axis renders
   as named-absent on the coverage line, never as PASS and never as a bogus UNVERIFIED.
5. `canonical_cause` maps every `A3/<kind>` prefix to its named bucket (ordered-before-catch-all,
   asserted like the boundary entries `report.py:134-139`).
6. Phase0: A3 FAIL flags the instance; A3 UNVERIFIED does not; ledger/report absent-never-zero.

## Dependencies

- Aspects `evaluator`, `author`, `corpus` (the refutation needs a banked A3 case).
- C1–C7 (all shipped).

## Open questions

- Whether `belay phase0 run` takes `--claim-author` or env-only (`BELAY_CLAIM_AUTHOR`).
  Recommend env-only for phase0/corpus + flag on verify. Decide at plan time.