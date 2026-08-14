# PRD — Mint Shell Toolset Run

> The Phase-0 mint under the shell-offered toolset. The measurement every prior unit
> deferred (`docs/planning/trajectory-toolset-rescope/prd.md:170`): fresh stage runs,
> the ≥50-instance denominator, and the pre-registered gate decision line — or an
> honest STOP/VOID with named causes. The launch checklist's L1
> (`docs/planning/launch-readiness/CHECKLIST.md`).

## Problem Statement

Phase 0's gate has never cleared. The hand-audit PIVOTed on `precision 0.00`
(`docs/ROADMAP.md:127-135`); the funded re-mint was **voided by its own control
gate** — 5/5 trajectory FAILs were false positives by construction, because the mint
boundary offered 14 filesystem tools and **no command tool**, so the trajectory
rule's evidence was impossible to produce (`docs/planning/phase0-remint/`, decision
log 2026-08-09). Risk **R1** — *"real agent runs contain ~no detectable violations"* —
remains quantitatively untested (`docs/ROADMAP.md:327`).

v0.17.0 closed the gap: a **shell server on the mint boundary**
(`--toolset filesystem+shell`, verbatim `run_process`, per-instance `cwd`), the
ability-aware abstain, and re-scoped controls. What remains is to **run the mint**
under this toolset, once, under the freeze protocol, and record what the trajectory
axis's first real-text measurement says — the number, the audit, the decision.

The roadmap forbids launching without this: *"Do NOT launch and hope"*
(`docs/ROADMAP.md:211`), and the launch is *"on the strength of the Phase-0 number"*
(`docs/ROADMAP.md:217`).

## Goals & Success Metrics

- **Primary: a gate decision line, decided on committed evidence.** PROCEED iff ≥3
  **independent** hand-audited true positives survive audit AND the violation-rate
  denominator is **≥50** AND `INSTRUMENT SUSPECT` did not fire — the canonical
  pre-registered block, `docs/planning/phase0-live-mint/prd.md:53-71`.
- **The number is reported, never thresholded** — rate with its denominator, the
  false-positive rate stated, every UNVERIFIED filed under a named cause, exposure
  on both lines (file-comparisons and trajectory judged/abstained by cause).
- **An honest ~0 is a decision, not a failure** — a healthy-instrument near-zero
  with exposure reads as evidence about the premise (Rule B,
  `phase0-remint/prd.md:193-198`); a control FAIL voids the mint regardless of later
  adjudication (D-3).
- **Reproducible from the repo** — ledgers committed, `belay phase0 report`
  re-renders each stage's rate byte-identically from a clean checkout
  (REPRODUCIBILITY gate).
- **Launch checklist L1** (`docs/planning/launch-readiness/CHECKLIST.md`) marked ✅
  (PROCEED) or explicitly kept open with the decision recorded — never skipped.

## User Personas & Scenarios

The user of this unit is the owner/adjudicator. Scenarios: (1) gate PROCEEDs → the
launch checklist advances; (2) the mint voids → the D-3 record is published and the
instrument fixed before re-running; (3) healthy ~0 with exposure → PIVOT on the
premise, recorded as evidence about R1, not a launch signal.

## Requirements

### Must-have — the run, per the pre-registered rules

- **U1 · Stage 1 (probe).** `control__flask-read-only` alone, fresh root
  `eval/mint/s6a/`, `--toolset filesystem+shell`. Gate (Rule A): captured + ≥1
  genuinely verifiable turn + control `VERIFIED_CLEAN`, else **STOP** (wiring
  defect). Committed: frozen invocation (no result) → run once → verbatim output.
- **U2 · Stage 2 (controls + fresh real).** The 4 controls at the head — 3 steered
  write controls + positive control `control__flask-verify-with-command` — plus
  **7 fresh real** instances (11 records), fresh root `eval/mint/s6b/`. Gates: capture
  rate ≥5/11; ≥1 verifiable turn; all controls `VERIFIED_CLEAN` (any control FAIL →
  **VOID**, D-3); **trajectory exposure ≥1 of 10 judged** (D-1) — else STOP and
  re-scope. Stage composition per `controls-rescope/composition-note.md:32-42`.
- **U3 · Stage 3 (the denominator).** The **full remaining fresh non-control pool**
  (owner decision, 2026-08-12) driven to the ≥50-instance denominator, fresh root
  `eval/mint/s6c/`. No abort except the quota breaker and the stage-2 gate outcome;
  capture rate <50% is the stop-loss → **publish the smaller denominator**; the
  canonical gate block must be copied into `PHASE0_RESULTS.md` **before** stage 3
  runs (`phase0-live-mint/prd.md`).
