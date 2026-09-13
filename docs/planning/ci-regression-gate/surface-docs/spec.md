# Aspect: surface-docs

## Problem slice

A capability a stranger cannot discover or wire into CI does not serve the Phase-2 metric
(≥40% of active teams wire the regression gate). The engine slice needs a minimal,
machine-checked surface: docs, help text, and the parity guard — no UI, no Action.

## User outcome

A self-hoster reads the README section, copies the CI snippet, sets `BELAY_RUN_ID`, banks a
baseline, and has a working gate in their pipeline — with the honest coverage statement
(the gate checks what crosses the MCP boundary; UNVERIFIED is never PASS).

## In scope

- README section: quickstart for the gate (bank → check), a CI YAML snippet (capture step +
  `belay gate check`), the exit-code table (0/1/2), the baseline-location/gitignore note,
  and the substrate recommendation (bank on the CI substrate).
- `--help` text for `gate baseline` / `gate check`; the coverage line on both surfaces.
- `docs/technical/TRACE_FORMAT.md` `run_identity` kind (owned by `run-identity`, referenced).
- Flag-parity declarations in `tests/test_cli_flag_parity.py` (owned by `gate-check`,
  verified here end-to-end).
- Docs tests (`tests/test_quickstart_docs.py` pattern) machine-check the README claims:
  commands exist, flags exist, exit codes documented match the implementation.
- No published number moves; no claim beyond the MCP boundary.

## Out of scope

- GitHub Action / CI templates beyond a README snippet.
- Console/compose wiring; live console changes.
- THREAT_MODEL changes (no new boundary; the gate runs the existing sandbox/replay).
- Marketing copy or launch assets.

## Acceptance criteria (written first)

1. The README quickstart commands are executable as written and covered by a docs test
   (command + flag existence; the snippet's commands parse).
2. Exit-code documentation matches the implementation (0/1/2) — asserted by test.
3. The coverage line appears on both gate surfaces (text and `--json`).
4. Flag-parity suite green with the new surface declared; no undeclared shared flag.
5. No published-number line changed anywhere (grep-style guard or docs test).

## Dependencies & sequencing

Last aspect; depends on `gate-check` and `divergence-banking` being implemented (docs must
describe shipped behavior, never planned behavior).

## Open questions

- Whether the snippet targets GitHub Actions only or stays CI-agnostic prose plus one
  GitHub example. Default: CI-agnostic prose + one GitHub Actions example.
