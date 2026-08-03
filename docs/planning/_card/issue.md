# feat/under-firing-measurable

**Type:** feat · **Id (slug):** `under-firing-measurable` · **Owner:** aliz
**Source:** inline brief (no GitHub issue — the tracker has never been used; all PRs are
issue-free). Produced by `/belay-next` on 2026-08-03 and invoked as
`bbf feat under-firing-measurable`.
**Base:** `origin/master` @ `4e5634d` (v0.11.0).

> **Predecessor.** This card replaces the previous `_card/issue.md`, which described
> `feat/phase0-reverify-banked` (merged at `55aed45`, released v0.11.0). That unit
> re-verified every banked Phase-0 capture under the detector that ships today
> (`no-assertion-weakening`) and produced **1/15 instances (6.7%)** over 22 non-control
> captures / 392 turns. Its own pre-registered reading rule
> (`docs/planning/phase0-reverify-banked/prd.md:74`) maps the outcome it got — *flags, but
> all on the fitted-on instance* — to *"not yet evidence of held-out sensitivity → report
> honestly; decide re-mint vs another detector pass on the payloads."* **This unit is that
> decision input.** The re-mint (`subscription-model-client`) remains its follow-on.

---

## Brief

Make A1's **silence** interpretable, so under-firing becomes measurable at all.

Today a ledger can say a capture flagged nothing, but not whether the rule ever had anything
to judge — `src/belay/verify/invariants.py:408-465` computes the in-scope `compared` count
and drops it into a **prose message only** (and discards it entirely on the FAIL and abstain
paths). `InstanceRecord` (`src/belay/phase0/ledger.py:126-134`) carries `turn_status_counts`,
`flagged_turns`, `unverified_causes` and `not_covered_turns` — and **no exposure field**.

Meanwhile `src/belay/corpus/metrics.py:45-48` defines `recall = TP / (TP + FN)` over an FN
cell that **no code path can populate**: `corpus/add.py:1` composes a case *"from a flagged
run"* and `phase0/runner.py:5` ingests *"the FAILing ones"*, so an adjudicated **miss** can
never become a case. `CLAUDE.md` already records the consequence: *"`FN 0` is an artifact of
construction, and the corpus cannot measure recall."*

Together these are why v0.11.0's *"14 instances flagged nothing"* cannot be separated from
*"the rule is blind to them"* — the **blindness clause**,
`docs/technical/PHASE0_RESULTS.md:698`.

Acceptance is **test-first**:

- **(a)** exposure is **structured data** on the A1 verdict and survives to the ledger and the
  report — on the **FAIL and abstain paths too**, not just PASS;
- **(b)** a ledger without an exposure field reads as **absent**, never as zero;
- **(c)** an **unflagged** turn can be composed into a corpus case and human-labeled, and
  `belay corpus run` classifies an expected-FAIL case that PASSes as a **REGRESSION**;
- **(d)** `belay corpus score` reports **recall with a real denominator**; `n/a` is never
  rendered as `1.00`;
- **(e)** the whole measurement is **deterministic and offline** with no API key, run **once**
  under the freeze protocol (tooling commit first, verbatim output second) over the banked
  captures.

### Out of scope

- **`subscription-model-client` and any re-mint.** This unit is the decision input for that
  ~11-hour spend, not the spend
  (`docs/planning/phase0-mint-resilience/subscription-model-client/spec.md`, specified,
  unbuilt).
- **Any edit to the `no-assertion-weakening` rule itself.** It is *measured* here, not
  changed. A defect this exposes is a finding for the next unit unless it makes the
  measurement impossible.
- Any change to A2/A3 semantics, `verdict.reduce`, or the `NOT_COVERED` boundary.
- C7 live console; C8 (A3 claim re-derivation); C9 export-back.

---

## Why this unit, and why now

