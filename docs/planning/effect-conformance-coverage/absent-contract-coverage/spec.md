# Aspect spec — `absent-contract-coverage` (the engine slice)

**Parent PRD:** `docs/planning/effect-conformance-coverage/prd.md`
**Sequence:** 1 of 3. Blocks `coverage-surface-parity` and `record-corrections`.
**Capability:** C4 (A2 effect-conformance). No new axis, no new status, no schema bump.

---

## Problem slice

A2 effect-conformance collapses **four different claims** into one `UNVERIFIED` status
(`src/belay/verify/effect.py:556-566`, the NOT_DECLARED fall-through with no `if`). One of the
four — *the server was observed and declared no `readOnlyHint`* — is not a failed attempt at all;
it is a **coverage boundary**. Because the other three genuinely are abstentions, the collapse
makes every turn against an annotation-less server UNVERIFIED, which is why `VERIFIED_CLEAN` is
unreachable and the mint's denominator is structurally zero.

**User outcome:** a turn against the pinned npm filesystem server that replayed and reproduced
its reply reduces to **PASS**, carrying an `effect` `NOT_COVERED` sub-verdict that says on every
surface what was not checked and why — instead of a bare UNVERIFIED that reads as *"the tool is
broken."*

---

## In scope

1. **Split the not-declared status by producer.**
   - Producer **iv** (`effect.py:225-231`) — snapshot observed, tool present in it, server
     declared no `readOnlyHint` → **`NOT_COVERED`**, axis `A2`, kind `effect`.
   - Producers **i–iii** (`:202-210`, `:215-223`, `:180-191`) → **`UNVERIFIED`**, unchanged,
     each keeping its existing named cause.
2. **An explicit, named, tested discriminator.** Do **not** ship the split resting on
   `ann.cause is None`, which works only by an undocumented dataclass default and would be
   silently re-merged by any future edit adding a `cause=` to `:225-231`. Carry the distinction
   on a named field on `TurnAnnotation` (`:116-133`), set at the single return site.
3. **The message must say something true on every path.** `effect.py:562-565` interpolates
   `{ann.cause}` and renders literally `did not declare readOnlyHint (None)` on the common case.
4. **The declared-vs-silent distinction survives in the message** (precedent requirement 6).
5. **Rewrite, quoting what it replaces**, any docstring whose stated rule this changes — at
   minimum `effect.py`'s module rule table (`:18-25`).
6. Re-vehicle the 5 incidental tests that use an un-annotated tool merely to manufacture a
   replayed-then-UNVERIFIED turn.

## Out of scope (this aspect)

- The four undisclosed surfaces, `_COVERAGE_PROSE`, and the persisted ledger field → aspect 2.
- `docs/STATUS.md` correction and stale prose in `CLAUDE.md` / `README.md` → aspect 3.
- Any change to `reduce`, `_RANK`, A1, A3, the trace format, or the corpus case schema.
- The `annotation_staleness` gap (PRD open question 4) — named follow-up, not built.
- The `replayed_any` predicate. **It is deliberately untouched**: the reduced status becomes PASS
  on its own, so the existing predicate works unchanged.

---

## Acceptance criteria (testable — written first, RED before GREEN)

**AC-1 — the boundary case becomes a coverage boundary.** A replayed turn whose tool is present
in an observed `tools/list` snapshot that declares no `readOnlyHint`, with a reproducing reply,
yields an `effect` sub-verdict with `Status.NOT_COVERED`, and the **turn** reduces to `PASS`.

**AC-2 — the three abstentions are untouched.** For each of producers i, ii, iii independently:
the `effect` sub-verdict is still `Status.UNVERIFIED`, still carries its existing named cause,
and the turn still reduces to `UNVERIFIED`. In particular
`tests/test_verify_effect.py:119` (`test_a_call_with_no_preceding_snapshot_is_unverified`) passes
**unmodified**.

**AC-3 — A2 keeps its teeth.** These pass unmodified (the protection list):
`tests/test_verify_effect.py:79`, `:145`, `:161`, `:244`, `:256`;
`tests/test_verify_tool_not_offered.py:1189` (whole-`Verdict` equality **including message**);
`tests/test_verdict_not_covered.py:91`, `:135`, `:165`.
A declared-true tool that mutates is still a grounded **FAIL**.

**AC-4 — the discriminator is explicit and guarded.** A test asserts the split keys on the named
field, **not** on `cause is None`; and a test fails if producer iv's return site starts passing a
`cause=` while the split still claims to distinguish it. (The point: re-merging the populations
must break a test, not pass silently.)

**AC-5 — no message renders a Python `None`.** No verdict message produced by
`render_effect_verdict` contains the substring `(None)`, on any of the four producers.

**AC-6 — the distinction is legible.** The `NOT_COVERED` message states that the server declared
no contract; the UNVERIFIED messages state that the contract could not be observed. A reader can
tell *"nothing was promised"* from *"we could not see what was promised."*

**AC-7 — the reduction is untouched.** `reduce` is not modified. `NOT_COVERED` is still dropped
before ranking, still never a reduced status, still never promotes; an all-`NOT_COVERED` set
still reduces to `UNVERIFIED`.

**AC-8 — `VERIFIED_CLEAN` becomes reachable, with one story.** An instance whose only turn is the
AC-1 turn has disposition `VERIFIED_CLEAN`, `violation_denominator() == 1`, `instrument_suspect`
False — **and** `turn_status_counts` reports that turn as `PASS`, not `UNVERIFIED`. (This is the
anti-two-stories check: the printed rate and the turn tally must agree.)

**AC-9 — measured blast radius.** The full suite is run before and after; every newly-RED test is
either in the deliberate-revisit list (`tests/test_verify_effect.py:103`, `:244`;
`tests/test_verify_turn.py:184`) or a re-vehicled incidental
(`tests/test_replayed_cause.py:94`, `:111`, `:144`, `:165`;
`tests/test_interop_attach.py:391`). **Any other newly-RED test is a stop-and-report.**

---

## Dependencies & sequencing

- Depends on: nothing unbuilt. C1/C4 shipped; the discriminator needs no new derivation.
- Blocks: aspect 2 (surfaces must disclose the new cause) and aspect 3 (record corrections).
- **PR #38 is open and red and touches the corpus recompute path.** Land it first or accept a
  merge conflict; not a hard blocker for this aspect.

## Open questions (resolve before coding)

1. **Does producer ii (tool absent from an observed snapshot) belong with i–iii or with iv?**
   Drafted as i–iii. If the tool is genuinely absent from a snapshot we *did* observe, that is
   arguably "no contract for this tool" rather than "unobserved". **Owner call.**
2. Should the named field be `annotations_object` (`"present"|"absent"`, already computed at
   `annotations.py:78`) or a purpose-built marker? `annotations_object` answers a narrower
   question (absent object vs *empty* object — both yield no `readOnlyHint`), so it may not be
   the right key on its own.

## Risks specific to this aspect

- **It rewards server silence** (PRD R-A) — the owner-accepted cost. The mitigation lives in
  aspect 2: the coverage line is non-suppressible, so declaring still buys a verdict with nothing
  withheld. **Aspect 1 landing alone therefore ships the cost without its mitigation** — do not
  release between aspects 1 and 2.
- The 9-test RED set was measured against a *broader* mutation than this split. The real set must
  be **measured, not assumed** (AC-9).
