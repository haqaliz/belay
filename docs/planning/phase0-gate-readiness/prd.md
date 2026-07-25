# PRD — Phase-0 Gate Readiness

**Unit:** `feat/phase0-stage3-publish/aliz` · **Slug:** `phase0-gate-readiness` · **Owner:** aliz
**Base:** `master` @ `ac81e3a` (v0.6.0) · **Capability:** the Phase-0 → Phase-1 gate (not a C-id;
it is the measurement that decides whether C7+ proceed)
**Inputs:** `docs/planning/_card/issue.md`, `docs/planning/_card/understanding.md`

---

## Problem Statement

`docs/technical/PHASE0_RESULTS.md` is entirely `TO-BE-FILLED`, including the Decision line.
Belay has a built spine (C1–C6, the Phase-0 runner, the mint harness) and **no published
number**. Every downstream capability — C7 live console first — is building past an
uncleared gate, and the gate is the one that tests whether the premise of the whole project
holds (**R1**, `docs/ROADMAP.md:237`).

The obvious move is "run Stage 3 and publish." **That would fail today, measurably.** The
mint drives the reference `@modelcontextprotocol/server-filesystem`, which declares
`openWorldHint: false`. On `master` as it stands, a declared-false network promise drags the
whole turn to `UNVERIFIED`, which pins *every* turn at UNVERIFIED regardless of agent
behavior — Stage 1 measured **12/12, `NO_VERIFIABLE_TURNS`, `INSTRUMENT SUSPECT`**. Stage 2
produced a usable number (2/9 flagged, 130 turns) **only because it was run from the
unmerged `feat/verdict-coverage-status/aliz` worktree**, where `NOT_COVERED` exists.

So the real problem is: **the engine that can produce the number is not on `master`, and
several things that must be true before a 15–20 hour, real-spend run are not yet true.**

**Who has this problem:** the founder, who cannot honestly answer "does Belay catch real
agent violations at a rate worth building a company on?" — and cannot launch C7 or the OSS
wedge on an unpublished premise.

## Goals & Success Metrics

The deliverable is **readiness**, measured by a smoke gate, not by the headline number.

| Goal | Measure |
|---|---|
| The number-producing engine is on `master` | `verdict-coverage-status` merged; suite green; release cut |
| The merge breaks nothing in C9 interop | No fabricated `unrestorable-pre-state` on a turn that replayed fine, pinned by a test against the **real** `verify_turn` contract; and every rendering surface that can print a verdict prints its coverage line, enforced by a test **per surface** — including `belay interop correlate` |
| The corrupt-success subset is expressible | A flagged case can be tallied as corrupt-success vs policy-violation **mechanically**, not only in prose |
| The gate cannot be decided after seeing the result | Pre-registered criteria + stop-loss committed in a commit that **precedes** any Stage-3 run, signed off by the founder |
| A 15–20h run will not fail for a known reason | Two separate checks, because one cannot do both jobs — see requirement 6: **(a) determinism check** — Stage 1's *existing captured trace* re-verified against merged `master` yields the expected FAIL on the corrupt-success turn and no relocation-induced false positive; **(b) liveness check** — a fresh 1-instance mint completes end-to-end, with **no verdict expectation** |
| The runbook matches the code | RUNBOOK steps execute as written against v0.6.0+ |

**Explicit non-metric:** this unit publishes **no violation rate**. Any number appearing in
`PHASE0_RESULTS.md` at the end of this unit is pre-registration and prior-stage evidence,
never a result.

## User Personas & Scenarios

**Primary — the founder, pre-launch.** Needs to decide PROCEED vs PIVOT on evidence they'd
be willing to publish and defend. Their failure mode is spending 20 hours to produce a
number that a hostile reader can dismantle.

**Secondary — the skeptical reader** (investor, HN commenter, prospective user). Arrives at
`PHASE0_RESULTS.md` assuming the founder graded their own homework. Must be able to
re-derive the headline number themselves and see exactly what was excluded.

## Requirements

### Must-have

