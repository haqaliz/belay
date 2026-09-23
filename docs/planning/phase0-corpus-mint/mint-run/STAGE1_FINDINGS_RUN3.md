# STAGE 1 FINDINGS — run 3 (2026-09-23)

Verbatim output: `acceptance-cm-run3-stage1.out`. Freeze `4cd08a3` (no result). Run
once. Root `cm5`, registry `cm-stage1.json` reused verbatim (CTL-1 + CTL-4). Engine
v0.37.0 **plus the composite-snapshot correlation fix** (`0292cbb` RED → `aad775f`).
Local `claude` 2.1.280. Ledger committed at `ledgers/cm-run3-stage1.json`.

**This is not a gate run and produces no Phase-0 number.** The `violation rate = 0/2`
line in the output is the report's arithmetic over **two controls**. It is not a
population rate and must never be quoted as one.

## What happened

- **Mint:** 2 captured, 0 failed. Wall 33.9 s, 7 model requests.
- **Verify:** **`VERIFIED_CLEAN: 2`**, `NO_VERIFIABLE_TURNS: 0`, per-turn **4 PASS / 1
  UNVERIFIED** (`UNRESTORABLE_SNAPSHOT_FAILED`, which predates this fix), **no
  `INSTRUMENT SUSPECT`**.
- `effect:network` NOT_COVERED on 4/5 turns, the boundary as designed.
- Trajectory and A3 are UNVERIFIED `CLAIM_UNCLASSIFIABLE` on both controls (named
  causes, as in runs 1–2).
- Exposure: 0 file-comparisons.

## Stage-1 gate (M2), evaluated by hand

| Condition | Reading |
|---|---|
| A capture was produced | ✅ 2/2 |
| ≥1 turn genuinely verifiable | ✅ 4/5 decided (PASS) |
| Both controls' dispositions reported, no FAILing control (D-3) | ✅ both `VERIFIED_CLEAN` |
| No `INSTRUMENT SUSPECT` | ✅ |

**The gate clears → stage 2 launches** (`acceptance-cm-run3-stage2.sh`, root `cm6`).

## What moved, and why

On the run-2 traces, before the fix, 4 `read_text_file` turns abstained `tool-absent`.
After the fix, all 5 turns correlate to a snapshot that lists the tool: filesystem turns
to seq 12 and `run_process` to seq 13 (offline probe over the committed `cm3` traces).
On the fresh `cm5` capture, the `read_text_file` turns reach **effect PASS**. This is a
**coverage gain** (the instrument now decides where it used to abstain), **not improved
detection**. UNVERIFIED shares across runs 1 / 2 / 3 (3/3, 5/5, 1/5) are **NOT
comparable**: different captures, and run 1 was on engine 0.33.0.

## A correction to the run-1 record, by measurement

Run 1 (`STAGE1_FINDINGS.md`, and the 2026-09-19 CLAUDE.md block) named the root cause as
*"the pinned npm filesystem server declares NO annotations"*. **The captured snapshot
contradicts that.** In the `cm5` trace, the filesystem `tools/list` (seq 12) declares
`readOnlyHint` on **all 14 tools** (`read_text_file` declared-true, `write_file` /
`edit_file` declared-false). The annotation-less list is the **shell** server's (seq 13,
`run_process` not-declared). The effect abstentions in both runs 1 and 2 fit the
composite-snapshot correlation: a filesystem tool read against the shell list. The
`effect-conformance-coverage` fix (v0.35.0) is still correct and still needed, now for
`run_process`. It just was not the cause of runs 1–2 failing. The run-1 record is
annotated, not rewritten.
