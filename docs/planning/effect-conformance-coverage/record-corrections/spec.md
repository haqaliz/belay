# Aspect spec — `record-corrections`

**Parent PRD:** `docs/planning/effect-conformance-coverage/prd.md`
**Sequence:** 3 of 3. Depends on aspects 1 and 2 having landed.
**No code changes.** Documentation only — but it is the aspect that keeps the record honest, and
this repo treats that as load-bearing, not cosmetic.

---

## Problem slice

Three classes of recorded statement stop being true when aspects 1–2 land, plus one that was
never true.

### 1. A recorded finding that overstates itself (was wrong before this unit)

`docs/STATUS.md:65-66` — *"against annotation-less servers a corpus-filling mint can never bank a
per-turn case."* **Not what the code does.** `reduce` ranks `FAIL (3) > UNVERIFIED (2)`
(`verify/verdict.py:67-73`, `:114-117`), so a turn whose effect dimension abstains but whose A1
or result-equivalence decides a FAIL reduces to FAIL and banks normally; `add_case` enforces **no
status precondition** (`corpus/add.py:4-8`). What the abstention actually blocked was
`VERIFIED_CLEAN`, hence the **denominator**. The mint banked nothing because its two controls
were honest negatives with no FAIL to bank (`STAGE1_FINDINGS.md:76-80`).

### 2. Prose that counts the `NOT_COVERED` dimensions

Under aspect 1 there are **two**, not one:
- `CLAUDE.md` — *"today exactly one: a tool's `openWorldHint: false` network promise"*
- `README.md:283`, `:306`, `:308`
- `tests/test_coverage_rendering.py:53-56` — *"the only NOT_COVERED sub-verdict that exists today"*
- `src/belay/cli.py:1552-1556` — names *"an un-annotated tool"* as a producer of
  replayed-but-UNVERIFIED, which is exactly the population that moves

### 3. The reclassification statement (required, not optional)

House wording, per `verdict-coverage-status` and its siblings:

> the `UNVERIFIED` rate before and after this change is **not comparable** — the drop is a
> reclassification of turns Belay never had an instrument for, **not** improved detection.

### 4. The rule table and disposition contract

`src/belay/verify/effect.py:18-25` states `not-declared -> UNVERIFIED (no contract to check
against)` as a flat rule. It must state the split, and **quote what it replaces**.

---

## In scope

1. Correct `docs/STATUS.md`, quoting the superseded sentence rather than deleting it (house
   style — corrections are additive and name what they replace).
2. Update every "exactly one `NOT_COVERED` dimension" statement listed above.
3. Add the reclassification / not-comparable statement wherever an UNVERIFIED rate is quoted
   across this boundary.
4. Update `effect.py`'s module rule table, quoting the replaced rule.
5. A `docs/STATUS.md` entry for the unit itself, in the established format: what shipped, what it
   does **not** do, what was measured, and the named residuals.
6. Record the two named follow-ups: the `annotation_staleness` gap (PRD open question 4) and the
   8-duplicated-coverage-sentences consolidation.

## Out of scope

- Any code change other than the `effect.py` docstring.
- Re-deriving or recomputing any published number.
- The `CHANGELOG.md` / release — a separate step, not this aspect.

---

## Acceptance criteria

**AC-1 — no published number moves.** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
`recall 0.00`, `3/93` appear **unedited**. Verify mechanically (grep before/after), not by eye.

**AC-2 — every correction quotes what it replaces.** No superseded claim is silently deleted.

**AC-3 — no stale count survives.** Grep for *"exactly one"*, *"the only NOT_COVERED"*, and
`effect:network` as a sole example; each hit is either updated or justified in place.

**AC-4 — the reclassification statement is present** wherever an UNVERIFIED rate crosses this
boundary, in the house wording.

**AC-5 — the `STATUS.md` entry names what this unit did NOT do:** it did not re-run the mint,
did not produce a Phase-0 number, did not change A1/A3/`reduce`/the trace format, and did not
close the `annotation_staleness` gap.

**AC-6 — the honest cost is recorded, not buried:** the unit **rewards server silence** (a server
omitting `readOnlyHint` now gets PASS where it got UNVERIFIED, and omission is the adversarial
move), accepted because this axis already disclaims adversarial coverage and A1 invariants are
load-bearing. This must appear in the record, not only in the PRD.

---

## Dependencies

Aspects 1 and 2 must have landed; otherwise the record would describe code that does not exist.

## Risks

- **The temptation to overstate the win.** This is a reclassification that makes an honest
  verdict legible — not improved detection, and not a new capability. Every sibling unit in
  `STATUS.md` states this discipline explicitly; this one must too.
