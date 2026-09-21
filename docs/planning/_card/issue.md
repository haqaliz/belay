# C10 first slice — the calibrated-triage seam (shadow mode)

> Inline brief (no GitHub issue). Source: belay-next handoff (2026-09-21) + owner additions (same day).

## Brief

C10 first slice: the calibrated-triage seam, shadow mode (owner demand-pull 2026-09-19).
A cheap calibrated decision model (Jev — TypeSafe's "System One") orders and samples the
replay queue behind a budget knob; execution alone decides every verdict. Triage is a
router, never a verdict.

The PRD for the full capability lives on the local branch `proposal/jev-triage`
(previously `feat/jev-triage`, renamed to free the ref namespace) at
`docs/planning/jev-triage/PRD.md`; port it into this worktree before planning.

## Guardrails (from the handoff)

- `BELAY_JEV_KEY` opt-in only; absent key ⇒ triage is a no-op with no network call
  (asserted on the constructed request/env, scrubbed by absence, never `""`).
- Egress limited to whitelisted derived features — never raw state or trace bytes
  (asserted on the constructed payload).
- A skipped turn is UNVERIFIED-by-budget, named, never PASS.
- Triage on vs off ⇒ identical verdicts on the turns replayed — the
  `--no-claim-axis`-style refutation, never weakened.

## Acceptance tests (written first; repo is test-first)

1. Triage on vs off ⇒ identical verdicts on the turns replayed.
2. Absent key ⇒ no-op, no network call.
3. Payload carries only whitelisted derived features.
4. Model stubbed — deterministic, no network in CI; live call `manual`-marked and owner-run.

## Owner additions (PS, 2026-09-21)

1. **BYOK local test key:** the owner can supply an API key for *local manual testing only*
   — it is never for users; users always provide their own key.
2. **Model-agnostic seam (laya):** there is a second model, **laya**
   (https://huggingface.co/convaiinnovations/laya), and the design must let users connect
   any triage model (jev, laya, …) later. The seam must be **provider-neutral** — not a
   Jev-specific implementation baked into the engine. This is a requirements change to the
   proposed PRD, which is Jev-named throughout.

## Caveat (recorded, do not paper over)

This slice is shadow mode: it banks no calibration ledger and saves no cost yet. The
ledger half is downstream of the owner declaring the second corpus-mint run (S-1) — do
not build it against a 100%-UNVERIFIED column.