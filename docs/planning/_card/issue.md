# Brief (inline; no GitHub issue)

Unit: `feat claim-author-live-probe` — the belay-next pick 2026-10-10, option A of
`docs/planning/claim-axis-legibility/prd.md:193-200` (risk R-D).

Belay kills its subprocess claim author at `AUTHOR_TIMEOUT = 60.0` s
(`src/belay/verify/author.py:63`; constructed unconditionally at
`src/belay/cli.py:971,1990,2145`, no knob), while the shipped reference author allows
its `claude -p` child 600 s (`src/belay/verify/reference_claim_author.py:65-67`). Run 3's
two trajectory-FAIL cases (`django-11422`, `django-14382`) came back `NO_CHECK_AUTHOR`
with the reason never recorded (`docs/planning/phase0-corpus-mint/audit-and-publish/AUDIT.md:87-91`).
R-D is a hypothesis, NOT a finding: the n=1 live proof (184.5 s whole-test wall) fit
inside the cap (`docs/planning/phase0-corpus-mint/a3-author/live-run.md:20,39`).

Scope: re-verify the two banked run-3 cases through the real CLI with the shipped
reference author configured, and record the observed `last_abstention` sub-cause
(`AUTHOR_TIMED_OUT` or another) plus any A3 verdict — C8's first real verdict on real
data. Freeze protocol (script containing no result). Conditional review-gate aspect: IF
the evidence reads `AUTHOR_TIMED_OUT`, ship an operator-settable author timeout
(env + flag parity on verify/phase0/corpus), bounded fail-closed abstention preserved;
otherwise the unit stops at the finding. Honesty lines: not a gate run, no Phase-0
number, no published number moves (11/60 = 18.3%, precision 0.00, 1/15, 4/16, recall
0.00, 3/93 stand unedited). The two `belay corpus label` judgments are the owner's
alone (AUDIT.md:93-97), not this unit. Suite baseline: 2895 passing (45 skipped, 14
deselected).