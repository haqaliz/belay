# Understanding — `feat/phase0-reverify-banked`

Written 2026-07-30 after a four-agent read-only dig (`dig-phase0-engine`, `dig-corpus-labels`,
`dig-published-record`, `dig-banked-data`; all four returned). Every claim is either cited to
`file:line` or was measured on disk in this session. Where an agent and my own measurement
disagreed, both are recorded and the disagreement named.

> Replaces the predecessor note for `phase0-stage3-publish`, preserved in git history.

---

## 1. What the work is really asking

Two deliverables sharing one execution:

1. **A measurement.** Re-verify the banked captures under the A1 rule that ships today
   (`no-assertion-weakening`, `src/belay/verify/invariants.py:615`) and report the number with
   its denominator. This is the only held-out real data the new rule has ever seen — it was
   fitted on the 7 negative fixtures plus `pytest-5227`, and `README.md:183` correctly says its
   precision is *"not yet measured"*.
2. **A record correction.** Every published Phase-0 number was produced by the **replaced**
   detector, so the record and the shipped code disagree. The repo already has a convention for
   fixing that without destroying provenance (§6).

**It is emphatically not a gate run.** PROCEED requires a denominator **≥50**
(`docs/planning/phase0-live-mint/prd.md:58-71`), and that clause is *detector-independent* — it
counts instances minted, not the rule that scored them. No re-verification of already-banked
data can satisfy it. R1's quantitative form stays untested.

---

## 2. The population, measured — including a correction to my own card

Measured this session over `eval/mint/*/batch/trace-*.jsonl` in the
`feat-verdict-coverage-status` worktree:

| Stage | Captures | Turns (`tools/call`) | Notes |
|---|---|---|---|
| `s1` / `s1b` / `s1p` | 1 / 1 / 1 | 20 / 20 / 11 | three independent mints of `pallets__flask-4045` |
| `s2/batch` | 9 | 130 | 7 instances + **2 controls** |
| `s3/batch` | 12 | 216 | 12 instances, **0 controls** |
| **total** | **24** | **397** | 10.31 MB of traces; 4.7 GB of stage dirs |

- **17 distinct trace ids** = 15 non-control instances + 2 controls.
- **`s2/batch` ∩ `s3/batch` = 5 instances** (`flask-4992`, `requests-1963`, `pylint-5859`,
  `pytest-5221`, `pytest-5227`), each pair differing in size *and* turn count — genuine
  independent re-mints, not duplicated files.
- Every trace has a sibling `.manifests/` dir, and **manifest count == turn count** in all 24.
- All 24 recorded `source_root` paths **exist on disk today**.

> **Correction to `_card/issue.md` as first written.** I wrote "16 unique instances". Wrong.
> The published **16** is a *sum of ledger rows* across four ledgers (`s1p` 1 +
> `stage1-recheck` 1 + `s2` 9 + `s3-partial` 5), double-counting `flask-4045` and the two
> instances shared by `s2.json`/`s3-partial.json`. The unique non-control population is **15**.
> Both "5 overlapping" and "2 overlapping" appear in evidence and **both are true, of different
> populations**: 5 in the captures on disk, 2 in the published ledgers. The card is now fixed.

**The finding underneath it.** `s3-partial.json` ledgered only **5 of s3's 12** captures, so
**7 captured instances appear in no ledger under `runs/` at all**. The re-verifiable population
is therefore *larger and cleaner* than the published one, and at 397 turns there is no reason
to reproduce the partial coverage.

**The 56 failed s3 instances cannot contaminate anything.** `s3/checkpoint.json` records
56 `failed` / 12 `captured`, all 56 reasons `Error code: 429`. All 56 have handshake-only traces
with **zero** `tools/call`, and **none is in `batch/`** — so `phase0 run <stage>/batch` cannot
pick them up. (Two are large — `django-12856` at 2.2 MB — but still zero tool calls.)

---

## 3. Four capabilities the acceptance criteria need, and none exists

This is the dig's core finding: **the unit is not "run a command and write up the output"** —
each of (a)–(d) names behaviour the engine does not have.

