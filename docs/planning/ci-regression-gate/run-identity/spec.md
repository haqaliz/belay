# Aspect: run-identity

## Problem slice

A trace carries no identity: the filename stem is the only key (`trace-<stamp>-<uuid8>`),
and `trace_id` is explicitly not unique across stages (`src/belay/phase0/population.py:12-16`).
A baseline bank cannot know that two captures are "the same run" without an in-band key.

## User outcome

The operator sets `BELAY_RUN_ID=<task>/<agent-version>` when capturing through the proxy;
the trace records it once; any reader can recover it without guessing.

## In scope

- `BELAY_RUN_ID` env read by the proxy (`src/belay/proxy.py`), recorded as a new trace
  record kind `run_identity` (field: `run_id`), `observation_point: "proxy"`, written once
  at proxy start when set. Unset ⇒ no record, no placeholder, absent-never-zero.
- Reader/derive helper (e.g. `derive_run_identity(records)`) returning the id or `None`.
- `docs/technical/TRACE_FORMAT.md` gains the record kind — **no schema version bump**
  (unknown-kind rule: `src/belay/trace.py:50-54`).
- Validation: a run id is a non-empty string; reject control characters; document the
  recommended `<task>/<agent-version>` shape.

## Out of scope

- Capture metadata beyond identity (model, prompt, task text) — explicitly not recorded;
  the proxy records wire bytes only.
- Identity in the `--json` verify report (the gate report carries it instead).
- Any change to existing record kinds or the schema version.

## Acceptance criteria (written first)

1. A capture with `BELAY_RUN_ID` set produces a trace whose derived identity equals the
   value; a capture without it derives `None`.
2. An old reader (schema-v1 reader without knowledge of the kind) reads the trace with the
   new record as a **skip**, never an error — schema round-trip and no version bump.
3. The record is written exactly once per trace and is byte-stable across two identical
   captures (modulo timestamps/ids).
4. A blank or control-character run id is rejected at capture time with a named error, or
   normalized per the spec — decided and pinned by test (fail-closed).

## Dependencies & sequencing

First aspect — `baseline-bank` and `gate-check` key on its output. No dependencies.

## Open questions

- Whether rejection is at proxy start (exit non-zero) or recorded as a `capture_error`.
  Default: reject at start with a clear message; a malformed id must never silently
  produce an anonymous capture.
