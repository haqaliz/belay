"""The approval channel: the directory contract, the poll, the refusal, the cache.

Aspect `approval-gate/hold-channel`. The channel is the composition object the
proxy root wires (aspect 4): request files written for the human, decision files
read atomically under a bounded fail-closed deadline, refusal bytes produced on
deny, and the tool-facts cache kept current from the live wire so `decide_c2s`
has facts at hold time.

The honesty rules that shape this module:

- **A partially-written decision is absent, never guessed.** A malformed file is
  retried to the deadline; the poll never invents a decision out of one.
- **The deadline is exact under the injected clock, in one pinned order.**
  Each tick reads the decision FIRST: a decision the poll found is a decision
  the human wrote, and the poll's granularity never costs them it. The deadline
  check runs only when no decision was found — past it, the hold is denied
  `APPROVAL_TIMEOUT` (fail-closed, never forwarded) and no later file is ever
  read again (M14: late decisions are ignored, never applied retroactively).
- **A default is not a declaration.** The live cache records what the wire said
  about each annotation through `declared.declared_state`, so an absent
  annotation and a literal `null` stay as different facts.
- **The gate never raises.** An internal fault (a channel I/O failure, a broken
  recorder) suppresses the call with a best-effort refusal and a decision record
  whose cause is `APPROVAL_FAULT` — a gate that cannot evaluate its trigger
  refuses loudly, never forwards a destructive call silently and never lets the
  client hang.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from belay.approval.gate import (
    DECISION_APPROVE,
    DECISION_DENY,
    Hold,
)

#: The directory contract's file names, stated once.
REQUESTS_DIR = "requests"
DECISIONS_DIR = "decisions"

#: How long the poll waits between reads, and how long a hold may wait for a
#: human before it is denied fail-closed. Both overridable at the composition
#: root (`BELAY_APPROVAL_TIMEOUT` for the deadline).
DEFAULT_POLL_INTERVAL = 0.1
DEFAULT_TIMEOUT = 300.0


class ApprovalDirUnusable(ValueError):
    """The approval directory cannot serve requests/decisions — a named startup
    failure the composition root refuses on (M1), never a mid-turn surprise."""


def validate_dir(approval_dir) -> None:
    """Make the requests/decisions subdirs usable, or refuse at startup.

    Raises `ApprovalDirUnusable` (a named `ValueError`-family failure) when the
    approval directory cannot serve the contract — the composition root turns
    that into a `belay:` refusal before any byte moves. The subdirs are created
    here so the first write is never the first failure.
    """
    root = Path(approval_dir)
    for name in (REQUESTS_DIR, DECISIONS_DIR):
        try:
            (root / name).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ApprovalDirUnusable(
                f"approval directory {str(root)!r} is unusable: cannot create "
                f"{name!r} ({type(exc).__name__}: {exc})"
            ) from exc
        if not (root / name).is_dir():
            raise ApprovalDirUnusable(
                f"approval directory {str(root)!r} is unusable: {name!r} exists "
                "but is not a directory"
            )


def write_request(approval_dir, hold: Hold) -> Path:
    """Write the hold's request file atomically; return its path.

    The contract fields (`hold_id`, `tool`, `request_id`, `triggers`,
    `created_at` wall time, `timeout` seconds) land in one temp file in the same
    directory, renamed into place — a reader can never observe a partial file,
    because the final name appears only once the temp is complete. Raises
    `OSError` on I/O failure; the gate's totality turns that into an
    `APPROVAL_FAULT` refusal, never a silent forward.
    """
    requests_dir = Path(approval_dir) / REQUESTS_DIR
    requests_dir.mkdir(parents=True, exist_ok=True)
    target = requests_dir / f"{hold.hold_id}.json"
    body = {
        "hold_id": hold.hold_id,
        "tool": hold.tool,
        "request_id": hold.request_id,
        "triggers": list(hold.triggers),
        # Wall time for the human; the hold's own `created_at` stays on the
        # injected clock, which is the clock the deadline is exact under.
        "created_at": time.time(),
        "timeout": hold.timeout,
    }
    fd, temp = _mkstemp(requests_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return target


def _mkstemp(directory: Path) -> tuple[int, str]:
    """tempfile in the SAME directory, so the rename never crosses filesystems.

    A cross-filesystem rename would copy rather than rename — a window in which
    the final name can exist half-written, which is exactly what the contract
    forbids.
    """
    import tempfile

    return tempfile.mkstemp(prefix=".belay-request-", dir=directory)


def read_decision(approval_dir, hold_id: str) -> Optional[dict]:
    """The human's decision for `hold_id`, or None when there is none readable.

    Absent file, malformed JSON, a missing `decision` key, and an unknown
    `decision` value all read as absent for THIS poll — the file is retried next
    tick, never guessed. The whole file is read in one `read`: a partially
    written decision is unreadable, and unreadable is absent.
    """
    path = Path(approval_dir) / DECISIONS_DIR / f"{hold_id}.json"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        decision = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(decision, dict):
        return None
    if decision.get("decision") not in (DECISION_APPROVE, DECISION_DENY):
        return None
    return decision


def await_decision(
    hold: Hold,
    *,
    read: Callable[[str], Optional[dict]],
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[dict]:
    """Poll for the hold's decision until one is found or the deadline is reached.

    Returns the decision dict, or None once the deadline owns the hold (the
    caller denies `APPROVAL_TIMEOUT`, fail-closed). One ordering, pinned: each
    tick reads the decision FIRST — a decision the poll found is a decision the
    human wrote, and it wins even when the tick's clock has already reached the
    deadline; the deadline is checked only when no decision was found. Once the
    loop has returned, nothing reads again: a decision file that appears after
    the timeout deny is never applied retroactively (M14).

    The loop never sleeps longer than `min(poll_interval, remaining)`; under the
    injected clock and a no-op `sleep` every timeout test is exact.
    """
    while True:
        decision = read(hold.hold_id)
        if decision is not None:
            return decision
        now = clock()
        if hold.expired(now):
            return None
        remaining = hold.deadline - now
        sleep(min(poll_interval, remaining) if remaining > 0 else 0.0)


def refusal_bytes(hold: Any, cause: str) -> bytes:
    """The JSON-RPC 2.0 error answering a denied `tools/call`, newline-terminated.

    Carries the request's OWN id (string, int, or null — never normalised), code
    `-32000`, a message naming the gate and the tool, and
    `data.belay.approval` naming the hold id, `decision: "deny"`, and the cause.
    Produced here, where the serialiser lives; delivered through the injected
    `deliver` callback, never through the proxy's forwarder. The fault path may
    hand a minimal stand-in (an id and tool with no hold) when no hold could be
    opened.
    """
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": getattr(hold, "request_id", None),
            "error": {
                "code": -32000,
                "message": f"approval gate denied {getattr(hold, 'tool', 'tool')}",
                "data": {
                    "belay": {
                        "approval": {
                            "hold_id": getattr(hold, "hold_id", None),
                            "decision": DECISION_DENY,
                            "cause": cause,
                        }
                    }
                },
            },
        }
    ).encode("utf-8") + b"\n"


__all__ = [
    "ApprovalDirUnusable",
    "await_decision",
    "read_decision",
    "refusal_bytes",
    "validate_dir",
    "write_request",
]