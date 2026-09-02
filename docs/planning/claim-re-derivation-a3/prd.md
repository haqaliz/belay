# PRD — claim-re-derivation-a3 (C8, axis A3)

> Owner: aliz · Branch: `feat/claim-re-derivation-a3/aliz` · Date: 2026-09-02
> Source: `docs/planning/_card/issue.md` (belay-next handoff brief, confirmed) ·
> `docs/planning/claim-re-derivation-a3/understanding.md` (Phase-2 dig).
> Capability: **C8** in `docs/technical/CAPABILITY_ROADMAP.md:768-808` — the last unshipped
> C-capability. All requirements below cite that spec's acceptance list unless noted.

## Problem Statement

Belay verifies agent steps by re-execution (A1 invariant, A2 replay). Neither axis can catch
**intent drift**: a faithful trace, in-policy actions, wrong meaning — e.g. an agent that edits
source, never runs the suite, and claims *"all tests pass."* A1's trajectory rule catches the
*shape* (claim without command evidence); nothing checks whether the **claim itself is true**.
C8 adds axis A3: a model *writes* an executable check for the agent's asserted post-conditions
(the trace's `claim` record); the engine *executes* it in the sandbox against the recorded final
state; the **exit code — not the model's opinion — decides**. It is the axis that gets *better as
base models improve* (a stronger model writes better checks) and the one the Phase 1→2 gate
requires: *"no shipped PASS is ever produced by A3, verified by test"* (`docs/ROADMAP.md:288`).

## Goals & Success Metrics

- **A3 ships subordinated and refutable** (`docs/ROADMAP.md:271`): `--no-claim-axis` disables it;
  every PASS/FAIL verdict survives unchanged — enforced by a test that must never be weakened
  (acceptance 1, `CAPABILITY_ROADMAP.md:792-795`).
- **A3 can never emit PASS** — property test, exhaustive over the status enum (acceptance 2,
  `CAPABILITY_ROADMAP.md:796-797`).
- **A synthesized check that will not execute yields UNVERIFIED**, never a guess (acceptance 3,
  `CAPABILITY_ROADMAP.md:798`).
- **The demo stays green with A3 present**, and a corrupt-success fixture yields **A3 FAIL
  corroborating A1 trajectory FAIL from an independent axis** (acceptance 4, re-scoped 2026-09-02 —
  the launch demo shipped as the negative control; see `docs/planning/launch-demo/` and decision D1).
- **Model calls sit behind an injectable seam and never run in CI** — fake injected; the live
  path is a manual gate (acceptance 5, `CAPABILITY_ROADMAP.md:801-802`).
- **Corpus compounds**: every A3 FAIL banks a labeled **intent-drift** case; the synthesized
  checks themselves are stored (eval data, `CAPABILITY_ROADMAP.md:804-806`).
- **Zero runtime dependencies preserved** (`pyproject.toml:44`) — no model SDK in the wheel.

## User Personas & Scenarios

- **Engineer running an agent unattended** ("did this run actually do the right thing?"): sees, at
  trace close, the instance-level line — the A1 trajectory verdict *and* the A3 claim verdict with
  the generated check's source and real exit code.
- **Operator of the mint/corpus**: intent-drift FAILs bank as labeled cases; `corpus run` replays
  them; `corpus score` measures A3 precision against human labels.

## Requirements

### Must-have (acceptances 1–5, test-first)

1. **A3 evaluator** (`evaluate_claim`-shaped, instance-level, beside `evaluate_trajectory_rules`):
   reads the trace's `claim` record (`src/belay/trace.py:389`, `src/belay/replay/reader.py:63-69`),
   reuses `classify_claim_text` (`src/belay/verify/trajectory.py:112-126`) as the trigger gate,
   materializes the recorded final state (replay of the final turn through the existing engine),
   runs the synthesized check in the sandbox (`contained`, network deny-all, bounded timeout),
   and emits at most one `Verdict(axis="A3", kind="claim", ...)`.
2. **Verdict contract** (hard, enforced by tests): A3 emits only WARN / FAIL / UNVERIFIED —
   **never PASS**; exit 0 → **silence** (no sub-verdict; decision D3); non-zero exit → FAIL;
   check cannot execute / timeout / unrestorable final state / no claim / unclassifiable claim →
   UNVERIFIED with a named cause from a **closed vocabulary**; every A3 verdict surfaces the
   check's **source** and **real exit code** (`CAPABILITY_ROADMAP.md:788`).
3. **`--no-claim-axis`** on every surface where A3 can evaluate (`belay verify`, `belay phase0 run`,
   `belay corpus run`), declared in the CLI parity guard (`tests/test_cli_flag_parity.py:45-75`).
   With the flag: A3 absent; A3-bearing corpus cases SKIP with a named cause (never REGRESS).
4. **Refutation test** (acceptance 1): run the corpus with and without `--no-claim-axis`; every
   PASS and every FAIL verdict identical — this test is the company's positioning encoded as CI.
5. **Property test** (acceptance 2): A3 cannot produce PASS for any input.
6. **Check-author seam** (decision D2): `CheckAuthor` protocol, injectable; deterministic fakes in
   tests; out-of-process BYOK reference author via subprocess (local CLI / local model / user
   script — nothing leaves the box, no vendor key). No author configured → the axis is **absent
   and named on the coverage line** (never UNVERIFIED, never PASS).
7. **Surfaces**: instance-level A3 line in `belay verify` text + `--json` (`src/belay/verify/json.py:192-214`
   pattern), phase0 disposition (A3 FAIL → `VERIFIED_FLAGGED`, alongside trajectory FAIL,
   `src/belay/phase0/runner.py:501-511`), ledger/report surfaces (absent-never-zero),
   `A3/...` labels in `canonical_cause` (`src/belay/replay/report.py:140-158`).
8. **Corpus**: intent-drift case (schema v5, mirroring the v4 `trajectory` field,
   `src/belay/corpus/case.py:82-88`), banked from A3 FAIL, recomputed by `corpus run` (MATCH /
   REGRESSION / STILL_MISSED / MISS_CLOSED), scored by `corpus score` (existing TP/FP machinery,
   `src/belay/corpus/metrics.py:236`).
9. **Demo acceptance** (acceptance 4, re-scoped — D1): the committed demo capture
   (`demo/capture/trace-20260827T001428Z-e23f999d.jsonl`) stays all-green with A3 present
   (check exits 0 → silence); a synthetic corrupt-success fixture (claim VERIFICATION, command
   tool offered but never used, suite fails at final state) yields **A3 FAIL and A1 trajectory
   FAIL on the same fixture** — the independent-axis corroboration.
10. **Zero-LLM guard updated deliberately** (`tests/test_verify_zero_llm.py:124-153`): the A3
    model import lives behind the injectable seam — never sidestepped.

### Should-have

- A3 coverage line on `belay interop correlate` and the console surface (the console renders
  `--json`; if the JSON gains an A3 record, the console renders it — no console code required
  beyond what `--json` already carries).
- The generated check and its exit code persisted with the case, so `belay corpus show` can
  render them.

### Nice-to-have

- WARN path for a check that exits non-zero but whose meaning is ambiguous (deferred — the v0
  WARN vocabulary stays empty; FAIL/UNVERIFIED/silence only).

## Technical Considerations

- **Axis placement**: A3 is **instance-level by construction** — the claim is session-level, and
  the check runs against the recorded final state. It sits beside `evaluate_trajectory_rules`
  (`src/belay/verify/trajectory.py:575-622`) at the three call sites (verify CLI `cli.py:738-750`,
  phase0 runner `runner.py:369-384`, corpus recompute `src/belay/corpus/run.py:479-543`).
- **Final state**: materialized by replaying the final turn through the existing engine
  (restore pre-state → invoke recorded call → post-workspace), then executing the check in that
  workspace under `contained` (`src/belay/sandbox/launch.py:188-248`), network deny-all.
- **`verdict.reduce` is untouched** — it is already axis-agnostic and guarantees the downgrade-only
  property structurally (`src/belay/verify/verdict.py:17-21, 99-117`). `NOT_COVERED` semantics,
  A1 and A2 are untouched.
- **BYOK / zero-dep**: the reference author is out-of-process (subprocess contract: JSON on stdin,
  JSON on stdout); the wheel gains no dependency (`pyproject.toml:44`). The live-model path is a
  manual gate (`manual` marker), never CI.
- **Determinism**: everything but the author is deterministic; the author is the only
  nondeterministic element and sits behind the seam; tests use fakes.
- **Naming**: module `src/belay/verify/claims.py`; rule/evaluator name `claim-re-derivation`;
  closed cause vocabulary `NO_CLAIM_RECORDED` / `CLAIM_UNCLASSIFIABLE` / `NO_CHECK_AUTHOR` /
  `CHECK_DID_NOT_EXECUTE` / `CHECK_TIMED_OUT` / `FINAL_STATE_UNOBSERVABLE` (final set at spec time,
  following `trajectory.py:136-147` conventions).

## Risks & Open Questions

- **R4** ("LLM judge with extra steps", `docs/ROADMAP.md:367`): the refutation test + property
  test + `--no-claim-axis` are the mitigation and ship as tests, never as intent. The demo/
  surfaces must never render A3 as a judge (exit code and check source are the rendered facts).
- **R7** (UNVERIFIED becomes the default): A3 abstentions are closed-cause-named; the "no author
  configured" state is *absence*, named on the coverage line — not an UNVERIFIED storm.
- **Synthesized checks that don't execute** (the harder feasibility risk from the card): the
  check author is a model; v0's bar is *an executable artifact with a declared argv*; anything
  else is `CHECK_DID_NOT_EXECUTE` (UNVERIFIED). The eval data (which checks execute) measures the
  thesis directly (`CAPABILITY_ROADMAP.md:804-806`).
- **Open (resolved in this PRD where marked)**: D1 (acceptance-4 re-scope), D2 (author seam),
  D3 (exit-0 silence) — all confirmed 2026-09-02. Open at spec time: exact final-state
  materialization when the final turn is unrestorable vs un-replayable (causes may split);
  whether `belay verify` should accept a `--claim-author` flag or read an env var (recommend
  env var `BELAY_CLAIM_AUTHOR` + flag, mirroring `--server`).

## Out of Scope

- **C9 export-back** and **GHCR publish** (deferred by name — see
  `docs/planning/observability-interop/prd.md:184-193`, `docs/planning/docker-selfhost/prd.md:71`).
- Extending the A1 trajectory-rule claim vocabulary (recorded decision 2026-08-12,
  `docs/planning/trajectory-toolset-rescope/prd.md:164-166`); A3 reuses the classifier as-is.
- Per-turn A3 verdicts (no per-turn claim exists); A3 never rewrites a turn verdict.
- Any agent framework surface, any bare-LLM-judge rendering, any raw-data egress or vendor key.
- The `check` grammar: v0 accepts an executable artifact the author declares (script or argv);
  no structured check DSL.