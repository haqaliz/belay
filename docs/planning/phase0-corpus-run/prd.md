# PRD — Phase-0 Corpus Runner

**Slug:** `phase0-corpus-run` · **Branch:** `feat/phase0-corpus-run/aliz` · **Owner:** aliz
**Capability:** the Phase-0 **gate** (between C5 and C6 in `CAPABILITY_ROADMAP.md`), not a new C-id.
**Status of engine:** C1–C6 merged (431 tests). This unit produces the *first real input* to C6.

---

## Problem Statement

Belay's engine is built (C1–C6) but **the corpus is empty and no violation-rate number has been
published.** Commit `5ed31f8` marks the Phase-0 gate *"reached"* (machinery built) — not
*cleared* (number published). `CLAUDE.md` names the next step verbatim: *"run the Phase-0 corpus
and publish the violation-rate number, then C7."*

The gate exists to answer the **only *Fatal* risk in the register, R1**: *does the engine catch
anything real?* If real agent runs contain ~no detectable violations, the premise is wrong and
every downstream capability (C7 console, C8 A3, C9 interop) is wasted effort — and it is worth
knowing in week 4, not month 6 (ROADMAP.md:23, 237).

**The missing artifact is a batch runner.** There is no run-many abstraction in the codebase
today (no `run_id`, no batch driver; `/runs/` is only a reserved gitignore convention).
Everything downstream — `verify_turn`, `add_case`, `run_corpus`, `score`, `set_label` — is
one-at-a-time and reusable as-is. **And `corpus score` cannot emit a violation rate**: nothing
records the total-runs denominator (`Metrics.total` is just `len(cases)`; every score denominator
derives from cases *present*). The runner must own that ledger.

**Evidence it's real:** 27–78% of benchmark-reported agent "successes" are corrupt successes
(arXiv 2603.03116); the A1 `tests/`-read-only invariant (`invariants.py:228`) is built precisely
to catch the cheating-agent class that A2 structurally cannot.

## Goals & Success Metrics

**Primary goal (this unit, Scope A):** a reproducible, CI-green **batch runner + report** that
takes N captured traces, verifies each, flags the FAILs, ingests them into the corpus, tracks the
total-runs denominator, and emits the number — proven end-to-end by a **deterministic, offline
acceptance test** against fixture servers. The live ≥50-instance mint that produces the published
number is a **separate, documented manual gate** (out of scope for "done" here — see Out of Scope).

**Success = all of:**
- `belay phase0 run` (name TBD in plan) ingests a directory of traces → verifies each turn
  in-process → adds every FAIL turn as a corpus case → writes a run **ledger** recording
  total-instances, total-turns, flagged, and UNVERIFIED-by-cause.
- `belay phase0 report` (or `--report`) prints **the number**: headline **violation rate =
  flagged-instances / total-instances**, plus per-turn FAIL rate, UNVERIFIED rate broken down by
  named cause, and FP-rate = 1 − precision (pulled from `corpus score`).
- A **deterministic offline acceptance test** drives fixture cheating servers
  (`weakening_editor_server`, `cheat_test_runner_server`) through the proxy via `conftest`
  helpers, runs the full trace → verify → flag → add → ledger → report pipeline, and asserts:
  a cheat trace flags at the exact turn (A1 FAIL), a clean trace does not, an UNVERIFIED turn is
  counted as UNVERIFIED (never PASS, never FAIL), and the report arithmetic matches hand
  computation. No network, no LLM, runs in CI.
- **Honesty preserved end-to-end:** UNVERIFIED is never rendered/counted as PASS or as a
  violation; every UNVERIFIED instance carries a named cause; the report never over-claims.

**Explicitly measurable at the live gate (Scope B follow-on, defined here, run later):**
reproducible violation rate with its denominator, ≥3 hand-audited true positives, a stated
false-positive rate, and an UNVERIFIED rate with every instance filed under a named cause
(ROADMAP.md:109–122). PROCEED if reproducible and non-zero; PIVOT if ~0.

## User Personas & Scenarios

- **The founder (now):** runs the runner over a set of minted traces to earn the Phase-0 number
  and decide go/pivot. Needs a *reproducible* harness so the number is credible — anyone can
  re-run it and reproduce it (reproducibility, not provenance, is what makes it credible,
  ROADMAP.md:94).
