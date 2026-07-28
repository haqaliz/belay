# Aspect — `run-accounting`

**Unit:** `phase0-mint-resilience` · **Order: THIRD** · **Covers PRD must-haves C (10–12).**

---

## Problem slice

**Nothing records what a mint costs. Anywhere.** Verified by grep across `eval/` for
`usage|prompt_tokens|input_tokens|cost|duration|elapsed` — the only hits are the *word* "cost"
in prose.

- `local_client.py:125-170` reads only `response.choices[0].message` and `finish_reason`. The
  real response's `.usage` (`prompt_tokens`/`completion_tokens`) is present and **discarded
  when `response` goes out of scope.**
- `anthropic_client.py:147-181` likewise discards `.usage` (`input_tokens`/`output_tokens`).
- `batch.py:201` **throws away `run_session`'s return value entirely** — line 201 is a bare
  call, not an assignment. The `Transcript` (`loop.py:51-65`) carries no counts and no timing.
- `checkpoint.py:56-80` stores exactly `{status, reason, trace_path}`, and `_validate_entry`
  (`:166-170`) **drops unknown keys on load.**

This is a pre-registered debt, not a discovery. `phase0-live-mint/prd.md:285-293` (Gap 3):
*"make **'record cost + wall-clock per instance' an explicit Stage-2 output**, and set a
stop-loss the founder agrees to in advance."* `mint-execution/spec.md:50` makes it acceptance
criterion 3. Stage 2 produced **one wall-clock anecdote** (~15 min for one sympy instance) and
**no spend figure at all** — `phase0-gate-readiness/prd.md:214` confirms: *"Stage 2 measured
wall-clock … but **no spend**."*

Consequence today: nobody can say what the remaining ~34 instances will cost in time or usage,
so no stop-loss can be set, and the write-up cannot state what the number cost to produce.

## User outcome

After any mint — partial or complete — the operator can answer: how long did each instance
take, how many model requests did it consume, how many tokens, and how many retries. That
makes a stop-loss expressible and the eventual write-up honest about the cost of the number.

## In scope

- **Per-instance accounting record**, durable beside the checkpoint:
  - `wall_clock_seconds` — measured in the **batch layer** behind an **injected clock**.
  - `model_requests` — count of `propose_next` calls that reached the provider.
  - `retry_count` — from `quota-circuit-breaker`.
  - `tokens` — input/output where the client exposes them; **absent, not zero, when it does
    not.** An unknown must never render as `0`.
  - `model` and `provider` — per-instance provenance (PRD must-have 16). The 12 banked
    instances ran on `gemini-3.1-pro-preview` and the remainder will not, so the published
    number must be able to name which model minted which instance.
- **Usage extraction in both existing clients** — read `.usage` off the response and surface
  it instead of discarding it. Duck-typed (`getattr`), so a fake or a provider that omits
  usage yields absent rather than raising.
- **A batch-level accounting summary** — totals and per-instance rows, renderable after a run.
- **`Checkpoint` schema extension**, `record` and `_validate_entry` changed **together**
  (`checkpoint.py:76-80`, `:166-170`), preserving fail-closed load and backward compatibility
  with `{status, reason, trace_path}`-only entries.

### Honest naming

**Under a subscription there is no per-token dollar cost.** "Cost" is therefore recorded as
**requests + tokens + wall-clock**, and the field names say so. **No dollar figure is
computed or stored** — a fabricated price would be exactly the kind of invented precision this
project exists to avoid. If a metered key is ever used again, price is applied at report time
from a stated rate, never baked into the ledger.

## Out of scope

- Error classification, the breaker, the re-arm → `quota-circuit-breaker`.
- Any new provider client → `subscription-model-client`.
- Setting the stop-loss *value* — that is the owner's judgement, informed by what this
  measures. This aspect makes the number expressible; it does not choose it.
- Computing or storing dollar amounts.
- Changing `src/belay/`.
- Reading the clock in `entrypoint.py` — its stated design rule is *"No clock, no
  randomness"* (`mint-entrypoints/plan_20260723.md:503`). Timing lives in the batch layer.

## Acceptance criteria (tests first, deterministic, offline)

1. **Wall-clock is recorded per instance** using an **injected clock**, asserted against a
   scripted fake clock — never against real elapsed time.
2. **`entrypoint.py` reads no clock.** Asserted structurally (the existing no-clock rule must
   survive this aspect), mirroring how `tests/test_minting_driver_transport.py` asserts module
   standalone-ness by AST walk.
3. **Request count is recorded** and matches the number of `propose_next` calls that reached
   the provider.
4. **Retry count is recorded** and agrees with the breaker's own count.
5. **Token usage is extracted** from an OpenAI-shaped response and from an Anthropic-shaped
   response via the existing `FakeOpenAIClient` / `FakeAnthropicClient` seams.
6. **A response with no usage field yields ABSENT, not zero.** Asserted explicitly — this is
   the honesty contract in code: an unmeasured quantity is never rendered as a measured zero.
7. **Per-instance `model` and `provider` are recorded**, and a batch driven with two different
   models records them distinctly.
8. **No dollar amount appears** anywhere in the record or the summary — asserted, so a later
   change cannot quietly add one.
9. **The summary reports totals with their denominators**, and states how many instances had
   usage available vs absent.
10. **Backward compatibility:** a checkpoint written without accounting fields still loads; a
    corrupt or unknown-status one still raises.
11. **Existing behavior is unchanged** — the full batch/checkpoint/entrypoint suites pass, and
    `batch.py`'s error containment is not weakened.

## Dependencies & sequencing

- **Depends on:** `quota-circuit-breaker` — it owns `retry_count` and lands the first
  `checkpoint.py` entry-schema change. Doing both schema changes in one place avoids a
  collision; sequence them, do not parallelize.
- **Blocks:** nothing, but its output is what answers *"what is the subscription's actual
  instances/day ceiling?"* (PRD open question 3).

## Risks

- **Schema collision with `quota-circuit-breaker`.** Both touch `record` + `_validate_entry`.
  Land the breaker first and extend, rather than designing two schemas.
- **Token usage under the CLI-backed client is uncertain.** `claude -p --output-format json`
  may or may not report usage; if it does not, this aspect's *absent-not-zero* rule is what
  keeps that honest. Do not block on it.
- **Do not let accounting become a performance narrative.** It exists to set a stop-loss and
  to state the cost of the number — not to make the mint look efficient.
