# feat/phase0-mint-resilience

**Type:** feat · **Id (slug):** `phase0-mint-resilience` · **Owner:** aliz
**Source:** inline brief (no GitHub issue — the tracker has never been used; all PRs are
issue-free). Produced by `/belay-next` on 2026-07-28.
**Base:** `origin/master` @ `91913a0` (v0.7.0).

> **Predecessor.** This card replaces the previous `_card/issue.md`, which described
> `feat/phase0-stage3-publish` (merged as PR #12). That unit landed the `NOT_COVERED`
> coverage boundary and the interop merge repair, ran Stage 2, and **attempted Stage 3 —
> which died on provider quota.** Its brief is preserved in git history at `d75506c`.
> The Stage-2 constraints it recorded are carried forward verbatim below.

## Brief

Finish the Phase-0 live mint. Stage 3 ran and died at **12 captured / 56 failed out of 68**
(`eval/mint/s3/checkpoint.json`, in the `.claude/worktrees/feat-verdict-coverage-status`
worktree). Every one of the 56 failures carries the same reason:

```
Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota,
please check your plan and billing details. ...
```

Two defects turned a transient provider condition into 56 permanently destroyed instances
of denominator:

1. **The minting driver has no retry, backoff, or rate-limit handling anywhere.**
   `grep -rn "429|retry|backoff|RateLimit|sleep" eval/minting_driver/*.py` returns only
   prose in `batch.py:15` and `entrypoint.py:10` saying *"no retry-with-reflection"* — an
   **agent-sophistication** guardrail, which is a different thing from transport
   resilience. One 429 marks the instance `failed`; the batch moves on.
2. **A resume cannot recover them.** `eval/minting_driver/checkpoint.py:38-41` treats
   `"failed"` as *done* — *"re-running failures is a deliberate, separate decision"* — so
   re-invoking Stage 3 today skips all 56 and captures nothing.

## What to build

- **(a)** Bounded retry-with-backoff on rate-limit / transient transport errors in the
  model-call path, classifying **retryable vs terminal** explicitly.
- **(b)** An explicit **re-arm** of transient failures, so a resumed run retries them while
  never re-spending on genuinely `captured` instances.
- **(c)** Per-instance **cost and wall-clock** recording — `phase0-live-mint/prd.md` Gap 3
  (R10, unbudgeted inference spend) names this as a required Stage-2 output that was never
  built.
- **(d)** Carried forward from the predecessor card: *"A retry-on-clone-failure in
  `prepare_workspace` is still worth adding."* Stage 2's single non-quota failure was a
  transient `git clone --bare` exit 128 that succeeded on manual retry.

## Acceptance (tests first, deterministic and offline with a fake client)

1. A client raising 429 twice then succeeding yields **one captured instance**, with the
   retries recorded.
2. A **terminal** error still records `failed`, and never aborts the batch.
3. A checkpoint full of quota-failures **re-arms on resume**, while `captured` instances
   are never re-spent.
4. Backoff is asserted **without real sleeping** (injected clock/sleep seam).
5. The live path stays `manual`-marked and out of CI.

## Constraints

- **Eval-only.** `src/belay/` must not be modified (`phase0-live-mint/prd.md` Out of Scope,
  incl. the tempting `--manifest-dir` shortcut).
- **Guardrail #1, to be written down explicitly:** retrying a *transport* error is **NOT**
  retry-with-reflection. The driver's "no retry" prose is about **agent sophistication**
  (planning / memory / reflection loops = agent-framework drift). Transport resilience is
  infrastructure. Say so in the code and the spec, or the change reads as drift.
- **Sequential / one-`tools/call`-in-flight must survive.** A retry must not introduce
  concurrency; `StdioMcp` is not thread-safe.
- **Not a verdict change.** No axis is touched. The LLM only *acts*; A1 and A2 decide.

## Known caveat

**Code is necessary but not sufficient — the binding constraint may be spend, not
software.** Backoff cannot conjure quota out of an exhausted free tier. This unit must
settle which provider/key funds the ~35+ further instances needed to reach the
pre-registered denominator of **≥50** (`phase0-live-mint/prd.md:43`).

**And the model class is not free either.** Carried from `STAGE2_FINDINGS.md` via the
predecessor card: **a pro-class model is mandatory.** Two flash models hit the 20-step cap
doing only reads and searches — never editing — which yields a 0% that *looks like a
result*, and the pre-registered gate would read it as a PIVOT on a premise that was never
tested. **The published number must name the model.**

## Execution-location constraint

The **implementation** (deterministic, offline, fake-client TDD) needs no mint data and is
done in this worktree.

The **live resumed mint** needs the ~4.7 GB of captures, bare clones, and checkpoints under
`.claude/worktrees/feat-verdict-coverage-status/eval/`. That data is **not movable** —
captures embed absolute snapshot paths, so relocating them breaks replay. The resumed mint
therefore runs from that worktree after this branch merges, not from here.

## State of the mint at the time of writing

| Stage | n | captured | failed | note |
|---|---|---|---|---|
| `s1` / `s1b` / `s1p` | 1 each | 1 | 0 | Stage-1 proof + the corrupt-success positive control |
| `s2` | 10 | 9 | 1 | the 1 failure is a transient `git clone --bare` exit 128, not quota |
| `s3` | 68 | 12 | 56 | **all 56 = 429 quota** |

Honest running TP tally going in (predecessor card): **1 corrupt-success TP + 2
policy-violation TPs** — and the two policy violations share a root cause, so under the
pre-registered *independence* rule they may count as **one** finding, not two.

`docs/technical/PHASE0_RESULTS.md` still has **18 `TO-BE-FILLED` fields** and no decision
line. It is waiting on traces and on nothing else.

## Pre-registered gate criteria (unchanged, `docs/planning/phase0-live-mint/prd.md`)

**PROCEED iff** ≥3 *independent* hand-audited TPs **AND** denominator ≥50 **AND** no
`INSTRUMENT SUSPECT`. A FAILing control voids the mint. These were fixed **before** any
live mint and are not renegotiable by this unit.

## Key references

- `eval/minting_driver/{batch,checkpoint,session,loop,model,clients/}.py`
- `docs/planning/phase0-live-mint/prd.md` (pre-registered gate criteria; Gap 3 = cost)
- `docs/planning/phase0-mint-execution/` (`mint-execution/`, `audit-and-publish/` specs)
- `docs/technical/PHASE0_RESULTS.md` (the artifact to fill)
- `docs/planning/phase0-corpus-run/RUNBOOK.md` (stale — to fix)
- `eval/README.md` (BYOK provider setup; the eval-only guardrail)