- **U4 · Quota semantics.** `quota` → stop the batch, remaining instances
  unrecorded/eligible; the quota-hit instance dispositioned `no_observation`;
  resume on the **same root**; `no_observation` re-arms, `captured` **never**
  re-rolls, no `--force` (`phase0-mint-resilience/prd.md:99-126`). `terminal`
  records `failed` and continues; `transient` gets bounded backoff only.
- **U5 · Freeze protocol.** Invocation tooling + this PRD + stage files committed
  first, containing no result; each stage run **once**; verbatim output committed
  next, whatever it says; a second run only if declared (Rule D,
  `phase0-remint/prd.md:208-209`). Never re-steer mid-mint; steering is stochastic.
- **U6 · Audit and publish.** Evidence inventory (`FLAGS.md`), hand-audit
  (`AUDIT.md`, owner; **every trajectory FAIL adjudicated** — S-5, no sampling of
  the trajectory axis), one FAIL hand-replayed end-to-end (`HAND_REPLAY.md`),
  reproducibility (`REPRODUCIBILITY.md` — clean-checkout `belay phase0 report`
  byte-identical to committed outputs, mismatch → STOP), then the **decision line**
  written by the owner with the mandatory disclosure set (`phase0-remint/
  audit-and-publish/plan_20260809.md:97-103`): rate+denominator, FP rate, UNVERIFIED
  by cause, exposure on both lines with Rule B's mechanical reading, the trajectory
  rule's measured precision on real model text, pool composition, coverage limits,
  and the D-1 gate supersession.
- **U7 · Publish the number.** `docs/technical/PHASE0_RESULTS.md` updated with the
  run's results and the decision; ledgers committed under
  `docs/planning/mint-shell-toolset-run/mint-run/ledgers/`; audit artifacts under
  `docs/planning/mint-shell-toolset-run/audit-and-publish/`; the launch checklist
  L1 line written.
- **U8 · Pre-flight smoke — promoted to must-have (2026-08-12 critique).** Run the
  manual dual-server smoke (`pytest-7432`, `--toolset filesystem+shell`) once in
  this worktree **before stage 1**. It has never run live
  (`mint-dual-server/smoke.md:70-83`) and it is the **first live evidence that the
  shell path verifies end-to-end** — without it, that evidence first arrives at
  stage 2, where a wiring failure voids the mint at 11-instance cost. The smoke is
  tooling validation, not a measurement: findings echoed, never asserted away; its
  finding taxonomy (model / wiring / instrument) is the pre-stage gate: an
  instrument-class finding → STOP and fix, never stage 1 with a known-broken
  boundary.
- **U9 · Verify composition, stated.** Every capture verifies via stock `belay
  phase0 run` with the filesystem server as the single `--server` (the composition
  the stock runner resolves). **`run_process` turns are dispositioned per the
  smoke's recorded finding** (`mint-dual-server/smoke.md:24-27`): shell-turn rows
  replayed through a filesystem-only server are not expected to reproduce — they
  are echoed, reported as `UNVERIFIED`-by-cause or a named finding, **never
  asserted away, never counted as replayed evidence**. The trajectory rule's
  evidence line (replayed exit-0 `run_process`) counts only turns that replayed
  verifiably; everything else is exposure (`EVIDENCE_UNOBSERVABLE` /
  `EMBEDDED_PATH_UNRELOCATABLE`), never silence. Any divergence from this
  composition is a recorded finding for the verify seam, not a silent adjustment.

### Should-have

- **S1 · Corpus migration.** Attempt to migrate the 5 banked remint FP cases from
  the remint worktree's `corpus/local/`; if unreachable, documented as such —
  the regression fixtures pin behavior (`trajectory-toolset-rescope/prd.md:161-163`).
- **S2 · Runbook corrections.** Any defect found while walking `eval/README.md`
  end-to-end is fixed in the same PR (pre-registered: the runbook is walked and
  corrected).

### Nice-to-have

- **N1 ·** `belay phase0 combine` trajectory sections (explicitly deferred —
  stage-gate reading is per-stage `run`/`report`).

## Technical Considerations

- **Effort (estimate, not a promise):** stage 1 ≈ 1 instance ≈ minutes; stage 2 ≈
  11 instances ≈ 10–15 min wall clock (re-mint: 10 instances ≈ 8 min / ~10k
  tokens); stage 3 ≈ ~65 instances ≈ 1–2 h wall clock, pausable by quota-stop and
  resumable on the same root; audit-and-publish ≈ half a day of the owner's
  adjudication + agent-prepared evidence. The constraint is the subscription path
  (requests + tokens + wall-clock, no dollars — `phase0-mint-resilience/prd.md:128-137`).
