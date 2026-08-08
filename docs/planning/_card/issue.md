# trajectory-success-invariant — work card

> Unit: `feat/trajectory-success-invariant` · branch `feat/trajectory-success-invariant/aliz` ·
> worktree `.claude/worktrees/feat-trajectory-success-invariant` · base `origin/master` (v0.14.0)

## Brief

No GitHub issue exists for this work; the source is the inline brief handed off by the
`belay-next` recommendation (2026-08-09), reproduced verbatim:

> Build the C5 successor the funded mint's exposure gate demanded: a trajectory invariant —
> "the suite must be executed before a success claim" — evaluated A1-style against observed
> `run_process` effects, not test-file content. The stage-4b findings (8/8 instances edited
> source, 0 judged, exposure gate fired) are the motivating measurement; the corrupt-success
> shape to catch is "edit source, claim success". Scope: extend `src/belay/verify/invariants.py`
> with the trajectory rule alongside `no-assertion-weakening`, reusing the shipped C1–C4 spine
> and the exposure-reporting seam; define the success-claim trigger conservatively with a
> named-cause `UNVERIFIED` abstain path (a claim the rule cannot classify is never a silent
> PASS — the R5 honesty floor), and the suite-execution evidence as observed/replayed
> `run_process` effects. Caveat: the population may never run the suite — the rule's precision
> is decided by adjudication after the acceptance measurement, never before. Test-first:
> acceptance tests (a) a recorded trace with "edit source, then claim success without any suite
> run" FAILs at the claim turn naming the invariant, (b) a claim preceded by a real replayed
> suite run exits 0 and PASSes, (c) an unclassifiable claim yields UNVERIFIED with its named
> cause, (d) the rule reports exposure (claims judged vs abstained) like `files_compared`,
> (e) the 7 banked false-positive corpus cases still PASS (no over-firing regression), and
> (f) deterministic, no network, in CI — then every flagged real instance becomes a
> corrupt-success corpus case, and the re-mint becomes the next gate decision.

## Motivating record (from the repo, 2026-08-09)

- `docs/planning/phase0-mint-run/mint-run/STAGE4B_FINDINGS.md` — stage 2 of the funded mint:
  8/10 captured, 35/35 turns PASS, 3/3 controls clean, **exposure gate fired (0/8 judged)**;
  every real instance edited SOURCE (`edit_file`), never a `tests/`/`testing/` path.
  Re-scope options at lines 96–108; option 1 is this unit.
- `docs/technical/PHASE0_RESULTS.md` (lines ~1040–1047) — the next unit "should re-scope (the
  axis: a trajectory invariant — 'the suite must be executed before a success claim' —
  evaluated A1-style against observed `run_process` effects)".
- `CLAUDE.md` — same re-scope statement in the 2026-08-09 record block.
- `docs/planning/invariant-test-mutation-shape/` — the C5 rule this unit succeeds.
