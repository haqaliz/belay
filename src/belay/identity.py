"""Run identity — the in-band key a baseline bank can join two captures on.

A trace's filename stem is not identity (`trace-<stamp>-<uuid8>`), and `trace_id`
is explicitly not unique across stages. The ci-regression-gate needs to know that
a capture and its baseline are "the same run", so the operator sets
`BELAY_RUN_ID=<task>/<agent-version>` when capturing through the proxy; the proxy
validates it fail-closed at startup and records it once as a `run_identity`
record. An unset env is absent-never-zero: no record, no placeholder, and
`derive_run_identity` returns `None` rather than a guessed id.

The validation contract, pinned by test: an id is a non-empty string with no
control characters (`ord(c) < 32 or c == 127`), no whitespace, and — split on
`/` — no empty segment (no leading, trailing or double slash) and no `..`
segment. Slashes themselves are legal: the recommended shape is
`<task>/<agent-version>`. The id becomes a baseline directory key downstream, so
path-traversal safety is decided here, at capture, where it is cheapest.
"""

from __future__ import annotations

from typing import Optional

RUN_ID_ENV = "BELAY_RUN_ID"


def derive_run_identity(records: list[dict]) -> Optional[str]:
    """The first non-empty string `run_id` from a `run_identity` record, else `None`.

    Pure, no I/O: it reads the records the reader already returns and never
    reaches for the writer. A malformed record (non-string, or empty `run_id`)
    is not a match — an unreadable id must derive to `None` (fail-closed at the
    gate), never to a coerced string.
    """
    for record in records:
        if record.get("kind") != "run_identity":
            continue
        run_id = record.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


def validate_run_id(run_id: str) -> None:
    """Refuse an id that cannot safely become a baseline directory key.

    Raises `ValueError` naming the violated rule. Called by the proxy at startup
    when `BELAY_RUN_ID` is set; the proxy turns it into a stderr message and
    exit 2, so a malformed id can never silently produce an anonymous capture.
    """
    if not run_id:
        raise ValueError("a run id must be a non-empty string")
    if any(ord(c) < 32 or ord(c) == 127 for c in run_id):
        raise ValueError("a run id must not contain control characters")
    if any(c.isspace() for c in run_id):
        raise ValueError("a run id must not contain whitespace")
    if any(not segment or segment == ".." for segment in run_id.split("/")):
        raise ValueError("a run id must not contain empty or '..' path segments")


__all__ = ["RUN_ID_ENV", "derive_run_identity", "validate_run_id"]
