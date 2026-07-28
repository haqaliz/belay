# Aspect — `quota-circuit-breaker`

**Unit:** `phase0-mint-resilience` · **Order: SECOND** (first code aspect)
**Covers PRD must-haves A (1–6) and B (7–9).**

---

## Problem slice

A daily-quota error destroyed 56 instances of denominator in 3m48s. The driver has no notion
of error *kind*: `batch.py:219-225` is a single bare `except Exception` that records
`str(exc)` and continues, and `checkpoint.is_done` (`checkpoint.py:82-88`) counts `failed` as
*done*, so a resume skips them forever.

The fix is **not primarily a retry**. The provider's own `retryDelay` was **39043s (≈10h50m)**
— no bounded backoff reaches that. What was lost is the *queue*: the batch should have
**stopped** and left the remaining instances eligible.

Both SDKs already retry internally (`max_retries=2`, honoring `retry-after`), unoverridden at
`local_client.py:76` / `anthropic_client.py:75` — so anything added here **stacks on an
existing invisible layer**, and the observed 429s are *already* post-retry.

## User outcome

A quota event costs **one** instance, not the whole remaining queue. A resume picks up exactly
where it stopped, re-driving only instances that produced **no observation**, and never
re-spending on a captured one.

## In scope

### Error classification

A duck-typed classifier mapping an exception to one of:

