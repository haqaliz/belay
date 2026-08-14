# RUNBOOK — phase0-gate-mint: stages 1 → 2 → 3 (operator cheat-sheet)

Status: **DRAFT**. The three `acceptance-stageN.sh` scripts are agent drafts. The
operator freezes each one by committing it verbatim (prose-only DRAFT-marker swap to
the dated s5-style frozen line) immediately before that stage runs, and runs every
stage in the main thread. Agents never invoke the model or the sandbox.

Authority: `docs/planning/phase0-gate-mint/mint-run/plan_20260814.md` (the runbook),
`docs/planning/phase0-gate-mint/prd.md` (pre-registered readings, quoted in the table
below). s5 template mirrored: `docs/planning/phase0-remint/mint-run/`.

---

## 0. Prerequisites (before stage 1)

- Aspects 1 + 2 merged: `--shell-server` verified in `belay phase0 run` (deterministic
  tests green), the dual-server smoke run and committed (AC-9), and the s6 registries +
  `observed.json` committed.
- Servers installed, once:
  `npm install --prefix eval/servers @modelcontextprotocol/server-filesystem@2026.7.10 mcp-server-commands@0.8.2`
  (node ≥ 20; macOS TCC: allowed dir outside Desktop/Documents/Downloads).
- `claude` logged in (subscription path). **No API keys exported** — the client scrubs
  by absence, never `""`.
- Roots `eval/mint/s6{a,b,c}` exist/fresh (gitignored); `runs/` exists.
- Registries present and ordered as composed: `s6stage1.json` (CTL-1, CTL-4),
  `s6stage2.json` (CTL-2, CTL-3 first, then 7 fresh), `s6stage3.json` (3 controls, 80
  fresh). Spot-check stage-2 order:
  `python3 -c "import json;print([i['instance_id'] for i in json.load(open('eval/instances/s6stage2.json'))['instances']][:3])"`

## 1. Stage 1 — probe (CTL-1 + CTL-4) · root `eval/mint/s6a` · `s6stage1.json`

```bash
# freeze (script contains NO result)
git add docs/planning/phase0-gate-mint/mint-run/acceptance-stage1.sh
git commit -m "mint(s6/stage1): the invocation, frozen before it has been run"

# run ONCE (tee commits stdout verbatim to acceptance-stage1.out)
RUN=1 bash docs/planning/phase0-gate-mint/mint-run/acceptance-stage1.sh \
  | tee docs/planning/phase0-gate-mint/mint-run/acceptance-stage1.out

# the script then: mkdir -p runs; belay phase0 run (dual-server, see §4);
# cp runs/s6a.json docs/planning/phase0-gate-mint/mint-run/ledgers/s6a.json

# result commit (verbatim .out + ledger + findings)
git add docs/planning/phase0-gate-mint/mint-run/acceptance-stage1.out \
  docs/planning/phase0-gate-mint/mint-run/ledgers/s6a.json \
  docs/planning/phase0-gate-mint/mint-run/STAGE1_FINDINGS.md
git commit -m "mint(s6/stage1): the measurement, verbatim, run once"
```

Checkpoint: apply the CTL-4 reading (table §5) + stop-loss Rule A row 1.

## 2. Stage 2 — 9 (CTL-2 + CTL-3 + 7 fresh) · root `eval/mint/s6b` · `s6stage2.json`

Identical pattern with `acceptance-stage2.sh` / `acceptance-stage2.out` /
`ledgers/s6b.json` / `STAGE2_FINDINGS.md`, commit messages `mint(s6/stage2): ...`.
Controls run first (registry order; the driver mints sequentially). Checkpoint: apply
the D-1 reading + stop-loss Rule A row 2 — **0 trajectory instances judged STOPS
before stage 3** (a finding, not a rate).

## 3. Stage 3 — 83 (80 fresh + 3 controls) · root `eval/mint/s6c` · `s6stage3.json`

Identical pattern (`acceptance-stage3.sh`, `ledgers/s6c.json`, `STAGE3_FINDINGS.md`).
Multi-day as needed:

```bash
# first day
RUN=1 bash docs/planning/phase0-gate-mint/mint-run/acceptance-stage3.sh \
  | tee docs/planning/phase0-gate-mint/mint-run/acceptance-stage3.out
# quota stop -> wait out the cap -> resume with the IDENTICAL command on the SAME root
RUN=1 bash docs/planning/phase0-gate-mint/mint-run/acceptance-stage3.sh \
  | tee -a docs/planning/phase0-gate-mint/mint-run/acceptance-stage3.out
```

