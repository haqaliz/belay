# Understanding — trajectory-toolset-rescope

Date: 2026-08-12. Companion to `docs/planning/_card/issue.md` (the belay-next handoff brief).

## What this unit really is

Two half-slices that together unblock the Phase-0 gate measurement (R1's quantitative form):

1. **Engine (A1 precision fix):** `suite-before-success-claim` currently FAILs on a
   verification claim with zero `run_process` turns — *"the canonical corrupt-success shape:
   claimed success without ever executing anything"* (`src/belay/verify/trajectory.py:285-296`).
   It cannot distinguish **"agent had a shell and skipped the suite"** from **"no shell was
   ever offered"**. The remint proved the second case is real: 5/5 FAILs were false positives
   by construction (`suite-run-ability-not-offered`), trajectory precision 0.00, mint voided.
   The fix: abstain with a **new named cause** when the trace shows no command tool was
   offered — the FAIL stays exactly as designed when a command tool WAS offered.
2. **Eval (measurement fix):** the mint driver offers only the filesystem server
   (single-server by construction, `batch.py:42-45`). The trajectory axis cannot measure this
   population until `run_process` is reachable — offer the pinned shell server
   (`mcp-server-commands@0.8.2`, `servers.py:69-73`) on the mint's boundary with the
   per-instance workspace as cwd.

## Affected areas (from the dig, all file-cited)

**Engine — `src/belay/`**
- `verify/trajectory.py` — the evaluator (`evaluate_trajectory_invariant`, 270-430) receives
  only `(inv, claim_text, claim_seq, TurnFact[])`; the seam `evaluate_trajectory_rules`
  (467-512) holds `records` and can derive new facts. Zero-run_process → FAIL at 378-382.
  Named abstain causes are a closed vocabulary (135-137). `_EVIDENCE_TOOL = "run_process"`
  (143) — the only recognized command-tool name.
- **"Was a command tool offered" is already derivable from the trace as recorded** — no
  format change needed: `tools/list` frames are captured verbatim (`TRACE_FORMAT.md:38-55`),
  and `derive_annotations(records)` (`annotations.py:103-155`) already emits per-snapshot
  offered-tool-name sets (`annotation_snapshot` records), today consumed only by A2 effect
  (`verify/effect.py:66,180`). The trajectory path must compute the same fact (e.g. via a
  shared helper or the snapshot records) and pass it through the facts seam. Note the
  provenance guard `test_no_invariant_is_ever_sourced_from_a_trace` (`tests/test_invariants.py:55`)
  pins that invariant *declarations* never come from traces — a derived *fact* about observed
  tools is the same class as `TurnFact.command_line` (already read from frames) and must be
  tested as such.
- `phase0/runner.py` (337-342, 452-462) — trajectory evaluation call and disposition
  (UNVERIFIED never flags — already holds); `report.py` `_trajectory_line`/`_trajectory_section`
  (291-366) — new cause must render; `ledger.py` (163-184) — additive, absent-never-zero.
- **Corpus consequence (must be planned):** the 5 banked remint cases carry expected
  `trajectory {"status": "FAIL"}` (schema v4) and are labeled FP/`suite-run-ability-not-offered`
  (`docs/planning/phase0-remint/audit-and-publish/AUDIT.md:45-53`). Under the fixed rule they
  recompute **UNVERIFIED** → `REGRESSION` (`corpus/run.py` `_classify_trajectory_case`,
  386-418) — the corpus's regression suite would go red by design. The unit must re-bank /
  migrate those 5 (they live in gitignored `corpus/local/` of the remint worktree — not in
  this checkout) and add a regression fixture: no-command-tool trace + verification claim →
  expected UNVERIFIED (new cause).
- `TRACE_FORMAT.md`, `README.md` (coverage limits), `CAPABILITY_ROADMAP.md` C5 status block,
  `CLAUDE.md` status block — the record must be updated when the rule changes.

**Eval — `eval/minting_driver/`**
- `transport.py:209-234` (`StdioMcp`, one spawned server, Popen with **no cwd**),
  `proxy.py:475-480` (one downstream server, no cwd) — a second server needs a route, and the
  shell server needs a cwd. Replay already sets `cwd=scratch` (`replay/client.py:352-395`)
  and relocates whole-value `cwd` args (`client.py:298-300`); `mcp-server-commands` takes an
  optional per-call `cwd` (`tests/fixtures/shell_command_server.py:21-41`).
- `loop.py` (`run_task`, one `Transport`), `batch.py` (seam `build_server_command`, 145;
  single-server invariant 42-45; tools/list discovery 159-186), `entrypoint.py` (no server
  flag — only `--server-root`; `--toolset`-style selection is new), `cli.py`, `servers.py`
  (shell pinned + `shell_server_command()` ready, takes no args).
- Agent-facing: the oracle never speaks MCP — the driver serializes ONE flat tool list into
  the prompt (`claude_cli_client.py:492-514`) and routes calls by bare tool name
  (`mcp.py:88-95`). Two servers ⇒ a merged tool list + a name→server router, all behind the
  gated proxy (R6/R7 preserved: every edit crosses the MCP boundary, one call in flight).
- `controls.py:103-148` — the three controls' task text; CTL-2's voiding claim was
  "…**and verified by reading it back**" (model-emitted, `STAGE2_FINDINGS.md:43`).
- Stage registries (`stage4.json` etc.) carry NO server field — server choice is purely the
  driver invocation (freeze scripts, `acceptance-stage{1,2,3}.sh`). No registry change needed.
- `eval/README.md` — runbook: install both pinned servers (gitignored `eval/servers/`),
  macOS TCC neutral-dir rule, shell server `/bin/sh` note; nothing states the mint shell cwd
  today.

## Verdict axes

**A1 only.** The trajectory rule is an instance-level A1 rule (`invariants.py:97`,
`INSTANCE_LEVEL_RULES`); the abstain is an A1 precision fix (never FAIL without evidence
ability; UNVERIFIED-never-PASS preserved; A2/A3 untouched; `verify_turn` per-turn exclusion
unchanged and pinned by test). No agent framework (the oracle stays a no-tools completion
subprocess), no LLM judge (all deterministic vocabulary), no raw-data egress (eval-only +
engine rule; committed artifacts stay ledgers/acceptance outputs).

## Open decisions (this unit's to make — the PRD interview must resolve)

1. **The abstain's scope.** Offered-set = union of tool names across `annotation_snapshot`
   records (if any). Decisions needed:
   - A snapshot **exists** and contains no command tool → abstain, `NO_COMMAND_TOOL_OFFERED`
     (the remint's 5 real traces; the s4/s5 population).
   - **No snapshot at all** (no tools/list captured): cannot know the ability. Options:
     keep the old FAIL (preserves behavior for snapshot-less traces, risks the FP-by-
     construction shape again) vs abstain with a distinct cause (`TOOLSET_UNKNOWN`). Honesty
     contract suggests abstain; the record must note it weakens detection on snapshot-less
     traces. Prefer the honest direction; flag both.
   - Multiple snapshots / `tools/list_changed`: union (a command tool offered at ANY point
     before the claim counts as offered).
2. **The classifier boundary on real text (the named caveat).** "verified by reading it
   back" → VERIFICATION (fires; the voiding CTL-2 claim); "confirmed … by reading the file
   back" → AMBIGUOUS (abstains; 4 real claims). AUDIT.md:63-70 records the gap for this
   unit. Options: (a) keep the vocabulary as-is and treat the abstain-side as correct
   conservatism (abstain is never a false PASS); (b) extend verification vocabulary to
   "confirmed" (more determinability, more FAIL risk on the D-3 tripwire). Lean (a), because
   determinability ≠ correctness and abstain is the safe direction — but the write-control
   path then still fires under a shell-offered mint unless the control is re-scoped (see 3).
3. **Control semantics under the rule (the D-3 tripwire).** With a shell offered, the write
   controls (CTL-2/CTL-3) can still classify VERIFICATION with zero commands → FAIL → mint
   void. The rule's evidence is deliberately loose ("a grep before a claim counts"), so a
   write task that reads back via the **filesystem** tool produces no evidence. Options:
   (a) steer control task text to completion-only reporting ("report that you created the
   file; do not claim verification") so the expected verdict is abstain/clean; (b) add a
   suite-running control whose task REQUIRES `run_process` evidence (expected PASS — the
   trajectory axis's first positive control); (c) accept that write-control FAIL under a
   shell-offered mint is a real rule firing and re-design D-3's control role. The PRD must
   pick the control composition for the next mint and pin expected verdicts.
4. **Shell server cwd.** `run_process` runs in the server's cwd; capture-side spawns pass
   none (driver's launch dir — wrong). Fix: `StdioMcp`/proxy spawn gains `cwd=layout.work_dir`
   (replay already restores cwd=scratch). Confirm no sandbox/Seatbelt interaction (Seatbelt
   profile confines writes to scope; cwd inside scope is fine).
5. **Dual-server routing.** CompositeTransport (two proxied `StdioMcp` sessions, tool-name →
   server map from each server's tools/list, one call in flight across the whole composite —
   R7) vs a merged single stdio front. Composite is the contained choice; the proxy stays
   one-per-server and the gated boundary is preserved per server.
6. **The 5 banked cases.** Migration path: they are local/gitignored (remint worktree) and
   will recompute REGRESSION under the fixed rule. Plan: re-bank with the new expected
   UNVERIFIED status (or migrate to the new-cause fixture set) during this unit, documented
   in the PRD; the audit labels (FP) stay as the human record.

## Contradictions / stale bits flagged (not papered over)

- `belay-worktrees` skill's "greenfield: no pyproject.toml" is stale — v0.16.0 ships
  `pyproject.toml` + 1492+ tests; `uv sync` works.
- `RUNBOOK.md` ledger/case examples were already flagged stale by `phase0-remint`
  (understanding.md:97-98); not this unit's scope unless the walk reaches them.
- The trajectory rule's evidence = *any* replayed exit-0 command (not a suite-name match) —
  documented approximation (`phase0-remint/understanding.md:99-102`); the abstain does not
  change that, only the ability precondition.
