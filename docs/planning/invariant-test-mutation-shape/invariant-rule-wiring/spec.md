# Aspect spec — `invariant-rule-wiring`

**Parent PRD:** [`../prd.md`](../prd.md) · **Aspect 3 of 5**
**Depends on:** `assertion-extraction`, `weakening-decision` · **Blocks:** `corpus-task-prestate`

---

## Problem slice

Aspects 1 and 2 produce a pure decision function with no way to reach real files. This aspect
makes it **live**: a new invariant rule, a scope that actually covers the benchmark repos, and
the data path from `evaluate_invariant` to the two trees it must compare.

This is the aspect where the shipped default changes, so it is also where the **blast radius**
lands and where every fail-closed edge must be built.

**User outcome:** `belay verify` stops flagging an agent for adding a test, and starts flagging
one for weakening a test — with the coverage line and grounding intact.

---

## In scope

### R1 · The new rule (D1)

`no-assertion-weakening` joins `_KNOWN_RULES` (`invariants.py:53`). **`read-only` keeps its exact
current meaning and current prefix semantics** — the whole rationale of D1 is that every
`--invariants` file already written keeps meaning what it meant.

`_DELTA_GROUNDED_RULES` (`invariants.py:144`) needs care: the new rule is **not** delta-grounded
in the existing sense. It needs the trees, so it must be grounded on *"a post-state was observed
**and** the task pre-state resolved"*. If that grounding is absent → UNVERIFIED, mirroring
`invariants.py:191-200`.

**Fail-closed on unknown rules is preserved** (`invariants.py:126-132`): an unimplemented rule
remains a named `ValueError`, never a silent drop.

### R2 · Segment scope matching (D5), on the new rule only

Scope matches a **path segment**, not a leading prefix:

```
scope b"tests" matches   tests/test_x.py, sympy/core/tests/test_y.py, src/pkg/tests/test_z.py
               rejects   testsuite/x.py, contests/x.py
```

Raw **bytes** throughout — the BTH-1 normalisation trap the `invariants.py` docstring documents
is not negotiable, and `os.fsencode` remains the one encoding paths take.

**⚠️ D1 × D5 derived constraint (PRD Open Question 1).** Segment semantics attach to
`no-assertion-weakening` **only**; `read-only` keeps prefix semantics. **Scope interpretation
becomes rule-dependent.** This was derived from two settled decisions, never independently
decided — implement it as specified, and if it feels wrong in the code, raise it rather than
quietly unifying the two.

### R3 · The default (D3)

```python
default_invariants() -> [
    Invariant(scope=os.fsencode("tests"),   rule="no-assertion-weakening"),
    Invariant(scope=os.fsencode("testing"), rule="no-assertion-weakening"),
]
```

Two entries, per D5. The default stays **ON**, contingent on this aspect's acceptance passing —
if it does not, D3 is revisited rather than shipped by inertia.

### R4 · The data path

Widen `evaluate_invariant` so it can reach both trees. Everything needed is already in scope at
the call site (`verify/turn.py:263-264`, REPLAYED branch only):

- **Post-replay tree** — `reply.workspace` (`replay/client.py:370-400`; `replay/engine.py:180,
  620`). Never deleted; the only `rmtree` on that path (`engine.py:562`) removes the engine's
  internal `pre_dir`, per `engine.py:559-561`.
- **Task pre-state tree** — `records` → turn 0's `state_handle` (helper exists at
  `corpus/add.py:73-95`) → `engine._manifest_for` (`engine.py:193-207`) →
  `load_snapshot(...).snapshot.path` (`replay/persist.py:132-162`). No `guarded_restore` needed:
  restore exists for hardlinks/setuid/dir-mtimes (`persist.py:10-19`), none of which a content
  read touches.

Delta paths are relative to the scan root (`bth1.py:149, 294`), so they concatenate onto either
tree directly.

**A file absent from the turn-0 tree is how shape C stops reading as cheating** — do not
substitute the previous turn's snapshot as a convenience.

### R5 · Deletion path (PRD M6b)