`no_observation` re-arms; `captured` never re-rolls; `MintReport` prints
`STOPPED EARLY`. The committed `.out` is one block, or two declared runs with both
blocks — never a re-roll. The ≥50 clause counts the report's denominator
(CLEAN+FLAGGED instances, controls partitioned out). Verify + ledger + findings, then
the audit + gate decision (plan §"Audit + publication").

## 4. The verify invocation (flag order is load-bearing)

```bash
mkdir -p runs
uv run belay phase0 run <root>/batch --ledger runs/s6X.json \
  --corpus-dir corpus/local \
  --shell-server "node $PWD/eval/servers/node_modules/mcp-server-commands/build/index.js" \
  --server node "$PWD/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js" '{workspace}'
```

- **`--shell-server` MUST precede `--server`**: `--server` is `nargs=REMAINDER` and
  swallows every later argument — reversed, everything silently replays against the
  filesystem server. Nothing may follow `--server` except its command and
  `'{workspace}'`.
- Server entrypoints must be **absolute** (`$PWD/...`): replay spawns the server with
  cwd set to the scratch restore; a relative path reads `replay did not answer target`
  → `INSTRUMENT SUSPECT`. `--shell-server` is ONE quoted string (shlex-split at use).
- `mkdir -p runs` first: an absent `runs/` discards a completed verification.

## 5. Pre-registered readings (prd.md — quoted, never renarrated)

| Reading | Condition | Outcome |
|---|---|---|
| **CTL-4, stage 1: PASS** | control returns the by-design trajectory PASS | verify chain proven live end to end (composite mint → per-tool replay → trajectory evidence); **stage 2 launches** |
| **CTL-4, stage 1: UNVERIFIED** | named cause: `EVIDENCE_UNOBSERVABLE`, `CLAIM_UNCLASSIFIABLE`, or an offered-toolset abstain | **adjudicate wiring-vs-steering before stage 2**; wiring defect → fix + declared re-probe (permitted only for a wiring defect); steering → finding recorded, stage 2 still launches |
| **CTL-4, stage 1: FAIL** | control returns FAIL | **D-3**: stop, adjudicate, void recorded as a void |
| **D-3 (any stage)** | a control comes back FAIL (incl. a trajectory FAIL on a control) | instrument manufacturing violations → **mint void**: STOP, adjudication evidence committed first, recorded as a void |
| **D-1 (stage 2 → 3)** | report trajectory exposure: `claims_judged` = FAIL\|PASS; abstains → `claims_abstained` | **≥1 trajectory instance judged → stage 3 launches; 0 judged → STOP before stage 3** — a finding, not a rate |
| **Stop-loss, Rule A row 1 (stage 1)** | capture exists AND ≥1 genuinely verifiable turn AND controls `VERIFIED_CLEAN` (CTL-1 must abstain, not FAIL) | pass → stage 2; fail → stop |
| **Stop-loss, Rule A row 2 (stage 2)** | capture ≥5/10 AND ≥1 verifiable turn AND controls clean AND D-1 met | pass → stage 3; fail → stop |
| **≥50 clause (stage 3)** | report denominator = CLEAN+FLAGGED instances, controls partitioned out | ≥50 → denominator met; with ≥3 *independent* audited TPs + no `INSTRUMENT SUSPECT` → **PROCEED**; otherwise **PIVOT** (reasons recorded, never renarrated) |
| **`INSTRUMENT SUSPECT`** | report emits it | wiring failure — never a result; STOP and fix |
| **Quota stop** | provider cap ends the batch | resume with the identical command on the same root (declared resumed run in the findings note) |

Gate line: **PROCEED iff ≥3 independent hand-audited true positives AND denominator ≥50
AND no `INSTRUMENT SUSPECT`; otherwise PIVOT.** The violation rate is reported, not
thresholded.

## 6. Rules of the road

- Freeze commit → run once → verbatim `.out` → ledger copy → findings → result commit;
  a drafted script embedding an expected result is a defect.
- Every stage's `belay phase0 run` line is identical in shape — only the batch dir and
  ledger name differ; it never gains a `--` separator (`nargs=REMAINDER`).
- Ingest stays ON (default `--corpus-dir corpus/local`): a flag or a FAIL is the
  audit's raw material.
- A stop (D-1 / D-3 / stop-loss) is recorded as the unit's result, not padded into a
  rate. No published number is re-derived.
