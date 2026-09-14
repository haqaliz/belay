"""Belay approval gate — hold risky tool calls pending human approval.

Package marker and the composition helper. Modules are imported directly
(`belay.approval.gate`, `belay.approval.channel`, `belay.approval.reader`);
`compose` is the hook-chain the proxy root installs, kept here so the proxy
stays free of the approval vocabulary.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

#: The directions the proxy passes to `before_frame`, named here once so the
#: chain can tell a request from a reply.
CLIENT_TO_SERVER = "c2s"
SERVER_TO_CLIENT = "s2c"


def compose(approval: Any, turn_gate: Optional[Callable[[bytes, str], Any]]):
    """Chain the approval hook ahead of the turn gate, per direction.

    c2s: `decide_c2s` runs FIRST — `False` (denied or faulted) returns `False`
    and the turn gate never runs, because a denied call is not a turn and must
    not snapshot anything. s2c: `observe_s2c` runs, then the turn gate — both
    forward. A `None` turn gate (an unsandboxed run) is handled: the approval
    hook alone rules.

    The returned hook never raises on its own: `decide_c2s` is total by
    contract (internal faults suppress and refuse with `APPROVAL_FAULT`) and
    `TurnGate.before_frame` never raises — and the proxy names and forwards on
    any raise anyway (`_FrameHold._run`). A denied call is reported to the
    observer as suppressed, exactly like any other suppressed frame.
    """

    def hook(frame: bytes, direction: str) -> bool:
        if approval is not None:
            if direction == CLIENT_TO_SERVER:
                if not approval.decide_c2s(frame):
                    return False
            else:
                approval.observe_s2c(frame)
        if turn_gate is None:
            return True
        return turn_gate(frame, direction)

    return hook


__all__ = ["CLIENT_TO_SERVER", "SERVER_TO_CLIENT", "compose"]