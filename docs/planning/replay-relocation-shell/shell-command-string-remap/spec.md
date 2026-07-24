# Aspect spec — `shell-command-string-remap`

**Parent PRD:** `docs/planning/replay-relocation-shell/prd.md` (must-haves 4, 5, 7)
**Sequencing:** SECOND. Depends on `shell-detect-abstain` (fixture, detector, cause constant).
**The core-engine fix — highest care. The content-corruption trap lives here.**
**Axis:** A2 (result-equivalence + effect-conformance).
**Status:** ✅ BUILT & merged (2026-07-24) — `relocate_command_line` (conservative, abstain-on-
doubt), the `_relocate_frame` / `_relocation_decision` wiring, and the darwin e2e. Full
`command_line` whole-token scope shipped (the Phase-0 spike proved it reliably safe).
**Accepted residual (path-as-data):** a whole-token in-root path used as command *data* (e.g. a
`grep` pattern) is relocated like an address and could make the replayed result diverge — rare,
a divergence at worst (never a corrupting rewrite), documented not silent; substring-fused data
already abstains. See the PRD's Out of Scope / Honesty Property 4.

## Problem slice & outcome

Recover faithful shell coverage: a `run_process` turn whose `command_line`/`argv` embeds an
**in-root absolute path as a whole token** is relocated to the scratch and replays faithfully,
earning a real PASS/FAIL. Anything not provably a clean whole-token path falls back to aspect 1's
**abstain** (UNVERIFIED). No content is ever corrupted.

## In scope

1. **Command-string relocation primitive** in `relocate.py` (pure, no I/O):
   - Tokenize the command with POSIX shell lexing (`/bin/sh` semantics, per `eval/README.md`).
   - A token is remapped **iff its entire value** `is_under` the recorded root (reuse `is_under`).
   - Rewrite is **span-precise on the original string**: locate the exact byte span of each
     whole-token in-root path and replace only those bytes with the scratch-prefixed path.
     **Do not tokenize-and-rejoin** (avoids re-quoting drift); all other bytes — quoting, spacing,
     flags, non-path tokens — are byte-identical.
   - `argv`-list form: same per-element whole-value rule (an element that is a whole in-root path
     → remap; else leave / trigger abstain per below).
2. **Abstain boundary (must-have 5).** Return the aspect-1 cause `EMBEDDED_PATH_UNRELOCATABLE`
   (UNVERIFIED) when any in-root path occurrence is **not** a clean whole token — substring of a
   token (`--file=/root/x`, `/root/x:/y`), inside a quoted blob the lexer keeps as one token, or
   the string is un-lexable. Decided before spawn. Conservative by design; no gate pressure to
   relax it.
3. **Wire into `_relocate_frame`** (`client.py:294-324`): a `run_process` branch that applies the
   command-string primitive to `command_line`/`argv` while preserving the JSON-RPC `id`; a frame
   with nothing to safely relocate is either abstained upstream or returned byte-identical.
4. **Confirm reply comparison needs nothing new:** a `run_process` reply carrying the absolute
   path (plain, and in a diff-header shape) compares equal after the existing
   `canonicalize_reply`/`canonicalize_obj` fold — an assertion test, not new code.

## Out of scope

- Partial-token / substring rewriting inside a command token (→ abstain instead).
- Non-`/bin/sh` shells, `stdin_text`/`timeout_ms` fields (not paths), `cwd` (already handled).
- Any change to capture-side bytes or the A1/A3 axes.

## Acceptance criteria (test-first)

1. **Contamination core (falsifiable):** an abs-path shell capture whose `command_line` embeds the
   workspace path, replayed with the original workspace **pristine / mutated / deleted**, yields
   the **same** verdict — invariant to live workspace state (fixture reply is deterministic so
   this isolates the state variable). *(Darwin-gated e2e.)*
2. **No content corruption:** a `run_process` whose command carries the root as **data** (e.g.
   `echo /root/x > out` where `/root/x` is *content*, or a grep pattern containing the root) is
   **not** rewritten in the content position; the observed delta reflects true content.
3. **No false negative:** a genuinely corrupt shell edit via a **relocatable** whole-token path
   (`sed -i ... tests/foo` with an absolute in-root path) **FAILs** — the write lands in the
   scratch so the delta is real.
4. **No false positive:** a benign correct shell edit via a relocatable whole-token path does
   **not** FLAG.
5. **Whole-token vs substring:** a whole-token in-root path is remapped; an in-root path embedded
   as a token substring → **UNVERIFIED** (`EMBEDDED_PATH_UNRELOCATABLE`), not a partial rewrite
   (unit tests on the primitive).
6. **Byte-precision:** relocating one path token leaves every other byte of the command string
   (quoting, spacing, other tokens) identical (unit test).
7. **`argv` form:** a whole-element in-root path in an `argv` list is remapped; a non-whole element
   abstains — same rule as `command_line`.
8. **Reply comparison unchanged:** a recorded `run_process` reply containing the absolute path
   (plain and diff-header shape) compares equal after relocation with no new normalization code.
9. **No regression:** every existing relocation/relative test stays green, incl. the
   scratch-isolation test.
10. **Determinism:** relocated shell replay is a pure function of (trace, snapshot); no clock,
    network, or ambient FS. Offline/CI-safe; darwin-gate only for real Seatbelt re-invoke.

## Dependencies & sequencing

- **Blocked by** `shell-detect-abstain` (needs the fixture, the detector, and the
  `EMBEDDED_PATH_UNRELOCATABLE` cause). Build second.

## Open questions / risks

- **Lexer fidelity:** `shlex.split(s, posix=True)` vs the server's real `/bin/sh` invocation —
  edge cases (globs, `$VAR`, redirection operators adjacent to a path). Any string the lexer
  can't faithfully round-trip to byte spans → **abstain** (the safe direction).
- **Span location:** mapping a lexer token back to its exact byte offset in the original string
  (shlex discards positions) — may need a position-preserving tokenizer or a careful scan.
  If exact spans can't be recovered for a token → abstain.
- **Realpath/symlink** consistency between recorded root and scratch (same normalization as the
  filesystem case; a miss falls to abstain, not a false verdict).