- **Capability mapping:** this unit is Phase-0 gate work, not a C-capability; it
  consumes C1–C6 + the v0.17.0 eval toolset (composite transport, shell server,
  controls) and ships **no `src/` change**. Environment: `claude` CLI 2.1.228
  (subscription path, `claude-cli` provider), D-6 operating point (`claude-opus-5`,
  `--max-steps 20`, `--request-timeout 120`), macOS Seatbelt, servers pre-installed
  in `eval/servers/` (absent in this worktree — install or
  `BELAY_EVAL_SERVER_ROOT`), scratch outside Desktop/Documents/Downloads (TCC).
- **Verdict impact:** none to the verdict contract. A1/A2/trajectory are all
  **measured** here, not changed; the trajectory rule's first real-text
  precision/recall is decided by adjudication in this unit, never predicted
  (Rule C). Replay determinism is preserved: `belay phase0 report` is a pure
  re-render of committed ledgers.
- **Verification of the unit itself:** the pre-registered gates ARE the acceptance
  tests. Phase-6 discipline applies if a harness defect surfaces (RED test → fix →
  re-verify), never to the run outcomes themselves.
- **Corpus:** every flagged turn ingests via `belay phase0 run`; every adjudicated
  TP/FP/miss is labeled via `belay corpus label` with root-cause keys; the corpus is
  the regression suite for the detector.

## Risks & Open Questions

| # | Risk | Tied to | Handling |
|---|------|---------|----------|
| R1 | Healthy-instrument ~0 rate (premise fails) | `docs/ROADMAP.md:327` | Recorded as a decision: Rule B reading requires exposure ≥40%; PIVOT is the honest outcome; never a launch signal |
| R1a | Exposure gate stops the run (0 of 10 trajectory-judged at stage 2) | D-1 | STOP and re-scope the population — a STOP is a decision, not a failure |
| D-3 | A control FAILs (steering is stochastic) | `phase0-remint/prd.md:215` | VOID, regardless of later adjudication; stage 1 probes the path first so cost is bounded |
| P1 | Provider daily cap mid-stage-3 | `phase0-mint-resilience` | Quota-stop pauses; resume on same root; `no_observation` re-arms |
| P2 | Positive control's command fails in the contained run (python3, sandbox denial) | `controls-rescope/composition-note.md:80-83` | Recorded finding; expectation never silently changed |
| P3 | REPRODUCIBILITY mismatch (clean-checkout report differs) | audit plan | STOP; reconcile ledgers before any decision line |
| P4 | Shell turns that cannot relocate → UNVERIFIED | `replay-relocation-shell` | Named cause (`EMBEDDED_PATH_UNRELOCATABLE`), counted as exposure, never a silent miss |
| P5 | **Shell-turn verify seam** — `run_process` turns replayed through the filesystem-only `--server` do not reproduce (U9) | `mint-dual-server/smoke.md:24-27` | Pre-stated composition: echoed, UNVERIFIED-by-cause, never counted as replayed evidence; a divergence is a recorded finding, not a silent adjustment |
| P6 | Pre-flight smoke shows a broken shell path (U8) | `mint-dual-server/smoke.md:85-96` | Instrument-class finding → STOP and fix before stage 1 — never stage 1 with a known-broken boundary |

**Open questions:** none outstanding — pool size (full ~65) and spend envelope
(pre-registered rules only) were decided with the owner 2026-08-12. Any new
ambiguity surfaced during the run is recorded in `mint-run/ledgers/` notes and
flagged at the review gate, never decided silently.

## Out of Scope

- **Anything but the number and its audit.** C7 console, C8/A3, C9 export-back,
  Linux sandbox, packaging, launch assets — all untouched (launch checklist L2–L8).
- **No `src/belay/` change** unless a harness defect blocks the run (then: TDD-fixed
  as a separate concern, pre-registered rules intact).
- **No re-running of captured instances** — `captured` never re-rolls; no second
  runs except declared per the freeze protocol.
- **No re-derivation of published numbers** (`4/16`, `precision 0.00`, `3/93`,
  `recall 0.00`, `1/15`, 17 judgments, the 2026-07-29 PIVOT) — reclassification
  discipline applies to any trajectory re-verification.
- **No extension of the claim-classifier vocabulary** (`trajectory-toolset-rescope/
  prd.md:160-164` — recorded decision).
