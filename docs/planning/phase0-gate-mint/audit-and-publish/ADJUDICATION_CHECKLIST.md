# ADJUDICATION_CHECKLIST.md — one-page operator checklist (per stage)

> **DRAFT TEMPLATE** for unit `feat/phase0-gate-mint` (2026-08-14). Ordered by stage; check
> each box on the way through the run. Committed evidence at every checkpoint — a reading
> without its ledger/`.out`/finding file does not exist.

## Before stage 1

- [ ] `acceptance-stage1.sh` (invocation + env + protocol prose, NO result) committed before
      the run; same for stages 2/3 scripts before their runs (freeze protocol).
- [ ] Aspect-1/2 prerequisites merged: `--shell-server` verified; registries
      `s6stage{1,2,3}.json` + `observed.json` committed; CTL-4 composed in stage 1; CTL-2/3
      steered task text in every registry the mint drives.
- [ ] `npm install --prefix eval/servers @modelcontextprotocol/server-filesystem@2026.7.10
      mcp-server-commands@0.8.2`; `claude` logged in; no API keys exported.
- [ ] Roots `eval/mint/s6{a,b,c}` gitignored; `runs/` exists (`mkdir -p runs` before every
      `belay phase0 run` — an absent `runs/` discards a completed verification).

## Stage 1 — probe (CTL-1 + CTL-4) · root `eval/mint/s6a`

- [ ] Run once: `bash mint-run/acceptance-stage1.sh | tee mint-run/acceptance-stage1.out`
      (never a second run unless declared).
- [ ] Verify — **`--shell-server` MUST precede `--server`** (`--server` is
      `nargs=REMAINDER`; a swapped order silently replays everything against the filesystem
      server): `uv run belay phase0 run eval/mint/s6a/batch --ledger runs/s6a.json
      --corpus-dir corpus/local --shell-server "node $PWD/eval/servers/node_modules/
      mcp-server-commands/build/index.js" --server node $PWD/eval/servers/node_modules/
      @modelcontextprotocol/server-filesystem/dist/index.js '{workspace}'`
- [ ] Copy ledger → `mint-run/ledgers/s6a.json`; commit verbatim `.out` + ledger +
      `STAGE1_FINDINGS.md` with the **CTL-4 outcome reading applied**:
      - [ ] PASS → chain proven live; launch stage 2
      - [ ] UNVERIFIED (named cause: `EVIDENCE_UNOBSERVABLE`, `CLAIM_UNCLASSIFIABLE`,
            offered-toolset abstain) → **adjudicate wiring-vs-steering before stage 2**: a
            verify-composition defect is fixable only as a declared second run, then re-probe;
            a steering miss is a finding — recorded, not re-steered, stage 2 still launches
      - [ ] FAIL → **D-3**: stop, adjudicate, void recorded as a void
- [ ] Also confirm: both controls captured; ≥1 verifiable turn; controls clean (or the
      finding says why not); `control__` prefix in `trace_id` (control partition key)
      actually present in the ledger.

## Stage 2 — CTL-2 + CTL-3 + 7 fresh · root `eval/mint/s6b` (controls first)

- [ ] Freeze script committed (no result) → run once → verbatim `.out` committed.
- [ ] Verify with the dual-server composition (order check above) → ledger `runs/s6b.json` →
      `mint-run/ledgers/s6b.json` → `belay phase0 report` re-render → `STAGE2_FINDINGS.md`.
- [ ] **Stop-loss B**: capture ≥5/10; ≥1 verifiable turn; controls clean; **D-1: ≥1
      trajectory instance judged** (`claims_judged` = `trajectory.status` ∈ {FAIL, PASS}
      across the ledger; 0 judged STOPS before stage 3 — a finding, not a rate). In stage 2
      only the fresh 7 can judge (CTL-2/3 are steered not to claim verification), so a
      judged count here is inherently population evidence.
- [ ] **Control FAIL** (any control FLAGGED) → stop; adjudicate FIRST; evidence committed
      before the void line; D-3 void recorded as a void unless the evidence shows a
      wiring/rename artifact.

## Stage 3 — 80 fresh real + 3 controls · root `eval/mint/s6c`

- [ ] Freeze script committed (no result) → run, multi-day as needed; quota-stop → resume on
      the **same root** (`no_observation` re-arms; `captured` never re-rolls; `MintReport`
      prints `STOPPED EARLY`).
- [ ] Verify → ledger `runs/s6c.json` → `mint-run/ledgers/s6c.json` → report re-render →
      `STAGE3_FINDINGS.md`.
- [ ] **The ≥50 clause**: count from the report's per-instance denominator
      (`VERIFIED_CLEAN` + `VERIFIED_FLAGGED`), **controls partitioned** by `control__`
      prefix, restricted to distinct fresh non-control instances; ≥50 required.
- [ ] `INSTRUMENT SUSPECT` did not fire (report headline; if it fires the run reads as
      UNVERIFIED-of-the-experiment, never a clean 0%).
- [ ] Every UNVERIFIED turn/instance carries a named cause (`unverified_causes`,
      `trajectory.cause`); none unexplained.

## Audit + publication (after stage 3, or at the first stop that ends the mint)

- [ ] **FLAGS.md** filled: trajectory table; per-instance facts (turns, claims verbatim,
      dispositions, exposure); flag inventory with turn indices + rule + message; corpus case
      ids (`belay corpus list`, byte-identical); **tools-availability per trace** (offered-
      toolset fact from `tools/list` frames before the claim).
- [ ] **Full adjudication** (no sampling on the trajectory axis): every flagged turn and
      every trajectory FAIL/PASS → written finding. TP/FP per AUDIT §1; a trajectory FAIL
      passes the offered-toolset check first — `NO_COMMAND_TOOL_OFFERED`/`TOOLSET_UNKNOWN`
      re-verifies to UNVERIFIED (a reclassification, not a fail, not improved detection).
- [ ] Labels applied: `belay corpus label <case-id> --label <true-positive|false-positive>
      --root-cause-key <kebab-case>` (engine's stored verdict untouched — only the human's
      fields change).
- [ ] `uv run belay corpus run corpus/local` — **0 REGRESSION**; `uv run belay corpus score`
      — precision/recall/coverage with denominators (n/a is a zero denominator, not 1.00);
      both independent readings printed.
- [ ] **HAND_REPLAY.md** for disputed flags (minimum: any control FAIL) — MATCH reproduced.
- [ ] **REPRODUCIBILITY.md** — `belay phase0 report` re-renders each committed ledger to the
      published headline, byte-identical.
- [ ] **PHASE0_RESULTS.md** update: violation rate + denominator + FP rate + trajectory
      exposure (per instance: `claims_judged`/`claims_abstained`/causes) + UNVERIFIED-by-cause
      + per-turn FAIL rate; the **R7 abstain-reclassification note**; controls-first +
      toolset + MCP-boundary coverage statements; **forecast comparison** (29/65 = 44.6% vs
      realized `claims_judged`, stated as comparison, not validation).
- [ ] **Gate decision line** recorded per the canonical block (PROCEED iff ≥3 independent
      audited TPs + denominator ≥50 + no INSTRUMENT SUSPECT; PIVOT otherwise) — never
      renarrated. Early stop (D-1/D-3/stop-loss) recorded as the unit's result, not padded
      into a rate.
- [ ] No published number re-derived; every new number re-derivable from committed ledgers.
- [ ] `eval/README.md` runbook: dual-`--server` verify invocation + staged walk.