| File | Says |
|---|---|
| `docs/planning/phase0-reverify-banked/prd.md:74` | the pre-registered reading for the result we got: *"not yet evidence of held-out sensitivity … decide re-mint vs another detector pass on the payloads"* |
| `docs/technical/PHASE0_RESULTS.md:698` | the blindness clause: the run *"cannot separate 'those captures contain no weakenings' from 'the rule is blind to them'"* |
| `docs/ROADMAP.md:134-135` | R1's misreading is the named hazard — a 0 must not be read as evidence for or against the premise |
| `CLAUDE.md` (status block) | *"the corpus cannot measure recall"*; `FN 0` is *"an artifact of construction"* |
| `src/belay/verify/invariants.py:465` | the exposure count already exists — as prose |

**The measurement opportunity, and its honest ceiling.** The exposure denominator is
**already computed** inside the invariant and thrown away. Surfacing it converts *"0 flags
across 14 instances"* into either *"0 flags out of M real opportunities"* (informative) or
*"0 opportunities"* (no signal, but no longer ambiguous). This is the same discipline the
repo already enforces for `NOT_COVERED` and the coverage line, applied to A1.

**The corpus half is a product defect, not an eval chore.** `belay corpus run` today is
*"evidence about over-firing ONLY"* (`CLAUDE.md`). A corpus that can hold a **missed**
violation makes under-firing regression-testable — moat #2, compounding.

---

## Logistics the dig must know

- **The captures are NOT in this worktree.** They are at
  `/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint/`
  (`s1`, `s1b`, `s1p`, `s2/batch`, `s3/batch`), with ledgers alongside under `…/runs/`.
  `eval/mint/` and `runs/` are gitignored and the captures embed absolute snapshot paths —
  **they are not movable** (verified previously: moving breaks replay). Point at them by
  absolute path; never copy or relocate.
- **The MCP server the traces name** is at
  `/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js`.
  Each corpus case's `server_command` is an absolute path to it — the corpus is
  **machine-bound through the server**, a known, unfixed property.
- **Neither of those two worktrees may be removed.** Both are detached HEAD with ~5.5 GB of
  unregenerable mint data.
- **The 7 labeled negative fixtures** are at `…/feat-verdict-coverage-status/corpus/local/`,
  with a hand-label backup at `…/corpus-labels-backup-20260729/`. They must survive any
  re-run **byte-identical** (`human_label` / `root_cause`).
- The v0.11.0 re-verification also produced **7 new corpus cases stored `pending`** (none
  labeled), which is why `corpus score` currently reads `precision n/a` (0 TP / 0 FP).
- Stock entrypoints: `belay phase0 run <trace-dir> --ledger OUT.json`, `belay phase0 report`,
  `belay phase0 combine`, `belay corpus add/label/run/score` (`src/belay/cli.py`).
- Baseline claimed by `CLAUDE.md`: **1238 tests, 1 platform-skip**, zero runtime dependencies.
  To be re-confirmed by the dig.

---

## Known caveats, carried forward from `/belay-next`

1. **This unit cannot clear the gate.** The pre-registered PROCEED clause requires a
   denominator **≥50** counting *instances minted*; it is detector-independent, so no work on
   banked data can satisfy it. **R1's quantitative form stays untested.**
2. **The most likely honest outcome is a null one.** If exposure turns out to be low — if the
   14 silent instances barely touched test files — the result is *"the rule had almost no
   opportunity to fire"*, which resolves the ambiguity but yields **no recall number**. That
   is a success of this unit and must be published as such, not padded.
3. **Two evidence grades, never merged.** *Execution* establishes exposure counts and
   verdicts; *human adjudication* — not execution — establishes whether an exposed-but-
   unflagged turn is a weakening. Keep them separate exactly as `PHASE0_RESULTS.md` does.
4. **Labels are load-bearing.** The 7 hand-labeled negatives must survive unrelabeled; a
   recomputed verdict change is a *report*, never a silent overwrite.
5. **`FN` entering the corpus changes what a green `corpus run` means** — again. It must be
   stated on the surface, or the next reader inherits the same confusion this unit exists to
   remove.
