# PRD: claim-author-live-probe

**Sources:** `docs/planning/_card/issue.md` (inline brief, belay-next pick 2026-10-10) · `docs/planning/_card/understanding.md` (deep dig, 2 agents) · `claim-axis-legibility/prd.md:193-200` (risk R-D, the pre-registered trigger) · `phase0-corpus-mint/audit-and-publish/AUDIT.md:87-91` (run-3 forensics) · owner decisions 2026-10-10 (interview).
**Evidence tags:** every factual claim is tagged [observed] (verified in code/records this unit's dig or a committed ledger) or [hypothesized] (the R-D inference this unit exists to test). No claim is merely plausible.

## Problem Statement

A3 (claim re-derivation, shipped C8) is the axis that "gets better as models improve" — a model *writes* an executable check, execution *decides*. Its real value cannot be measured until real author invocations produce real verdicts. The two banked run-3 trajectory-FAIL cases (`django-11422`, `django-14382`) are exactly such real claims (`VERIFICATION`, cited *"verified by reading the file back"`), and on both the A3 axis returned `NO_CHECK_AUTHOR` — an abstention whose cause was **never recorded** ([observed] `AUDIT.md:87-91`: *"The ledger does not record which, and nobody observed it"*).

The candidate cause is structural and written into the code: Belay kills its subprocess claim author at `AUTHOR_TIMEOUT = 60.0` s ([observed] `src/belay/verify/author.py:63`, constructed with the default at `src/belay/cli.py:971`, `:1990`, `:2145` — no operator knob anywhere, [observed] zero hits for any timeout flag/env across `src/` and `tests/`), while the shipped reference author allows its own `claude -p` child 600 s ([observed] `src/belay/verify/reference_claim_author.py:65-67`). Whether the cap actually killed a still-working author on run 3 is **unknown** — the n=1 live proof (184.5 s whole-test wall) fit inside the cap ([observed] `a3-author/live-run.md:20,39`), so this is [hypothesized], explicitly NOT a finding (`claim-axis-legibility/prd.md:193-200`: *"Changing the timeout is out of scope (it changes A3 behavior); if the next A3-enabled run reads `AUTHOR_TIMED_OUT`, that is the next unit's evidence"*).

**This unit is that next A3-enabled run** — made cheap: two traces, not a mint.

## Goals & Success Metrics

1. **[Must] The observation is made.** Re-verify the two cm6 traces through the real CLI with the shipped reference author configured. The recorded `last_abstention` sub-cause — `AUTHOR_TIMED_OUT` (detail `no reply within 60s`), `AUTHOR_EXITED_NONZERO` (one-line stderr), `AUTHOR_DECLINED`, `AUTHOR_RAISED`, or a produced check — is committed, whatever it says (freeze protocol). Measurable: the verify `--json` `claim` record carries `sub_cause`/`sub_cause_detail` ([observed] `verify/json.py:301-336`; this is exactly what run-3's ledger could not say).
2. **[Must] C8's first real verdicts are recorded, if produced.** A produced check whose execution exits non-zero is A3's first real FAIL on real data (an observation, never a corpus mutation); exit 0 is D3 silence. Either way the finding note says which, verbatim (`sub_cause`/`exit_code`) — never inferred.
3. **[Conditional, review-gate] The knob ships ONLY if the evidence reads `AUTHOR_TIMED_OUT`.** Per the owner's decision (interview, 2026-10-10): keep the 60 s default; add `BELAY_CLAIM_AUTHOR_TIMEOUT` env + `--author-timeout` on the three author-constructing surfaces; bounded fail-closed abstention preserved; `test_verify_author.py:121`'s pin (`configured.timeout == AUTHOR_TIMEOUT`) survives. If the evidence is any other sub-cause, the unit stops at the finding — a knob without the warrant is out of scope.
4. **[Must] Honesty lines hold.** Not a gate run; produces no Phase-0 number; no published number moves (`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00`, `3/93` stand unedited); the two `belay corpus label` judgments remain the owner's alone ([observed] `AUDIT.md:93-97`); old ledgers are never back-filled.

## Personas & Scenarios

- **The operator (this unit's actor, the owner).** Runs the frozen probe once: `belay verify --json` × 2 against the cm6 traces with `BELAY_CLAIM_AUTHOR` set to a recording wrapper around `python -m belay.verify.reference_claim_author --model claude-opus-5` (the live-run precedent, [observed] `a3-author/live-run.md:10-21`), wall-timed, `manual`-marked, never CI ([observed] `pyproject.toml:77-94`).
- **A future A3 operator.** If the knob ships: a slow author no longer silently abstains; README documents the env and flag. Scenario: `BELAY_CLAIM_AUTHOR_TIMEOUT=300 belay verify ...` or `--author-timeout 300` on the three surfaces — the reference author's 600 s bound becomes reachable through the engine.

## Requirements

### Must-have (the probe)

- P1 — Freeze protocol (Rule D, [observed] `phase0-mint-run/prd.md:97-101`): the invocation script is committed **first, containing no result** (grep-checked for result shapes, commitments verbatim from the run-3 precedent [observed] `mint-run/acceptance-cm-run3-stage2.sh`); the run happens **once**; verbatim stdout is committed next, whatever it says; a second run only if declared; the freeze commit hash is named in the findings.
- P2 — The wrapper-record trick ([observed] `tests/test_reference_claim_author_live.py:136-150`, `a3-author/live-run.md:80-84`): `--claim-author` points at a wrapper that appends a marker byte per invocation (and records wall start/stop) then `exec`s the shipped module, so **"the author ran" is an observed fact** — a run where A3 never engaged is a failed probe, asserted `invocations >= 1`.
- P3 — The surface is `belay verify <trace> --manifest-dir <dir> --claim-author <wrapper> --server node <fs-server> '{workspace}' --json` ([observed] the e2e shape `tests/test_claim_axis_e2e.py:91-108`; the `{workspace}` token and required `--manifest-dir` are the two documented operator-error hazards, `live-run.md:91-105`). The JSON key of interest is `claim` (not `claim_record` — hazard 3).
- P4 — Traces: `/Users/aliz/dev/at/holder/belay/mint/cm6/batch/trace-django__django-11422.jsonl` and `.../14382.jsonl` with their `.manifests` siblings ([observed] each carries one claim record at seq 24, `observation_point: session`; run-3 ledger `mint-run/ledgers/cm-run3-stage2.json` records both as `claim UNVERIFIED [NO_CHECK_AUTHOR]`).
- P5 — The manual-marked probe test `tests/test_claim_author_live_probe.py`: `manual`-marked, darwin-gated with named cause, FAILS with instructions when `BELAY_REFERENCE_AUTHOR_MODEL` is unset (never a skip) ([observed] the live-test pattern `test_reference_claim_author_live.py:24-28,107-125`).
- P6 — Findings note at `docs/planning/claim-author-live-probe/` (STAGE findings model, [observed] `mint-run/STAGE1_FINDINGS_RUN3.md`): observed sub-cause(s), A3 verdict(s) or silence, author wall-times via the wrapper, the R-D answer stated as a finding (evidence) or non-finding (hypothesis resolved otherwise), and the named follow-up if the knob ships.

### Conditional must-have (review gate, only if P6's evidence reads `AUTHOR_TIMED_OUT` on ≥1 trace)

- K1 — `BELAY_CLAIM_AUTHOR_TIMEOUT` env + `--author-timeout SECONDS` flag on the **three** author-constructing surfaces: `verify`, `gate baseline`, `gate check` ([observed] the `--claim-author` row at `tests/test_cli_flag_parity.py:152-158` is exactly this set; **correction to the brief**: `phase0 run` is env-only by pinned decision [observed] `tests/test_verify_claim_surfaces.py:202-219`, `cli.py:2964` — the env alone reaches it; `corpus run` never constructs an external author [observed] `corpus/run.py:728-745` — it gets nothing).
- K2 — Parsing is fail-closed: un-lexable/absent/negative ⇒ defaults; the env is read where `author_from_env` runs, the flag where `--claim-author` is parsed. The def-time default-arg trap is respected (monkeypatching `AUTHOR_TIMEOUT` after import is not enough — [observed] `surface-threading/plan_20260925.md:58-61`).
- K3 — Flag-parity guard: a new `--author-timeout` row in `EXPECTED` ([observed] `tests/test_cli_flag_parity.py` discovery test `:209-223` fails any undeclared shared flag).
- K4 — Boundedness preserved: beyond the (possibly raised) bound, the abstention is byte-identical `AUTHOR_TIMED_OUT` / `NO_CHECK_AUTHOR`, never a crash, never a hang; timeout tests are small-valued sleeps (the `test_verify_author.py:83-87` shape, no timing assertions).
- K5 — Docs: README's claim-author section gains the knob line (today it states no timeout value — [observed] `README.md:161-166,295,349`); a STATUS/C8 "as built" addendum line stating the default is unchanged.

### Should-have

- S1 — The probe also records the **author-invocation wall time** from the wrapper (start/stop around the exec), so the finding can state "author completed in N s, engine bound 60 s" or "engine killed at 60 s" — the numeric form of R-D.
- S2 — A `triaged` note in the findings on whether `TRIAGE_TIMEOUT` (60 s, mirror decision [observed] `jev-triage/triage-seam/spec.md:33`) needs the same reconsideration — observation only, no triage change (Jev measured 0.9 s at n=1 [observed] `jev-triage` record; no evidence of starvation).

### Nice-to-have

- N1 — A one-line `phase0 report`/ledger pre-render check that a `sub_cause` of `AUTHOR_TIMED_OUT` renders visibly (already shipped by claim-axis-legibility [observed]) — verification only, no code.

## Technical Considerations

- **Axis**: A3 only (downgrade-only; a timed-out author is UNVERIFIED `NO_CHECK_AUTHOR`, never PASS — [observed] `claims.py:431-445`). A1/A2, `verdict.reduce`, and the `--no-claim-axis` refutation are untouched; the knob changes *when an author may complete*, never *what a verdict means*.
- **Surfaces reality (correcting the brief)**: the brief said "verify/phase0/corpus" — that is the `--no-claim-axis` set. The author-construction set is `verify`/`gate baseline`/`gate check` (flag) + `phase0 run` (env-only) + `corpus run` (none). The PRD adopts the code's set.
- **Bound state**: `last_abstention` is per-instance; `verify`/`phase0` evaluate A3 sequentially, one claim per trace (pinned, OQ-3 [observed] `claim-axis-legibility/prd.md:204-206`) — the probe's two traces are sequential, no concurrency.
- **Traces are NOT copied into the worktree** ([observed] the no-raw-data-egress + no-trace-copy rule, `belay-worktrees` skill; `corpus/local` is gitignored): the probe points at `~/dev/at/holder/belay/mint/cm6/...` by absolute path. The `.manifests` sibling is required for replay.
- **Cost**: one author invocation per trace (2 total); each verify replays its trace to materialize the final state before authoring ([observed] `_materialize_final_state`, `claims.py:479-517`) — the expensive, non-author part; wall time bounded by the e2e precedent's 600 s per-process detector ([observed] `test_claim_axis_e2e.py:70`).
- **Baseline**: suite 2895 passing, 45 skipped, 14 deselected ([observed] `STATUS.md:25-26`).

## Risks & Open Questions

- **R1 (Med/Med)** — The author's model call is unavailable or errors on probe day (quota, network): the observed sub-cause would be `AUTHOR_EXITED_NONZERO` with the reference author's one-line stderr ([observed] its named error classes, `reference_claim_author.py:139-158`). That is a valid observation but does NOT test R-D. Mitigation: the findings note says so plainly; a re-run is the owner's declared decision (Rule D allows a declared second run); the freeze script's model is an env/parameter, not baked.
- **R2 (Low/Med)** — Host-side env leakage into the author child: the reference author scrubs `ANTHROPIC_*` by absence ([observed] `reference_claim_author.py:72-76,209-224`) but the operator's `claude` identity still applies; the probe is BYOK by construction, never an engine credential.
- **R3 (Low/Low)** — Verify's own replay of the cm6 traces drifts from run 3 (fixtures unchanged, but the A3 evaluation is deterministic-modulo-model). The committed run-3 factuals (`claim` text, ledger row) are the correctness anchor; a divergent replay would itself be a finding (instrument drift), recorded not papered over.
- **OQ-1** — If one trace reads `AUTHOR_TIMED_OUT` and the other reads a different sub-cause: the knob decision keys on ≥1 TIMED_OUT observation (the engine cap is shown reachable/obstructive); the finding states both.
- **OQ-2** — Knob flag name: `--author-timeout` (preferred; matches "the author's timeout") vs `--claim-author-timeout` (longer, more explicit that it is the *claim* author, not the triage or invariant author). Owner pick at the review gate.
- **OQ-3** — Does the env fallback on `phase0 run` accept the same env name? Yes by construction ([observed] `author_from_env` reads one env; adding a timeout env extends it) — but `phase0 run`'s timeout is then only env-set, no flag (its `--no-claim-axis`-style flag parity is a separate pinned decision, untouched).

## Out of Scope

- The two `belay corpus label` judgments (`AUDIT.md:93-97`) — the owner's alone, parallel to this unit.
- Any classifier vocabulary change (the 10/12 `CLAIM_UNCLASSIFIABLE` decision, closed 2026-08-12 and re-confirmed by the `trajectory-claim-coverage` dig).
- `FINAL_STATE_UNOBSERVABLE`'s vocabulary (shipped 2026-10-03) and the evaluator's caller-supplied-`workspace=` short-circuit (named C8 follow-on, unchanged).
- Re-deriving or re-rendering run 3's A3 results (sub-causes were never recorded and cannot be recovered — stated, never inferred) — the probe is a *new* observation under a *new* run, not a back-fill.
- `TRIAGE_TIMEOUT` changes; `CHECK_TIMEOUT` (check-execution, 60 s) — a separate bound the reference author is not designed to exceed.
- `corpus run`/`phase0 run` gaining a `--claim-author` flag (pinned decisions, untouchable here); corpus mutation of any kind.
- Any verdict, status, reduction, exit-code or gate behavior change; any published number.
- The A3 WARN vocabulary (empty in v0).

## Approval

Owner approval at the review gate (this PRD + prd-generator's flagged gaps). The conditional aspect (K1–K5) is itself gated on the probe's evidence — a second review decision at the implementation checkpoint, not auto-advanced.