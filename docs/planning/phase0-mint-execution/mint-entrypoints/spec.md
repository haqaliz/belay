# Aspect — `mint-entrypoints`

**Unit:** `phase0-mint-execution` · **Sequence:** 2 of 5
**Placement:** `eval/` (eval-only; no `src/belay/` changes)

---

## Problem slice

There is **no committed way to run a mint**. No CLI, no `__main__`, no argparse anywhere under
`eval/`. `run_mint` (`eval/minting_driver/batch.py:123-137`) is real and correct but is invoked
**only from tests with fakes**. Stage 1 ran from an uncommitted `scratchpad/drive_one.py` that
no longer exists (`STAGE1_FINDINGS.md:5-6`).

**Therefore the Stage-1 result cannot be reproduced from the repo.** For an artifact whose
entire purpose is reproducing the number, that is the defect that matters most after the
engine fix.

**User outcome:** the founder (or any reader) can mint one instance by id, and a batch from a
selection file, using committed code and the documented commands.

---

## In scope

1. **One-instance-by-id entry point** — takes an instance id, resolves it from the registry,
   preps the workspace, drives the gated capture, bridges, and reports where the artifacts
   landed. This is the Stage-1 tool and the smallest reproducible unit of the mint.
2. **Batch entry point** — wraps `run_mint` with the registry, checkpoint, and bridge wired;
   resumable; per-instance error containment already exists in `run_mint` and must not be
   weakened.
3. **Explicit `request_timeout`** plumbed from the entry point. `None` silently means
   `DEFAULT_TIMEOUT = 10.0` (`transport.py:53`), too tight for a live model plus a cold `node`
   start under Seatbelt. There is no env override today; the entry point must make it settable
   and must not default to 10s.
4. **Model wiring for the decided provider** — `gemini-flash-latest` over the OpenAI-compat
   endpoint. **`ANTHROPIC_API_KEY` must be unset or explicitly overridden**: the driver prefers
   Anthropic whenever that key is present, which would silently switch providers mid-mint.
   A fresh model client **per instance** (clients accumulate conversation state).
5. **A server-install preflight** — `eval/servers/` is gitignored and absent from both
   checkouts. The entry point should fail fast with the exact install command
   (`servers.py:113` already carries it via `MissingServerError`) rather than mid-mint.

---

## Out of scope

- Agent sophistication — no planning, memory, retry-with-reflection, or multi-step autonomy.
  That is agent-framework drift (guardrail #1). The driver stays thin and sequential.
- Parallel/concurrent minting — sequential by design (`StdioMcp` is not thread-safe).
- The pool/draw artifacts — `instance-pool` aspect.
- Any `src/belay/` change.

---

## Acceptance criteria (test-first)

1. **`test_single_instance_entrypoint_is_importable_and_wired`** — the one-instance path
   resolves an id from the registry and calls through prep → capture → bridge, with fakes.
   Deterministic, offline, no spend.
2. **`test_entrypoint_requires_explicit_timeout`** — the 10s default cannot be reached silently.
3. **`test_fresh_model_client_per_instance`** — instance N does not inherit instance N-1's
   conversation state.
4. **`test_missing_servers_fail_fast_with_install_command`** — absent `eval/servers/` produces
   the actionable error before any workspace prep or model call.
5. **`test_batch_entrypoint_resumes_from_checkpoint`** — a batch interrupted at instance k
   resumes without re-running 1..k-1.
6. **`test_provider_selection_is_explicit`** — a stray `ANTHROPIC_API_KEY` in the environment
   cannot silently change which model mints.

All offline with fakes; the live path stays `manual`-marked and never runs in CI.

---

## Dependencies and sequencing

- **Depends on:** `replay-batch-server-rooting` (no spend before the engine is trustworthy).
- **Blocks:** `mint-execution`.
- Pairs naturally with `instance-pool` — the batch entry point consumes `selected.json`.

---

## Open questions / risks

- **Should the entry point be a `belay` subcommand or an `eval/` script?** It must **not**
  become a product surface — `eval/` is explicitly not the `belay` CLI
  (`minting-driver/spec.md`). Keep it under `eval/`.
- The manual smoke's oracle is weak (accepts `VERIFIED_FLAGGED`, bypasses `bridge_capture`
  via `manifest_dir_for=`). Strengthening it is nice-to-have 22 and belongs here if it is
  cheap.
