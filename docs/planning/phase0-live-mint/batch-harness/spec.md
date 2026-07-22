# Aspect spec — `batch-harness`

**Parent PRD:** `docs/planning/phase0-live-mint/prd.md` (must-haves 3–11)
**Sequencing:** second. Depends on `instance-registry` for its input records.
**This aspect carries the unit's highest-risk path (the rename bridge).**

## Problem slice

`run_session` drives exactly one instance and propagates every exception. Nothing prepares
a workspace, maps traces to instances, contains errors, resumes after a crash, or bridges
the manifest-naming mismatch. Without those, a 50-instance mint either aborts partway
after real inference spend, or produces traces the runner reads as all-UNVERIFIED and
reports as `INSTRUMENT SUSPECT` — a **fake PIVOT**.

## In scope

1. **Per-instance workspace prep** — obtain the repo at `base_commit` and lay out:
   ```
   <root>/<instance-id>/workspace/     ← BELAY_SANDBOX_SCOPE
   <root>/<instance-id>/snapshots/     ← BELAY_SNAPSHOT_DIR (SIBLING of scope, never inside)
   <root>/<instance-id>/traces/        ← BELAY_TRACE_DIR (private per instance)
   ```
2. **Gated capture wiring** via the existing `gated_env` + `proxy_command`
   (`eval/minting_driver/capture.py`) — all three env vars, always.
3. **The rename bridge** — after each instance, move
   `traces/trace-<ts>-<hex>.jsonl` → `<batch-dir>/trace-<instance-id>.jsonl` and
   `snapshots.manifests/` → `<batch-dir>/trace-<instance-id>.manifests/`,
   so the stock `belay phase0 run` resolves manifests via its
   `<trace-stem>.manifests` convention (`phase0/runner.py:74-83`). Snapshot **trees** may
   stay put — manifest `tree_path` is absolute (`replay/persist.py:109`).
4. **Sequential drive** — one instance at a time, one `tools/call` in flight, a **fresh
   model client per instance** (clients accumulate state, `anthropic_client.py:84-87`).
5. **Per-instance error containment** — any exception is recorded with a reason and the
   batch continues, mirroring `run_batch`'s `ERRORED` discipline (`runner.py:123-135`).
6. **Resume** — a checkpoint file recording per-instance status (`captured`, `failed`,
   plus the reason); re-entry skips completed instances.
7. **A configurable request timeout** threaded `run_session → run_task →
   transport.request`. Today `DEFAULT_TIMEOUT = 10.0` (`transport.py:53`) is unreachable
   through `run_session` and will not survive a cold `npx -y` fetch.
8. **Two segregated batches** — filesystem and shell servers each get their own batch dir
   and ledger; the harness never mixes them into one trace dir.

## Out of scope

- Any change to `src/belay/` — including adding `--manifest-dir` to `phase0 run`.
  The bridge is a harness-side rename. **This boundary is load-bearing** (eval-only
  guardrail, `minting-driver/spec.md`).
- Concurrency (`StdioMcp` is not thread-safe, `transport.py:213-215`; sequential also
  keeps R7-by-construction and avoids the macOS TCC stall).
- Calling the live model in tests — every test here uses fakes.
- Running the actual mint (that is `mint-execution`).
- Retry-with-reflection, planning, or memory in the agent loop — **agent-framework drift**.
  Retrying a *failed instance* is fine; making the *agent* smarter is not.

## Acceptance criteria (test-first)

1. `test_drives_instances_sequentially_never_more_than_one_call_in_flight` — with a fake
   transport and scripted model over N instances, a re-entrancy counter never exceeds 1
   (extends the existing single-session test to the batch layer).
2. `test_rename_bridge_produces_the_layout_phase0_run_resolves` — **the highest-value test
   in the unit.** After a simulated capture, assert
   `<batch>/trace-<id>.jsonl` and `<batch>/trace-<id>.manifests/` exist, and that
   `phase0.runner.default_manifest_dir_for(trace)` resolves to the directory actually
   containing the manifests.
3. `test_a_failing_instance_does_not_abort_the_batch` — one instance raises `ServerExited`;
   the remaining instances still run and the failure is recorded with its reason.
4. `test_resume_skips_already_captured_instances` — re-entry after a simulated crash drives
   only the uncaptured instances, and the checkpoint reflects both runs.
5. `test_resume_after_partial_instance_does_not_emit_a_half_written_trace` — an instance
   interrupted mid-capture is retried or recorded as failed, never left as a partial trace
   that the runner would read as a real (short) instance.
6. `test_each_instance_gets_a_fresh_model_client` — the factory is invoked once per
   instance; no client instance is reused.
7. `test_snapshot_dir_is_a_sibling_of_the_scope_never_inside_it` — the prepared layout
   satisfies the gate's constraint (`gate.py:303-315`).
8. `test_timeout_is_threaded_through_to_the_transport_request` — a configured timeout
   reaches `transport.request`, rather than silently using the 10s default.
9. `test_filesystem_and_shell_batches_are_written_to_separate_dirs` — no single trace dir
   ever contains traces from two different servers.
10. `test_short_denominator_run_reports_instrument_suspect_not_zero_percent` — an
    end-to-end assertion over the harness → `phase0 run` → `report` path that a mint with
    ~no verifiable turns reads as `INSTRUMENT SUSPECT` (the R6 false-zero defense,
    card acceptance #2). May reuse the existing darwin-gated e2e machinery.

All deterministic and CI-safe (fakes only). Platform-gated where the sandbox is required,
consistent with the existing `tests/test_phase0_e2e.py`.

## Dependencies

- `instance-registry` (input records).
- Existing: `eval/minting_driver/{session,loop,capture,transport}.py`,
  `src/belay/phase0/runner.py` (read-only consumer contract).

## Risks / open questions

- **The rename bridge is the fake-PIVOT risk.** Criterion 2 exists specifically to guard
  it, and `mint-execution` Stage 1 verifies it against a real capture before any spend.
- **Repo acquisition cost** — cloning 7 large repos (django, sympy) once and reusing them
  via `git worktree`/cached bare clones is likely necessary; a fresh clone per instance is
  wasteful. Sizing to be settled in the plan.
- **`npx` cold-start latency** interacts with criterion 8; the default timeout must be
  raised meaningfully, not nudged.