- **A skeptical reader (later):** re-runs the harness against the same traces and gets the same
  number. The deterministic acceptance test is their proof the pipeline is sound before they
  trust the live figure.

## Requirements

### Must-have (Scope A — this unit)

1. **Batch driver over traces.** Input: a directory of `trace-*.jsonl` files (+ their
   `.manifests` siblings). For each: `read_trace` → `derive_correlation` → `tool_calls` → loop
   `verify_turn(records, n, server_command=…, manifest_dir=…, invariants=default_invariants())`
   in-process. Read `TurnVerdict.status` directly (no shelling out; there is no `--json`).
2. **Flag rule.** A turn is flagged iff `TurnVerdict.status is FAIL`. UNVERIFIED and PASS are not
   flagged. (Kept distinct throughout — `verdict.py:34`.)
3. **Corpus ingest.** For each flagged turn, call `add_case(...)` (reuse verbatim, `add.py:97`)
   into `corpus/local/`, `human_label="pending"` (the engine never labels its own cases).
   A flagged turn with an unrestorable pre-state is recorded in the ledger as
   *flagged-but-unaddable* with its cause — never silently dropped.
4. **Run ledger (the denominator).** A machine-readable ledger recording: total instances, total
   `tools/call` turns verified, per-status turn counts (PASS/WARN/FAIL/UNVERIFIED), flagged
   instances, and UNVERIFIED turns bucketed by named cause. Lives under gitignored run output
   (contains real data — no egress). This is what `corpus score` structurally cannot hold.
5. **The report.** Emits the headline **violation rate = flagged-instances / total-instances**
   (denominator stated), plus per-turn FAIL rate, UNVERIFIED rate by cause, and FP-rate =
   1 − precision (from `score`). Never prints a rate without its denominator; never folds
   UNVERIFIED into PASS or into violations.
5a. **Instance disposition states (denominator discipline).** Each instance resolves to exactly
   one of: `verified-clean` (≥1 verifiable turn, no FAIL), `verified-flagged` (≥1 FAIL turn),
   `no-verifiable-turns` (a trace with zero turns Belay could verify — e.g. all UNVERIFIED, or
   handshake-only), or `errored` (mint/verify crashed). The plan MUST state which states sit in
   the violation-rate denominator. Default: violation rate = `verified-flagged` /
   (`verified-clean` + `verified-flagged`); `no-verifiable-turns` and `errored` are reported as
   **separate counts**, never folded into the clean bucket.
5b. **Instrument-failure guard (R6 false-zero defense).** The report MUST distinguish "0%
   violations across N instances that each captured ≥1 `tools/call` turn" from "instances
   captured ~no turns." A mint dominated by `no-verifiable-turns` / empty traces is reported as
   **UNVERIFIED-of-the-experiment (instrument suspect)**, explicitly NOT as a clean 0% violation
   rate. This is the single most important honesty property of the report: it makes a real PIVOT
   signal impossible to confuse with a broken instrument.
5c. **Flagged-but-unaddable path.** A FAIL turn whose pre-state cannot be restored (so `add_case`
   raises, `add.py:122`) is still a caught violation. The ledger counts these separately and the
   report includes them in the violation numerator (they were flagged) while noting they are not
   replayable corpus cases. They are never silently dropped.
6. **Deterministic offline acceptance test** (the shippable proof) — as specified in Success.
7. **Honesty tests with teeth:** assert UNVERIFIED is counted in neither the violation numerator
   nor the clean bucket; assert the report refuses a denominator-less rate.

### Should-have

8. **The minting driver** — a thin, sequential, BYOK MCP agent loop that drives file/shell ops
   through MCP filesystem+shell servers behind the proxy, **one `tools/call` at a time** (so R6
   and R7 are satisfied by construction). Lives under `eval/` (or `scripts/`), **NOT** in the
   `belay` product CLI, and is documented as eval/mint infrastructure, **not an agent framework**
   (guardrail #1). Its own acceptance is a single-instance smoke run, gated manual (uses a live
   model) — never in CI.
9. **Instance-selection helper / notes** for macOS-runnable SWE-bench-lite instances (no Docker).

### Nice-to-have

10. A `--sample N` mode for the small live pilot (Scope C shape), so a ~5–10 instance proof can
    publish a preliminary number with an honest `n=` caveat.

