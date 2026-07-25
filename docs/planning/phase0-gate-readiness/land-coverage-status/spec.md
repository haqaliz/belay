# Aspect — `land-coverage-status`

**Unit:** `phase0-gate-readiness` · **Sequence:** 1 of 5
**Placement:** `src/belay/replay/report.py`, `docs/planning/_card/issue.md`, `CLAUDE.md`,
release machinery
**Ships with:** `interop-merge-repair` (aspect 2) — **the same PR**. Landing this alone
introduces a known correctness regression; see that spec.

---

## Problem slice

`feat/verdict-coverage-status/aliz` holds the engine change that makes a Phase-0 mint
measurable at all, and it is not on `master`. Without `NOT_COVERED`, every turn through the
reference filesystem server reduces to `UNVERIFIED` (Stage 1: 12/12, `NO_VERIFIABLE_TURNS`,
`INSTRUMENT SUSPECT`), so the denominator is zero and Stage 3 would be a void run.

**User outcome:** `master` can produce a non-zero, honest violation-rate denominator.

## In scope

- Merge `master` into the branch (or rebase — see sequencing note), resolving:
  - `src/belay/replay/report.py` — both sides append to `_PREFIX_LABELS`. **Concatenate.**
    The branch's specific-before-catch-all ordering constrains only its own five
    `REPLAYED_*` entries; master's `embedded path unrelocatable` entry is order-independent.
  - `docs/planning/_card/issue.md` — per-unit scratch card; take either side.
- Keep the suite green and confirm the count moves as expected (branch baseline
  `754 passed, 1 skipped, 1 deselected`, plus whatever master's 31 commits contribute).
- Decide the disposition of `5d9a63a` (Stage-2 findings + `eval/instances/stage2.json`).
  It is out-of-unit content riding along, **and** it is the best evidence the unit works.
  Default: let it ride, and say so in the PR body rather than silently including it.
- PR against `master`, merge, cut a release.
- Fix `CLAUDE.md`'s stale "463 tests" claim.
- Prune the two verified-merged leftover worktrees and their local branches
  (`feat-invariant-verdict-a1`, `feat-phase0-mint-execution`).

## Out of scope

- Any change to `NOT_COVERED` semantics. This aspect **lands** the design; it does not
  revisit it.
- The interop repairs — aspect 2, same PR, separate commits.
- Anything touching the mint or `PHASE0_RESULTS.md` numbers.

## Acceptance criteria (test-first)

1. **The merged tree is green.** Full suite passes on the merged result. Recorded as an
   exact count, not "tests pass".
2. **`_PREFIX_LABELS` retains both sides.** A test asserts that *both* master's
   `embedded path unrelocatable` mapping and the branch's five `REPLAYED_*` mappings resolve
   correctly after the merge — the concatenation is the one place a silent drop would hide.
3. **The reduction still refuses to promote.** The branch's existing exhaustive guard
   (`tests/test_verdict_not_covered.py::test_not_covered_is_never_a_reduced_status`) passes
   unchanged on the merged tree — `NOT_COVERED` is never a reduced status, and an
   empty-after-filter set reduces to `UNVERIFIED`, never `PASS`.
4. **A `readOnlyHint` FAIL is never softened** by the merge
   (`tests/test_verdict_not_covered.py:150` green).
5. **Denominator sanity, on real data:** re-verifying Stage 1's existing captured trace
   against the merged tree yields verifiable turns rather than 12/12 `UNVERIFIED`. This is
   the aspect's load-bearing check — it is the difference between a measurable mint and a
   void one. (Shared with aspect 5's determinism check; run it here first.)
6. **No release without aspect 2.** A merge commit containing this aspect but not
   `interop-merge-repair` fails acceptance by definition.

## Dependencies and sequencing

- No code dependencies; this is the first aspect.
- **Merge, do not rebase**, unless the history needs to be linear for the release. The
  branch is 31 behind with 10 commits; a merge keeps `5d9a63a` and the phase commits
  legible, and the conflict set is identical either way (`git merge-tree` confirms two).
- `eval/clones/` (743 MB) lives in the branch's worktree and is gitignored — it does **not**
  move with the merge. Aspect 5 handles relocation; do not copy `/eval/mint/` or
  `/corpus/local/` anywhere (run state, provenance-bound).

## Open questions / risks

- **`corpus run` REGRESSIONs are expected after this lands**, confined to the
  `A2 / effect:network` entry: cases stored pre-release recorded that sub-verdict as
  `UNVERIFIED` and now recompute as `NOT_COVERED`. Confirm the diff is confined to that
  entry; a REGRESSION on any other axis is real. Do **not** relabel cases to silence it.
- Whether the release is a minor (`v0.7.0`) — the verdict contract gains a fifth status, so
  minor at least; this is user-visible behavior change on every rendering surface.
