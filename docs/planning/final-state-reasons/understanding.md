# Understanding: final-state-reasons (Phase 2 dig)

Legibility only, mirroring `claim-axis-legibility`. Axis: A3 (cause stays UNVERIFIED
`FINAL_STATE_UNOBSERVABLE`; never PASS). No verdict, status, reduction, exit code, gate,
corpus outcome or published number moves.

## The four collapsed reasons (`claims.py:458-492`, filed at `:380-390`)
| # | Reason | Condition | Line |
|---|---|---|---|
| a | no turn | `not calls` | 474-476 |
| b | replay raised | `replay_turn` raised | 483-489 |
| c | not replayed | `reply.status != REPLAYED` | 490 |
| d | no workspace | REPLAYED but `reply.workspace is None` | 490 |

c and d share one `or` expression today. c could split further by `reply.status`/`cause`
(`replay/engine.py:192-213`). A caller-supplied `workspace=` bypasses all four.
No test or code depends on the message text (only the cause is asserted).

## Pattern to mirror
Closed vocabulary + frozen `Abstention` (`claims.py:81-136`), `expected["sub_cause"]` /
`sub_cause_detail`, guard `tests/test_claim_vocabulary_guard.py`, threaded additively via
`sub_cause_fields` (`verify/json.py:319-334`) to: verify --json, phase0 ledger
(`runner.py:672`), corpus case (`claim_case`; validator accepts null/string, so schema stays
v5), verify text (`cli.py:1571`), phase0 report (`report.py:444`), corpus show (`cli.py:2778`).

## Pins an additive field changes (amend additively, name each)
- `test_claim_subcause_surfaces.py:113-127` — `_OTHER_CAUSES` includes FINAL_STATE_UNOBSERVABLE.
- `test_verify_claims_subcause.py:143-151` — sub_cause only on NO_CHECK_AUTHOR.
- `test_claim_vocabulary_guard.py` — pins exactly 8 sub-causes.
Not affected: `cm-stage1.report.txt` golden (committed ledger has no sub_cause; renders as before).

## Open design questions (for the PRD)
1. Shared `SUB_CAUSES` vocabulary vs a separate final-state vocabulary/type. Sharing widens
   the pinned-8 guard; separate leaves it untouched.
2. Split c by `reply.status`/`cause`, or keep four coarse reasons.
3. Detail text for b (exception) must stay one line, <=200 chars, no raw state bytes.