| # | Criterion | Status today | Citation |
|---|---|---|---|
| (a) | merged ledger + tested dedup | **absent.** No merge, no dedup, no multi-ledger `report`. `RunLedger` is a bare `list[InstanceRecord]`, so a naive concat double-counts every shared `trace_id` in every aggregate | `phase0/ledger.py:104-162`, `cli.py:1258-1273` |
| (b) | ledger records rule identity | **absent — and no version field either.** Nine serialized fields, none naming a rule, config, or sha. An old-detector ledger is indistinguishable from a current one *by reading it* | `phase0/ledger.py:92-100,165-240` |
| (c) | controls reported separately | **absent.** Controls are only a `control__` id prefix (`eval/instances/controls.py:89-150`); `report.py` has no control branch, so a control folds into the **headline violation rate** silently. "A FAILing control voids the mint" is prose, enforced nowhere in code | `phase0/report.py`, `phase0-live-mint/prd.md:73-85` |
| (d) | re-ingest never overwrites a label | **absent — and the real behaviour is worse than an overwrite** (§4) | `corpus/add.py:266-284`, `phase0/runner.py:246-262` |

Useful asymmetry for (b): `Case` **does** record `invariants` per case (`corpus/add.py:306`), so
the corpus knows which rule flagged it while the ledger does not. That is the shape of the fix.

---

## 4. The re-ingest hazard, traced end to end (highest severity)

Running the stock command over the banked stages with the default `--corpus-dir` does real
damage, and it surfaces as a *measurement result* rather than as an error:

1. `runner.py:255` always passes `human_label="pending"` — a re-ingest that **succeeds** stamps
   over a human adjudication.
2. It does not succeed: `add.py:279` calls `shutil.copytree(..., case_dir / "prestate")` with
   **no `dirs_exist_ok`**, so an existing case dir raises `FileExistsError`.
3. That is **not** a `ValueError`, so `runner.py:261`'s handler misses it. It reaches
   `run_batch`'s broad `except Exception` (`runner.py:147`) and the **entire instance** is
   recorded `ERRORED` — every turn's data discarded, not just the colliding turn.
4. `ERRORED` is **excluded from `violation_denominator()`** (CLEAN+FLAGGED only,
   `ledger.py:114-120`), so the denominator silently *shrinks*; enough of them trips
   `instrument_suspect()` (`report.py:65-87`) — **a fake `INSTRUMENT SUSPECT`, i.e. a fake
   PIVOT**, the failure mode this repo already treats as load-bearing.
5. `add.py:272` truncates `trace.jsonl` **before** the raise, leaving the case dir
   half-overwritten: new trace, old `prestate/`, old `case.json`.

The labels therefore survive **by accident** (the crash lands before `write_case`), at the cost
of a corrupted case dir and a bogus ledger. There is **no `--no-ingest` flag**
(`cli.py:1778-1847`); the only lever is `--corpus-dir`. No test covers a collision.

**Backup caveat:** `corpus-labels-backup-20260729/` holds only 7 flat `case.json` files — no
`trace.jsonl`, `prestate/`, or `task_prestate/`. It restores adjudications, not replayability.

---

## 5. Feasibility — confirmed, with one honest unknown

```
belay phase0 run <STAGE>/batch --ledger OUT.json --corpus-dir <scratch> \
  --server node /Users/aliz/…/feat-phase0-mint-execution/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js '{workspace}'
```

- `--server` is a `REMAINDER` passthrough and the literal `{workspace}` token is substituted
  per-trace with that trace's own recorded root (`cli.py:1835-1846`) — that is what lets **one**
  command verify a heterogeneous batch.
- Server entrypoint exists (28,217 bytes, ESM); `node` is v22.21.1. An absolute `trace_dir`
  works — nothing in `run_batch` assumes repo-relative paths (`runner.py:131`, `:81-90`).
