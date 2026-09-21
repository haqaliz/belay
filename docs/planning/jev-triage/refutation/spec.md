# Spec — aspect `refutation`

**Problem slice:** the guarantees, pinned by tests — the same shape as the
`--no-claim-axis` refutation (`tests/test_refutation_no_claim_axis.py`).

**In scope**
- **Identity:** triage on vs off ⇒ identical verdicts on the turns replayed — PASS/FAIL
  byte-identical on the committed demo capture through the real CLI, exit codes agree,
  plus an anti-vacuity spy proving the on-side really consulted triage and the off-side
  never did.
- **Absent ⇒ no-op:** no flag and no env ⇒ no subprocess, no network — asserted on the
  constructed request/env (scrubbed by absence, never `""`).
- **Whitelist:** the constructed payload assertion (the honest-line pair for egress).
- **Manual live test:** `manual`-marked, owner-run, darwin-gated: the Jev reference
  author against the real REST endpoint with the owner's `BELAY_JEV_KEY` (local test
  only, never for users, never committed); FAIL-with-instructions when the env is unset
  (`test_reference_claim_author_live.py:118-125` shape); prints the exact command, model
  id, wall clock, and outcome for the record.

**Out of scope:** the calibration ledger; any promotion of triage to a verdict.

**Acceptance (test-first)**
- Identity test (above) — must never be weakened; the test's docstring states the rule.
- Absent-key no-op test (above).
- Payload whitelist assertion (above).
- Live test is `manual`-marked and excluded from CI (`addopts -m 'not manual'`).

**Dependencies:** all four prior aspects. **Sequencing:** last — it pins the whole.

**Open questions:** none blocking.