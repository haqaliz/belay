# Spec — evaluator (A3 engine core)

> Part of `claim-re-derivation-a3` (C8). PRD: `../prd.md`. Parent decisions D1–D3 confirmed 2026-09-02.

## Problem slice

The pure A3 engine: given a trace's claim, a check author, and sandbox access, produce at most one
A3 verdict — or silence. Everything else (flags, surfaces, corpus, demo) consumes this.

## In-scope

- `src/belay/verify/claims.py`:
  - `evaluate_claim(...)` — instance-level evaluator beside `evaluate_trajectory_rules`
    (`src/belay/verify/trajectory.py:575-622`). Inputs: claim text + seq (via
    `extract_claim`, `trajectory.py:227-245`), classification (reuse `classify_claim_text`,
    `trajectory.py:112-126` — **no vocabulary extension**), author seam, check-runner seam,
    manifest dir + server command (to materialize the final state), timeout.
  - Decision table (all rows tested):
    | Condition | Result |
    |---|---|
    | No author configured | **absent** (None — axis named on coverage, never UNVERIFIED) |
    | No claim record | UNVERIFIED `NO_CLAIM_RECORDED` |
    | Claim not VERIFICATION-classified | UNVERIFIED `CLAIM_UNCLASSIFIABLE` |
    | Final state unrestorable / final turn unreplayable | UNVERIFIED `FINAL_STATE_UNOBSERVABLE` |
    | Author returns no executable check | UNVERIFIED `NO_CHECK_AUTHOR` |
    | Check fails to launch / times out | UNVERIFIED `CHECK_DID_NOT_EXECUTE` / `CHECK_TIMED_OUT` |
    | Check exits non-zero | FAIL (observed = exit code + output) |
    | Check exits 0 | **silence** (None — D3; silence is not PASS) |
  - `Verdict(axis="A3", kind="claim", status=FAIL|UNVERIFIED, observed=<exit code>,
    expected=<"exit 0">, message=<check source + real exit code>)` — the check's **source** and
    **real exit code** always surface (`CAPABILITY_ROADMAP.md:788`).
  - Closed cause vocabulary, module-level constants (conventions: `trajectory.py:136-147`).
- `CheckAuthor` Protocol + `Check` result type (`source: str`, `argv: list[str]` or script +
  declared interpreter). Injectable; deterministic fakes in tests.
- `CheckRunner` seam: `run_check(check, *, workspace, timeout) -> CheckResult(exit_code, output,
  error)`; real implementation uses `contained` (`src/belay/sandbox/launch.py:188-248`),
  network deny-all, cwd = the materialized final workspace.
- Final-state materialization: replay the final turn through the existing engine
  (`src/belay/replay/engine.py:479-709`) into a scratch dir; run the check in the resulting
  workspace. Never mutate live state, never the original trace.

## Out-of-scope

- CLI/flag wiring (aspect `surfaces`), corpus banking (aspect `corpus`), demo fixtures
  (aspect `demo-acceptance`), the model-backed author (aspect `author`).
- Per-turn A3; `verdict.reduce` changes; A1/A2 changes; trajectory vocabulary changes.

## Acceptance criteria (test-first)

1. Every decision-table row above is a test; each UNVERIFIED carries its named cause.
2. **Property test**: `evaluate_claim` cannot produce a `PASS` verdict for any input — exhaustive
   over the status enum and over the decision table (acceptance 2 of
   `CAPABILITY_ROADMAP.md:796-797`).
3. A check that fails to execute yields UNVERIFIED, never a guess (acceptance 3).
4. Exit 0 yields silence — no sub-verdict, asserted explicitly (D3).
5. The check's source and real exit code are present in every A3 verdict's message/fields.
6. Author + runner are injectable seams; tests use deterministic fakes; no model call anywhere
   in the test path (acceptance 5).
7. Deterministic, no network (fake runners; the real `contained` path exercised on the host
   substrate, darwin-gated where the sandbox is).

## Dependencies

- C1–C6 (all shipped). Reuses `extract_claim`, `classify_claim_text`, replay engine,
  `contained`, snapshot restore. Nothing new outside `src/belay/verify/` (+ tests).

## Open questions

- Final-turn replay cost: the evaluator replays the final turn once more. Acceptable for v0
  (one replay per trace); a caller-supplied workspace param can short-circuit later.
- Whether `CHECK_TIMED_OUT` folds into `CHECK_DID_NOT_EXECUTE` (decide at plan time; a single
  cause keeps the vocabulary smaller).