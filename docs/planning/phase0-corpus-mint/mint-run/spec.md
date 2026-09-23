# Aspect — `mint-run`

**Grade: MEASURED.** A live, stochastic, **unrepeatable** run. Not TDD-able: the
deterministic aspects (`a3-author`, `mint-registry`, `verify-parity`) carry the
test-first weight and are complete and green.

> **AMENDMENT — RUN 2 DECLARED (2026-09-22, owner S-1).** Run 1 ran once
> (`acceptance-cm-stage1.sh` → `acceptance-cm-stage1.out`) and its pre-registered gate
> said STOP (`STAGE1_FINDINGS.md`). This is the **declared** second run (Rule D: "a
> second run only if declared"). What changes:
> - **Fresh roots under the holder: `cm3` (stage 1), `cm4` (stage 2).** `cm1` holds
>   run-1's batch + checkpoint (never reused); `cm2` was never touched and stays
>   reserved. New frozen scripts `acceptance-cm3-stage1.sh` / `acceptance-cm4-stage2.sh`
>   (or run-2-named), committed **containing no result** before the run.
> - **Registries reused verbatim:** `eval/instances/cm-stage1.json` (CTL-1 + CTL-4) and
>   `cm-stage2.json` (CTL-2 + CTL-3 + 8 fresh reals, controls first). No regeneration,
>   no seed change (`SEED_HISTORY` stays empty; byte-identical regeneration remains the
>   reproducibility check — run it, do not change it).
> - **Controls re-driven as a declared decision** (owner-confirmed 2026-09-22): run-1's
>   CTL-1/CTL-4 produced observations, and the anti-re-roll letter reads "an instance
>   that produced an observation is never re-armable" — controls are the run's own
>   calibration instruments, not population draws; run 1's stage-1 gate never cleared;
>   per-stage fresh controls are the gate-mint pattern. Recorded, not silent.
> - **The instrument the probe died on is fixed:** `effect-conformance-coverage`
>   (v0.35.0) — not-declared `readOnlyHint` is now an `effect` `NOT_COVERED` sub-verdict
>   that `reduce` drops before ranking, so replayed turns against the annotation-less
>   npm server reduce via their other sub-verdicts and `VERIFIED_CLEAN` is reachable.
>   The `UNVERIFIED` rate across this boundary is **not comparable** to run 1's — a
>   reclassification, never improved detection. Residuals: `UNRESTORABLE_SNAPSHOT_FAILED`
>   untouched (run 1 lost 1/3 probe turns to it) and the three observation-failure
>   producers remain UNVERIFIED.
> - **Verify via stock `belay phase0 run`** (the frozen scripts' shape) — NOT the mint's
>   `--verify` (the shell-threading parity gap is fixed by the `verify-parity` aspect,
>   but the scripts' direct form remains authoritative).

## Problem slice

Drive the corpus-filling mint and verify its captures, under the pre-registered protocol,
so that trajectory / per-turn / A3 FAILs **bank as corpus cases**.

## Binding protocol rules (none optional, none this unit's to reinterpret)

| Rule | Source | Meaning here |
|---|---|---|
| **D — freeze** | `phase0-mint-run/prd.md:97-101` | Scripts committed **first, containing no result** (grep-checked); each stage run **once**; verbatim output committed next, **whatever it says**; a second run only if **declared** |
| **A — stage gating** | `phase0-mint-run/prd.md:73-79` | stage 1 probe gates stage 2; controls **first** |
| **D-3 — control void** | `phase0-remint/prd.md:215` | A FAILing control **VOIDS the run**, regardless of later adjudication |
| **Exposure gate (D-1)** | `phase0-remint/prd.md:94-101` | 0 of N judged on the trajectory line → **STOP** |
| **INSTRUMENT SUSPECT** | `report.py:6-12` | → **STOP**. Never a 0% |
| **S-1 — the auditor is the owner** | `plan_20260809.md:24-29` | This aspect prepares **evidence, never judgments** |
| **Honesty properties** | `phase0-live-mint/prd.md:310-317` | Rate always with its denominator; UNVERIFIED never PASS; a PIVOT written as plainly as a PROCEED |

## In scope

1. **Run-2 frozen invocation scripts**, committed before the run, containing **no result**
   (grep-checked; the freeze is itself a committed test — the `test(mint-run)` RED that
   pins the scripts' shape: fresh absolute roots under the holder, committed registries
   referenced verbatim, `--shell-server` before `--server`, `BELAY_CLAIM_AUTHOR`
   exported, no result shapes).
2. **Stage 1** (probe): `cm-stage1.json` — CTL-1 + CTL-4, re-driven as declared
   (amendment above), root `cm3`.
3. **Stage 1 gate**, evaluated before stage 2 is launched: a capture must be produced,
   ≥1 turn genuinely verifiable, both controls clean (D-3: a FAILing control VOIDS).
4. **Stage 2**: `cm-stage2.json` — CTL-2 + CTL-3 + 8 fresh real (never driven), controls
   first, root `cm4`.
5. Verify each stage through **stock `belay phase0 run`**, ingesting into the corpus
   (with `--shell-server` before `--server`, `BELAY_CLAIM_AUTHOR` exported).
6. Verbatim outputs committed, whatever they say.

## The invocation, and the two things it must get right

**`--root` and `--clones-dir` are ABSOLUTE, under `~/dev/at/holder/belay/`** (MH-1).
`--root` is cwd-relative (`entrypoint.py:224-236`) and manifests record an absolute
`source_root`, so a worktree-relative root dies with the worktree — **the defect repaired
at the start of this unit**, where three missing symlinks left 1,344 recorded paths dead.
Writing outside the worktree removes the cause rather than adding a fourth stub.

**`--shell-server` MUST precede `--server`** — `--server` is `nargs=REMAINDER` and
swallows everything after it (`eval/README.md:790-793`). Measured this session: I hit this
myself replaying `s1p`.

Composition, reused verbatim from the only mint measured to produce TPs (2026-08-12):
`--provider claude-cli --model claude-opus-5 --max-steps 20 --request-timeout 120
--toolset filesystem+shell`.

**A3:** `BELAY_CLAIM_AUTHOR` is exported so the claim column fills. This is the first mint
that can fill it — `run_verify`'s missing `claim_author=` was fixed in this unit
(`b030843`), and the reference author shipped (`ebebcac`), proven live at n=1
(`a3-author/live-run.md`).

## Out of scope

- **Any violation rate** (Q1). Dispositions and banked-case counts only.
- **Owner labeling / adjudication** (Q3, S-1). Cases bank as `pending`.
- **Stage 3 / the ≥50 denominator.** Not safely reachable, not attempted.
- Re-driving any **real instance** that produced an observation (the 8 cm-stage2 reals
  were never driven and are eligible; run-1's stage-1 reals are not in these registries).
  Controls re-drive is in scope, as declared in the amendment above.
- Tuning any rule, prompt or threshold to change what the mint finds.

## Acceptance — measured, never asserted

Outcomes are **observations**. The run cannot fail for producing an unwelcome result; it
fails for being run wrong.

| # | Criterion |
|---|---|
| M0 | Scripts committed **before** the run, containing no result (grep-checked) |
| M1 | Stage 1 captures, with its capture rate and denominator stated |
| M2 | Stage 1 gate evaluated **explicitly** before stage 2 launches |
| M3 | Stage 2 captures, rate and denominator stated |
| M4 | **Controls: every disposition reported.** A FAILing control → **VOID**, published as such |
| M5 | `INSTRUMENT SUSPECT` → STOP, never a 0% |
| M6 | Exposure + trajectory lines reported per instance |
| M7 | **A3 column filled** — a verdict or a named cause, never `claim unrecorded` |
| M8 | Trajectory FAILs **bank** as `trace-<instance>-trajectory`; per-turn FAILs bank or are reported `flagged-but-unaddable` with named causes |
| M9 | `corpus run` over the grown corpus: **0 REGRESSION** |
| M10 | No published number moves |

## Risks

| Risk | Note |
|---|---|
| **D-3 void** | Killed the 2026-08-09 re-mint. CTL-2/3 carry the anti-D-3 steering sentence, which *lowers* the probability, never guarantees. A void is **published**, never hidden |
| **Zero exposure** | Killed `phase0-mint-run` (0/8 judged). The gate stops before the larger stage |
| **Nothing flags** | The likeliest outcome at n=8. A run that banks nothing is a **recorded result** — the corpus stays at 7 and the record says why |
| **Quota stop** | Breaker writes `no_observation`, which re-arms; `captured`/`failed` never re-roll |
| **Clone cost** | django + sympy bare clones, fetched once, cached in the holder |

## Note on evidence grade

Everything this aspect produces is **execution evidence**. Whether a flagged turn is a
true positive is **human adjudication** — a different grade, and the owner's (S-1). The
two must never be merged.
