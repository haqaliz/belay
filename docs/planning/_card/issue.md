# phase0-remint — work card

> Unit: `feat/phase0-remint` · branch `feat/phase0-remint/aliz` ·
> worktree `.claude/worktrees/feat-phase0-remint` · base `origin/master` (v0.15.0)

## Brief

No GitHub issue exists for this work; the source is the inline brief handed off by the
`belay-next` recommendation (2026-08-09), reproduced verbatim:

> Continue the funded Phase-0 mint under the shipped v0.15.0 trajectory rule
> (suite-before-success-claim): the exposure gate fired at stage 2 (0/8 judged — every real
> instance edited source), so stage 3 (the >=50 denominator) never launched and R1's
> quantitative form is still untested. This unit drives the pre-registered staged plan
> (phase0-mint-run/prd.md): fresh roots under eval/mint/, controls first, freeze protocol
> (Rule D — frozen invocations committed before the run, verbatim .out committed after, run
> once), ledgers committed, per-stage gates: stage 1 control VERIFIED_CLEAN, stage 2 >=5/10
> captured + 3/3 controls clean + exposure judged >=1 (decide pre-registered how the report's
> trajectory exposure line satisfies the exposure gate), stage 3 the full 68 with quota-stop
> resume, then audit-and-publish: full hand-audit of every flag, corpus labeling, the
> exposure-forecast instrument re-run, and the PHASE0_RESULTS.md decision line. Caveat: the
> trajectory rule's precision on real model text is unmeasured (no mint has run under it) —
> heavy classifier abstention could re-fire the exposure gate, and adjudication decides
> precision, never prediction. Consume the engine as-is (no src/belay/ change without
> stopping); eval-side driver changes only if a stage gate names one.

## Motivating record (from the repo, 2026-08-09)

- `docs/planning/phase0-mint-run/mint-run/STAGE4B_FINDINGS.md` — stage 2 of the funded mint:
  8/10 captured, 35/35 turns PASS, 3/3 controls clean, **exposure gate fired (0/8 judged)**;
  every real instance edited SOURCE (`edit_file`), never a `tests/`/`testing/` path.
  Re-scope options at lines 96–108; option 1 (the trajectory invariant) shipped as v0.15.0.
- `docs/technical/PHASE0_RESULTS.md:1040-1047` — the next unit is the re-scope's payoff:
  "the re-mint then becomes the next gate decision" — see also
  `docs/planning/trajectory-success-invariant/prd.md:37` and
  `docs/technical/CAPABILITY_ROADMAP.md` (2026-08-09 status block).
- `docs/planning/trajectory-success-invariant/` — the shipped rule this unit judges with:
  default-on instance-level A1 rule, claim classifier with named abstain causes
  (`NO_CLAIM_RECORDED` / `CLAIM_UNCLASSIFIABLE` / `EVIDENCE_UNOBSERVABLE`), trajectory
  exposure line in `belay phase0 report`, trajectory FAILs bank as corrupt-success corpus
  cases (schema v4).
- **Decisive fact (from the dig):** the s4 captures were minted at engine v0.13.0, which
  predates the claim record (`000844a`, v0.15.0). Banked s4 traces therefore have NO claim
  records — a re-verification of banked captures under the trajectory rule would read
  `NO_CLAIM_RECORDED` on every instance. **The re-mint must be a fresh mint.**
- `docs/planning/phase0-mint-run/prd.md` — the pre-registered staged plan (Rule A gates,
  Rule B near-zero reading, Rule C high-rate guard, Rule D freeze protocol, M0–M7 metrics,
  audit sampling rule, §5 req. 17 forecast re-run) carried into this unit's PRD.
