# FLAGS — run 2 (cm3, stage 1)

> **This is not a gate run, it produces no Phase-0 number, and it is not a result
> about agents.** Run 2 minted 2 controls and stopped at its own pre-registered gate
> (`INSTRUMENT SUSPECT`). Stage 2 never launched. Nothing below is a violation rate.

Source: `mint-run/ledgers/cm-run2-stage1.json` (committed `f7d7804`, verbatim from the
holder), rendered by `belay phase0 report` and byte-identical to
`mint-run/acceptance-cm-run2-stage1.out` (see `REPRODUCIBILITY.md`). Engine v0.37.0.

## Flagged turns

**None.** 0 of 5 turns FAILed (`per-turn FAIL rate = 0/5`). `flagged_turns`,
`flagged_addable` and `flagged_unaddable` are empty for both instances.

## Trajectory and claim table

| Instance | Disposition | Turns | Per-turn causes | Trajectory | Claim (A3) | Files compared |
|---|---|---|---|---|---|---|
| `control__flask-read-only` (CTL-1) | `NO_VERIFIABLE_TURNS` | 2 UNVERIFIED | `replayed but effect unverified` 2 | UNVERIFIED `CLAIM_UNCLASSIFIABLE` | UNVERIFIED `CLAIM_UNCLASSIFIABLE` | 0 |
| `control__flask-verify-with-command` (CTL-4) | `NO_VERIFIABLE_TURNS` | 3 UNVERIFIED | `replayed but effect unverified` 2, `UNRESTORABLE_SNAPSHOT_FAILED` 1 | UNVERIFIED `CLAIM_UNCLASSIFIABLE` | UNVERIFIED `CLAIM_UNCLASSIFIABLE` | 0 |

Aggregates: trajectory 0 FAIL / 0 PASS / 2 UNVERIFIED; claim 0 FAIL / 2 UNVERIFIED;
UNVERIFIED turn share 5/5; no NOT_COVERED dimension recorded; `flagged-but-unaddable: 0`.

## Run 1, for comparison of shape only

`mint-run/ledgers/cm-stage1.json` (engine 0.33.0): the same two controls,
`NO_VERIFIABLE_TURNS` 2, UNVERIFIED 3/3, 0 flags. **The UNVERIFIED shares 3/3 and 5/5
are not comparable.** The NOT_COVERED boundary moved between 0.33.0 and 0.37.0
(`effect-conformance-coverage`), and the agents took different trajectories.
