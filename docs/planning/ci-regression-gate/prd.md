# PRD: CI Regression Gate

**Slug:** `ci-regression-gate` · **Type:** feat · **Owner:** aliz · **Date:** 2026-09-13
**Phase:** 2 (`docs/ROADMAP.md:299`) · **Capabilities:** builds on C1–C6 (all shipped); no new C-id.
**Sources:** `docs/planning/_card/issue.md` (belay-next handoff brief), `docs/planning/_card/understanding.md` (deep dig), `docs/ROADMAP.md:295,305,314,380`.

---

## Problem Statement

Teams running agents unattended have no way to know whether a new agent version (prompt,
model, or harness change) broke a behavior that previously worked. Today they re-run the
task and eyeball the outcome — the outcome-only scoring that is structurally blind to
corrupt successes (**27–78%**, arXiv 2603.03116) and to procedural regressions.

Belay already has both halves of the answer, unconnected:

- **Verification**: `belay verify` re-executes a capture against real state and produces
  grounded verdicts (A1 invariant, A2 replay, instance-level trajectory; A3 when enabled).
- **Detector regression**: `belay corpus run` fails CI when *detection* regresses — a
  banked case that used to be caught no longer is.

What does not exist is the **agent-side** gate: bank a known-good run's grounded verdicts
as a baseline, then in CI compare a new capture's verdicts against it and fail the build on
a grounded regression. `docs/ROADMAP.md:305` names this as Phase 2's first goal:
*"a past run replays in CI; a new agent version that breaks a previously-passing trajectory
fails the build. This is the first surface with obvious budget attached."*

**Evidence it matters:** R11 (*OSS adoption ≠ revenue*, Med/High, `ROADMAP.md:380`) names
the CI gate as *"the first surface with a named budget"*; the Phase-2 adoption metric is
*"≥40% of active teams wire the regression gate"* (`ROADMAP.md:314`); the Phase-1→2 gate
explicitly watches for *"≥2 users explicitly ask for a shared/CI surface"*
(`ROADMAP.md:295`). That demand-pull criterion is **not yet met** — see Risks.

## Goals & Success Metrics

**Goal:** a team can bank a verified capture as a baseline and, in CI, compare a new
capture against it — failing the build on any grounded regression, with named causes,
deterministically, no LLM, nothing leaving the box.

**Success metrics — these are the acceptance tests, written first (repo discipline):**

| # | Metric | Test shape |
|---|--------|-----------|
| 1 | **Regression caught** | A baseline re-verified after an injected trajectory change (a new failing turn, changed tool sequence) yields a named regression and non-zero exit — never a silent pass. |
| 2 | **Clean stays clean** | An unchanged re-run yields a clean result, byte-stable against the baseline report. |
| 3 | **Compounds the corpus** | A regression's divergence banks as a corpus case and recomputes `MATCH` through `belay corpus run`. |
| 4 | **Honest abstention** | A missing or unrestorable baseline yields `UNVERIFIED` with a named cause — never a false clean, never a false regression. |
| 5 | **CI-safe** | Deterministic, no network, no model calls; runs in the standard suite. |

Secondary: gate-check wall-clock is the same order as verifying the traces involved;
`--json` output is machine-consumable by a CI step.

## User Personas & Scenarios

ICP: engineers running agents unattended in production — the person who has to answer
*"did this run actually do the right thing?"* and today cannot.

- **Agent maintainer (primary).** Has a known-good capture for task T under agent vN.
  Before merging vN+1, CI captures T through the proxy and runs `belay gate check`; the
  build fails if any previously-passing turn, trajectory, or claim verdict worsens.
- **Reviewer / auditor.** Opens the gate report (text or `--json`) and sees the exact
  named `(axis, kind)` divergences, each with the concrete diff that grounded it.
- **Platform engineer (self-hoster).** Wires the check into their existing CI. The
  baseline bank lives on their infra — artifact cache, their repo, a mounted volume —
  and Belay never uploads it.

## Requirements

### Must-have

- **M1 · Run identity.** Capture-time `BELAY_RUN_ID` env is recorded in the trace as a new
  record kind (`run_identity`), documented in `docs/technical/TRACE_FORMAT.md`. **No schema
  version bump**: the reader's unknown-kind rule keeps old readers compatible, and the new
  reader exposes a derive helper. A trace without identity is usable only with an explicit
  `--run-id` (S2) or fails closed with a named cause.
- **M2 · Baseline bank.** `belay gate baseline <trace> [--server -- CMD…]` verifies the
  capture, then stores a **self-contained, replayable** baseline directory keyed by run id:
  the trace, its manifests + snapshots, the stored server command, provenance (engine
  version, platform, capabilities), and the expected verdict set (per-turn, trajectory, and
  claim when declared). Re-banking an existing run id is refused (exit 2) without `--force`.
- **M3 · Gate check.** `belay gate check <trace> [--server -- CMD…] [--json]` resolves the
  baseline by run id, **re-verifies the baseline with the current engine** (replay — so the
  comparison is re-execution-grounded, not stored-opinion), verifies the new capture, diffs
  the verdict sets, and exits non-zero on regression. The baseline's stored server command
  is the default boundary; `--server` overrides.
- **M4 · Divergence policy — mirrors `corpus run` exactly.** SKIP-first: a baseline that
  cannot run (server-not-runnable, substrate/capability mismatch) is a named-cause
  abstention, never a regression. Then exact equality on the recomputed verdict set per
  dimension; **any new FAIL or worse status → `REGRESSION`** with named `(axis, kind)`
  divergence rows carrying expected vs observed status. New `UNVERIFIED` turns are named and
  reported; they never fail the gate alone.
