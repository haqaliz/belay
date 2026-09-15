"""The approval gate's events, derived from the trace's additive record kinds.

`approval_hold` and `approval_decision` are first-class trace observations,
written through `TraceWriter.record` (see `belay.trace.KINDS`), so this reader
is a pure filter over records: it reports the events in `seq` order with the
recorded fields untouched, and it never repairs.

**The reader reports, never repairs.** A hold with no decision (a trace cut
mid-hold — the shutdown path) yields the hold event and nothing else: a
fabricated decision would assert an outcome that was never observed. A decision
with no preceding hold is reported as-is — the missing hold is the trace's own
statement. A `cause` outside the closed vocabulary (`APPROVED` / `DENIED` /
`APPROVAL_TIMEOUT` / `APPROVAL_SHUTDOWN` / `APPROVAL_FAULT`) passes through
untouched rather than being corrected or dropped.

**The closed-kind check.** Only the two kinds declared here are events. Any
other kind — `frame`, `connection_window`, a derived kind, or a future
approval-adjacent kind this reader does not understand — is skipped. Skipping
is by exclusion from the closed set, so it can never be mistaken for an event
and nothing is invented into one.

The kinds never describe a frame: a suppressed request and its refusal never
cross the server boundary, so no `frame` record names them and nothing from the
gate flows through the correlation machinery.
"""

from __future__ import annotations

APPROVAL_KINDS = ("approval_hold", "approval_decision")

# The closed cause vocabulary the gate writes. The reader does not validate
# against it — a value outside the set is the trace's statement, not the
# reader's to repair — but the vocabulary is named here once, where the
# contract lives.
CAUSES = (
    "APPROVED",
    "DENIED",
    "APPROVAL_TIMEOUT",
    "APPROVAL_SHUTDOWN",
    "APPROVAL_FAULT",
)

# The contract fields each kind's event carries, per the aspect's field contract.
_FIELDS = {
    "approval_hold": ("hold_id", "tool", "request_id", "triggers", "timeout"),
    "approval_decision": ("hold_id", "decision", "cause", "waited"),
}


def derive_approval_events(records: list[dict]) -> list[dict]:
    """Every approval event in the trace, in `seq` order.

    Each event is the recorded record's contract fields under its `kind`
    (`approval_hold`: `hold_id`, `tool`, `request_id`, `triggers`, `timeout`;
    `approval_decision`: `hold_id`, `decision`, `cause`, `waited`), with `seq`
    kept so an event is locatable in the trace it came from. A trace with no
    approval records yields `[]`, never a placeholder.
    """
    events = [
        {
            "kind": record["kind"],
            "seq": record["seq"],
            **{
                field: record[field]
                for field in _FIELDS[record["kind"]]
                if field in record
            },
        }
        for record in records
        if isinstance(record, dict) and record.get("kind") in APPROVAL_KINDS
    ]
    events.sort(key=lambda event: event["seq"])
    return events


__all__ = ["APPROVAL_KINDS", "CAUSES", "derive_approval_events"]