# Aspect spec — `replay-relocation`

**Parent PRD:** `docs/planning/replay-absolute-path-fidelity/prd.md` (must-haves 2–6)
**Sequencing:** SECOND. Depends on `record-workspace-root` (needs the recorded root).
**The core-engine fix. Highest care — this is the A2 replay moat.**

## Problem slice

With the original root now recorded, make replay **faithful for absolute-path servers** by
relocating the recorded root → the scratch restore, additively and gated. Fix both failure
directions the dig confirmed: false-positive reads (leak to live state) and false-negative
writes (denied → empty delta → effect PASS).

## Shell-server determination (task 1, DONE 2026-07-22)

Read `mcp-server-commands@0.8.2`'s `run_process` schema (`build/tools.js:20-50`): it takes
`command_line` **or** `argv` (the command — paths appear **embedded inside** these strings),
plus an optional `cwd` (a clean path field), `stdin_text`, `timeout_ms`.

**Conclusion: the shell server is a DISTINCT, harder problem → filesystem fixed here, shell
is a follow-up unit** (stated openly per the PRD rule). Reasoning, which also **sharpens the
filesystem rule**:

- The safe, content-preserving, server-agnostic rule for **mutated arguments** is:
  **remap a string iff its *entire value* is an absolute path under the recorded root.**
  This covers the filesystem `path` field and the shell `cwd` field; it **never** touches
  `content`/`newText`/`oldText` (file content that may legitimately contain the path) — those
  aren't whole-value paths. Content is preserved by construction, satisfying the PRD's locked
  content boundary without any per-tool field registry.
- The shell's `command_line`/`argv` embed paths **inside** a command string (`python
  /abs/x.py`). The whole-value rule deliberately won't touch them, and a *substring* remap of
  a mutated command string reopens the content-corruption risk. Faithful shell replay
  therefore needs command-string-aware relocation — a separate, harder design. Out of scope
  here; filed as `replay-relocation-shell` follow-up so the Phase-0 number's shell batch is
  known-contaminated, not silently so.
- **Asymmetry (the key insight):** *arguments* are mutated → remap **conservatively**
  (whole-value path only). *Replies* are only compared → normalize **liberally** (substring
  anywhere, e.g. diff `Index:` lines) because it's transient and can't corrupt anything.

## In scope

1. **A committed absolute-path fixture server** — takes an absolute root arg and addresses
   files by **absolute path** (the inverse of every existing cwd-relative fixture). Supports
   a read and an edit tool with **deterministic** replies (pin any timestamp/ordering) so
   tests isolate the workspace-state variable. This closes the gap that let the bug survive.
2. **Gated relocation**, active only when a root is recorded **and** a replayed `tools/call`
   carries absolute paths under that root:
   a. **Argv root-token rewrite** — before spawn (`client.py:322`), replace an argv token
      that *is* or is *under* the recorded root with the scratch root
      (`spawn.scope.snapshot_root`). Only in-root tokens; never arbitrary args.
   b. **`arguments` whole-value path remap** — recursively over the frame's `arguments`
      string values, swap the recorded-root prefix → scratch prefix **only for a string whose
      *entire value* is an absolute path under the recorded root** (the sharpened rule from
      the shell determination). This covers filesystem `path` (and shell `cwd`) and **never**
      touches `content`/`newText`/`oldText`, which are file content — content is preserved by
      construction, no per-tool field registry. Re-serialize the frame preserving the
      JSON-RPC `id`.
   c. **Reply comparison normalization** — inside `result_equivalence` (`engine.py:375`),
      canonicalize the recorded reply (original paths) and the replayed reply (scratch
      paths) to the same form by substituting **both** roots (as substrings, anywhere they
      appear — diff headers, `file://` URLs, nested JSON) with a placeholder. **Comparison-
      only**: transient, never persisted, never written to the scratch.
3. **Prefix rule:** remap iff a string's realpath'd form has the recorded root as a path
   prefix. Out-of-root absolute paths (`/etc/...`, libs) are left unmapped.
4. **Honest fallback:** a turn that *needs* relocation (in-root absolute paths present) but
   whose manifest has **no** recorded root → **`UNVERIFIED`**, named cause
   `original workspace root not recorded; cannot relocate absolute paths`. Never a false
   verdict. A cwd-relative turn (no in-root absolute paths) is untouched.
5. **Content boundary (locked):** rewrite **only** the argv root token and `arguments` path
   fields; reply substitution is comparison-only. A file that legitimately *contains* the
   path, and content bytes in the scratch, are never altered — the delta sees real content.

## Out of scope

- **Shell server (`run_process`)** unless the plan's task 1 shows the same prefix-remap
  trivially covers it. If distinct, it's a follow-up unit (stated openly).
- General path virtualization / VFS; bind-mounts/symlinks; argv-token root inference for
  rootless traces (all rejected in the PRD).
- A1 / A3; the capture-side byte-pump (untouched — relocation is replay-only).

## Acceptance criteria (test-first)

1. **Contamination (the falsifiable core):** an abs-path-server capture replayed with the
   original workspace **pristine**, **mutated**, and **deleted** yields the **same** verdict
   — invariant to *live workspace state* (not "byte-identical replies"; the fixture reply is
   deterministic so this isolates the state variable).
2. **No false positive:** a benign correct edit via the abs-path server does **not** FLAG.
3. **No false negative:** a genuinely corrupt edit via the abs-path server **does** FAIL —
   the write must land in the relocated scratch so the delta is real.
4. **Diff-reply normalization:** a recorded reply that is a unified **diff** containing the
   absolute path (the Stage-1 `edit_file` shape) compares equal after relocation — no false
   positive from a path buried in an `Index:`/`---`/`+++` line.
5. **Out-of-root untouched:** a turn reading `/etc/hosts` (or any out-of-root abs path) is
   not remapped and behaves as today.
6. **Honest fallback:** a rootless manifest + an in-root absolute path → `UNVERIFIED` with
   the named cause; never PASS/FAIL.
7. **Content not corrupted:** an edit that writes the literal workspace path into a file
   replays without the content being rewritten; the delta reflects the true content.
8. **No regression:** every existing cwd-relative fixture/replay test stays green —
   especially `test_replay_runs_against_a_scratch_copy_and_leaves_the_original_untouched`.
9. **Determinism:** relocated replay is a pure function of (trace, snapshot); no clock, no
   network, no dependence on ambient FS.

All deterministic, offline, CI-safe. Darwin-gate only where real Seatbelt replay is needed,
matching existing replay-test conventions.

## Dependencies

- `record-workspace-root` (the recorded root). Hard blocker.
- Existing: `src/belay/replay/{client,engine}.py`, `src/belay/sandbox/{launch,scope}.py`,
  the replay fixtures.

## Open questions / risks

- **Task 1 = the shell-server determination** (per PRD) — do before building must-have 2.
- **Reply canonicalization symmetry** — substituting both roots to one placeholder must be
  order-independent and must not collide (e.g. if scratch path contains the original root as
  a substring — it won't, they're disjoint mkdtemp/workspace paths, but assert it).
- **Frame re-serialization vs id-correlation** — the relocated frame must keep `_await_key`/
  `_matches` working; test a relocated frame's id round-trip explicitly.
- **Realpath consistency** — recorded root and scratch root must be normalized identically or
  the prefix match misses (→ falls to honest UNVERIFIED, not a false verdict, but still a
  coverage loss). Test a symlinked root.
