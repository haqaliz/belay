# TEMPLATE_HAND_REPLAY.md — disputed flags replayed (Phase 3)

> **DRAFT TEMPLATE** for unit `feat/phase0-gate-mint` (2026-08-14). Fill during the run.
> Procedure per the re-mint precedent; the choice of flags below is made by the operator,
> not predicted here.

**Date:** <yyyy-mm-dd> · **Branch:** `feat/phase0-gate-mint/aliz` @ <commit>
**Chosen flag(s):** <case-id[, case-id…] — minimum: every disputed flag; at least any
control FAIL (the load-bearing one — if its FAIL were a wiring/rename artifact, a D-3 void
itself would be suspect)>

## The instance and its claim

- **Trace:** `eval/mint/s6<stage>/batch/<trace_id>.jsonl` (gitignored; the committed record
  is the ledger + the verbatim transcription in `FLAGS.md` §2).
- **Turns:** <n> — <tool sequence summary>. Per-turn replay statuses (ledger
  `turn_status_counts`): <...>.
- **Claim (verbatim):** *"<claim text>"* — classified <determinable | not determinable>.
- **Evidence turns:** <n> — <n> `run_process` turn(s) before the claim, replayed exit-0:
  <list or none>. Offered toolset (FLAGS §5): <offered | not offered | unknown>.

## The replay

- **Turn-level flags** carry a per-turn replay diff: re-run the stored case and assert the
  engine reproduces the recorded sub-verdict.
- **Trajectory cases are instance-level:** no per-turn replay diff exists (no command effect
  to diff — FLAGS §4 for the stored-evidence shape). The honest replay re-executes the
  verdict computation from the stored trace + claim records and asserts it reproduces the
  recorded verdict:

```bash
uv run belay corpus run corpus/local
uv run belay corpus show <case-id>
```

Verbatim result (<date>, this worktree):

```
<paste `corpus run` output — per-case MATCH/REGRESSION lines + aggregate>
<paste `corpus show` excerpt — expected verdict vs recomputed verdict>
```

## Observed vs recorded

- **Recorded verdict:** <FAIL|PASS|UNVERIFIED> (`<rule>`, scope `<scope>`, <evidence_count>
  evidence turns).
- **Observed under the restored pre-state:** <identical verdict | divergence — describe>.
- **Delta:** <none | describe exactly — a divergence is a REGRESSION: the corpus line says
  so, and this file records what the operator did next>.

## Verdict of the hand-replay

<MATCH — the flag is a genuine engine verdict on the recorded data, not a fixture glitch;
or REGRESSION — what was found and whether it changes the D-1/D-3/gate reading.>
