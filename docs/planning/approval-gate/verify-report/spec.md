# Aspect: verify-report

**Slug:** `approval-gate/verify-report` · **Depends on:** `trace-observations` (aspect 4)

## Problem slice

`belay verify` reports the trace's approval events on its text and `--json`
surfaces: hold counts and decisions by cause, absent-never-zero, with the coverage
line discipline. The verify JSON contract gains one additive section; the pinned
snapshot fixture is updated deliberately and documented. No verdict axis moves — a
denied call is an observation, never a turn and never a verdict.

## In-scope

- A derived `approval` section on `belay verify --json`: `{"approval": {"holds": N,
  "decisions": {"APPROVED": n, "DENIED": n, "APPROVAL_TIMEOUT": n,
  "APPROVAL_SHUTDOWN": n, ...}}}` — present iff the trace carries approval records
  (absent otherwise, never a fabricated `0`; absent-never-zero).
- The text renderer gains a line naming holds and decisions by cause when present
  (e.g. `approval: 1 held, 1 denied (APPROVAL_TIMEOUT)`), and nothing when absent.
- The `tests/fixtures/verify_json_snapshot.json` snapshot fixture is updated
  deliberately (additive change, documented in the commit); the existing JSON
  contract tests stay green with the documented shape change.
- `README.md`: the honest coverage line gains the approval-gate sentence (the gate
  holds on declared annotations; it is not an adversarial control — `CLAUDE.md`
  scoping), plus the optional env vars if the quickstart mentions the proxy envs.

## Out-of-scope

Corpus banking, console UI, phase0/gate surfaces (a follow-on if demand appears),
any verdict-axis change, any published-number change.

## Acceptance criteria (test-first)

1. `belay verify --json` on a trace with approval records yields the additive
   `approval` section with exact counts per cause; on a trace without any, the
   section is absent (never `{"approval": {}}` and never a zero).
2. The text renderer prints the approval line exactly once when records exist and
   not at all when absent; the line travels with the coverage line (the honesty
   contract: a surface that reports events still says what was verified).
3. A trace mixing denied, approved, and timed-out calls reports 3 holds with the
   right per-cause split.
4. The JSON snapshot fixture diff is exactly the additive section (no other key
   changes); the diff is reviewed and committed deliberately.
5. The flag-parity suite (`tests/test_cli_flag_parity.py`) is green with no new
   declarations (approval config is env-only in this slice — the guard is checked,
   not widened).
6. No verdict axis moves: verify on an approval-carrying trace produces the same
   per-turn verdicts as verify on the same trace with the approval records stripped
   (the events are orthogonal to A1/A2/A3).

## Dependencies and sequencing

Aspect 4's kinds and reader. Read `src/belay/verify/json.py` and the text renderer
before planning the exact insertion points; the snapshot fixture lives at
`tests/fixtures/verify_json_snapshot.json`.