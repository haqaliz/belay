# Aspect spec — `shell-detect-abstain`

**Parent PRD:** `docs/planning/replay-relocation-shell/prd.md` (must-haves 1–3, 6, 7)
**Sequencing:** FIRST. The honesty floor + the keystone fixture that both aspects use.
**Axis:** A2. Strengthens UNVERIFIED-never-PASS.

## Problem slice & outcome

Close the **silent miss**: a `run_process` turn embedding an in-root absolute path in a
`command_line`/`argv` string is currently not detected (`turn_needs_relocation` tests whole-value
only) → replayed un-relocated against the original workspace → contaminated verdict. This aspect
makes such a turn **detected and, absent relocation, honestly UNVERIFIED** with a named cause —
before any spawn. No false verdict, no silent miss. (Actual relocation is aspect 2; until it
lands, every detected shell turn abstains.)

## In scope

1. **Keystone fixture — a `run_process` shell server** at `tests/fixtures/` (none exists).
   - Mirrors `tests/fixtures/abs_path_editor_server.py` structure/conventions.
   - One `run_process` tool accepting `command_line` (string, path embedded), `argv` (list), and
     `cwd` (whole-value path); **deterministic** reply that carries the path (isolates the
     workspace-state variable). No annotations (matches the real server, `eval/README.md`).
2. **Field-shaped detection of executed-command paths.** `command_embeds_in_root_path` recognizes
   an in-root path embedded in the shell server's **executed-command fields** — `command_line`
   (string) and `argv` (an element embedding a path that is not itself whole-value). It does NOT
   inspect inert content fields or whole-value paths (those are already correct). **As-built note
   (`1f44cf2`):** the earlier "substring anywhere, server-agnostic" form (PRD Gap 2) was built and
   reverted because it regressed the filesystem content-mention case; the executed-command danger
   is inherently field-shaped. The whole-value `cwd` field continues to be handled by the existing
   rule — this branch is only for the embedded-in-command case.
3. **New named cause** `SHELL_COMMAND_UNRELOCATABLE` — sibling constant in `engine.py` near
   `:101-114`, exported in `__all__` (`:574-578`), with a stable short bucket label in
   `report.py` `_PREFIX_LABELS` (`:92-98`).
4. **Route detected shell turns to abstain** in `_relocation_decision` (`engine.py:290-324`):
   with a recorded `source_root` and a detected embedded in-root path, return
   `(None, SHELL_COMMAND_UNRELOCATABLE)` **until aspect 2 provides relocation**. Decided before
   restore/spawn.
5. **Gate-wiring correctness (must-have 6).** The shell server has no argv root token; ensure the
   detected shell turn does **not** wrongly hit `UNROOTABLE_SERVER_COMMAND` (which keys on an
   argv token). Gating is on manifest root + embedded path.

## Out of scope

- Any actual rewriting of the command string (that is aspect 2 — this aspect always abstains for
  the embedded case).
- The `cwd` whole-value path (already handled).
- Reply normalization (already substring-folds; a confirmation test may live here or aspect 2).

## Acceptance criteria (test-first)

1. **Detection fires:** a `run_process` turn with `command_line` embedding an in-root absolute
   path is detected as needing relocation (unit test on the detector).
2. **Honest abstain, not silent miss:** with a recorded root, that turn yields **UNVERIFIED** with
   cause `SHELL_COMMAND_UNRELOCATABLE` — asserted at the `_relocation_decision` / replay level,
   decided before spawn. Never PASS/FAIL.
3. **No UNROOTABLE misfire:** the root-less shell server command does **not** produce
   `UNROOTABLE_SERVER_COMMAND` for a shell turn gated on the manifest root (wiring test).
4. **`cwd`-only turn untouched:** a `run_process` turn addressing files via the whole-value `cwd`
   field (no embedded path) is handled by the existing rule and is **not** forced to abstain.
5. **Report bucket:** `SHELL_COMMAND_UNRELOCATABLE` maps to a stable bucket label in the Phase-0
   report (unit test on `report.py`).
6. **No regression:** all existing relocate/relocation tests stay green.
7. **Determinism / offline:** unit + wiring tests are pure; any real-Seatbelt e2e is darwin-gated
   (`darwin_only`), matching `tests/test_replay_relocation_e2e.py` conventions.

## Dependencies & sequencing

- Depends on the shipped `replay-absolute-path-fidelity` + `replay-batch-server-rooting` (present
  on the base branch). **Blocks** `shell-command-string-remap` (aspect 2 builds on the fixture,
  the detector, and the cause constant).

## Open questions / risks

- Where the tool-name-aware detector branch lives cleanly (in `relocate.py` with the tool name
  passed in, vs a thin `engine.py` pre-check) — a plan decision; keep `relocate.py` pure.
- The fixture must be deterministic and self-tested (add a `tests/test_*_fixture` guard mirroring
  `tests/test_abs_path_fixture.py`).
