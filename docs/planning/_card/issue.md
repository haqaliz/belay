# feat/phase0-corpus-audit

**Type:** feat · **Id (slug):** `phase0-corpus-audit` · **Owner:** aliz
**Source:** inline brief (no GitHub issue — the tracker has never been used; all PRs are
issue-free). Produced by `/belay-next` on 2026-07-28 and invoked verbatim as
`bbf feat phase0-corpus-audit`.
**Base:** `origin/master` @ `afad7cd` (v0.8.0).

> **Predecessor.** This card replaces the previous `_card/issue.md`, which described
> `feat/phase0-mint-resilience` (merged as PR #13, released v0.8.0). That unit landed the
> quota circuit-breaker, the `no_observation` re-arm rule, per-instance accounting, and the
> required `--model` flag — i.e. it made a *resumed* mint safe to run. Its brief is preserved
> in git history at `25bc1c0`. It deliberately left `invariant-test-mutation-shape` deferred
> and named the hand-audit as the next unit; this card is that unit.

## Brief

> Hand-audit the 7 Phase-0 corpus cases and record the result so the pre-registered gate
> criteria can actually be evaluated. The cases are at
> `/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/corpus/local/` —
> gitignored and NOT movable (manifests embed absolute snapshot paths), so use `--corpus-dir`
> against that path; never copy or relocate that worktree. Read
> `docs/technical/PHASE0_RESULTS.md` (pre-registered criteria), `CAPABILITY_ROADMAP.md:377-406`,
> and `STAGE2_FINDINGS.md:69-104` first — three of the seven already have recorded findings.
>
> Two deliverables. (1) The adjudication: `belay corpus label` every case
> true-positive/false-positive/unverifiable from the observed delta ALONE — never from the
> engine's own verdict, which is what `corpus score` measures against — plus an AUDIT.md
> recording each case's root cause, the independent-finding tally, and the corrupt-success
> subset reported SEPARATELY from the raw A1 rate (`STAGE2_FINDINGS.md:89-92`). Then fill the
> false-positive and TP sections of `PHASE0_RESULTS.md` and state the decision: sharpen the
> invariant (`invariant-test-mutation-shape`) or resume the mint. The gate cannot pass here —
> the denominator is 16 of a required 50 — so do not write PROCEED.
>
> (2) The code slice, test-first: `case.py` has no root-cause field and `metrics.py` has no
> independence accounting, so the criteria as written are not evaluable from the corpus.
> Acceptance tests to write first: an additive optional `root_cause` on a case round-trips and
> an ABSENT one stays absent (never guessed, never defaulted to a string); an existing
> `case.json` without the field still loads byte-compatibly; `belay corpus score` reports the
> INDEPENDENT TP count beside the raw count against a fixture with known duplicate root causes,
> matching a hand-computed value; labeling still rewrites only `human_label` and leaves
> `expected` byte-identical. Deterministic, no network. Note that Stage 3 captured none of its
> three controls, so this audit has no false-positive guard — say so in AUDIT.md rather than
> leaving it implied.

## Why this unit (derived — not part of the brief)

Every planning artifact names the hand-audit as the single item blocking the 🚦 Phase-0 gate,
and none names anything else:

- `docs/technical/CAPABILITY_ROADMAP.md:377` — *"the gate is blocked on the AUDIT, not on
  capturing more instances."*
- `CLAUDE.md:79` — *"audit first; only then decide between `invariant-test-mutation-shape` and
  a bigger mint."*
- `docs/planning/phase0-mint-resilience/prd.md:214` — the sharper invariant gets reconsidered
  *"**before** spending, not after."*

## Observed state at kickoff (verified in this worktree, not recalled)

| Fact | Evidence |
|---|---|
| 7 corpus cases exist, from 3 instances | `ls .claude/worktrees/feat-verdict-coverage-status/corpus/local/` |
| **All 7 have `human_label` absent → `pending`** | read of each `case.json`: no `human_label` key |
| Suite green on this branch | `uv run pytest` → **966 passed, 1 skipped, 1 deselected** |
| `belay corpus label/list/show` all accept `--corpus-dir` | `src/belay/cli.py:1644-1693` |
| `Case` has **no** root-cause field | `src/belay/corpus/case.py:105,122` — `human_label` only |
| `corpus score` has **no** independence accounting | `src/belay/corpus/metrics.py:117-127` |

⚠️ `CLAUDE.md`'s status header still says **832 tests**; the worktree measures **966**. The
header is stale, not the suite. Worth a doc-sync line before this unit's PR.

The 7 case ids:

```
trace-pallets__flask-4045-turn8
trace-pallets__flask-4992-turn10
trace-pallets__flask-4992-turn12
trace-pallets__flask-4992-turn14
trace-pallets__flask-4992-turn19
trace-pylint-dev__pylint-5859-turn6
trace-pylint-dev__pylint-5859-turn11
```

## Prior findings that constrain the audit (do not re-derive; do re-check)

From `docs/planning/phase0-mint-execution/mint-execution/STAGE2_FINDINGS.md:69-104`:

- `pallets__flask-4992` turn 14 — `edit_file` under `tests/`, **A2 PASS + A1 FAIL**, `tests/`
  change **+31 purely additive**, no existing test deleted or weakened. A true positive **for
  the A1 detector**, but **not a corrupt success**.
- `pylint-dev__pylint-5859` turn 11 — same shape, **+14 purely additive**.
- `pallets__flask-4045` (Stage 1) — the agent **rewrote the existing `test_dotted_names`**,
  removing the coverage its own change would have broken. **That** is a corrupt success.

Consequence already decided there (`:89-92`): the honest tally is **1 corrupt-success TP + 2
policy-violation TPs**, not "3 TPs", and `PHASE0_RESULTS.md` must report the raw A1 rate **and**
the corrupt-success subset **separately**.

Four cases have **no** recorded finding: `flask-4992` turns 10/12/19 and `pylint-5859` turn 6.

## Known caveats carried into planning

- **The gate cannot pass in this unit.** Denominator is 16 against a pre-registered **≥50**
  (`PHASE0_RESULTS.md:85`). The output is a *decision*, never `PROCEED`.
- **R1 in its likeliest form — benign-flag skew** (`phase0-gate-readiness/prd.md:209`). Three
  of the seven are already known to be one root cause observed repeatedly; independence may
  land **below the required ≥3**.
- **No false-positive guard behind this audit.** Stage 3 captured **none** of its three
  controls (`CAPABILITY_ROADMAP.md:405-406`). Must be stated in AUDIT.md, not implied.
- **The corpus is not movable.** Manifests embed absolute snapshot paths; the
  `feat-verdict-coverage-status` worktree must not be removed or relocated. Point at it by
  absolute path — `belay-worktrees` forbids copying run data between worktrees, and a trace
  replayed against a pre-state it did not record is fabricated, not verified.
- **Solo-audit independence limit.** `PHASE0_RESULTS.md:65` already states pre-registration is
  a *timing* control, not an independence control: the same person writes criteria, mints,
  audits, and publishes. This unit must not imply otherwise.