| Kind | Meaning | Behavior |
|---|---|---|
| `quota` | a daily/period cap; retry is **hours** away | **stop the batch** |
| `transient` | rate-limit or transport blip; retry is **seconds** away | bounded retry-with-backoff |
| `terminal` | everything else | record `failed`, continue (today's behavior, unchanged) |

- **Duck-typed only** — `getattr(exc, "status_code", None)`, message/body shape. Importing an
  SDK at module scope breaks the import-isolation contract pinned by
  `tests/test_minting_driver_clients_import.py` (contract at `clients/__init__.py:8-14`).
- **An unrecognised error classifies `terminal`.** Never optimistically `transient` — that
  would retry into a wall. Conservative in the safe direction (PRD Gap 2).
- Reference shape to recognise, from the real failures: HTTP 429 with
  `'status': 'RESOURCE_EXHAUSTED'`, `quotaId: GenerateRequestsPerDayPerProjectPerModel`, and a
  `RetryInfo.retryDelay` of `39043s`. A 429 whose retry hint is **large** is `quota`; a 429
  with a short or absent hint is `transient`. Encode that threshold explicitly, do not infer
  it from the word "quota" alone.

### The breaker

- On `quota`: **stop `run_mint` cleanly.** Remaining instances are left **unrecorded** in the
  checkpoint so they stay eligible. Report the instance it fired on and the provider's retry
  hint.
- The instance that hit the quota gets a **distinguishable disposition** — it produced no
  observation and must not read as an ordinary failure.
- `Checkpoint` gains that disposition in its validated vocabulary. **`record` and
  `_validate_entry` change together** (`checkpoint.py:76-80`, `:166-170`) — the loader drops
  unknown keys, so a half-change silently loses data.
- **Fail-closed loading is preserved.** An unknown status still raises
  (`checkpoint.py:39`, `:73-80`).
- **Backward compatibility:** a checkpoint written before this aspect (only
  `captured`/`failed`) must still load. The 56 existing quota-`failed` entries are the real
  migration case — see *Open question*.

### Bounded retry (secondary)

- `transient` only, bounded attempts, exponential backoff, via an **injected `sleep` seam**:
  `sleep: Callable[[float], None] = time.sleep`. No `time.sleep` exists anywhere in `eval/`
  today; this introduces the pattern.
- Retry count is recorded per instance (consumed by `run-accounting`).
- **Placement:** a `Model`-shaped wrapper applied at the `ModelFactory` boundary in
  `entrypoint.make_model_factory` (`entrypoint.py:263-330`). This is the narrowest seam that
  stays in `eval/`, is trivially fakeable, and **structurally cannot** retry a `tools/call` —
  that is a different object at `loop.py:117`.
- **`run_task` stays retry-free**, so `loop.py:11-12`'s *"no retries"* claim remains literally
  true. `loop.py` and `batch.py`'s loop body are not restructured.

### Narrow re-arm

- A resume may re-drive an instance **only** if it produced **no observation**: quota-stopped,
  or a transient failure that exhausted its retries.
- It may **never** re-drive `captured`.
- **The prior record is preserved, not overwritten.** `eval/README.md:303-311` bans `--force`
  precisely because it *"lose[s] the record of what already ran"*; this must be strictly
  narrower and keep the history.
- **Not a re-roll.** `mint-execution/spec.md:52` puts *"retrying instances to improve the
  number"* out of scope; `:90-92`: *"silently re-rolling until the number looks good is
  precisely the dishonesty this project exists to prevent."* An instance that produced an
  observation is never re-armable — **enforced in code**.

### Transient clone retry

- Bounded retry on `git clone --bare` in `prepare_workspace`. `STAGE2_FINDINGS.md:44-52`:
  the single Stage-2 attrition case, and *"the same clone succeeded on retry"*. Same injected
  `sleep` seam; a persistent failure still raises `WorkspacePrepError`.

## Out of scope

- Cost/token/wall-clock recording → `run-accounting`.
- Any new provider client → `subscription-model-client`.
- Concurrency of any kind. A blocking `sleep` on the single thread is safe; a threaded or
  async retry is not (`StdioMcp` is not thread-safe, `transport.py:212-213`).
- Agent sophistication — no planning, memory, or reflection. Resilience is transport
  infrastructure; `batch-harness/spec.md:52-53` and `batch.py:20-21` pre-authorize
  instance-level retry as *"a later, explicit choice"*, and this aspect is that choice.
- Changing `src/belay/`.

## Acceptance criteria (tests first, deterministic, offline)

1. **Quota stops the batch.** A fake model raising a quota-shaped error on instance 3 of 10
   leaves instances 4–10 **absent** from the checkpoint, and `run_mint` returns/reports the
   stop with its cause. *(This is the aspect's headline test — it is the defect that cost 56
   instances.)*
2. **The quota-stopped instance is distinguishable** from a `failed` one in the checkpoint.
3. **Transient retries then succeeds.** A fake raising a transient error twice then returning
   a valid `ToolCall` yields **one captured instance**, with retry count 2 and **no real
   sleeping** — asserted on the recorded **sequence of delays** (e.g. `[1.0, 2.0]`), never on
   elapsed wall time.
4. **Transient exhausts** its bounded attempts → recorded as no-observation, batch continues.
5. **Terminal is unchanged.** Records `failed`, batch continues.
   `test_batch_error_containment_is_not_weakened` (`tests/test_minting_driver_entrypoints.py:781`)
   passes **unmodified**.
6. **An unrecognised exception classifies `terminal`**, not `transient`.
7. **Retry sends an identical request.** A retried `propose_next` issues a request byte-identical
   to the first attempt — `propose_next` calls `_ingest_new_messages` (mutating `self._seen`
   and the message list) *before* the API call, so a retry is safe only because that mutation
   strictly precedes the throwing call. Assert via `FakeOpenAIClient.calls`.
8. **Re-arm re-drives no-observation instances only**; a `captured` instance is never
   re-driven (extends the existing resume test).
9. **Re-arm preserves the prior failure record.**
10. **An instance with an observation is not re-armable** — asserted explicitly, because this
    is the anti-re-roll contract in code.
11. **A pre-existing `{captured, failed}`-only checkpoint still loads**; a corrupt or
    unknown-status one still raises.
12. **Clone retry:** a `prepare_workspace` whose clone fails once then succeeds yields a
    prepared workspace; a persistently failing clone still raises `WorkspacePrepError`.
13. **Single-in-flight survives.** The existing sequential / re-entrancy tests
    (`tests/test_minting_driver_loop.py`, `tests/test_minting_driver_batch.py`) pass unmodified.

## New test scaffolding required

`ScriptedModel` (`fakes.py:22`) **cannot raise a provider error** — its only exception path is
`ScriptExhausted` on over-call. This aspect must add:
- a **fault-injecting model fake** (raise exception E on attempt N, succeed on N+1), and
- a **recording `sleep` double** appending requested delays to a list.

## Dependencies & sequencing

- **Depends on:** nothing in this unit (may land in parallel with `gate-readiness-unblocked`).
- **Blocks:** `run-accounting` (shares the `checkpoint.py` entry schema — do the schema change
  once, here) and `subscription-model-client` (reuses the classifier).

## Open question

**What to do with the 56 existing quota-`failed` entries** in
`.claude/worktrees/feat-verdict-coverage-status/eval/mint/s3/checkpoint.json`. They were
recorded before this vocabulary existed, and their `reason` strings are unambiguous
(`RESOURCE_EXHAUSTED`, one signature, 56/56). Options: (a) a one-shot reclassification tool
that rewrites them to the no-observation disposition **preserving the original reason**;
(b) require the operator to delete them by hand; (c) make the re-arm rule recognise a
quota-shaped `reason` on a legacy `failed` entry. **(a) is preferred** — auditable, preserves
history, and does not bury a migration inside the resume path. Decide at tech-plan.
