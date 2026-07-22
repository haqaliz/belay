# Understanding — `phase0-mint-execution`

**Date:** 2026-07-23 · **Branch:** `feat/phase0-mint-execution/aliz` (off `master` @ `07890e7`, v0.4.0)
**Source:** `docs/planning/_card/issue.md` (inline brief; `gh` tracker empty)
**Baseline:** worktree green — 624 passed, 1 skipped, 1 deselected.

This note is the Phase-2 dig. It supersedes the card's optimistic framing: the work is
**not** "run the mint that was blocked." Three independent code-reading passes found that
**the batch replay path is still unfaithful**, and that the operator entry point the mint
needs **does not exist**. Both are stated below with citations.

---

## 1. What the work is really asking

Produce **the number** — the per-instance violation rate with its denominator, FP rate, and
UNVERIFIED-by-cause breakdown — and write the pre-registered PROCEED or PIVOT. This is the
**Phase-0 gate itself**, not a capability (`CAPABILITY_ROADMAP.md:323-328`). It consumes
C1–C6 and adds no verdict axis.

It tests risk **R1**, the only Fatal-impact entry on the register (`ROADMAP.md:237`).

---

## 2. 🔴 The blocking finding: batch replay is still contaminated (a NEW defect)

The card assumed `replay-absolute-path-fidelity` (v0.4.0) unblocked the mint. **It unblocked
the single-instance path only.** The batch path — the one the mint actually uses — has a
distinct, unfixed defect of the same family.

**Mechanism, verified in code (not inferred):**

- `belay phase0 run` accepts **one static** `--server` command for a whole batch dir:
  `server_command: list[str]` at `src/belay/phase0/runner.py:90`, threaded unchanged to every
  trace and turn (`runner.py:115,174,200`), parsed once at `src/belay/cli.py:1044`.
- Each trace's `source_root` is read correctly **per turn from that turn's own manifest**
  (`src/belay/replay/engine.py:388`; recorded at `src/belay/sandbox/gate.py:435`). The
  *arguments* side handles heterogeneity properly.
- The *argv* side does not. `remap_argv` rewrites a token only if `is_under(token, from_root)`
  (`src/belay/replay/relocate.py:93-108`), and returns a `changed` flag — which
  `src/belay/replay/client.py:371` **discards via `[0]`**. Verified directly: no caller in
  `src/` consumes it.
- So for every instance whose workspace ≠ the one static `--server` root token: arguments
  are rebased onto the scratch, the server's allowed-dir is **not**, the filesystem server
  rejects the scratch paths, the reply diverges from the recorded success,
  `classify_determinism` re-runs the same broken command and calls it DETERMINISTIC, and
  `src/belay/verify/result.py:18` gives `DIVERGED + DETERMINISTIC → FAIL`.

**Consequence:** every instance except the one matching the `--server` token comes back
`VERIFIED_FLAGGED` (`runner.py:201-206`), inflating the published rate toward **~100%** — as
**false FAILs, not UNVERIFIED**. This is precisely the artifact the symmetric FP guard and
the "verify ONE before scaling" rule exist to prevent, and it is invisible at n=1.

**No test covers it.** Every relocation e2e case builds the server command from the *same*
root as the capture (`tests/test_replay_relocation_e2e.py:99` `_server_cmd(root)`, used at
:312, :339, :369, :401, :488, :592). `tests/test_replay_relocate.py:54-70` asserts an
out-of-root token is left verbatim — correct in isolation, and exactly the hole here.

**Capture already solved this; replay didn't.** `eval/minting_driver/batch.py:82-95`
documents the identical hazard and takes a per-instance `build_server_command(layout)` seam
(`eval/minting_driver/servers.py:152`). `run_batch` has no equivalent —
it takes `server_command: list[str]`, not a `server_command_for(trace)` callable.

**Two candidate fixes** (a decision for the gate, not for me):
- **(a) Per-trace server-command seam** — thread `server_command_for(trace)` through
  `run_batch`/CLI. Makes the batch actually verifiable. More surface, touches the CLI.
- **(b) Consume the `changed` flag** — when relocation is on and no argv token moved, return
  **UNVERIFIED** with a named cause instead of spawning a mis-rooted server. Small, strictly
  honest, but yields a batch of UNVERIFIED → `INSTRUMENT SUSPECT` → no number.
- They compose: (b) is the honesty floor, (a) is what produces a denominator. Doing (b)
  alone converts a false-FAIL mint into a no-number mint; doing (a) alone leaves the silent
  failure mode in place for anyone else.

**Scope collision:** the `phase0-live-mint` PRD put "*Any change to `src/belay/`*"
explicitly out of scope (`prd.md:227-229`). That constraint was written when the harness-side
bridge was the only gap. It cannot hold now — **this unit must own a core-engine change**, or
the number cannot be produced honestly. Flagged for the gate.

---

## 3. 🔴 The second blocker: there is no way to run this

