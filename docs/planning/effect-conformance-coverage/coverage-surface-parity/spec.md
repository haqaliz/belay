# Aspect spec — `coverage-surface-parity`

**Parent PRD:** `docs/planning/effect-conformance-coverage/prd.md`
**Sequence:** 2 of 3. Depends on `absent-contract-coverage`. **Must not be skipped or deferred
past a release** — it carries aspect 1's mitigation.

---

## Problem slice

Today a `NOT_COVERED` dimension is **rare**: it appears only where a tool declared
`openWorldHint`. Aspect 1 makes one **routine** — every turn against an annotation-less server.
That converts four latent gaps into the live false-PASS-by-omission path this repo forbids.

The precedent's own hard rule, which this aspect exists to satisfy
(`verdict-coverage-status/prd.md:203-209`):

> **no surface may render a turn's status without also rendering its coverage line — enforced by
> a test per surface, not by review.**

**Four surfaces render a clean/PASS status with NO coverage disclosure, and NONE has a coverage
test:**

| surface | file:line | today |
|---|---|---|
| `belay corpus list` | `src/belay/cli.py:2303` | bare status column |
| `belay corpus run` aggregate | `src/belay/cli.py:2065-2072` | a MATCH discloses nothing; only a divergence surfaces the kind |
| `belay corpus score` | `src/belay/cli.py:2194-2197` | nothing — and its own `coverage` metric means *adjudicable labels*, a name collision |
| `belay phase0 combine` | `src/belay/phase0/report.py:786` | `_coverage_section` never called on this path |

---

## In scope

1. A coverage disclosure on each of the four surfaces above, each pinned by its own test.
2. **A `_COVERAGE_PROSE` entry for the `effect` kind** (`src/belay/phase0/report.py:145`), which
   has exactly one entry today (`effect:network`); an unlisted kind falls back to the anonymous
   *"outside what Belay observes"* (`:198`) and **no test forces an entry**.
3. **Persisted, not computed.** Confirm the coverage dimension survives a ledger round-trip, per
   the precedent's requirement 4 — *"The coverage statement must be a LEDGER FIELD, not a runtime
   computation"* — because `belay phase0 report` is a pure re-render. Verify `not_covered_turns`
   admits a second kind; bump the schema **deliberately and with a test** if it does not.
4. `belay interop export` — `_coverage_dimensions` (`src/belay/interop/export.py:109`) writes
   `belay.verdict.coverage` only `if uncovered_kinds:` and carries **kinds without the message**.
   Decide and pin: either always write it, or document the conditional.
5. Resolve the **name collision** on `coverage` (`corpus score`'s adjudicable-label metric,
   `belay replay`'s replayed/unverified counts) at least in help text, so a reader is not misled.

## Out of scope

- The verdict change itself (aspect 1) and the record corrections (aspect 3).
- The console — already fully pinned and correct (`TurnRow.vue`, `TraceView.vue`,
  `ReplayDialog.vue`, `console/src/server/types.ts`); it renders `null` as *"coverage
  unavailable"* and is the model to copy, not a thing to change.
- Consolidating the 8 duplicated coverage sentences into one helper. **Tempting and out of
  scope** — a refactor of 8 render sites mid-unit risks the very disclosure it is meant to
  protect. Record as a follow-up.

---

## Acceptance criteria (testable — written first)

**AC-1..AC-4 — one per undisclosed surface.** For each of `corpus list`, `corpus run` (on a
**MATCH**, not only a divergence), `corpus score`, `phase0 combine`: a case/instance whose turn
carries an `effect` `NOT_COVERED` sub-verdict renders a coverage disclosure alongside the status.
Each test must **fail against today's code** before the fix.

**AC-5 — the prose is not anonymous.** `phase0 report` renders a named sentence for the `effect`
kind, not the generic fallback. A test fails if a new `NOT_COVERED` kind reaches the report with
no `_COVERAGE_PROSE` entry.

**AC-6 — round-trip persistence.** A ledger written with an `effect` coverage dimension and then
**re-parsed from disk** re-renders that dimension. (Drive it through a fresh parse, matching
`tests/test_coverage_rendering.py:285`, the load-bearing one — not an in-memory object.)

**AC-7 — the rule is enforced structurally.** A guard test enumerates the status-rendering
surfaces and fails if one renders a status without a coverage path, so the **next** surface added
cannot silently omit it. (This is the durable form of the precedent's hard rule.)

**AC-8 — no published number moves.** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
`recall 0.00`, `3/93` appear unedited.

---

## Dependencies & sequencing

Depends on aspect 1 (there must be a routine `effect` `NOT_COVERED` to disclose). **Do not
release between 1 and 2:** aspect 1 ships the cost (a PASS where there was an UNVERIFIED) and
aspect 2 ships the mitigation (that PASS is never silent about what it did not check).

## Risks

- **Scope inflation:** 8 duplicated render sites mean a new cause must reach each. The guard test
  (AC-7) is the defense against this recurring.
- **The `coverage` word is overloaded three ways** in the CLI already. Renaming is out of scope;
  misleading a reader is not acceptable either. Resolve in help text.