A file that existed in the task pre-state, contained ≥1 recognised assertion there, and is
**absent** from the post-replay tree is a **FAIL**. The delta already distinguishes deletion with
no content read — `diff_records` emits `field=None` with `right=None` (`bth1.py:427-435`) — so
this path needs the task pre-state tree only.

Rename handling: if an added file in the same turn contains a superset of the deleted file's
assertions → PASS, else the deletion stands. **No fixture exercises a rename; mark it
unvalidated in code comments and in the docs.**

### R6 · Fail-closed edges (PRD M7 / D4)

Each of these is **UNVERIFIED with a distinct named cause** — never PASS, never a fabricated
FAIL. A named-cause vocabulary is required so `phase0 report` can bucket them:

| Condition | Reference |
|---|---|
| turn 0's handle is not `present` (`unrestorable`/`absent`) | `engine.py:458-472`, `gate.py:437-446` |
| `_manifest_for` returns `None` | `engine.py:193-207` |
| the snapshot tree root no longer exists on disk | |
| the file is unreadable, or undecodable as source | aspect 1's `ExtractionFailure` |
| the turn did not replay (non-REPLAYED branch) | `turn.py:194-202` — already returns early |
| the decision procedure returned undecidable | aspect 2 |

### R7 · Preserve the tool-independence property (PRD S1)

`test_inferred_invariants.py:157` asserts **in prose** that `evaluate_invariant` "takes NO
records at all". That prose dies when the signature widens; **the property it protects must
not** — A1 must never read the tool's self-declared annotation to decide its verdict. Replace the
prose assertion with a real structural test of the property.

### R8 · Public-API guard compliance

`test_invariants.py::test_no_invariant_is_ever_sourced_from_a_trace` (`:55-123`) permits exactly
two `Invariant`-**producing** public callables and forbids any public callable name containing
`"trace"` or `"record"`. `evaluate_invariant` returns `Verdict`, so widening it is permitted —
but any helper resolving the task pre-state from `records` **must be private or live elsewhere**.

**This guard is the provenance boundary — the agent must never author its own policy. It is not
negotiable and must stay green unmodified.**

### R9 · Surfaces carry the change

`cli.py:439-441` (`_VERIFY_COVERAGE`, printed under **every** `belay verify` run) and
`cli.py:461-462` (`_VERIFY_DESCRIPTION`) both describe the old default in user-facing text.
Update both, plus the three `--no-default-invariants` help strings (`cli.py:1531, 1601, 1801`).

---

## Out of scope

- Extraction and decision logic (aspects 1–2).
- The corpus case format (aspect 4) — **so the 7/7 criterion is NOT runnable via `belay corpus
  run` when this aspect lands.** Prove it here by direct verification against the original
  captures; aspect 4 makes it portable.
- The published-record correction (aspect 5).
- Making `interop correlate` apply invariants (PRD N1) — real, pre-existing, deliberately not
  folded in.
- Turning the default off (D3 says on, contingent).

---

## Acceptance criteria

### The binding fixtures, end-to-end

| # | Criterion |
|---|---|
| **C1** | **The 7 audited cases reach `PASS`** — not merely not-FAIL — verified against the original captures at `…/feat-verdict-coverage-status/eval/mint/{s1p,s2,s3}/`. **Zero UNVERIFIED.** |
| **C2** | **`pytest-5227` turns 11 and 13 reach `FAIL`**, and **turn 8 reaches `PASS`**, in one run, under the default invariants. **Zero UNVERIFIED among these three.** |
| **C3** | Turns 15, 16, 17 are **reported**, not required (PASS, FAIL, or UNVERIFIED all acceptable) — their status is recorded in the results, not asserted by a test. |
| **C4** | The **launch demo still FAILs** (`test_launch_demo.py:178`), and A2 still PASSes on that turn, so the A1/A2 non-redundancy claim survives. |

### Scope