- **No one-instance-by-id entry point exists.** No CLI, no `__main__`, no argparse anywhere
  under `eval/`. `run_mint` (`eval/minting_driver/batch.py:123-137`) is real, correct, and
  invoked **only from tests with fakes**. Stage 1 was driven by an uncommitted
  `scratchpad/drive_one.py` (`STAGE1_FINDINGS.md:5-6`) that no longer exists — **the exact
  Stage-1 invocation cannot be re-run from the repo as-is.** That is a reproducibility gap in
  the artifact whose entire purpose is reproducing the number.
- **`selected.json`, `pool.json`, and the dataset fetch script do not exist.** The stratified
  draw (`eval/instances/selection.py:97`) is built and tested but has no pool to draw from.
  The only committed instance data is one prose entry in `eval/instances.md`.
- **`eval/servers/` is not installed** (gitignored; absent from both checkouts). Install per
  `eval/minting_driver/servers.py:113`.
- **The manual smoke is a weak oracle**: it accepts `VERIFIED_FLAGGED`, so the Stage-1 false
  positive *satisfied* it (`STAGE1_FINDINGS.md:77-79`), and it bypasses `bridge_capture` via
  a `manifest_dir_for=` override, so it never exercises the load-bearing bridge.

---

## 4. Affected areas

| Area | Files | Change |
|---|---|---|
| Core replay (batch server rooting) | `src/belay/replay/client.py`, `src/belay/phase0/runner.py`, `src/belay/cli.py` | **New** — the §2 fix |
| Eval entry point | `eval/` (new module) | **New** — one-instance-by-id + batch runner |
| Instance pool | `eval/instances/`, new `pool.json` / `selected.json` | **New** — fetch + draw + controls |
| Results / docs | `docs/technical/PHASE0_RESULTS.md`, `phase0-corpus-run/RUNBOOK.md`, `STAGE1_FINDINGS.md`, `ROADMAP.md` | Fill / correct / de-stale |

---

## 5. Guardrail check (`CLAUDE.md`)

- **No agent framework.** The driver stays thin and sequential; no planning, memory, or
  retry-with-reflection. Unchanged by this unit.
- **No LLM judge.** The model only *acts*. A1/A2 decide. No axis changes; A3 untouched.
- **UNVERIFIED never PASS.** Directly load-bearing here — fix (b) exists precisely to keep a
  mis-rooted replay from reading as a verdict.
- **No raw-data egress.** Traces/corpus stay local; BYOK only.
- **Verdict axes touched:** none. The §2 fix corrects *fidelity* of A2's inputs; it does not
  change what any axis claims.

---

## 6. Contradictions found (flagged, not papered over)

1. **`STAGE1_FINDINGS.md:9-12` and `RUNBOOK.md:5-18` still say the number is BLOCKED** on
   finding #3 — stale since v0.4.0. But per §2 the *batch* path is genuinely still blocked,
   so the correction must be precise, not a blanket "unblocked".
2. **Three different gate statements exist.** `ROADMAP.md:117-121`, `PHASE0_RESULTS.md:92-100`
   (no "reproducible" clause; adds a non-zero-rate clause), and the PRD's pre-registered block
   (`prd.md:58-71`, adds denominator ≥50 + "independent" TPs, removes the rate threshold). The
   PRD's is intended canonical and is **in neither downstream doc**.
3. **RUNBOOK says parallelism is safe** (`:94`, with a parallel loop at `:96-103`) —
   contradicts sequential-by-design (`prd.md:119-121, 233`). A **6th** RUNBOOK defect, not on
   the known list of five.
4. **Stale line citations** across the planning docs (~+15 shift in RUNBOOK cites after the
   warning header; `ROADMAP.md:118` → `:120`).
5. `record-workspace-root` / `replay-relocation` are aspects of
   `replay-absolute-path-fidelity`, **not** of `phase0-live-mint` (which has four:
   instance-registry, batch-harness, mint-execution, audit-and-publish).

---

## 7. Open questions for the interview

1. **Scope:** does this unit own the core-engine fix (§2)? Which shape — (a), (b), or both?
2. **Provider + budget:** `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` are both present. Stage 1
   used Gemini (`gemini-flash-latest`; `gemini-2.5/2.0-flash` 404 on this key). The driver
   prefers Anthropic when its key is set. Stage 3 is ~65–70 live instances — unbudgeted.
3. **Shell batch:** run filesystem-only and disclose the exclusion, or block on
   `replay-relocation-shell` first? (PRD must-have 11 wants two segregated batches.)
4. **Launch target / controls:** ~65–70 to land ≥50 after attrition, incl. 3 controls —
   confirm, and confirm the draw seed is committed.
5. **Does the corrected RUNBOOK have to be walked end-to-end by hand** before publishing?
   (`audit-and-publish/spec.md:64-66` says yes — it is the reproduce-the-number artifact.)