1. **Land `feat/verdict-coverage-status/aliz` on `master`.** 10 commits, currently 31
   behind, never PR'd, suite green (`754 passed, 1 skipped`; the plan's baseline was 719, so
   the branch adds 35). `git merge-tree` reports **exactly two conflicts, both trivial**:
   `src/belay/replay/report.py` (both sides append to `_PREFIX_LABELS` — concatenate; the
   branch's specific-before-catch-all ordering is internal to its own five entries, and
   master's relocation-shell entry is order-independent) and `docs/planning/_card/issue.md`
   (per-unit scratch — take either). **`src/belay/cli.py` auto-merges**: branch hunks at
   442/575–583/614/1064, master's `interop` hunks at 1115+ and 1530+ — disjoint. So the
   *textual* merge is minutes; requirement 2 is the actual work.
2. **Repair the two things the merge breaks in C9 interop. Both are part of landing, not
   follow-ups.** `belay.interop` did not exist when the branch forked, so neither is
   covered by any test on either side.

   **2a — Interop fabricates `unrestorable-pre-state` (a correctness regression, and the
   more serious of the two).** `src/belay/interop/attach.py:139` derives the cause
   structurally:
   ```python
   cause = UNRESTORABLE_PRE_STATE if turn_verdict.cause is not None else None
   ```
   resting on the invariant its own comment states — *"`TurnVerdict.cause` … is ALWAYS
   `None` on a REPLAYED turn."* The branch **invalidates that invariant**:
   `src/belay/verify/turn.py:274` now sets `cause=_replayed_cause(sub_verdicts)` whenever a
   replayed turn reduces to UNVERIFIED. After the merge, a span whose turn replayed
   perfectly well is labeled with a named cause **asserting a snapshot-restore failure that
   never happened** — Belay inventing a fact about its own execution, which is a worse
   failure than silence. Fix: discriminate on the actual non-REPLAYED branch rather than on
   `cause is not None`, correct the `attach.py:25–33` docstring, and add a test that
   exercises the **real** `verify_turn` contract. The existing
   `tests/test_interop_attach.py::test_matched_replayed_pass_turn_has_no_bespoke_cause`
   hand-builds `TurnVerdict(..., cause=None)` through the `verify=` stub seam, so **a green
   merged suite is not evidence here** — that test cannot fail on this bug.

   **2b — Interop renders a PASS with no coverage line.**
   `src/belay/interop/report.py:61-67` prints `r.status.value` and `render()` emits no
   coverage block; `to_json()` emits no sub-verdicts. A matched span against the reference
   filesystem server prints `UNVERIFIED` today and will print bare **`PASS`** after the
   merge. This also silently falsifies that module's own docstring invariant
   (`report.py:13–17`) — written when the boundary lived *in* the status, it becomes untrue
   without a single line of it changing. Fix: coverage block in `render()`, sub-verdicts in
   `to_json()`, a per-surface test, and correct the docstring.

   **2c — Close the branch's own two untested surfaces** (cheap, and the branch's rule was
   "a test per surface, not by review"): `belay verify` per-turn (`cli.py:558 _emit_verdict`
   works but is unpinned) and `belay corpus show` (`cli.py:1049–1053` prints
   `axis/kind/status` without the message, losing the declared-vs-not-declared distinction).
3. **Build the finding-kind tally.** `src/belay/corpus/case.py:41` defines a fail-closed
   frozenset of exactly four labels — `true-positive`, `false-positive`, `unverifiable`,
   `pending`. Nothing distinguishes a corrupt-success TP from a policy-violation TP, so
   `STAGE2_FINDINGS.md`'s "report the raw A1 rate and the corrupt-success subset
   **separately**" is currently unsatisfiable mechanically. Add an **orthogonal** field
   (proposed `finding_kind`), surfaced in `corpus score` / `phase0 report`, under three
   non-negotiable constraints that keep it out of the label-trap
   (`src/belay/corpus/metrics.py:16–22`):
   - **Human-set only.** The engine must never derive `finding_kind` from the diff. An
     engine that characterizes its own finding is the same failure as an engine that labels
     its own case.
   - **Defaults to `unclassified`**, fail-closed on any unknown value — the same shape as
     `human_label` → `pending`, so existing cases keep parsing.
   - **Excluded from precision/recall.** It is a *reporting* dimension for splitting the
     tally, never an input to the confusion matrix. Letting it score would manufacture the
     100%-precision-by-construction lie `metrics.py` exists to prevent.
