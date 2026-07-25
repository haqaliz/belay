# feat/replay-relocation-shell

**Type:** feat · **Owner:** aliz · **Source:** inline brief (no GitHub issue; tracked follow-up)
**Base:** local `master` @ 603c75a (contains `replay-batch-server-rooting`: `{workspace}`
placeholder + `UNROOTABLE_SERVER_COMMAND`/`ROOTLESS_RELOCATION` guards — the foundation this
extends). Note: origin/master (07890e7, v0.4.0) is BEHIND local master; the dependency commits
are unpushed.

## Brief

Extend replay path-relocation to the **shell server** (`mcp-server-commands`), whose
`command_line` / `argv` fields embed the workspace path *inside* command strings — the tracked
follow-up that the shipped filesystem relocation fix (`replay-absolute-path-fidelity`, v0.4.0)
deliberately deferred.

**Why now (moat + gate):** The filesystem relocation fix shipped, but its own spec split shell
out openly (`docs/planning/replay-absolute-path-fidelity/replay-relocation/spec.md:34`): shell
embeds paths inside command strings, so *"the Phase-0 number's shell batch is
known-contaminated, not silently so."* The Phase-0 mint runs a shell batch
(`eval/minting_driver/batch.py:25` — "once per server (filesystem, shell)";
`eval/minting_driver/servers.py:165` `shell_server_command()` takes no root), so shell turns
today replay with their embedded absolute paths pointing at the *original* workspace — a
false-verdict risk (R5, the worst outcome this engine can produce) or an excluded-from-the-number
coverage loss. This is core **A2 replay-moat** work; the parent spec labels it *"The core-engine
fix. Highest care."*

**Axis:** A2 (deterministic replay: result-equivalence + effect-conformance). No A1/A3 change.

## The hard part (caveat — R5)

The filesystem case uses a **whole-value** remap rule: rewrite a string iff its *entire value*
is an absolute path under the recorded root. That rule deliberately **cannot** touch a path
buried inside a shell command string (`python /abs/x.py`), and a naive **substring** remap of a
*mutated* command string reopens the exact content-corruption risk the whole-value rule was
built to avoid (`spec.md:30-38`). Faithful shell replay needs **command-string-aware**
relocation — a distinct, harder design. The guardrail is the parent spec's asymmetry insight:
*arguments* are mutated → remap **conservatively**; *replies* are only compared → normalize
**liberally**. Where a command string can't be safely relocated, the turn must fall to **honest
UNVERIFIED with a named cause — never a false verdict** (UNVERIFIED-never-PASS).

## Acceptance tests (test-first — adapt the parent spec's, shell-specific)

1. **Contamination core (falsifiable):** a shell capture embedding the workspace path in
   `command_line`, replayed with the original workspace **pristine / mutated / deleted**, yields
   the **same** verdict (invariant to live workspace state).
2. **No content corruption:** a command string that legitimately *contains* the path as data is
   not rewritten; the observed delta reflects true content.
3. **`cwd` whole-value already works:** a shell turn addressing files via the clean `cwd` field
   (whole-value path) is relocated correctly today and stays green — this feature is about the
   *embedded-in-command-string* case, not `cwd`.
4. **Honest fallback:** a shell turn that needs relocation but cannot be safely
   command-string-relocated → **UNVERIFIED** with a named cause, never PASS/FAIL.
5. **No regression:** every existing cwd-relative + filesystem-relocation replay test stays
   green (esp. the scratch-copy isolation test).
6. **Determinism:** relocated shell replay is a pure function of (trace, snapshot); no clock, no
   network, no ambient-FS dependence. Offline, CI-safe; darwin-gate only for real Seatbelt replay.

## Key references

- `docs/planning/replay-absolute-path-fidelity/replay-relocation/spec.md` (§ shell-server
  determination, task 1, DONE 2026-07-22 — the schema read + the split rationale)
- `src/belay/replay/engine.py` (`WORKSPACE_PLACEHOLDER`, `UNROOTABLE_SERVER_COMMAND`,
  `ROOTLESS_RELOCATION`, `turn_needs_relocation`, relocation dispatch)
- `mcp-server-commands@0.8.2` `run_process` schema: `command_line` | `argv` (paths embedded),
  optional `cwd` (clean path field), `stdin_text`, `timeout_ms`
- `eval/minting_driver/{batch,servers}.py` (the shell batch that consumes this)
