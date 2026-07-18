# Understanding — phase0-corpus-run

**Phase 2 dig.** Synthesis of three read-only agent maps (proxy/ingest, verify, corpus) +
README/roadmap constraints. All `file:line` anchors verified against the worktree at
`feat/phase0-corpus-run/aliz` (master @ 81f407c, C1–C6 merged, 431 tests).

---

## What the work is really asking

Clear the **Phase-0 gate**: mint a corpus by running real agent runs through the Belay proxy,
then **publish the number** — violation rate *with* its false-positive rate *and* its UNVERIFIED
rate (ROADMAP.md:109–122). The C6 machinery exists but the corpus is empty and no number has
been published (`CLAUDE.md` status: *"Next: run the Phase-0 corpus and publish the
violation-rate number"*).

The missing artifact is a **batch runner** — there is *no* run-many abstraction in the codebase
today (confirmed: no `run_id`, no batch driver; `/runs/` is only a reserved gitignore
convention). Everything downstream is one-at-a-time and reusable as-is.

## The end-to-end shape (grounded in the code)

Per instance:
1. **Capture** — launch `python -m belay.proxy <mcp-server…>` (proxy is a *module entry point*,
   not a `belay` subcommand — `proxy.py:530`), env-driven: `BELAY_TRACE_DIR` (record),
   `BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` (turn on A1/A2 snapshot gating; snapshot dir is
   **required** when scope is set — `proxy.py:544`). One proxy invocation = one
   `trace-<ts>-<hex>.jsonl` (`trace.py:144`). Drive the agent; it points at the proxy by naming
   `python -m belay.proxy <realserver>` as its MCP server command (`tests/test_real_client.py:43`).
2. **Verify** — `read_trace(file).records` → `derive_correlation` → `tool_calls` enumerates
   turns; loop `verify_turn(records, n, server_command=…, manifest_dir=…, invariants=default_invariants())`
   in-process (`turn.py:140`; the exact loop `_cmd_verify` runs, `cli.py:511`). **There is no
   whole-trace API and no `--json`** — call `verify_turn` and read `TurnVerdict.status`
   directly; do not shell out and parse stdout.
3. **Flag** — a turn is a caught failure iff `TurnVerdict.status is FAIL` (`verdict.py:34`).
   The A1 default invariant **`tests/` read-only** (`invariants.py:228`) is what catches a
   cheating SWE-bench agent that A2 structurally cannot. UNVERIFIED is a distinct third bucket,
   never folded into PASS or FAIL.
4. **Add** — `add_case(corpus_dir, records=…, target_turn_index=N, verdict=…, manifest_dir=…,
   server_command=…, invariants=…, human_label="pending")` composes one self-contained case dir
   under gitignored `corpus/local/<id>/` (`add.py:97`). Requires a **restorable pre-state** or it
   raises (`add.py:122`). `add` does *not* require the turn to be flagged (it will add a PASS),
   and it **never** auto-labels — a FAIL is stored `pending` (D3 boundary, `add.py:14`).
5. **Label** — a human runs `belay corpus label <id> --label true-positive|false-positive|unverifiable`
   (`curate.py:34`); `pending` is not human-settable. The engine never labels its own cases.
6. **Score** — `belay corpus score` → precision/recall/coverage over decisive+adjudicable cases,
   UNVERIFIED excluded and lowering coverage (`metrics.py:114`). FP-rate = 1−precision;
   UNVERIFIED-rate falls out of the `unverified` tally / coverage.

## THE load-bearing finding: the denominator problem

**`corpus score` cannot emit the violation rate.** Nothing in the corpus records total-runs —
`Metrics.total` is just `len(cases)` (added cases), and every score denominator derives from
cases *present* in the corpus (`metrics.py:157`). Violation rate = flagged / **total runs
audited**, and total-runs lives nowhere. → **The runner must own a denominator ledger** (how
many instances/turns were verified), compute violation-rate itself, and pull FP-rate +
UNVERIFIED-rate from `score`. This is net-new and is the single most important thing the PRD
must nail: *the number is a runner-owned artifact, not a `corpus score` output.*

## Affected areas / where code lands

- **Net-new:** a Phase-0 batch driver + a run ledger + a violation-rate report. Likely a new
  `belay` subcommand (e.g. `belay corpus batch` / `belay phase0 run`) or a `src/belay/phase0/`
  module. Reuses verbatim: `verify_turn`, `add_case`, `run_corpus`, `score`, `set_label`,
  `read_trace`/`derive_correlation`/`tool_calls`.
- **Untouched engine:** this work changes *no verdict logic*. It exercises A1 (tests/ read-only)
  + A2, and produces corpus cases. No new axis. (A3 does not exist yet — no `--no-claim-axis`.)

## Verdict-axis placement

Does not add or modify an axis. It **exercises A1 (invariant)** as the cheat-catcher and A2 as
the fidelity check, and it is the first real *input* to the C6 corpus. The deliverable is
detection evidence, not a verdict-path change.

## Guardrail check (CLAUDE.md) — one real tension to flag

- ✅ No raw-data egress — cases stay under gitignored `corpus/local/`.
- ✅ No bare LLM judge — verdicts stay the deterministic engine's; the human labels.
- ✅ UNVERIFIED never PASS — enforced by the existing engine; the report must preserve it.
- ⚠️ **"No agent framework" tension.** To mint the corpus we must *drive an agent*. If the
  runner ships our *own* agent loop as a product surface, that drifts toward authoring an agent.
  Mitigation to decide in the PRD: the minting agent should be an **off-the-shelf open
  MCP-native agent** (BYOK), and any driver we write is **eval infrastructure** (a test/mint
  harness), explicitly not a product surface. Flag, don't paper over.

## Feasibility risks that reshape the whole unit (surface in the PRD)

1. **R6 — the MCP boundary (fatal-if-ignored).** Belay only sees `tools/call` crossing the
   stdio pipe (`index.py:190`; CLAUDE.md "Known cost"). An agent doing edits via built-in
   `Bash`/`Edit` yields an **empty trace → false zero**. The minting agent MUST route file/shell
   ops through MCP **filesystem + shell** servers behind the proxy. Verify with ONE instance
   before scaling to 50.
2. **R7 — batching → UNVERIFIED dominates (README:159).** A turn's pre-state is only capturable
   while nothing else is in flight; clients that batch independent `tools/call` (Claude Code,
   Cursor, OpenAI agents SDK — *the default*) hit `unrestorable` → UNVERIFIED, and Belay refuses
   to serialize them (that would change agent behavior). → the minting agent must issue tool
   calls **one at a time**, or the number is mostly "shrug." This is the second load-bearing
   agent-selection constraint.
3. **macOS-only engine (README:156).** Sandbox = Seatbelt (`sandbox-exec`), snapshot = APFS
   `clonefile`; off-darwin the sandbox *raises*, and `verify_turn`/`run_case` SKIP on non-darwin
   (`run.py`, guard confirmed). SWE-bench-lite normally runs in Linux/Docker — here the instance
   workspace + test run must live on the **macOS filesystem**, and instances whose test harness
   needs Docker/Linux-only deps are out of scope for v0 minting. Instance selection is a real
   sub-problem.
4. **Live vs. deterministic (the C8-style seam).** Driving a real agent needs live LLM calls —
   non-deterministic, never in CI. So split: (a) a **deterministic, offline** runner acceptance
   test using the existing fixture servers (`conftest.run_traced`, `proxy_cmd`, the
   `weakening_editor_server`/`cheat_test_runner_server` fixtures) that proves the
   trace→verify→add→score→report pipeline end-to-end against fakes; (b) the **live ≥50-instance
   mint** behind a manual gate, producing the published number. The shippable *code* is (a) + the
   driver; the *number* is the output of running (b).

## Open questions for the requirements interview (Phase 3)

1. **Which minting agent?** Off-the-shelf open MCP-native agent that (a) routes file/shell
   through MCP and (b) does not batch tool calls. Candidates + BYOK model. This is the crux.
2. **Scope of this unit:** does it deliver *the runner + a deterministic acceptance test* (code,
   shippable now), with the live ≥50-run mint + published number as the run-it step — or must the
   published number itself be in-scope for "done"? (Feasibility says split; confirm.)
3. **Violation-rate definition:** per-instance (an instance violates if any turn FAILs) vs.
   per-turn. Report both? What denominator does the gate want stated?
4. **Instance set:** which SWE-bench-lite instances are macOS-runnable without Docker? How many
   to target for the first mint (gate says ≥50; feasibility may force a smaller honest first cut
   with the constraint stated).
5. **Report artifact:** where the number lives (a committed `docs/` report? a `belay …
   report` command output?) and exactly which figures (violation rate + denominator, FP rate,
   UNVERIFIED rate with per-cause breakdown, ≥3 hand-audited TPs).
6. **Guardrail resolution:** confirm the minting driver is eval infrastructure, not a product
   agent surface.