4. **Pre-register the gate criteria and a stop-loss, for founder sign-off, committed before
   any Stage-3 run.** PROCEED iff ≥3 *independent* hand-audited TPs AND denominator ≥50 AND
   no `INSTRUMENT SUSPECT`; a FAILing control voids the mint. Plus a concrete wall-clock and
   spend stop-loss (PRD Gap 3, `phase0-live-mint/prd.md:285–293`).

   **State plainly what pre-registration does and does not buy.** This is a solo project:
   the founder writes the criteria, signs them off, runs the mint, and audits the flags.
   Pre-registration is a **timing control — it fixes *when* the criteria were set — not an
   independence control.** It does not make the audit independent, and the published
   document must not imply that it does. To make the timing claim checkable rather than
   trusted, the pre-registration **commit hash and timestamp** are published in
   `PHASE0_RESULTS.md`, so a reader can verify for themselves that it preceded the run.
5. **Record the standing TP tally conservatively: 2 independent findings, not 3** — one
   corrupt success (`pallets__flask-4045`, rewrote `test_dotted_names`) and one additive-test
   pattern (`flask-4992` + `pylint-5859` share the tool `edit_file` and the root cause), with
   the collapsing reasoning stated. Stage 3 therefore needs **≥1 further independent finding**.
6. **Stage-1 smoke, split into two checks that must not be conflated.**
   A fresh 1-instance mint *cannot* serve as the readiness gate on its own: if it returns
   `VERIFIED_CLEAN`, that is equally consistent with (a) the false-positive fix working,
   (b) detection having broken, and (c) the agent simply not making the same edit this run.
   Replay is deterministic; **agent behavior is not**. So:
   - **(a) Determinism check — the actual gate.** Re-verify Stage 1's **existing captured
     trace** against merged `master`. Expected: the corrupt-success turn
     (`pallets__flask-4045`, rewritten `test_dotted_names`) still FAILs, and the
     shell-relocation false positive is gone. Deterministic, cheap, and a real regression
     test on the merge.
   - **(b) Liveness check — not a verdict test.** A fresh 1-instance mint completes
     end-to-end on merged `master` (clone → gated capture → bridge → `phase0 run` → replay).
     Pass = it completes and produces verifiable turns. **No verdict expectation**; a clean
     result here is not evidence of anything and must not be reported as such.
7. **Refresh `docs/planning/phase0-corpus-run/RUNBOOK.md`** to match v0.6.0+.

### Should-have

8. **Resolve the clone-cache location.** `eval/clones/` is 743 MB and exists **only** in the
   `feat-verdict-coverage-status` worktree; it is gitignored and does not travel. Stage 2's
   "no clones needed in Stage 3" mitigation holds only in that directory. Relocating bare
   mirrors is safe — they are upstream data, not run state (unlike `/eval/mint/` and
   `/corpus/local/`, which must never be copied between worktrees).
9. **Retry-on-clone-failure in `prepare_workspace`** — Stage 2's one attrition case (exit
   128) was transient and succeeded on retry.
10. **Prune the two merged-but-leftover worktrees** (`feat-invariant-verdict-a1`,
    `feat-phase0-mint-execution`), both verified fully merged.

### Nice-to-have

11. Fix `CLAUDE.md`'s stale "463 tests" (actual: 754 + 1 skipped).

## Technical Considerations

**Verdict-axis impact.** This unit introduces **no new verdict axis**. It measures A1 + A2
as built and lands A2's `NOT_COVERED` sub-verdict. No A3, no LLM anywhere in the verdict
path. The LLM in play is the *minted agent under test* — the subject of measurement, not the
judge. The minting driver stays eval-only and is not a product surface, so no agent-framework
drift (`CLAUDE.md` guardrails 1 and 2 hold).

**`NOT_COVERED` semantics (landing, not being designed here).** Sub-verdict-only; dropped
before ranking; the empty-after-filter case reduces to `UNVERIFIED`, never `PASS`. The
honesty cost is that a `PASS` now means "passed on the dimensions Belay checks", which is
exactly why requirement 2 is a must-have rather than a polish item.

**The UNVERIFIED rate is not comparable across this boundary.** Turns that were UNVERIFIED
only because of an unobservable network promise become PASS + `NOT_COVERED`. Any before/after
comparison must state that the drop is a **reclassification, not improved detection**.