- The filesystem server's recorded args are **workspace-relative** (`"path":
  "src/flask/scaffold.py"`), so the `run_process`/`command_line` relocation edge case does not
  apply to this server type.
- Offline and keyless: no network, no randomness; the only clock read is `captured_at` at the
  CLI boundary (`cli.py:1211`). So (e) is nearly free — but must still be **pinned by a test**,
  since nothing enforces it.
- **Honest unknown:** whether all 397 turns are single-root-relative is a replay-time answer;
  only `s1` was spot-checked. Cross-root reads would degrade to `UNVERIFIED`, not to a false
  PASS — the safe direction, and the UNVERIFIED-by-cause line would expose it.

Wall-clock is driven by 397 restore+re-invoke+diff cycles, not by the 4.7 GB.

---

## 6. Two conventions to follow, not reinvent

**The freeze protocol** — `invariant-rule-wiring/acceptance.sh` (committed `95e6ff8`, freezing
`151a267`), verbatim from its header: *(1)* the frozen rule is committed FIRST, in a commit
containing no result of the run; *(2)* the script is run ONCE and its output committed verbatim
in the NEXT commit, whatever it says; *(3)* a second run is permitted ONLY if declared as such
in the write-up. It prevents iterating against a held-out fixture and presenting the result as
a first attempt. Fixture-agnostic, so it applies here unchanged.

**The correction convention** — from `PHASE0_RESULTS.md:88-92,335-451` and the
`Superseded — kept for the record` blocks: retrofit a **warning banner** above stale numbers;
keep the original sentence and **append** an annotation beside it; add a literal **"what
changed, and what did not"** table; state the **evidence grade** (execution vs human
adjudication) explicitly; and **name what was deliberately left untouched, and why** — shipped
`CHANGELOG` entries are never rewritten (the correction goes in the *next* entry) and dated
planning docs stay stale on purpose, because they are the provenance trail.

---

## 7. Pre-existing defects in the record — surfaced, NOT to be silently fixed

Already parked by the repo, with reasons; fixing them here would be exactly the scope creep the
convention forbids:

- **The `16` denominator is internally inconsistent**, and the doc says so
  (`PHASE0_RESULTS.md:104` vs `:109-111`; Open Item #1 at `:437-443`).
- **`0% UNVERIFIED` is false as a whole-mint claim** and is already self-corrected in place
  (`:164` vs `:174-186`): `s2` is 2/130, `stage1-recheck` 1/12, both *"replayed but result
  unverified"*. **Detector-independent** — it will persist across the re-verify.
- **"5 distinct runs" vs "3 runs contributed cases" vs "4 ingestion timestamps"** is
  unreconciled and deliberately left so (Open Item #3, `:448-451`).

Side staleness found: `CLAUDE.md`'s *"1005 tests"* is out of date — this branch measures
**1198 passed, 1 skipped, 1 deselected**. And `README.md:183` is the one public sentence this
unit's result will invalidate.

---

## 8. Guardrail and axis check (`CLAUDE.md`)

- **Axis:** measures **A1** only. Changes **no** verdict semantics — not A2, not A3, not
  `verdict.reduce`, not the `NOT_COVERED` boundary. The A1 *rule* is out of scope: it is the
  thing under measurement, and editing it mid-measurement is what the freeze protocol prevents.
- **No agent framework, no LLM judge:** re-verification is pure re-execution, zero model calls;
  the zero-LLM AST guard over `src/belay/verify/` is untouched.
- **No raw-data egress:** captures and corpus stay in their worktrees, gitignored, referenced by
  absolute path. Only the ledger, the report, and the write-up are committed.
- **UNVERIFIED never PASS:** unchanged, and the UNVERIFIED-by-cause line must travel with the
  number.

---

## 9. Ambiguities for the interview (Phase 3)

1. **Population unit — captures or instances?** 24 captures vs 15 unique non-control instances
   (`flask-4045` minted 3×, five instances 2×). This decides the published denominator.
2. **Dedup policy for a duplicated instance** (acceptance (a)): worst-verdict-wins, latest
   capture wins, or report both? They are re-mints with different trajectories, so they can
   legitimately disagree.
3. **Where detector identity lives** (acceptance (b)): a new `RunLedger` field — a `src/belay/`
   schema change needing back-compat that reads an old ledger as *unrecorded*, never as
   *current* — or an out-of-band sidecar?
4. **Is the `add_case` collision defect (§4) in scope**, or is a scratch `--corpus-dir` enough?
   It is a real product defect, discovered here.
5. **How far does "correct the published record" go** — the minimal correction plus
   `README.md:183`, or also the parked Open Items in §7?
