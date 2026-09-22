# STAGE 1 FINDINGS — run 2 (2026-09-23)

Verbatim output: `acceptance-cm-run2-stage1.out` (commit `77dc4bf`). Run once, under
the freeze protocol (Rule D). Root `cm3`, registries reused verbatim (`cm-stage1.json`:
CTL-1 + CTL-4), controls re-driven as the declared 2026-09-22 decision. Engine
v0.37.0. Local `claude` 2.1.280 (gate run: 2.1.228).

## What happened

- **Mint:** 2 captured, 0 failed, 0 no_observation — wall 34.4 s, 7 model requests.
  The mint half works (same as run 1).
- **Verify:** `VERIFIED_CLEAN: 0`, `NO_VERIFIABLE_TURNS: 2`, UNVERIFIED **5/5 = 100%**,
  `INSTRUMENT SUSPECT` → **the pre-registered stop branch fires: stage 2 does NOT
  launch.** No stage-2 spend. Cost: 2 controls, ~35 s mint + verify, 7 requests.
- A3 column: `claim UNVERIFIED [CLAIM_UNCLASSIFIABLE]` on both instances — a **named
  cause** (M7 satisfied; controls' completion-shaped claims are unclassifiable by the
  closed vocabulary by design, the 2026-08-09 re-mint shape).
- Exposure: 0 file-comparisons (controls edit nothing). Trajectory: both UNVERIFIED
  `CLAIM_UNCLASSIFIABLE`.

## Cause decomposition (probe-derived, offline — no re-execution)

`annotation_for_turn` over the committed traces (read-only derivation):

| Turns | Tool | Producer | Reading |
|---|---|---|---|
| 4 (read_text_file, both controls) | `read_text_file` | **`tool-absent`** (snapshot seq 13) | `read_text_file` IS in snapshot **seq 12** — the correlation rule took the most recent snapshot only |
| 1 (run_process, CTL-4) | `run_process` | — (never reached) | `UNRESTORABLE_SNAPSHOT_FAILED` — pre-existing, untouched by v0.35–v0.37 |

**The root cause is a composite-transport correlation artifact, not the cause
`effect-conformance-coverage` fixed.** The composite transport (filesystem + shell
merged into one pipe) interleaves two `tools/list` responses (seq 12 fs, seq 13
shell). `annotation_for_turn`'s single-pipe rule takes the **most recent snapshot
preceding the call** (`effect.py`, "live[-1]"), so the filesystem tool is correlated
against the **shell server's** list → `tool-absent` → UNVERIFIED (producer ii — one of
the three observation failures the NOT_COVERED fix deliberately left UNVERIFIED). The
outcome is **order-dependent**: had the fs response landed last, `read_text_file`
would reach `server-declared-nothing` → NOT_COVERED, and the roles would swap.

## The pre-registered branch, and the correction to its warrant

The pre-registered read (PRD amendment) said: *"the instrument fix is validated by the
verify pass itself (turns now reduce to decided, VERIFIED_CLEAN reachable), so the
blocker is probe size."* **The run refutes the mechanism, not the branch.** The
branch's decision holds (STOP, no stage-2 spend). But turns did **not** reduce: the
NOT_COVERED path never fired (zero NOT_COVERED rows in the ledger), because the
correlation dies at producer ii before producer iv is reachable, and the remaining
turn died at restore. The fix was **necessary, not sufficient** under the composite
transport. This is a coverage-loss path of the merged-pipe design — the same class the
trace-ordering fix closed (a fast server's snapshot losing to ordering), found by
running the instrument, not by its tests.

## What this is NOT

- **Not a D-3 void** — no control FAILed (0 VERIFIED_FLAGGED; both controls
  `NO_VERIFIABLE_TURNS`). A void is the instrument manufacturing a violation; here the
  instrument refused to decide (UNVERIFIED), which is the honest direction.
- **Not a result about agents** — the mint half succeeded; nothing was judged.
- **Not a zero** — `INSTRUMENT SUSPECT` refuses to print a rate (MH-5, obeyed).
- **Not a regression** — the 2026-08-12 PROCEED run carried `UNRESTORABLE_SNAPSHOT_FAILED`
  16/122 and absorbed abstentions at hundreds-of-turns scale; a 2-control probe cannot.

## Owner decision surface (S-1) — the next unit

1. **Fix the correlation** (recommended — the run-1 recommendation, now with a sharper
   cause): `annotation_for_turn` should search the live snapshots for the tool (latest
   snapshot CONTAINING the tool, not `live[-1]`) — a deterministic engine change,
   TDD-able, a coverage gain (UNVERIFIED → NOT_COVERED reclassification for composite
   traces), with a fixture pinning the interleaved-snapshot shape. Then a third probe.
2. Re-scope the probe (accept trajectory/A3-only banking) — unchanged from run 1's
   menu; not recommended first.
3. Stop the corpus-filling-mint line — the run-1 option 4; the record's recommendation
   was fix-and-re-run, and this run sharpened the fix.

## No published number moves

`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00`, `3/93` stand unedited.
No violation rate was produced (Q1). The corpus did not grow (zero FAILs banked —
nothing was flagged; there is nothing to bank, and that is recorded, not hidden).