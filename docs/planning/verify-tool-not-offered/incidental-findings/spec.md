# Aspect A4 — `incidental-findings`

> Two pre-existing defects found while digging, neither caused by this unit. Owner directed
> that both be **recorded AND fixed**.

## Finding 1 — corpus recompute never threads the shell server

`src/belay/corpus/run.py:run_case` (`:522`) and `_recompute_trajectory_case` (`:478`) call
`verify_turn` / `_verify_one_trace` with **only** `case.server_command`; neither threads
`shell_server_command`, though `_verify_one_trace` supports it. A trajectory case whose
original run routed `run_process` turns to a shell server silently recomputes those turns
against the stored **filesystem** command.

**Latent today** — `suite-before-success-claim` reads `records`, not per-turn replay
outcomes — but it is a landmine for anyone widening the shell axis.

**Constraint:** case schema **v4 stores ONE resolved command** and stays that way
(`prd.md` → Out of scope). The fix threads the command; it does not grow the format.

### Acceptance
- **AC-1** A trajectory case whose turns include `run_process` recomputes those turns against
  the routed command, not the stored fs command.
- **AC-2** A per-turn case is unchanged (regression).
- **AC-3** The 182-banked-case shape still loads and recomputes identically — no schema bump,
  no re-add required.

## Finding 2 — broadcast JSON-RPC id collision after trace merge

`eval/minting_driver/composite.py:_broadcast` (`:243`) sends `initialize` and `tools/list` to
**every** session carrying the **same** JSON-RPC id (one `MonotonicIds()` counter,
`eval/minting_driver/loop.py:99-102`). After `merge_session_traces`, `derive_correlation`
keys pending requests on `(direction, type(id), id)` with **no session component**
(`src/belay/index.py:75`, `:140`) and a request record **overwrites** the prior pending entry
— so the second session's request evicts the first, a reply can pair against the wrong
request, and `status` can misreport `duplicate-response` though both replies really happened.

**Untested:** `tests/test_minting_driver_trace_merge.py:215` covers only unique-id
`tools/call` turns and explicitly notes correctness depends on "unique JSON-RPC ids across
the composite". `offered_toolset` survives only **by accident** (it does not filter on
`status`).

### Honest limit, stated up front
This **cannot be validated against the real merged mint data** — the s6 captures no longer
exist (`prd.md` → Constraints). It is pinned by a **constructed two-trace fixture with
colliding ids**: a legitimate test, but **not a replay of history**, and the PR must say so.

### Acceptance
- **AC-4** A constructed merged trace with two sessions sharing a `tools/list` id correlates
  **both** pairs correctly — no eviction, no spurious `duplicate-response`.
- **AC-5** The existing unique-id merge tests stay green (regression).
- **AC-6** A test pins the previously-accidental property explicitly: `offered_toolset`'s
  reading is correct on a collided merged trace *by construction*, not by not-filtering.

## Out of scope
- Any redesign of the composite or of id allocation beyond what AC-4 requires.
- Re-running or re-deriving any mint.

## Dependencies & sequencing
- **Independent of A1–A3.** Land last; it must not delay the honesty fix.
- Finding 2 touches `src/belay/index.py` (engine) and `eval/` — the engine change is the
  load-bearing half and needs the tighter review.
