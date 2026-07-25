# Aspect — `interop-merge-repair`

**Unit:** `phase0-gate-readiness` · **Sequence:** 2 of 5
**Placement:** `src/belay/interop/attach.py`, `src/belay/interop/report.py`,
`src/belay/cli.py`, `tests/test_interop_attach.py`, `tests/test_coverage_rendering.py`
**Ships with:** `land-coverage-status` (aspect 1) — **the same PR.**

---

## Problem slice

`belay.interop` (C9, merged in v0.5.0) did not exist when `verdict-coverage-status` forked,
so the branch's "coverage travels on every surface" rule never reached it — and, worse, the
branch invalidates an invariant interop depends on. Merging aspect 1 alone ships **a
fabricated fact and a silent over-claim**, neither caught by any existing test.

**User outcome:** after the merge, `belay interop correlate` states what it checked and never
asserts something about the run that did not happen.

## In scope — three defects, in priority order

### 2a — The fabricated cause (correctness regression; do this first)

`src/belay/interop/attach.py:139`:

```python
cause = UNRESTORABLE_PRE_STATE if turn_verdict.cause is not None else None
```

Its own comment states the premise: *"`TurnVerdict.cause` … is ALWAYS `None` on a REPLAYED
turn."* Aspect 1 breaks it — `src/belay/verify/turn.py:274` now sets
`cause=_replayed_cause(sub_verdicts)` whenever a replayed turn reduces to `UNVERIFIED`.
Result: a span whose turn **replayed fine** is labeled `unrestorable-pre-state`, asserting a
snapshot-restore failure that never occurred.

Fix: discriminate on the **actual non-REPLAYED branch**, structurally — not on
`cause is not None`. Correct the now-false premise in the `attach.py:25–33` docstring.

**Why the existing test does not catch it:**
`tests/test_interop_attach.py::test_matched_replayed_pass_turn_has_no_bespoke_cause`
hand-builds `TurnVerdict(..., status=Status.PASS, cause=None)` through the `verify=` stub
seam. It cannot fail on this bug, because it never exercises the contract that moved.

### 2b — `PASS` rendered with no coverage line

`src/belay/interop/report.py:61–67` prints `r.status.value`; `render()` (`:70–97`) emits no
coverage block and `to_json()` (`:99–124`) emits only `span_id`/`turn_index`/`status`/`cause`
— no sub-verdicts. A matched span against the reference filesystem server prints
`UNVERIFIED` today and will print bare **`PASS`** after the merge.

This also falsifies that module's own docstring honesty invariant (`report.py:13–17`),
written when the boundary lived *in* the status: *"`UNVERIFIED` renders as the literal word …
never grouped under a matched/'OK' summary that would read as PASS."* After the merge the
boundary lives in a dropped sub-verdict the module never reads, and the sentence becomes
untrue without one character of it changing. **Correct the docstring as part of the fix** —
a stale honesty invariant is worse than none.

### 2c — The branch's own two unpinned surfaces

The branch's rule was "a test per surface, not by review", and two surfaces slipped:
- **`belay verify` per-turn** — `cli.py:558 _emit_verdict` does print every sub-verdict with
  its message, so it works; it just isn't pinned.
- **`belay corpus show`** — `cli.py:1049–1053` prints `axis/kind/status` but **not the
  message**, so the declared-vs-not-declared distinction is lost on that surface. Round-trip
  is tested (`tests/test_coverage_compat.py:87`); rendering is not.

## Out of scope

- Exporting verdicts back into a collector, multi-trace aggregation, the `NOT_COVERED`
  reclassification *of span buckets* — all deferred C9 follow-ups, unchanged here.
- Any new verdict, status, or axis. This aspect computes nothing; it repairs a derivation
  and adds disclosure.

## Acceptance criteria (test-first — RED before GREEN)

1. **No fabricated cause.** A turn that replays and reduces to `UNVERIFIED` with a named
   replayed cause correlates to a span whose `cause` is **not** `unrestorable-pre-state`.
   The test must drive the **real `verify_turn`**, not the stub seam — a version of this
   test that passes against the pre-fix code is not a valid test.
2. **The real unrestorable case still reports.** A genuinely unrestorable pre-state still
   yields `unrestorable-pre-state`. (Guards against fixing 1 by deleting the signal.)
3. **`PASS` never renders bare.** A matched span whose turn carries a `NOT_COVERED`
   sub-verdict renders with its coverage line in `render()`, and `to_json()` carries the
   sub-verdict. Asserted on the CLI surface (`belay interop correlate`), not only on the
   module.
4. **`UNVERIFIED` still renders as the literal word** in its own column, never grouped under
   a matched/OK summary — the module's original invariant, now actually enforced.
5. **The docstrings match the code.** `attach.py:25–33` and `report.py:13–17` state premises
   that are true of the merged tree.
6. **`belay verify` per-turn and `belay corpus show`** each carry a coverage-rendering test;
   `corpus show` prints the sub-verdict message.
7. **No verdict changes.** Every pre-existing PASS/FAIL verdict is byte-identical; this
   aspect adds disclosure and fixes a cause derivation, and touches nothing else.

## Dependencies and sequencing

- **Hard dependency on aspect 1's merged tree** — 2a is only reproducible once
  `verify/turn.py:274` and `interop/attach.py` are in the same tree. Sequence: merge locally,
  write the RED tests, fix, then PR both together.
- 2a before 2b: a fabricated fact outranks a missing disclosure.

## Open questions / risks

- **The stub-seam lesson generalizes.** Other tests may stub contracts that have since
  moved. Worth a quick scan for `verify=`-style seams while here — but do not expand this
  aspect into a test-suite audit; note findings and move on.
- Whether the coverage line belongs in `render()` per-span or once as a footer. Per-span
  is noisier; a footer risks being read as applying to spans it doesn't cover. Lean
  per-span, matching `_emit_coverage`'s existing shape.
