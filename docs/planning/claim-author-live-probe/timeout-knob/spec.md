# Aspect spec: timeout-knob (GATED — ships only on probe evidence)

**Source:** `docs/planning/claim-author-live-probe/prd.md` (requirements K1–K5, OQ-2/OQ-3).
**Status: LOCKED BY DEFAULT.** This aspect's execution is gated on the probe's evidence:
it starts only if the probe's findings record ≥1 `AUTHOR_TIMED_OUT` observation. Until
then it is planned, not implemented. This spec exists so the evidence decision has a
ready-made, already-planned shape.

## Problem slice

If (and only if) the probe shows the engine's 60 s `AUTHOR_TIMEOUT` killing a
still-working author, operators need a bound they can raise. The reference author's own
600 s child bound must become reachable through the engine. Default unchanged (60 s);
opt-in only. Owner decision 2026-10-10: keep the default; `BELAY_CLAIM_AUTHOR_TIMEOUT`
env + `--author-timeout` flag on the three author-constructing surfaces; flag name
`--author-timeout`; knob triggers only on an actual kill (near-break headroom is recorded
in the findings but does not trigger).

## In-scope requirements

- K1 — `BELAY_CLAIM_AUTHOR_TIMEOUT` env (read where `author_from_env` runs) +
  `--author-timeout SECONDS` flag on `verify`, `gate baseline`, `gate check` (the
  `--claim-author` surface set). `phase0 run` reaches it via env only (its flag absence is
  pinned); `corpus run` gets nothing (it never constructs an external author).
- K2 — Fail-closed parsing: absent/blank/un-lexable/≤0 ⇒ default 60.0; the def-time
  default-arg trap is respected (`author_from_env` must build `SubprocessAuthor(cmd,
  timeout=<resolved>)`, never rely on a post-import monkeypatch).
- K3 — Flag-parity guard: new `--author-timeout` row in `EXPECTED`
  (`tests/test_cli_flag_parity.py`).
- K4 — Boundedness preserved: past the (raised) bound the abstention is byte-identical
  `AUTHOR_TIMED_OUT`/`NO_CHECK_AUTHOR`; tests use small timeouts with sleeps, no timing
  assertions; `test_verify_author.py:121`'s pin (`configured.timeout == AUTHOR_TIMEOUT`)
  survives (default unchanged).
- K5 — Docs: README claim-author section gains the knob lines; STATUS/C8 "as built"
  addendum states the default is unchanged.

## Out-of-scope boundaries

No default change; no `phase0 run`/`corpus run` flags (pinned); no `TRIAGE_TIMEOUT`
change; no `CHECK_TIMEOUT` (check-execution) change; no `authoring/protocol.py`
(invariant-authoring) copy; no verdict/status/reduction/gate/number moves.

## Acceptance criteria

1. RED first: a test asserting an operator-raised bound lets a slowly-sleeping stub author
   complete (small values, e.g. sleep 0.5 s, timeout 2.0 s — no timing assertions on the
   elapsed wall).
2. Env-only, flag-only, and both-set precedence behave as specified; blank/≤0/env-absent
   fall back to the shipped 60.0 default.
3. A stub that outlasts the *resolved* bound still abstains `AUTHOR_TIMED_OUT` with the
   byte-identical detail string.
4. Flag-parity discovery test passes with the declared row; the `--claim-author` row is
   untouched.
5. README + STATUS/C8 addenda committed in the same PR as the code.

## Dependencies & sequencing

Gated on `probe`'s `FINDINGS.md` (≥1 `AUTHOR_TIMED_OUT`). If the evidence reads
otherwise, this aspect stays unbuilt and the knob decision is recorded as declined in the
findings.

## Open questions / risks

- Flag name: `--author-timeout` (decided 2026-10-10) — final if `--claim-author-timeout`
  reads clearer at the review gate, the PRD's OQ-2 is resolved the same way.
- Env applicability to `phase0 run` is by construction (env-only author path) — no new
  phase0 surface is created.