## Technical Considerations

- **Where code lands.** Net-new `src/belay/phase0/` (batch driver + ledger + report) with a
  `belay phase0` subcommand group in `cli.py` (matches the existing argparse-subparser pattern).
  Reuses verbatim: `verify_turn` (`turn.py:140`), `add_case` (`add.py:97`), `score`/`Metrics`
  (`metrics.py:114`), `set_label` (`curate.py:34`), `read_trace`/`derive_correlation`/
  `tool_calls`. The **minting driver is separate** (`eval/`), product-CLI-free, BYOK.
- **Capture wiring (for the live gate).** `python -m belay.proxy <mcp-server…>` with
  `BELAY_TRACE_DIR` + `BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` (snapshot dir required when
  scope set, `proxy.py:544`). One invocation = one trace file. Agent points at the proxy by
  naming it as its MCP server command (`test_real_client.py:43`).
- **Determinism.** The runner itself is deterministic given fixed traces (verify re-executes but
  against restored pre-state; the acceptance test uses fixture servers, no clock/network). The
  *live mint* is non-deterministic (real LLM) and is the reason for the Scope A/B split — same
  pattern the roadmap reserves for C8's model seam (never in CI, manual gate).
- **Verdict impact: none.** This unit changes no verdict logic. It **exercises A1** (tests/
  read-only, the cheat catcher) and **A2**, and feeds C6. No new axis; A3 does not exist yet
  (no `--no-claim-axis`).
- **UNVERIFIED path.** Explicit and first-class: an unrestorable/nondeterministic/no-manifest
  turn stays UNVERIFIED, is bucketed by cause in the ledger, excluded from the violation
  numerator, and reported separately. This is the honesty contract as code (ROADMAP.md:114).

## Risks & Open Questions

- **R1 (Fatal) — the premise.** This whole unit exists to test it. Mitigated by making the number
  reproducible; the runner is the instrument, the live gate is the experiment.
- **R6 (High) — the MCP boundary → false zero.** If the minting agent edits via built-in
  `Bash`/`Edit`, traces are empty. Mitigated by the sequential MCP driver routing all file/shell
  through MCP servers; **verified with ONE instance before scaling.** The runner's report must
  surface "turns captured per instance" so an all-empty mint is visible, not silently a zero.
- **R7 (Med→High) — batching → UNVERIFIED dominates** (README:159). The default agent batches
  concurrent `tools/call` → `unrestorable`. Mitigated by the driver issuing one call at a time.
  If UNVERIFIED still dominates in the live gate, that is itself a gate signal (R7), not a bug to
  hide.
- **macOS-only engine** (README:156). `verify_turn`/`run_case` SKIP off-darwin. The instance
  workspace + test run must live on the macOS filesystem; Docker/Linux-only instances are out of
  scope for v0 minting. Instance curation is real work (should-have #9).
- **Guardrail #1 — "no agent framework."** The minting driver is the one place this could drift.
  Resolved: it is eval/mint infrastructure, sequential and minimal, kept out of the product CLI,
  documented as non-product. Flagged, not papered over.
- **Open:** exact subcommand naming (`belay phase0 run/report` vs `belay corpus batch`) — settle
  in tech-plan. Report output location for the published writeup (a `docs/technical/
  PHASE0_RESULTS.md` template filled at the live gate) — settle in tech-plan.

## Out of Scope

- **The live ≥50-instance mint and the published number itself** (Scope B). Defined here as the
  follow-on gate; not part of "done" for this unit. Requires live LLM + wall-clock + manual audit.
- **Any new verdict logic or axis.** Untouched.
- **A3 / claim re-derivation.** Does not exist yet; not referenced.
- **Linux/Docker substrate.** The engine is macOS-only; a Linux slice is a separate future unit.
- **Shipping the minting agent as a product surface.** It is eval infra only.

## Definition of Done (this unit)

Code merged on `feat/phase0-corpus-run/aliz` with: the `belay phase0` batch runner + ledger +
report, the sequential MCP minting driver under `eval/` (should-have), a **deterministic offline
acceptance test** proving the full pipeline against fixture cheating servers, honesty tests with
teeth, and `uv run pytest` green. The live mint is a documented, runnable next step — not a
prerequisite for merge.
