# Aspect — `coverage-status`

**Unit:** `verdict-coverage-status` · **Sequence:** 1 of 1 (single aspect; the change is one
contract and must land whole — a half-applied status is the false-PASS scenario)

---

## Problem slice

Introduce `NOT_COVERED`: a **sub-verdict-only** status for dimensions Belay structurally
cannot observe, excluded from the reduction, and always accompanied by a coverage statement
on every surface that renders a verdict.

**User outcome:** a turn reports PASS *on what Belay actually verifies*, `UNVERIFIED` regains
its honest meaning ("we tried and could not"), and no reader can see a status without also
seeing what was outside coverage.

---

## In scope

1. `Status.NOT_COVERED`, and `reduce` filtering it before ranking — empty-after-filter yields
   **`UNVERIFIED`**, never `NOT_COVERED`.
2. The CLI's duplicate ordering `_worst` (`cli.py:625-633`) kept in lockstep — it decides the
   **exit code** (`cli.py:550`).
3. `network_subverdict` emits `NOT_COVERED` for **declared-false** and **declared-non-boolean**
   only. Not-declared and declared-true keep returning `None` (unchanged).
4. The sub-verdict **message** still distinguishes *"this tool promised and we did not check"*
   from *"nothing was promised"* — the direct answer to the counter-argument.
5. Every rendering surface: `belay verify` per-turn and aggregate, the always-on coverage
   banner, `phase0 run`, `phase0 report`, the ledger, corpus cases.
6. The coverage statement persisted as a **ledger field** (so `phase0 report` can render it)
   and placed **outside** `report.py`'s `INSTRUMENT SUSPECT` branch.
7. Cause on the REPLAYED path (`turn.py:227-233`) plus a stable `_PREFIX_LABELS` entry, so
   causes bucket by name instead of `unknown` — and not one bucket per turn.
8. `runner.py:196-202` decides `replayed_any` explicitly rather than by accident.
9. `cli.py:1067` creates the ledger's parent directory.
10. `corpus/case.py:50` `_KNOWN_STATUSES` gains the status; optional `schema_version` on cases.
11. Docs: `CLAUDE.md:143-145`, `README.md:149-151`, the banner wording, and a rewritten
    `effect.py` docstring stating the NEW reasoning (never silently deleted).

## Out of scope

- The replay engine's separate `REPLAYED`/`UNVERIFIED`/`NOT_VERIFIABLE` namespace and
  `Disposition`. Parallel enums; do not touch.
- Making network egress observable.
- Emitting `NOT_COVERED` for not-declared / declared-true turns (open question, deferred).

---

## Acceptance criteria (test-first)

**The guarantees:**
1. `test_not_covered_is_never_a_reduced_status` — exhaustive over the status enum: no input
   combination makes `reduce` return `NOT_COVERED`.
2. `test_not_covered_never_reads_as_pass` — per surface (verify per-turn, verify aggregate,
   phase0 report, ledger JSON, corpus case): the string `PASS` never stands in for it.
3. `test_reduce_of_only_not_covered_is_unverified` — the empty-after-filter case.
4. `test_existing_verdicts_survive_unchanged` — every PASS/FAIL in the suite/fixture corpus is
   identical before and after. (Honest limit: test-covered verdicts, not all possible traces.)
5. `test_network_dimension_never_softens_a_readonly_fail` — the existing guard
   (`test_verify_network.py:168-186`) must survive with `NOT_COVERED`.

**The outcome:**
6. `test_reference_server_turn_reduces_to_pass` — a replayed turn with `readOnlyHint: true`
   and `openWorldHint: false`, clean delta, reduces to **PASS** with a `NOT_COVERED` network
   sub-verdict. (This is `test_verify_network.py:137-165` inverted — renaming it is the
   visible commitment of this change.)

**The rendering rule (per surface, not by review):**
7. `test_<surface>_renders_coverage_with_status` — for each surface, a turn carrying a
   `NOT_COVERED` sub-verdict cannot be rendered without its coverage line. Includes
   `test_phase0_report_shows_coverage_from_a_stored_ledger` (the field must persist) and
   `test_coverage_line_survives_instrument_suspect`.

**The fixes:**
8. `test_replayed_unverified_turn_names_its_cause` — no `unknown` bucket; a stable label, not
   one bucket per turn.
9. `test_phase0_run_creates_the_ledger_parent_dir`.
10. `test_corpus_case_round_trips_a_not_covered_sub_verdict`.

All deterministic, offline, fixture servers only.

---

## Dependencies and sequencing

- **Depends on:** nothing. Off `master`.
- **Blocks:** `phase0-mint-execution` aspects 4-5 (the mint cannot produce a denominator).

---

## Open questions / risks

- **The top risk:** a PASS reading as "network verified". Criterion 7 is the mitigation and it
  is non-negotiable — if it cannot be made airtight, the change should not ship.
- Existing corpus cases whose network sub-verdict flips will read as **REGRESSION** under
  `belay corpus run` (exact-set comparison, `corpus/run.py:198-201`). Expected; call it out.
- New corpus cases are unreadable by pre-change Belay (`_KNOWN_STATUSES` is fail-closed).
- The Phase-0 write-up must state that the UNVERIFIED rate before/after is **not comparable**,
  so the drop is not read as improved detection.
