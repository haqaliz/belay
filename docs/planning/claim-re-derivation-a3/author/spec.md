# Spec — author (out-of-process BYOK check author)

> Part of `claim-re-derivation-a3` (C8). PRD: `../prd.md`. Decision D2 confirmed 2026-09-02:
> protocol + out-of-process BYOK; zero runtime deps preserved (`pyproject.toml:44`).

## Problem slice

The model-backed check author, behind the `CheckAuthor` seam: an adapter that turns the agent's
claim (plus trace facts) into an executable check. **Nothing leaves the box; no vendor key;
nothing proxied** (`CLAUDE.md` guardrails, `CAPABILITY_ROADMAP.md:790`).

## In-scope

- `src/belay/verify/author.py` — a `CheckAuthor` implementation that shells out to a user-supplied
  command (subprocess):
  - Contract: Belay writes a JSON prompt to the command's stdin (claim text, classification,
    tool-call facts, final-state file list); the command writes JSON to stdout:
    `{"source": <the check, verbatim>, "argv": <how to run it>}` or
    `{"error": <reason>}` → `NO_CHECK_AUTHOR` (UNVERIFIED).
  - Configuration: env var `BELAY_CLAIM_AUTHOR` (a command line, shlex-split) and/or a
    `--claim-author CMD` flag on the surfaces (mirrors `--shell-server`/`--server` shape;
    decide exact flag at plan time). Unset → the evaluator treats the axis as absent.
  - The reference implementation ships no model client: the user's command is whatever local
    model CLI / script they point at (claude CLI, ollama, their own script). The adapter is
    BYOK by construction.
- A `manual`-marked test for the live path (never CI — acceptance 5,
  `CAPABILITY_ROADMAP.md:801-802`), plus a deterministic fake-author test that round-trips the
  stdin/stdout contract (the fake runs in CI).
- Author **timeout** (bounded; default per plan) → `NO_CHECK_AUTHOR` (UNVERIFIED), never a hang.

## Out-of-scope

- Any model SDK dependency (wheel stays zero-dep); any network egress; the check grammar
  (v0 = executable artifact with declared argv; PRD Out of Scope).

## Acceptance criteria (test-first)

1. A fake author command round-trips: stdin JSON parsed, stdout JSON honored, check executed.
2. Author command exits non-zero / malformed stdout / timeout → UNVERIFIED `NO_CHECK_AUTHOR`.
3. `BELAY_CLAIM_AUTHOR` unset → evaluator returns **absent** (None), never UNVERIFIED, never PASS.
4. The seam test asserts no model import exists anywhere in `src/belay/verify/` (zero-LLM guard
   updated deliberately — `tests/test_verify_zero_llm.py:124-153`).
5. Live-path test is `manual`-marked and skipped by default CI (`pyproject.toml` addopts).

## Dependencies

- Aspect `evaluator` (the `CheckAuthor` Protocol).
- C1–C6.

## Open questions

- Flag vs env only: recommend env var `BELAY_CLAIM_AUTHOR` for `phase0 run`/`corpus run` +
  a `--claim-author` flag on `belay verify` (the interactive surface). Decide at plan time.
- Default author: none. The axis stays absent until the user configures one — the honest
  default (no silent half-configured axis).