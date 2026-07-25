# Understanding — `replay-relocation-shell`

**Date:** 2026-07-24 · **Owner:** aliz · **Axis:** A2 (deterministic replay). No A1/A3 change.
**Base:** local `master` @ 603c75a (has `replay-batch-server-rooting`; unpushed to origin).
**Inputs:** `docs/planning/_card/issue.md`, the parent `replay-absolute-path-fidelity/` PRD +
`replay-relocation/spec.md`, and a full code map (below, all cited).

## What the work is really asking

The shipped filesystem relocation fix made replay faithful for servers that pass an absolute
path as a **whole-value** argument (`{"path": "/root/x"}`). The **shell server**
(`mcp-server-commands`, tool `run_process`) is different: it embeds the workspace path *inside*
a command string — `command_line: "python /root/x.py"` or an `argv` list element. The
whole-value remap rule deliberately cannot touch that, so shell turns are the tracked follow-up.

## The exact current-state defect (confirmed by code map)

1. **Detection misses it.** `turn_needs_relocation` (`src/belay/replay/relocate.py:192-202`)
   tests only **whole-value** strings via `_contains_in_root_string` (`relocate.py:205-213`):
   `is_under("python /root/x.py", root)` normpaths the *entire* string, which is not under the
   root → returns **False**. So a `run_process` turn embedding an in-root path is **not
   detected**.
2. **Therefore it is not even abstained.** Because detection returns False, `_relocation_decision`
   (`src/belay/replay/engine.py:290-324`) sees "no relocation needed" and proceeds to replay
   **without** relocation and **without** UNVERIFIED. The `UNROOTABLE_SERVER_COMMAND` guard never
   fires for shell (it is reached only when a turn *is* detected as needing relocation).
3. **The replay is then contaminated (R5).** Replay sets `cwd=scratch` but the embedded command
   still contains the **original** absolute path. So the command reads/writes the *original*
   workspace: a corrupt write is either sandbox-denied (scratch is the write-root) → empty
   scratch delta → **effect PASS (false negative)**, or a read leaks live state → **false
   positive**. Same two directions the filesystem fix closed — but for shell, **silently**.
   This is exactly what `replay-relocation/spec.md:34` means by *"known-contaminated, not
   silently so"* at the doc level; at the verdict level it is silent today.

**Note (already handled, do not rebuild):** a shell turn addressing files via the clean
whole-value **`cwd`** field + relative paths trips the existing whole-value rule and relocates
correctly today. This feature is only about the **embedded-in-command-string** case. And reply
comparison already substring-folds both roots (`canonicalize_reply`/`canonicalize_obj`,
`relocate.py:146-189`), so shell replies with embedded paths compare correctly with **no
change** — confirm, don't rebuild.

## The design fork (the central PRD decision)

For a `run_process` turn carrying an in-root absolute path embedded in `command_line`/`argv`:

- **Option A — detect + honest abstain (UNVERIFIED).** Add a shell-aware detector; when an
  embedded in-root path is present, return a new named cause (e.g. `SHELL_COMMAND_UNRELOCATABLE`)
  → the turn is **UNVERIFIED**, never a false verdict. *Closes the silent-contamination hole
  (R5) with minimal risk. Does not recover coverage — shell turns become UNVERIFIED, not
  PASS/FAIL.* Low risk; squarely honest.
- **Option B — command-string-aware relocation.** Tokenize the command string, rewrite only
  **whole-token** in-root paths → scratch (preserving quoting and never touching non-path
  content), so the shell turn replays faithfully and earns a real PASS/FAIL. *Recovers coverage;
  higher risk — this is the content-corruption trap the parent spec split out
  (`spec.md:30-38`).* The guardrail is the spec's asymmetry: arguments remap **conservatively**,
  replies normalize **liberally**; anything the tokenizer can't prove safe falls to Option A's
  abstain, never a guess.

**My read:** Option A is the **non-negotiable floor** — it converts a silent false verdict into
an honest UNVERIFIED and is worth shipping alone. Option B is the value-add (recovers shell
turns for the Phase-0 number). Whether to build B now or defer it as a second unit is the main
question for the interview. Note the mint's *violations* are filesystem edits, so the number can
likely stand on the filesystem batch with shell turns honestly UNVERIFIED — which argues A-first.

## Affected areas / seams (from the map)

- `src/belay/replay/relocate.py` — new command-string primitive + shell-aware detector branch in
  `turn_needs_relocation`/`_contains_in_root_string`.
- `src/belay/replay/client.py:294-324` (`_relocate_frame`) — the only place `arguments` are
  rewritten before re-send; needs a `run_process` branch (relocate-or-abstain).
- `src/belay/replay/engine.py:290-324` (`_relocation_decision`) + a new named-cause constant near
  `:101-114`, exported in `__all__` (`:574-578`); the tool name is available in `replay_turn`.
- `src/belay/replay/report.py:92-98` (`_PREFIX_LABELS`) — a stable Phase-0 bucket for the new cause.
- **New fixture (keystone): a `run_process` shell server** under `tests/fixtures/` — none exists;
  mirror `tests/fixtures/abs_path_editor_server.py` with a `command_line`/`argv`/`cwd` tool and a
  path-carrying reply.
- Tests: unit (`tests/test_replay_relocate.py`), wiring (`tests/test_replay_relocation_wiring.py`),
  darwin-gated e2e (mirror `tests/test_replay_relocation_e2e.py`).

## Ambiguities / open questions (for the interview)

1. **A-only, or A+B?** (the fork above). If B: is a shell command tokenizer (shlex-style) in
   scope, and what is the exact "cannot prove safe → abstain" boundary?
2. **What makes a shell turn "rooted"?** The shell server passes **no argv root token**
   (`eval/minting_driver/servers.py:165-171`), so relocation must be gated on the manifest
   `source_root` + an embedded in-root path — *not* on an argv token. The existing
   `UNROOTABLE_SERVER_COMMAND` logic keys on an argv token and must not misfire here.
3. **`argv` vs `command_line`.** `run_process` accepts both; `argv` elements can be whole-token
   paths (closer to the filesystem case) while `command_line` is one string. Treat them the same
   (per-token) or differently?
4. **Does the mint actually need shell coverage for the number,** or is honest-UNVERIFIED-for-shell
   acceptable at the gate? (Decides whether B is gate-blocking or a nice-to-have.)

## Guardrail check (CLAUDE.md)

Pure hardening of the A2 replay moat — no agent framework, no LLM judge, no raw-data egress.
Strengthens UNVERIFIED-never-PASS (the abstain path). On-moat, on-thesis.
