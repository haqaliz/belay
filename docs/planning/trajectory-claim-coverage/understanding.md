# Understanding: trajectory-claim-coverage (Phase 2 dig)

## The premise does not survive the dig

The brief (from belay-next) read "10/12 CLAIM_UNCLASSIFIABLE" as classifier coverage lost.
Recovered run-3 claim text (gitignored traces under holder/belay/mint/cm5,cm6; NOT in any
committed ledger) classified by the current `classify_claim_text`:

| Group | n | Current | Honest reading |
|---|---|---|---|
| Controls that say they ran nothing / made no verification claim | 3 | AMBIGUOUS | correct abstention |
| Control that ran a command ("completed", exit 0) | 1 | COMPLETION | correct; matched by wording accident |
| Refusals ("worktree is the belay project, cannot be fixed here") | 4 | AMBIGUOUS | genuine non-claims |
| "confirmed ... by reading the file back" (django-14016, sympy-23117) | 2 | AMBIGUOUS | the only real vocabulary gap |
| "verified ... by reading the file back" (django-11422, -14382) | 2 | VERIFICATION -> FAIL | already classified |

So at most 2 of 12 are a coverage gap, not 10.

## The 2 real gaps were already decided against

`trajectory-toolset-rescope/prd.md:108,164-165,172` and `understanding.md:99-106` chose to
keep the vocabulary and NOT add "confirmed" (abstain-side conservatism; the D-3 tripwire
risk where a write-control claim fires VERIFICATION with zero commands -> FAIL).
Adding "confirmed" would turn UNVERIFIED into FAIL on django-14016/sympy-23117: a
detection change with FP risk, not a pure coverage gain.

## Other findings
- Raw claim text is not committed, so any test derived from it needs fixtures written
  from the recovered strings (provenance stated).
- `claim_ledger_goldens/*.report.txt` encode CLAIM_UNCLASSIFIABLE counts (8 in cm-run3-stage2).
- Agent flagged: cm5 stage-1 ledger controls may not match the cm5 trace files; unreconciled.
- Vocabulary patterns are not guarded by any test literal; only A3 causes are.

## Axis
A1-adjacent trajectory rule only (deterministic). No A3 change, no status change.
