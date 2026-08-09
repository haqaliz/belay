# Aspect spec — claim-record

**Feature:** `trajectory-success-invariant` · **Aspect:** `claim-record` (first, dependency of the other two) ·
**Date:** 2026-08-09

## Problem slice

The trajectory rule ("the suite must be executed before a success claim") needs the **claim**
to judge. Today the claim does not exist in the record: `Done` is parsed by the model client
inside the minting driver (`eval/minting_driver/clients/claude_cli_client.py:580-624`), the
loop returns on it without it ever crossing the MCP proxy (`loop.py:112-115`), and
`run_mint` discards the `Transcript` (`batch.py:358-367`). The proxy records only what
crosses the wire. A rule built on "success claims" is structurally blind until the claim is
recorded.

## In scope

1. **A post-close appender in the format module.** `src/belay/trace.py` gains a public
   `append_claim_record(path, *, text=None)` that appends one well-formed `claim` record to a
   closed trace file:
   - Envelope preserved exactly: `v: 1`, `kind: "claim"`, `seq` = last recorded `seq + 1`
     (strict monotonicity, never a duplicate, never a gap), `t_in` via the existing `_now`,
     `observation_point: "session"` (the observer is the driver, not the proxy — never lie
     about who saw what).
   - `text` is the claim text when available; the key is **absent** (never `""`) when there
     is none — an empty string would occupy a meaning it doesn't have.
   - Named errors, never silent: missing file, empty file, or an unparseable/invalid last
     `seq` raise a named exception the driver surfaces. An unrecorded claim is an unjudged
     instance; it must not masquerade as anything else.
   - The helper exists so the format's guarantees stay inside `trace.py` — the "never reach
     past into `_append`" rule (`trace.py:262-272` docstring) applies to the driver too.
2. **Format documentation.** `docs/technical/TRACE_FORMAT.md` documents the `claim` kind:
   fields, observer (`session`), the append rule, and that readers/replay treat it as a
   non-frame record (skipped by the indexer, `index.py:110`; never replayed).
3. **Driver wiring.** The minting driver records the claim at session close:
   - `run_mint` (batch path) keeps the `Transcript` and, when the run stopped with a `Done`
     (not `max_steps`), appends the claim record to the capture trace **before**
     `bridge_capture` (so the claim rides inside `trace.jsonl` through the bridge with zero
     bridge changes).
   - Claim text = `Done.reason` when non-empty; absent otherwise. `max_steps` or error
     termination → **no claim record** (nothing was claimed; aspect 2 abstains honestly with
     `NO_CLAIM_RECORDED`).
   - Any single-instance session path (if one exists) gets the same treatment through the
     same helper.
   - **Pinned-hash guard:** `CLAUDE.md` records that `loop.py`/`batch.py` are byte-unmodified
     behind a pinned hash + a meta-test that the guard notices an edit. This aspect
     intentionally modifies `batch.py` (and possibly the transcript seam), so the guard's
     pinned hash is updated in the same commit — the meta-test stays (it proves the guard
     works, which is its only job).
4. **Tolerance pinned by test** (the code is already tolerant; the tests make it a contract):
   - The indexer's derived records are byte-identical for a trace with and without a claim
     record (non-frame records were already skipped — `index.py:110`).
   - Replaying any turn of a trace that contains a claim record is unaffected (claim records
     are not frames, correlate to nothing, and are never gathered for replay).
   - `append_claim_record` round-trips: reading the appended file back yields the record with
     `seq` strictly greater than every prior record's.

## Out of scope

- Classification of the claim text (verification vs completion) — aspect `trajectory-rule`.
- Any verdict, invariant, runner, ledger, report, or phase0 change.
- Corpus changes — aspect `corpus-trajectory`.
- Backfilling claims for existing captures (stage-1/2/4b) — impossible; nothing was claimed
  into a record.

## Acceptance criteria (test-first)

1. `append_claim_record` writes a well-formed envelope record with `seq = last + 1`, `kind
   == "claim"`, `observation_point == "session"`, and `t_in` present.
2. `text` present when given; the key absent (never `""`) when not.
3. Missing file / empty file / invalid last `seq` → named error, never silent.
4. Two appends to the same trace yield strictly increasing `seq`s (no duplicate, no gap).
5. A trace with a claim record indexes identically to the same trace without it (no new
   `index_gap`, no derived-record difference).
6. Replaying a turn of a claim-bearing trace reproduces the same verdict as the same trace
   without the record.
7. `run_mint` with a `ScriptedModel` that ends in `Done(reason=...)` appends a claim record
   whose text equals the reason; empty reason → record with `text` absent.
8. `max_steps` termination appends **no** claim record.
9. The claim record survives `bridge_capture` (rides inside `trace.jsonl`).
10. Deterministic, no network, runs in CI; the pinned-hash meta-test still proves the guard
    notices an edit (and the updated pin passes).

## Dependencies & sequencing

None — this aspect is independent and is the first build step for the feature. Aspect 2
consumes the `claim` kind; aspect 3 consumes aspect 2's verdicts.

## Open questions / risks

- **Transcript seam:** `Transcript` carries `done: Done` but not the model's full final reply
  text (`loop.py:51-65`). If the full text is wanted for classification, the `Model` protocol
  or `Transcript` must grow — **decision for this aspect:** record `Done.reason` only; the
  full-text seam is a follow-up if the classifier (aspect 2) is starved.
- **Single-instance path:** confirm whether `eval/minting_driver/{cli,entrypoint}.py` runs
  sessions outside `run_mint`; if so, wire the same append.
- **Pinned-hash test location:** find the guard test by searching for the hash pin; update it
  in the same commit as the `batch.py` change.
