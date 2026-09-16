# Spec: `reference-author` — the `claude -p` reference author and the live proof

**Parent:** `docs/planning/invariant-authoring/prd.md` (M7)
**Status:** draft, pending review gate

## Problem slice

The protocol is only real if a model can implement it. This aspect ships a
reference author that wraps `claude -p` under the proven BYOK shape, with the
R6/R7 guarantees asserted on the constructed argv **and** env, and it records one
real end-to-end run — manual, never CI — against the committed launch capture.

## In scope

- `src/belay/authoring/reference_author.py`, runnable as
  `python -m belay.authoring.reference_author --model <full-id>`: reads the
  protocol JSON on stdin, builds the prompt, runs `claude -p` with
  `--output-format json --tools "" --strict-mcp-config --safe-mode
  --no-session-persistence --system-prompt <author prompt>` (the proven argv,
  `eval/minting_driver/clients/claude_cli_client.py:422-447`), parses the reply,
  emits the protocol JSON on stdout.
- The injectable `runner=` seam so every test is offline; no `claude` binary in CI.
- Env scrub: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`
  removed **by absence, never `""`**, on a copy — `os.environ` never mutated; no
  key is read or passed.
- Full model id required (never the `opus`/`sonnet` aliases — the D-2 discipline,
  `subscription-model-client/prd.md:350`).
- stdlib only; no SDK import (the SDK-absent import contract pattern).
- The manual live smoke: infer with the reference author on the launch demo's task
  spec, calibrated against the committed launch capture
  (`docs/planning/launch-demo/demo-capture/`, the negative control, 7/7 PASS),
  then verify the capture with the emitted artifact — expect no FAIL. Recorded
  verbatim; read as **"the path works at n=1"**, never a quality claim.

## Out of scope

- Any live-model test in CI; any API key handling; any non-`claude` reference
  author (Ollama / local models are operator-supplied commands through the same
  seam).
- The artifact schema and trust rules (`artifact-trust`); the infer orchestration
  (`authoring-protocol`).

## Acceptance criteria (testable)

1. **No tools, no inherited MCP.** The constructed argv carries `--tools ""` **and**
   `--strict-mcp-config`, asserted separately (R6/R7 by construction); the model id
   is a full id, not an alias.
2. **Env scrub by absence.** The child env is a copy with the three `ANTHROPIC_*`
   variables removed by `pop` (a variable never set stays absent, never `""`);
   `os.environ` is unmutated; no key is read or passed — asserted on the
   constructed env, not only the argv.
3. **Protocol round trip.** Given the protocol JSON on stdin and a fake runner
   returning a canned `claude -p` reply, the author emits protocol JSON on stdout
   that `infer` accepts.
4. **Failure modes are named.** A non-zero child exit or an unparseable model reply
   exits non-zero with a named error; no partial protocol output.
5. **Offline by construction.** Every test runs with the `runner=` seam and no
   subscription; the live smoke is `manual`-marked and never collected in CI.
6. **Live proof (manual, recorded).** One real run on this machine: infer →
   artifact → verify the launch capture → no FAIL; the verbatim output is
   committed as evidence. No claim beyond "the path works at n=1".
7. **Zero new dependencies.** stdlib only; the SDK-absent import contract test
   covers the new module.

## Dependencies and sequencing

Depends on `authoring-protocol` (the protocol shape) and `artifact-trust` (the
emitted schema). Ships after both.

## Open questions

- Wheel placement vs a `scripts/` script: the PRD's open question. Leading
  decision: in the wheel (`src/belay/authoring/`), because a self-hoster installing
  from PyPI cannot reach `eval/`; dark by default.
- Whether the reference author should also accept a system prompt override —
  deferred; the author prompt is a constant for the first slice.