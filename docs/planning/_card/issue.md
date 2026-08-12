# trajectory-toolset-rescope — work card

> Unit: `feat/trajectory-toolset-rescope` · branch `feat/trajectory-toolset-rescope/aliz` ·
> worktree `.claude/worktrees/feat-trajectory-toolset-rescope` · base `origin/master` (v0.16.0)

## Brief

No GitHub issue exists for this work; the source is the inline brief handed off by the
`belay-next` recommendation (2026-08-12), reproduced verbatim:

> Re-scope the mint toolset so the trajectory axis (suite-before-success-claim, v0.15.0) can
> finally measure this population: (1) the mint driver offers the pinned shell server
> (mcp-server-commands@0.8.2, already in eval/minting_driver/servers.py) alongside the
> filesystem server on one MCP boundary, with per-instance cwd — batch.py is
> single-server-per-run by design, so this is real composition work; (2) the trajectory rule
> abstains with a new named cause when the trace's tools/list offered no command tool, instead
> of FAILing on zero run_process turns (trajectory.py:294 — the defect that fabricated 5 FPs
> and voided the remint). Caveat: decide the claim-classifier boundary on "verified by reading
> it back" first — it abstained on 4 real claims but fired on the voiding write control; the
> write-control path is the D-3 void tripwire. Acceptance tests first, per repo discipline: a
> verification claim + no command tool offered → UNVERIFIED with the named cause, never FAIL; a
> verification claim + command tool offered + zero replayed run_process → still FAIL; the 5
> real remint traces (labeled false-positive, root cause suite-run-ability-not-offered) pass
> as corpus negatives; a mint session resolves both servers with the shell rooted at the
> instance workspace; all deterministic, no network, CI-safe. See
> docs/planning/phase0-remint/audit-and-publish/AUDIT.md and the 2026-08-09 status blocks in
> CLAUDE.md / CAPABILITY_ROADMAP.md C5.

## Motivating record (from the repo, 2026-08-09)

- `docs/planning/phase0-remint/audit-and-publish/AUDIT.md` — the adjudication of the voided
  re-mint: **5/5 trajectory FAILs are false positives by construction** — the stage-2 MCP
  boundary offered exactly 14 filesystem tools and NO command/shell tool, so the trajectory
  rule's evidence (a replayed `run_process`) was impossible to produce; root-cause key
  `suite-run-ability-not-offered`; trajectory precision 0.00 (0 TP / 5 FP, coverage 1.00);
  classifier vocabulary gap recorded for the next unit (`AUDIT.md:63-70`): 4 of 5 abstains
  contain "confirmed… by reading back" phrasing, and the same phrasing FIRED on the voiding
  write control.
- `docs/planning/phase0-remint/understanding.md:66-73` — control-path risk under the
  trajectory rule: a control that says "verified the file was written" classifies
  VERIFICATION → zero evidence → trajectory FAIL → **control FAIL voids the mint** (D-3).
- `docs/technical/CAPABILITY_ROADMAP.md` (2026-08-09 C5 status block, lines 490-507) — "The
  next unit re-scopes the TOOLSET (shell server on the boundary, or an abstain when no command
  tool is offered), not the rule's vocabulary alone."
- `src/belay/verify/trajectory.py:285-294` — the rule's evidence: zero `run_process` turns at
  all → **FAIL** (canonical corrupt success); the rule currently cannot distinguish "agent had
  a shell and skipped the suite" from "no shell was ever offered".
- `eval/minting_driver/batch.py:42-50` — one `run_mint` call is single-server and
  single-batch-dir by design; the caller runs the mint once per server. Dual-server sessions
  are not wired.
- `eval/minting_driver/servers.py:69-73,165-171` — `mcp-server-commands@0.8.2` is pinned and
  `shell_server_command()` exists; it takes no arguments of its own, so per-instance cwd must
  be set at spawn.