**Expected `corpus run` REGRESSIONs.** `corpus/run.py` compares recomputed sub-verdicts
against stored ones exactly, so any case stored before this release whose network sub-verdict
was `UNVERIFIED` now recomputes as `NOT_COVERED` and reports **REGRESSION**. Expected, not a
defect, and confined to the `A2 / effect:network` entry — a REGRESSION on any other axis is
a real one.

**Re-derivability, stated precisely.** The ledger path is caller-chosen (`belay phase0 run
--ledger OUT.json`, `cli.py:1000–1067`) and `belay phase0 report <ledger.json>`
(`cli.py:1080–1088`) is a pure re-render — no replay, no clock. So **the number is
re-derivable by a stranger from a committed ledger**. The **cases are not**: `/traces/`,
`/runs/`, `/corpus/local/`, `/eval/mint/`, `/eval/clones/` are gitignored (`.gitignore:18–35`)
under the no-raw-data-egress guardrail. The write-up must state this split rather than claim
full case-level auditability.

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **R1 — the premise is wrong** | The risk this unit exists to let us test. Not retired here; readiness only. |
| **Benign-flag skew (the likeliest failure)** | If Stage 3's flags are dominated by additive-test policy violations that collapse under the independence rule, a 15–20h run could land <3 independent TPs and force a PIVOT on a premise never actually tested. **Decision: keep `invariant-test-mutation-shape` deferred** per `STAGE2_FINDINGS.md:94–104` — designing the sharper invariant against 3 known cases is the guess that document warned against. Accepted with eyes open; requirement 5 makes the standing tally honest so the exposure is visible before the spend. |
| **R6 — false zero** | Structurally guarded: `INSTRUMENT SUSPECT` fires rather than publishing a clean 0%. Requirement 6's smoke gate is the practical check. |
| **Model capability is load-bearing** | Flash-class models never edited, yielding a 0% that *looks like a result* — worse than INSTRUMENT SUSPECT. Pro-class required; the published number must name the model. |
| **Rebase risk** | **Low** — `git merge-tree` reports two trivial conflicts; `cli.py` auto-merges. The risk is not the merge, it is requirement 2. |
| **A green merged suite is not evidence** | The one interop test that *should* catch requirement 2a builds its `TurnVerdict` through a stub seam, so it cannot fail on the bug. Any "tests pass, ship it" reasoning on this merge is unsound; the new tests must exercise the real `verify_turn` contract. This generalizes: stub-seam tests silently decouple from contracts that move. |
| **Cost, unquantified** | Stage 2 measured wall-clock (~15 min for one sympy instance at 20 turns) but **no spend**. django+sympy are 58 of 65 drawn. Stop-loss (requirement 4) is the control. |

**Open questions**
1. Exact `finding_kind` vocabulary and default. It must be orthogonal to `human_label` and
   must never let the engine label its own case (`corpus/metrics.py:16–22`). Adding a
   required field breaks existing cases, so it needs one documented safe default — the same
   shape as `human_label` → `pending`.
2. Where the committed ledger should live so a stranger can find it (`docs/technical/`?).
3. Whether the Stage-1 re-mint should reuse Stage 1's instance or a fresh one — reusing it
   is the direct false-positive check, which argues for reuse.

## Out of Scope

- **The Stage-3 live mint itself** (~65–70 instances, 3 controls) — a separate, explicitly
  authorized act, by user decision.
- **The audit and the published number** — follows Stage 3.
- **`invariant-test-mutation-shape`** — deliberately deferred until real cases exist.
- **C7 live console** — downstream of the gate.
- Any Linux/Windows sandbox port; the engine is macOS/Seatbelt-only and says so.

## Aspects

| Aspect | Boundary |
|---|---|
| `land-coverage-status` | Rebase, resolve 5 files, green suite, PR, merge, release; prune leftover worktrees |
| `interop-merge-repair` | Fix the fabricated `unrestorable-pre-state` cause (against the real `verify_turn` contract, not the stub), then coverage emission on `interop correlate`; close the two untested surfaces |
| `finding-kind-tally` | Orthogonal case field + scoring/report surfacing of the corrupt-success subset |
| `gate-preregistration` | Criteria + stop-loss + conservative TP tally, drafted for sign-off, committed before any run |
| `stage1-remint-smoke` | Clone-cache relocation, retry-on-clone, 1-instance re-mint, RUNBOOK refresh |