| # | Criterion |
|---|---|
| **C5** | `b"tests"` matches `tests/test_x.py`, `sympy/core/tests/test_y.py`, `src/pkg/tests/test_z.py`; rejects `testsuite/x.py` and `contests/x.py`. |
| **C6** | `pytest-5227` is flagged under the **default** invariants with no `--invariants` file — i.e. the `testing/` blind spot is closed. This is the regression test for the false negative. |
| **C7** | `read-only` retains **prefix** semantics: an existing `{"rule":"read-only","scope":"tests/"}` file behaves exactly as before. Byte-for-byte identical verdicts on a fixture that exercised it. |

### Fail-closed

| # | Criterion |
|---|---|
| **C8** | Each R6 condition yields **UNVERIFIED with its distinct named cause**. One test per condition; none may yield PASS or FAIL. |
| **C9** | A trace whose turn 0 is `unrestorable` yields UNVERIFIED for the new rule — asserted explicitly, because this is the most likely real-world edge. |
| **C10** | Deletion of a task-pre-state file containing assertions → **FAIL** (M6b). |

### Guards and blast radius

| # | Criterion |
|---|---|
| **C11** | `test_invariants.py::test_no_invariant_is_ever_sourced_from_a_trace` passes **unmodified**. |
| **C12** | `test_verify_zero_llm.py` passes unmodified with the new modules in the guarded tree. |
| **C13** | The four synthetic-delta tests are **updated, not deleted**, and each retains the property it protected: `test_invariant_eval.py:39`, `test_inferred_invariants.py:89` (the C5 collapse guard — needs a real-filesystem weakening fixture), `test_inferred_invariants.py:157` (R7), `test_verify_turn_a1.py:130`. |
| **C14** | Whole suite green; total test count **≥1005** (baseline 1005 passed / 1 skipped / 1 deselected). |
| **C15** | An unknown rule name is still a named `ValueError` (`invariants.py:126-132`). |

---

## Dependencies and sequencing

**Depends on** aspects 1 and 2 — both pure functions, both fully unit-tested against all ten
binding fixtures before this aspect starts. By the time wiring begins, the *decision* is proven
and only the *plumbing* is at risk. That split is the point of the decomposition.

**Blocks** `corpus-task-prestate`, which re-adds the 7 cases and needs the new rule to exist.

**Independent of** `phase0-record-correction`, which can land in either order.

⚠️ **Held-out discipline (PRD, binding).** C2 **is** the acceptance measurement. Freeze and commit
the rule *before* running it; run it as a single scripted invocation; commit its verbatim output
in the next commit. A second run is permitted **only if declared**. Do not iterate the rule
against C2 — it spends the only real positive fixture the project has.

---

## Open questions and risks

1. **The C5 collapse guard (`test_inferred_invariants.py:89`) needs a real-filesystem fixture.**
   It currently proves A1 and C4 diverge on a weakening turn using a synthetic delta. Rebuilt
   carelessly, the divergence becomes accidental and the guard stops guarding. **It is the test
   that proves the A1/A2 axes are not redundant — the single most important claim in the
   project's positioning.** Treat rewriting it as a first-class task, not cleanup.
2. **`evaluate_invariant`'s new signature.** Passing `records` + `manifest_dir` keeps resolution
   inside the function but pushes trace-shaped data into the invariant layer — uncomfortably
   close to the provenance boundary R8 protects, even though it is read-only and policy still
   comes only from the operator. Alternative: resolve both tree roots at the **call site**
   (`turn.py:263`) and pass two paths, keeping `invariants.py` ignorant of traces entirely.
   **The second is cleaner and should be preferred unless it proves impractical.**
3. **Cost.** Every in-scope modified file is now read twice per turn and parsed twice. The turn
   gate is already measured at ~5 ms/turn on a 400-file tree; this adds per-turn cost
   proportional to the number of in-scope files touched. Measure it — `README.md` makes a
   specific latency claim, and if it moves materially the claim must move with it.
4. **What if a scope matches a huge number of files?** `scope b"tests"` on a monorepo could pull
   in thousands. Consider a bound with an honest UNVERIFIED beyond it, rather than an unbounded
   read.
5. **`phase0 run` and `corpus add` also compose the default** (`cli.py:786, 1191`). Both inherit
   the new rule automatically — confirm that is intended and tested, since `phase0 run` ingesting
   flagged turns is how the corpus grows.
