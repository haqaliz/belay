# Brief (inline; no GitHub issue)

Unit: `feat final-state-reasons` (option 2 from the trajectory-claim-coverage dig, 2026-10-02).

`FINAL_STATE_UNOBSERVABLE` (A3 claim axis, `src/belay/verify/claims.py:403-421`) collapses four
distinct reasons into one cause, the same shape `claim-axis-legibility` fixed for
`NO_CHECK_AUTHOR` (8 sub-causes). Named as a follow-up in
`docs/planning/claim-axis-legibility/prd.md` section 8.

Scope: legibility only. Name which of the four reasons applied, via a closed vocabulary with a
guard test, and thread it through the same surfaces. No verdict, status, reduction, exit code,
gate or corpus outcome moves; no published number moves (11/60 = 18.3%, precision 0.00, 1/15,
4/16, recall 0.00, 3/93). Cause stays UNVERIFIED. Mirror the claim-axis-legibility design.
