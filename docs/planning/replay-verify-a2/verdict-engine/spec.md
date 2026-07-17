# Aspect spec — `verdict-engine`

**Feature:** `replay-verify-a2` (C4) · **PRD:** [`../prd.md`](../prd.md)
**Scope:** M1–M8, S1–S3. One aspect — the Verdict model, its two checks, the reduction, and the CLI
are one coherent thing, and C4 is not cuttable.

## Problem slice

Belay replays (C3) but renders no verdict. C4 turns per-turn replay observations into a grounded
A2 verdict — result-equivalence (gated on determinism) and effect-conformance (delta vs the tri-state
annotation) — reduced worst-wins so UNVERIFIED is never PASS. **Zero LLM.**

**Outcome:** `belay verify <trace>` emits, per turn, PASS / FAIL / UNVERIFIED with concrete grounding
(the recorded-vs-observed diff, or the annotation + observed write), and an aggregate FAIL list. A2's
PASS means "the trace reproduces", never "the agent was correct".

## In scope
M1 Verdict model (PASS/WARN/FAIL/UNVERIFIED) · M2 worst-wins reduction, UNVERIFIED>PASS structural ·
M3 result-equivalence gated on determinism · M4 effect-conformance (per-turn annotation correlation +
readOnlyHint vs delta) · M5 every C3 status mapped, NOT_VERIFIABLE never PASS · M6 `belay verify` +
both-sub-verdicts report · M7 zero-LLM, tested · M8 honest coverage statement ·
S1 openWorldHint via deny-all denials (fallback: honest UNVERIFIED) · S2 FAIL-as-corpus-case shape ·
S3 incoherence surfaced.

## Out of scope
A1/invariants (C5) — reduction is A1-ready but A1 not built. A3/`--no-claim-axis` (C8). The corpus
store (C6) — emit ingestable cases only. Successful egress under allow-all (not observable). Non-macOS,
non-stdio. Any LLM check.

## Acceptance criteria (test-first)
A1 fabricated result -> FAIL + exact diff · A2 clean deterministic -> PASS · A3 clock/random ->
UNVERIFIED (not FAIL) · A4 readOnlyHint:true + write -> FAIL naming annotation+write · A5 un-annotated
-> UNVERIFIED for effect, result-equiv still decides · A6 unrestorable/absent -> UNVERIFIED, never PASS ·
A7 reduction: one UNVERIFIED + one PASS -> UNVERIFIED (structural) · A8 zero LLM (grep test) ·
A9 PASS-on-the-cheat: pre-state visibly weakened, replays PASS, documented as A1's job · A10 C1+C2+C3
untouched (290) · A11 (S1) openWorldHint:false + deny-all egress denial -> FAIL, or honest UNVERIFIED.

All deterministic, no network, CI-runnable (macOS).

## Dependencies
Upstream: C3 (replay_turn, classify_determinism, reader, persist, report), C1 (annotations, declared,
bth1, frames, index), C2 (launch.DenialCapture, network_policy, substrate). C4 unblocks the Phase-0
number and C5 (A1 slots into C4's reduction).

## Risks
R-C4-1 nondet divergence -> false FAIL (determinism gate). R5 over-claiming egress (M8 + S1 bound).
R-C4-2 NOT_VERIFIABLE -> PASS (the hole). R-C4-3 model can't hold A1 later. R-C4-4 S1 stderr flaky.
