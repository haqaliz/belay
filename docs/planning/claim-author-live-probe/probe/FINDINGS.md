# FINDINGS — claim-author live probe (run 2026-10-10)

Freeze protocol (Rule D, `phase0-mint-run/prd.md:97-101`): the invocation was frozen at
commit `3ce820d` by the artifacts in this directory (no result in the script — grep-checked);
the run happened **once**; the verbatim outputs (`run-trace-{11422,14382}.out/.err`,
`probe-marker`, `probe-wall`) were committed next at `8869fe4`, whatever they said. A second
run would require a declared decision.

## The observation (verbatim, execution grade)

| Trace | Author invocations (marker) | Author wall-time (wrapper) | Author outcome | A3 record on the document |
|---|---|---|---|---|
| `django-11422` | 1 | start→end: 24 s | check produced, executed contained | `claim_silence` — `check.exit_code: 0` (D3 silence), a substantive AST-based check on `iter_modules_and_files()` |
| `django-14382` | 1 | start→end: 15 s | check produced, executed contained | `claim_silence` — `check.exit_code: 0` (D3 silence), a line-77 content check on `django/core/management/templates.py` |

Both documents: aggregate **5/5 PASS, 0 UNVERIFIED**; trajectory **FAIL** with the identical
message run 3 committed (*"the claim asserts verification success with 0 evidence turn(s)"* —
a **MATCH** with `mint-run/ledgers/cm-run3-stage2.json`, replay fidelity held); `effect:network`
NOT_COVERED on 5/5 turns; stderr empty on both arms.

## The R-D answer

**Hypothesis refuted at n=2.** R-D (`claim-axis-legibility/prd.md:193-200`) asked whether the
two run-3 `NO_CHECK_AUTHOR` abstentions could be the engine's own 60 s `AUTHOR_TIMEOUT`
killing a still-working author. On the identical traces, the identical author path, and the
identical model, the author completed in **24 s and 15 s** — far inside the cap — and produced
checks that executed and exited 0. **The engine's bound did not kill a working author.
The timeout is not the cause of run 3's abstentions.**

What this does NOT say, stated plainly:

- Run 3's two abstention causes remain **unobservable** — they were never recorded, and this
  probe is a new observation, not a back-fill (the standing honesty rule: old ledgers are
  never re-derived).
- This run's success does not prove run-3's abstentions were transient either — their cause
  (a one-off author launch failure, a model-side refusal, a parse failure under run 3's
  conditions) is simply beyond the recorded evidence, exactly as the earlier records said.
  The structural suspicion R-D described is now **measured-away for the engine bound**: the
  produced checks complete at 15–24 s, a quarter of the cap.
- A3 silence (exit 0) is not a PASS (D3): the check re-derived the claim's *content* from the
  final state; the trajectory FAIL measures the claim's *procedure* (zero command evidence).
  The two axes answered different questions, as designed. Neither is a verdict about the agent.

## Conditional aspect — decision

The `timeout-knob` aspect's trigger was pre-registered as *≥1 observed `AUTHOR_TIMED_OUT`*
(`prd.md` requirement 3; owner decision 2026-10-10: knob only on an actual kill, never on
headroom). **No `AUTHOR_TIMED_OUT` was observed. The trigger did not fire → the aspect is NOT
BUILT.** The knob stays absent; `test_verify_author.py:121`'s pin and the 60 s default stand
untouched. The near-break-case question is moot: headroom was 36–45 s, not 2 s.

## Secondary observations

- **First real `claim_silence` records on real data** (the v0.39.0 record, previously stub-
  proven only): the A3 axis engaged, both checks were code-specific and non-vacuous, both
  executed under `contained()` against the replayed final state. This is C8's first real
  outcome on real data — two actual checks written by a frontier model for two real claims,
  resting at exit 0.
- The checks themselves are committed verbatim inside the `.out` documents (the `claim_silence`
  source) — the "synthesized checks" corpus C8's PRD values (`CAPABILITY_ROADMAP.md:828-829`).
- Triage-timeout reading (S2): nothing here touches `TRIAGE_TIMEOUT`; Jev measured 0.9 s at
  n=1 and no starvation evidence exists — the mirror decision stands (`jev-triage/triage-seam/
  spec.md:33`), observation only.
- The manual probe test now has a passing live reference: re-running it against either trace
  should reproduce this shape (owner's subscription permitting); it remains owner-run only.

## Honesty lines

**Not a gate run; produces no Phase-0 number.** No published number moves (`11/60 = 18.3%`,
`precision 0.00`, `1/15`, `4/16`, `recall 0.00`, `3/93` stand unedited). No verdict, status,
reduction, exit-code, corpus or gate behavior moved; no `src/` change shipped; the two
`belay corpus label` judgments remain the owner's alone (`AUDIT.md:93-97`). Suite baseline
unchanged (2895 passing, 45 skipped, 14 deselected). The cost was two author invocations
(24 s + 15 s) plus the two full-trace replays behind them.