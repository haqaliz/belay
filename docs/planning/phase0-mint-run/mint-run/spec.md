# Spec — `mint-run`

**Aspect of:** `phase0-mint-run` · **PRD:** `docs/planning/phase0-mint-run/prd.md`
**Date:** 2026-08-09

## Problem slice

The execution of the funded gate mint: three staged live runs under the freeze protocol,
each gated by the PRD's pre-registered Rule A. No new code — the driver, bridge, checkpoint,
and verify machinery are shipped and consumed as-is. The deliverable per stage: a frozen
invocation (committed with no result), one live run (verbatim output committed), a verified
ledger (committed), and a findings note. The gates decide whether the next stage launches.

## In scope

| Stage | Drive | Root | Registry | Gate (PRD Rule A) |
|---|---|---|---|---|
| 1 | `one control__flask-read-only` | `eval/mint/s4a` | `stage4a.json` | capture + ≥1 verifiable turn + control `VERIFIED_CLEAN`; else STOP |
| 2 | `batch` (10 = 3 controls + 7 real) | `eval/mint/s4b` | `stage4.json` | ≥5/10 captured + ≥1 verifiable turn + controls all `VERIFIED_CLEAN` + **exposure gate: ≥1 of 10 judged**; a control FAIL voids the mint |
| 3 | `batch` (68) | `eval/mint/s4c` | `selected.json` | no abort except the quota breaker; resumable on the same root |

Fixed parameters (owner decisions): `--provider claude-cli --model claude-opus-5
--max-steps 20`, `--request-timeout 120` (default), fresh root per stage, sequential drive,
gated capture by construction. Servers: filesystem only, pre-installed in `eval/servers/`
(via `npm install --prefix eval/servers @modelcontextprotocol/server-filesystem@2026.7.10
mcp-server-commands@0.8.2`, or `$BELAY_EVAL_SERVER_ROOT` pointing at the holder copy).

## Out of scope

- Any engine change; any re-arm or reuse of the s3 checkpoint; shell server batch;
  parallel/concurrent minting; SWE-bench evaluation (never "solved").
- The audit (next aspect) — but flagged turns ARE ingested into the corpus by `belay phase0
  run` (default), so cases exist for the audit.

## Acceptance criteria (per stage)

1. **Freeze:** the `acceptance.sh` (invocation + env + protocol prose, no result) is
   committed **before** the run; the registry it names is in the same commit.
2. **Run once:** stdout captured verbatim to `acceptance.out`, committed next, whatever it
   says (Rule D). A second run only if declared as such.
3. **Verify:** `mkdir -p runs`; `belay phase0 run <batch-dir> --ledger runs/s4X.json
   --corpus-dir corpus/local --server node <fs-entrypoint> '{workspace}'` (no `--`); ledger
   copied into `docs/planning/phase0-mint-run/mint-run/ledgers/` and committed.
4. **Gate:** the PRD Rule A row is applied to the ledger; the outcome (pass → next stage,
   or stop with the named reason) is written into the findings note and the next stage does
   not launch until the gate passes.
5. **Findings note:** `STAGE4{A,B,C}_FINDINGS.md` — engine/version, model, verbatim report
   block, rate with denominator, controls' dispositions, UNVERIFIED by named cause, exposure
   line (judged/zero/unrecorded), reproducibility commands, wall-clock, requests/tokens.

## Edge cases (each pre-decided)

- **Quota stop** → `no_observation` on the stopping instance, later instances absent; resume
  on the SAME root after the cap resets (re-arm by construction). The limit shape is a
  finding (R-4), recorded verbatim.
- **Unrecognised provider error** → `terminal` → `failed` → instance skipped; a resumed run
  does not re-drive it (anti-re-roll).
- **Stage-2 exposure gate fires (0/10 judged)** → STOP per PRD Rule A; write the re-scope
  decision; stage 3 does not launch.
- **Control FAIL (any stage)** → the mint is **void** (PRD req. via `phase0-live-mint/prd.md`);
  record it, hand-replay the flag (next aspect), publish the void as a detector finding.
- **`INSTRUMENT SUSPECT`** on any ledger → a wiring/bridge failure, never a result; STOP and
  fix before spending more.
- **`MissingServerError` / clone failure** → setup failure, not a result; fix and re-run the
  stage (the freeze protocol's anti-re-roll applies to results, not to runs that never
  happened).

## Dependencies & sequencing

Third aspect. Blocked by `oracle-argv-safe-mode` (the frozen argv) and `stage-registries`
(the stage-1/2 registries). The live invocations run in the **main thread** (the
`live-smoke-confirmation` S-6 precedent: irreversible, spend-incurring steps are not
delegated). Blocks `audit-and-publish`.

## Open questions / risks

- Wall-clock: ~20 min (stage 1) → ~2–3 h (stage 2) → ~8–11 h (stage 3, resumable). The
  operator schedules the runs; the gates bound the uninterpretable spend at stage-2 size.
- macOS TCC prompt mid-batch: allowed-dir is `eval/clones`-adjacent (sibling layout, per the
  `workspace.py` design) — Stage-1 answer was "no prompt"; if one appears it is recorded.
