# Card — phase0-mint-run

Source: inline brief (belay-next handoff, 2026-08-09). No GitHub issue exists for this unit;
the slug lives in the branch and PR.

## Brief

Drive the Phase-0 gate mint end-to-end on the funded subscription path: run the
~65–70-instance batch (`eval/minting_driver/`) through `claude -p` with controls drawn FIRST,
staged 1 → ~10 → rest, under the freeze protocol (script committed without result, verbatim
output committed after). Consume the shipped engine as-is — no `src/belay/` change without
stopping to re-derive. Acceptance is the pre-registered gate criteria at
`docs/planning/phase0-live-mint/prd.md:58-71`, already committed in
`docs/technical/PHASE0_RESULTS.md`: denominator ≥50, ≥3 *independent* hand-audited TPs, no
`INSTRUMENT SUSPECT`, FP rate stated, a FAILing control voids the mint — plus a full hand-audit
of every flag and a hand-replay of one FAIL to confirm the delta is real. Then fill
`PHASE0_RESULTS.md` and write the PROCEED or PIVOT. Caveat: the single smoke instance produced
ZERO exposure (source edit, not tests) — if the mint returns near-zero, report it under the
pre-registered reading rules as uninterpretable about agents, and the forecast's 44.6%
relationship to exposure is unmeasured (`docs/planning/subscription-model-client/prd.md:74-85`).
Resolve the two open questions first (model id, `--safe-mode`) and verify the pre-registered
criteria commit predates the first Stage-3 mint commit.
