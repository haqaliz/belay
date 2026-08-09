"""The driver-side claim-record seam: append the session's claim to the capture trace.

The trajectory rule needs the agent's final claim to judge, and the claim never
crosses the proxy: the model client parses `Done` itself, the loop returns on
it without it ever crossing the wire, and the capture ends with the last
`tools/call` reply. `append_claim_record` (`src/belay/trace.py`) owns the
format's guarantees — the envelope, `seq = last + 1` continuation, the
absent-never-empty `text` key, and the named `TraceClaimError` for a
missing/malformed trace. The driver owns the two things AROUND that call:

- **WHEN to append.** Only a session that stopped with a `Done` claimed
  anything; `max_steps` or an error means nothing was claimed and nothing may
  be recorded. The decision lives in `run_mint` (`batch.py`), which knows the
  `Transcript`'s `stop_reason`; this module only knows the trace directory.
- **WHETHER a capture exists to append to.** A run whose session produced no
  `trace-*.jsonl` — a fake-transport test run, or a session that died before
  the gate wrote anything — has no sequence for the claim to continue, so the
  driver skips the append instead of crashing. When a trace IS present, the
  named-error contract of `append_claim_record` applies in full: a malformed
  capture reads as `failed` through `run_mint`'s per-instance containment,
  never as a silently-claimed success.

The exactly-one rule is the same rule the bridge lives by
(`bridge.py:109-121`): zero traces is "nothing captured" (skip the claim; the
bridge names the missing capture `NoTraceError`), and more than one is a
violated mint invariant that the bridge will surface as `MultipleTracesError`
immediately after — appending to one of several would guess which capture was
claimed, so the driver stays silent and lets the bridge name the violation.

`belay` is imported LAZILY, inside the function, for the same reason
`entrypoint.run_verify` imports it lazily (`entrypoint.py:936-946`): `eval/`
must import with `belay` absent from the environment
(`test_cli_module_imports_without_belay_installed`), and a claim record only
ever lands in a real capture, which exists only because the gated proxy ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

StrPath = Union[str, "Path"]


def record_session_claim(trace_dir: StrPath, *, text: str | None) -> None:
    """Append the session's claim to the single capture trace under `trace_dir`.

    Finds the `trace-*.jsonl` the gated proxy wrote (the same glob
    `bridge_capture` uses) and appends the claim record via
    `belay.trace.append_claim_record`, so the record rides inside the capture
    through the bridge. Skips the append — silently, by design — when no trace
    exists (a fake-transport run has no capture and must not crash) or when the
    dir holds more than one (the bridge names that violation itself). When
    exactly one trace exists, `append_claim_record`'s named-error contract
    applies unchanged: a malformed capture raises `TraceClaimError`, which
    `run_mint`'s containment records `failed` — an unrecorded claim must never
    masquerade as a recorded one.

    `text` is the claim text when there is one; `None` or whitespace-only
    yields a record without the `text` key (the format's absent-never-empty
    rule, decided inside `append_claim_record`).
    """
    traces = sorted(Path(trace_dir).glob("trace-*.jsonl"))
    if len(traces) != 1:
        return
    from belay.trace import append_claim_record

    append_claim_record(traces[0], text=text)


__all__ = ["record_session_claim"]
