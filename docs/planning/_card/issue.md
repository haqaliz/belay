# Brief (inline; no GitHub issue)

Unit: `feat trajectory-claim-coverage` (belay-next pick, 2026-10-02).

Widen the trajectory rule's success-claim classifier (`src/belay/verify/trajectory.py`,
`CLAIM_UNCLASSIFIABLE` ~L137/399/411) so fewer real agent claims abstain.

Evidence: corpus-mint-second-run run 3 had 10/12 `CLAIM_UNCLASSIFIABLE`
(`docs/planning/claim-axis-legibility/prd.md:210`, `understanding.md:68`).

Caveats:
1. Overfitting: the 2026-08-12 decision kept the vocabulary narrow; widen by structure,
   never by an allowlist fitted to those 12 strings.
2. A RECLASSIFICATION, not improved detection. UNVERIFIED shares across runs are not
   comparable; 11/60 = 18.3%, precision 0.00, 1/15, 4/16, recall 0.00, 3/93 stand unedited.
3. Confirm the 12 claim strings are recoverable from the committed cm5/cm6 ledgers first.

Tests first: (a) existing classifications byte-unchanged (golden); (b) newly-classifiable
claims land on a named decided outcome with a closed-vocabulary cause; (c) prose that merely
mentions "tests" never becomes a VERIFICATION claim (red under an over-broad matcher);
(d) --no-claim-axis identity and flag-parity guard stay green.
