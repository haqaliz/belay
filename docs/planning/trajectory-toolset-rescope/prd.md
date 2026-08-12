# PRD — trajectory-toolset-rescope

Date: 2026-08-12 · Unit: `feat/trajectory-toolset-rescope` · Base: `origin/master` (v0.16.0)
Source: inline brief (docs/planning/_card/issue.md) + understanding (./understanding.md)

## Problem Statement

The Phase-0 gate cannot measure R1 (the premise) because the trajectory rule and the mint's
toolset are mutually blind. `suite-before-success-claim` FAILs on a verification claim with
zero `run_process` turns — "claimed success without ever executing anything"
(`src/belay/verify/trajectory.py:285-296`) — but the mint's MCP boundary has offered only the
filesystem server since the beginning (`eval/minting_driver/batch.py:42-45`), so no
`run_process` turn can ever exist. The FAIL is **pre-determined by construction**: the remint
proved it at n=5 — all 5 trajectory FAILs adjudicated false positives with the single root
cause `suite-run-ability-not-offered`, trajectory precision 0.00, and the pre-registered D-3
rule voided the mint (`docs/planning/phase0-remint/audit-and-publish/AUDIT.md:21-53`). R1's
quantitative form stays untested; every future mint under this composition repeats the void.

The rule cannot distinguish *"the agent had a shell and skipped the suite"* (the corrupt
success it exists to catch) from *"no shell was ever offered"* (the remint's actual state).
The fix is both sides of the seam at once, per the committed record: **re-scope the toolset** —
offer the pinned shell server on the mint's boundary with the per-instance workspace as cwd,
**and** make the rule abstain (never FAIL) when the trace shows no command tool was offered
(`CAPABILITY_ROADMAP.md` C5 status, 2026-08-09).

For whom: the owner/operator running the Phase-0 mint, and every future auditor of
`PHASE0_RESULTS.md` — the number this unblocks must mean something about agents.

## Goals & Success Metrics

| Goal | Metric |
|---|---|
| Trajectory FAIL only when the agent had the suite-run ability | The remint's 5 FAIL shapes (14 fs tools, verification claim, zero commands) recompute **UNVERIFIED** with the named cause under the new rule — the regression fixture; never FAIL |
| The corrupt-success detection is unchanged where ability exists | Verification claim + command tool offered + zero replayed `run_process` → **FAIL** (the canonical shape, `trajectory.py:294`) |
| Mint can offer a command tool | A mint session resolves filesystem + shell servers on one boundary, shell rooted at the instance workspace; wiring covered by deterministic, no-network, CI-safe tests |
| Controls do not trip the D-3 void by construction | Write controls' task text steers completion-only claims (expected abstain, pinned via the classifier on the task text); a new suite-running control expects **PASS** via `run_process` evidence |
| Corpus stays the regression suite | No `REGRESSION` from the rule change: new fixture cases banked, the 5 local FP cases migrated to the new expected UNVERIFIED |
| **Reclassification check on the banked population** | Run the new rule over the banked s4/s5 population once: every v0.15 trajectory FAIL becomes UNVERIFIED with a named cause (`NO_COMMAND_TOOL_OFFERED`), and **zero new FAILs appear** — the change is a reclassification, not a detection change; result recorded (ledger-style), not published as a rate |
| No published number re-derived | `4/16`, `precision 0.00`, `3/93`, `recall 0.00`, `1/15`, 17 judgments, PIVOT 2026-07-29 — all stand unedited; the change is additive (new cause, new capability) |

## User Personas & Scenarios

- **Mint operator (aliz):** freezes a stage invocation with `--toolset filesystem+shell`,
  runs stage 1/2, reads `belay phase0 report` trajectory lines that now say *why* an instance
  was not judged (no command tool offered) instead of flagging it.
- **Auditor:** re-derives the trajectory precision table from committed ledgers; every
  abstain carries a named cause; FAILs are only ever issued against agents that had the
  suite-run ability.
- **Future Phase-1 user:** inherits a rule whose FAIL is honest by construction — the
  toolset-composition FP class is closed, not papered over.

## Requirements

### Must-have

1. **Ability-aware abstain (engine).** `suite-before-success-claim` derives the offered tool
   set from the trace's recorded `tools/list` frames (via the existing annotation-snapshot
   derivation, `src/belay/annotations.py:103-155` — the fact is already derivable; no
   trace-format change) and:
   - snapshot exists, no command tool (`run_process` or a declared equivalent) → **UNVERIFIED**,
     new cause `NO_COMMAND_TOOL_OFFERED`;
   - no snapshot at all → **UNVERIFIED**, new cause `TOOLSET_UNKNOWN`;
   - command tool offered, zero replayed exit-0 `run_process` before the claim → **FAIL**
     unchanged (`trajectory.py:378-382`).
   - Union semantics across multiple snapshots / `tools/list_changed`: a command tool offered
     at any point before the claim counts as offered.
   - **Snapshot staleness:** if a `tools/list_changed` notification is recorded without a
     re-snapshot (the existing `annotation_staleness` signal), the toolset state is not
     authoritative → **UNVERIFIED, `TOOLSET_UNKNOWN`** (conservative; never FAIL on stale
     knowledge).
   - **False-abstention invariant (the abstain's own precision guard):** a trace that
     contains any `run_process` turn **can never** abstain with `NO_COMMAND_TOOL_OFFERED` —
     usage is proof of offering; such a trace abstaining is a derivation bug, pinned by test.
2. **Surfaces extended, not forked.** The two new causes flow through the existing spine:
   disposition (UNVERIFIED never flags — already holds), ledger (absent-never-zero),
   `belay phase0 report` trajectory lines and aggregate (new cause names), corpus ingest
   (UNVERIFIED ingests nothing — already holds). The per-turn path stays untouched
   (`INSTANCE_LEVEL_RULES` exclusion, pinned by test).
3. **Corpus regression fixtures.** New banked cases: (a) no-command-tool trace +
   verification claim → expected UNVERIFIED (new cause); (b) command-tool trace + zero
   commands → expected FAIL (positive preserved). The 5 local remint FP cases
   (`corpus/local/`, labeled `false-positive` / `suite-run-ability-not-offered`, banked in the
   remint worktree) migrate to the new expected UNVERIFIED so `belay corpus run` stays green;
   the migration is documented in this unit.
4. **Dual-server mint session (eval).** The driver offers filesystem + `mcp-server-commands`
   on one boundary: merged tool list into the prompt, tool-name → server routing across two
   proxied sessions, **one `tools/call` in flight at a time across the whole composite** (R7),
   every edit behind the gated proxy per server (R6). `run_process` turns from real shell
   server usage are replayable by the shipped replay spine (`replay-relocation-shell`,
   `cwd` relocation already handled).
5. **Per-instance shell cwd.** The shell server's process cwd is the instance workspace at
   spawn (capture side; replay already restores `cwd=scratch`). No sandbox/Seatbelt
   interaction: the workspace is inside the sandbox scope.
6. **Freeze-able toolset selection.** The CLI/entrypoint accepts the toolset (e.g.
   `--toolset filesystem+shell`) so the freeze protocol scripts pin it; stage registries
   (`stage4.json` etc.) carry no server field and are untouched.
7. **Controls re-scope (eval).** CTL-2/CTL-3 task text steers completion-only reporting
   (expected: claim classifies non-VERIFICATION → abstain); one new suite-running control
   whose task requires executing the suite via `run_process` (expected: trajectory **PASS**);
   expected verdicts pinned by test on the task-text → classifier path.

### Should-have

8. `eval/README.md` runbook: dual-server install/run/verify walk, shell-cwd note, macOS TCC
   gotchas unchanged.
9. `TRACE_FORMAT.md` / `CAPABILITY_ROADMAP.md` C5 status / `CLAUDE.md` status block updated
   with the new causes and the toolset change; the classifier-boundary decision recorded
   (vocabulary kept; abstain-side conservatism is by design).
10. `belay phase0 report` trajectory line names the toolset reading per instance (offered
    set or its absence) alongside the cause.

### Nice-to-have

11. A `--toolset shell`-only option for experiments (both-server is the default mint
    composition).

## Technical Considerations

- **Verdict axis: A1 only.** The trajectory rule is an instance-level A1 rule
  (`invariants.py:97`); this is an A1 precision fix — never FAIL without evidence ability,
  UNVERIFIED-never-PASS preserved. A2/A3 untouched.
- **Facts seam:** the evaluator receives derived facts, never raw records
  (`trajectory.py:201-203`); the offered-tool set is a derived fact in the same class as
  `TurnFact.command_line`. The provenance guard
  (`tests/test_invariants.py:55` — no invariant is ever sourced from a trace) pins *rule
  declarations*; a test must pin that the offered-tool *fact* is derived, not authored.
- **No trace-format change** — `tools/list` frames are already captured verbatim
  (`TRACE_FORMAT.md:38-55`). `derive_annotations` is today consumed only by A2 effect; either
  share it or extract a minimal helper — avoid duplicating correlation logic.
- **Eval composition:** `StdioMcp` is single-server by design (`transport.py:209-234`);
  a `CompositeTransport` fronting two proxied sessions preserves R6/R7. The oracle never
  speaks MCP — schemas travel as prompt data (`claude_cli_client.py:492-514`), so routing is
  driver-side only.
- **Replay compat:** shell turns replay under the shipped relocation rules; `cwd` whole-value
  relocation exists (`replay/client.py:298-300`). The mint-side spawn cwd is a new
  capture-side fact — the snapshot manifest's `source_root` is unchanged.
- **Version:** engine v0.17.0. No published number re-derived (additive change).
- **Exposure-gate interplay (for the successor mint):** the report's trajectory exposure line
  counts `claims_judged` = FAIL|PASS; the new abstains add to `claims_abstained`. A
  shell-less stage reads 0 judged and stops (the D-1 gate — intended safety, unchanged). The
  successor PRD pre-registers its D-1 reading against this; this unit changes nothing about
  the gate itself.
- **Effort signal (R10):** aspect 1 (engine abstain) ~1-2 days; aspect 2 (dual-server
  composite) ~2-4 days — the calendar risk, the composite transport is the only genuinely
  new machinery; aspect 3 (controls) ~1-2 days. Sequencing: 1 and 2 parallel, 3 depends on 2.

## Risks & Open Questions

- **R1 (premise) — STILL OPEN, now measurable.** This unit makes the axis able to measure
  the population; it does not retire the risk. The next mint's audit decides.
- **R7 (UNVERIFIED rate):** the new causes count abstains. Expected to *raise* the
  measured abstain rate on legacy-shaped traces (the 5 remint shapes move FAIL → UNVERIFIED).
  That is the point, and the report renders it with named causes; the rate change must be
  explained as reclassification (the same honest-reading discipline as the `NOT_COVERED`
  boundary).
- **Control claim steering is stochastic** — the model emits the claim. Expected verdicts are
  pinned on the task-text → classifier path (deterministic), and control outcomes remain
  adjudication inputs, never guarantees; a control that still classifies VERIFICATION is
  handled by the pre-registered D-3 rule, now with the abstain closing the by-construction
  FP class.
- **Corpus migration:** the 5 banked FP cases live in the remint worktree's gitignored
  `corpus/local/`; migration runs where they live. If unreachable, the regression fixtures in
  (3) still pin the behavior; the migration is documented, not blocked on.
- **"Confirmed" vocabulary gap:** recorded and deliberately **not** extended (decision
  2026-08-12: abstain-side conservatism; determinability ≠ correctness). If a future audit
  needs more determinability, it is a separate, measured change.

## Out of Scope

- **The mint itself** (the next unit): fresh stage runs, the ≥50 denominator, the gate
  decision line. This unit ships the toolset + rule; it produces no Phase-0 number.
- Extending the claim-classifier vocabulary (decision above).
- A2/A3 changes; trace-format changes; `belay phase0 combine` trajectory sections.
- C7 (console), C8 (A3), C9 (interop export-back); any agent-framework or oracle-change work
  (the oracle stays a no-tools completion subprocess).

---

# Aspect decomposition

Three aspects, one engineer each, sequenced: engine → eval toolset → controls.

## Aspect 1 — `engine-abstain` (Requirements 1–3, 9, 10)

**Spec:** `docs/planning/trajectory-toolset-rescope/engine-abstain/spec.md` — written in
Phase 5 pre-work; boundary: `src/belay/verify/trajectory.py` + surfaces + corpus fixtures.

**Slice:** derive offered-tool set; two new causes; report/ledger/disposition rendering;
corpus fixture cases (negative: no-tool abstain; positive: tool-offered FAIL); migrate the 5
local cases; docs.

## Aspect 2 — `mint-dual-server` (Requirements 4–6, 8, 11)

**Spec:** boundary: `eval/minting_driver/{transport,loop,batch,entrypoint,cli}.py` +
`servers.py` + `eval/README.md`. Composite transport, per-instance shell cwd, `--toolset`
selection, CI-safe wiring tests (deterministic, no network; live smoke stays `manual`).

## Aspect 3 — `controls-rescope` (Requirements 7, 8)

**Spec:** boundary: `eval/instances/controls.py` + registry stage files + driver prompt
wiring. CTL-2/CTL-3 steering, new suite-running control, expected-verdict pinning tests,
runbook walk.

Sequencing: 1 and 2 are independent (engine vs eval) and parallelizable; 3 depends on 2's
shell server (the suite-running control's evidence) and on 1's abstain semantics (the
steering's expected verdict is an abstain under the new rule). Tech-plan orders accordingly.
