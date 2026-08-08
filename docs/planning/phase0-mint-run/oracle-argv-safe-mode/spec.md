# Spec — `oracle-argv-safe-mode`

**Aspect of:** `phase0-mint-run` · **PRD:** `docs/planning/phase0-mint-run/prd.md`
**Date:** 2026-08-09 · **Owner decision (interview):** add `--safe-mode`.

## Problem slice

The mint's oracle argv is part of the frozen invocation, and the unit card requires the two
open questions resolved *before* stage 1. `--safe-mode` is the reproducibility flag P2
identified (`subscription-model-client/prd.md:307`): it isolates the oracle from the
operator's hooks, plugins, and `CLAUDE.md` while leaving OAuth/keychain auth intact — a mint
whose oracle inherits the operator's `CLAUDE.md` is not reproducible on another box
(`prd.md:335-338`). It is absent from code and tests today; nothing in the repo has probed it.

## In scope

1. One paid probe (P2-style, ~$0.5): the full mint argv **plus** `--safe-mode`, from a
   scrubbed env (`env -i HOME PATH USER`), asserting exit 0, `result:"OK"`, `is_error:false`,
   and the API key absent from the child environment. Verbatim output committed.
2. `--safe-mode` added to `ClaudeCliModel._build_command` (`eval/minting_driver/clients/
   claude_cli_client.py:424-452`), in the flag block with the other isolation flags.
3. A criterion-level test asserting `--safe-mode` is present on the constructed argv,
   extended from the criterion-8 isolation assertions in `tests/test_minting_driver_claude_cli.py`;
   `--bare` remains absent.
4. Docs: `eval/README.md` subscription section states the flag and why; the PRD's decision
   table records the closure of OQ2.

## Out of scope

- Any `src/belay/` change.
- Re-probing the other isolation flags (P0–P8 stand; the probe re-checks only the delta).
- Changing `--model` handling, timeout, accounting, or any other criterion.

## Acceptance criteria (test-first)

1. New test (RED first): the constructed argv for `ClaudeCliModel` contains `--safe-mode`
   exactly once, and `--bare` is absent (extend the existing criterion-8 test or add a
   sibling — one flag per assertion, matching the current test granularity).
2. All 20 existing criteria still pass; the suite stays green (`1492 passed` baseline + the
   new test).
3. The probe output is committed verbatim beside the code change, and states the child-env
   key assertion.
4. `eval/README.md` names the flag in the subscription-path argv and its reason.

## Dependencies & sequencing

First aspect in execution order — the frozen stage-1 invocation must name the final argv.
Blocked by nothing; blocks `mint-run`.

## Open questions / risks

- **R-7 residual (named in the parent PRD):** `--safe-mode` semantics could change in a
  future CLI release; the argv assertion catches the flag's disappearance, not a silent
  meaning change. Residual and documented.
- If the probe **fails** (auth broken under `--safe-mode`), the decision flips to
  run-without-and-disclose; the probe evidence is committed either way, and the PRD decision
  table gets a dated correction — never a silent revert.
