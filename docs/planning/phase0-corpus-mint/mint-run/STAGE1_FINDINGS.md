# Stage 1 findings — the gate STOPPED the run

**STATUS: RUN, once (2026-09-19). Verbatim output: `acceptance-cm-stage1.out`,
committed at `75b24ed` before this diagnosis was written.**

**STAGE 2 WAS NOT LAUNCHED.**

---

## What happened

```
run size: 2 instances
  VERIFIED_CLEAN: 0        VERIFIED_FLAGGED: 0
  NO_VERIFIABLE_TURNS: 2   ERRORED: 0
INSTRUMENT SUSPECT
overall UNVERIFIED turn share = 3/3 = 100.0%
UNVERIFIED by cause: UNRESTORABLE_SNAPSHOT_FAILED: 1
                     replayed but effect unverified: 2
```

`INSTRUMENT SUSPECT` is a pre-registered **STOP** — *"wiring failure, never a result"*
(`phase0-remint/prd.md:92`) — and the stage-1 gate requires a capture **and ≥1 genuinely
verifiable turn and clean controls**, *"else STOP: instrument or wiring defect, fix before
spending"* (`phase0-mint-run/prd.md:73-79`).

**The probe did its job.** It cost 2 control instances — 67.5 s, 5 model requests,
10 in / 494 out tokens — instead of 12 instances.

## What this is NOT

- **Not a D-3 void.** No control came back FAIL; both came back `NO_VERIFIABLE_TURNS`
  with named causes. A void is the opposite direction — the instrument *manufacturing* a
  violation. Nothing here was manufactured.
- **Not a result about agents.** The mint half **succeeded**: 2 captured, 0 failed,
  0 `no_observation`. Agents acted; traces were produced. The defect is downstream, in
  verify/replay.
- **Not a zero.** `INSTRUMENT SUSPECT` exists so a run that verified nothing can never
  read as *"we checked and nothing was wrong"* (`report.py:6-12`, the R6 false-zero
  defense). The report refuses to print a violation-rate headline, which is correct.
- **Not a regression from this branch** — see below.

## Diagnosis

### 1. Both causes are PRE-EXISTING, proven from the committed gate ledgers

The s6 captures are gone, but `mint-shell-toolset-run/mint-run/ledgers/` survives. The
2026-08-12 run **that PROCEEDed** shows both causes:

| Ledger | Dispositions | Causes |
|---|---|---|
| `s6a` (1-control probe) | 1 CLEAN | — |
| `s6b` | 6 CLEAN, 5 FLAGGED | `UNRESTORABLE_SNAPSHOT_FAILED` **16** |
| `s6c` | 15 CLEAN, 37 FLAGGED, 1 NO_VERIFIABLE | `UNRESTORABLE_SNAPSHOT_FAILED` **122**, `replayed but effect unverified` **8** |

**Neither cause is new, and neither was introduced by this unit.** What differs is
*scale*: s6c absorbed 122 snapshot failures across hundreds of turns and still produced
52 verified instances, because those instances had many turns and some verified. This
probe had **3 turns**, and the same pre-existing abstention rate consumed all of them.

### 2. `replayed but effect unverified` — the pinned servers declare no annotations

> **[Corrected 2026-09-23 (`STAGE1_FINDINGS_RUN3.md`) — this measurement is WRONG, and
> the cause below is superseded.** Re-derived from this run's own capture
> (`$HOLDER/mint/cm1/batch/`, both traces): the filesystem `tools/list` (seq 12) declares
> `readOnlyHint` on **all 14 tools**. Only the shell server's list (seq 13, `run_process`)
> declares nothing. The effect abstentions come from the composite-transport correlation:
> `annotation_for_turn` read the latest snapshot (the shell list), so filesystem tools read
> as `tool-absent`. Fixed at `aad775f`. The text below is kept as it was written.]**

**Measured:** the capture contains **no `readOnlyHint` / `annotations` anywhere**.
Effect-conformance therefore abstains by its own rule — *not-declared → UNVERIFIED, no
contract to check against* (`effect.py:22-25`).

This is the engine being **honest, not broken**: a server that declares nothing gives
effect-conformance nothing to check. But it means every turn against these servers
carries an UNVERIFIED sub-verdict, and worst-status-wins pulls the turn to UNVERIFIED
even when result-equivalence passed.

Note the contrast with the demo capture, where turns reach PASS: `demo/server.py`
**does** declare annotations. The pinned npm `@modelcontextprotocol/server-filesystem`
does not.

### 3. `UNRESTORABLE_SNAPSHOT_FAILED` — one turn, no manifest written

CTL-4 produced 2 turns but only 1 manifest: one turn's snapshot failed, so it has no
restorable pre-state and can never be verified or banked.

### 4. MH-1 WORKED — the path fix held

The manifests record
`source_root: /Users/aliz/dev/at/holder/belay/mint/cm1/<instance>/workspace` — absolute,
in the holder, **outside any worktree**. The defect repaired at the start of this unit
(three missing symlinks, 1,344 dead recorded paths) **will not recur for these
captures**. This is the one clear success of the run.

## The real finding: the probe is too small to clear its own gate

The gate demands ≥1 genuinely verifiable turn. The controls are deliberately tiny — CTL-1
is a pure read (1 turn), CTL-4 is read-then-command (2 turns). Against servers that
declare no annotations, **every** turn carries an effect-UNVERIFIED sub-verdict, so
clearing the gate depends on a turn surviving both that and the snapshot-failure rate.
At 3 turns, that is close to a coin flip.

`s6a` — a 1-control probe — cleared it on 2026-08-12. This one did not. Both are
consistent with a pre-existing abstention rate biting a very small sample.

## Decision required (owner — S-1: the auditor is the owner)

The protocol is unambiguous that stage 2 must not launch. What it does **not** decide is
which of these to do next:

1. **Fix the instrument first.** The annotation-abstention interaction is the deeper
   issue: against annotation-less servers, *every* turn is UNVERIFIED on the effect
   dimension, so the corpus-filling mint can never bank a per-turn case. That is a real
   coverage-loss path and arguably the more valuable unit than the mint itself.
2. **Re-scope the probe** so the gate is informative at this size — e.g. a probe with
   more turns, or a gate that reads the trajectory line rather than per-turn verifiability.
3. **Declare a second run** under Rule D and proceed to stage 2 anyway, accepting that
   per-turn cases will not bank and only trajectory/A3 cases might.
4. **Stop the unit** and keep what shipped: the A3 reference author, the `run_verify`
   blocker fix, and a reproducible registry.

**Recommendation: (1).** *"This is an invariant problem, not a sample-size problem"* was
the 2026-07 lesson; the same shape applies here. A mint cannot bank per-turn corpus cases
while every turn abstains on effect, and spending 12 instances to rediscover that would
repeat the exact mistake the record already warns about.

## No published number moves

`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00` and `3/93` stand
unedited. Nothing here is a candidate to replace them, and this run produces **no rate**
of any kind — by Q1's decision and by `INSTRUMENT SUSPECT`'s refusal.