- **M5 · Banking.** By default a regression's divergences bank into the corpus through the
  existing `add_case` path (self-contained case, deterministic id, standard per-turn
  namespace); `--no-ingest` disables. Banked cases recompute `MATCH` through
  `belay corpus run`.
- **M6 · Exit contract.** `0` = comparison ran, no regression (named SKIPs/UNVERIFIED may be
  present); `1` = regression; `2` = preflight (missing/unreadable baseline, no run identity,
  unusable baseline) with the outcome rendered `UNVERIFIED` + named cause — never a silent
  clean, never a false regression.
- **M7 · No axis or number moves.** No verdict axis, invariant, coverage line, trace field
  (beyond the additive record kind), or published number changes. `UNVERIFIED` is never
  rendered as `PASS`; the coverage line travels on every gate surface.
- **M8 · Flag parity.** The new replay-bearing surface declares its flags in
  `tests/test_cli_flag_parity.py` — a deliberate widening. `--shell-server` is carried
  because replayed traces may contain shell turns.

### Should-have

- **S1 · `--json` report** for CI parsers: run id, per-dimension divergences, coverage,
  exit-relevant summary.
- **S2 · `--run-id` fallback** for captures that predate the trace record (explicit,
  never inferred).
- **S3 · CI quickstart** in `README.md` (capture step + `belay gate check` YAML snippet),
  machine-checked by the docs tests.
- **S4 · Shape reporting.** Turn-count / tool-sequence changes are reported as named
  `shape` divergences — informational, they do not fail alone. A different path that still
  passes is not a regression; verdict-worsening decides.

### Nice-to-have

- **N1 · `--strict-shape`** to fail on any shape change (opt-in).
- **N2 · GitHub Action wrapper** — deferred; the brief says keep wiring minimal.

## Technical Considerations

**Architecture fit.** Phase 2; reuses the deterministic spine end-to-end:

| Need | Existing machinery to generalize |
|------|----------------------------------|
| Verify a whole trace | `_verify_one_trace(..., ingest=False)` (`src/belay/phase0/runner.py:241`) |
| Machine report | `verify/json.py` (pinned contract, `tests/fixtures/verify_json_snapshot.json`) |
| Diff + named causes | `classify_case` / `_divergences` / `Divergence` (`src/belay/corpus/run.py:436,289`) — generalized from case-vs-expected to capture-vs-baseline |
| Banking | `add_case` (`src/belay/corpus/add.py:280`), deterministic ids, self-contained case dirs |
| Replay relocation | `replay/engine.py` + manifests (`source_root`, `{workspace}` placeholder) — unchanged |

**Trace format.** One additive record kind (`run_identity`), `observation_point: "proxy"`,
written once at proxy start when `BELAY_RUN_ID` is set. Unknown-kind skips make it
backward/forward compatible without a schema bump (`src/belay/trace.py:50-54`). The reader
gains a derive helper; nothing existing changes.

**Determinism.** Both sides are re-verified by the same engine in the same run, so engine
drift cancels rather than manufacturing divergences. Nondeterministic tools yield per-turn
`UNVERIFIED` with named causes and never fail the gate alone (R7 discipline).

**Substrate coupling (named adoption hazard).** A baseline banked on macOS and checked on
Linux yields the named capability-mismatch SKIP (the cross-substrate corpus precedent),
never a false regression. Docs recommend banking baselines on the CI substrate where
possible.

**Verdict impact.** None on the axes. The gate **consumes** A1/A2/trajectory (and A3 claim
when declared and enabled) and adds no status. Run-level UNVERIFIED causes are a closed
vocabulary: `NO_RUN_IDENTITY`, `BASELINE_NOT_FOUND`, `BASELINE_UNRESTORABLE`,
`BASELINE_CAPABILITY_MISMATCH`, `IDENTITY_MISMATCH`.

**No raw-data egress.** Baselines default under a gitignored `baselines/local/`, path
user-specified; nothing is uploaded. Baselines carry verdicts + traces + snapshots, exactly
what the user's own infra already holds.

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **R11 — adoption ≠ revenue; demand-pull unmet** (the Phase-1→2 gate's ≥2-user criterion is not satisfied) | Build the engine slice thin; defer Action/compose/UI wiring; acceptance tests carry the shape so the surface can be re-cut when real reports arrive. |
| **R10 — solo bandwidth** | Scope capped at five aspects; no UI. |
| **R7 — UNVERIFIED dominates and the gate says nothing** | Coverage line + named causes on every surface; UNVERIFIED alone never fails the build, so the failure signal stays meaningful. |
| **Cross-substrate baselines** | Capability-mismatch SKIP with named cause; docs recommend banking on the CI substrate. |
| **Comparison noise / false regressions** | Same-run re-verification cancels engine drift; nondeterministic turns abstain; shape changes report-only. |
| **Identity discipline** (`BELAY_RUN_ID` reuse across tasks) | `gate baseline` refuses to overwrite without `--force`; docs recommend `<task>/<agent-version>` ids; an absent/duplicate identity fails closed. |

## Out of Scope

Approval gate · shared-corpus server · second ingest surface · UI/compose wiring · GitHub
Action packaging · live OTLP exporter / multi-trace aggregation · A3 WARN vocabulary ·
multi-arch images · structural trajectory diffing as a hard fail (shape is report-only) ·
cross-baseline trending/aggregation.

## Open Questions (resolved at review, defaults chosen)

1. **Unusable baseline exit code** — chosen `2` (preflight, distinct from a regression's
   `1`), rendered `UNVERIFIED` + named cause. Confirm.
2. **Baseline update semantics** — chosen: refuse re-bank without `--force`; no versioned
   baselines in v1. Confirm.
3. **Baseline re-verification cadence** — chosen: every `gate check` (deterministic,
   drift-cancelling), no cache. Confirm.
