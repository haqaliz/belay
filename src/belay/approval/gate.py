"""The approval gate's pure decision core: parse a frame, decide, hold.

Aspect `approval-gate/decision-model`: given a c2s frame and the live
annotation facts for the tool it names, decide hold / no-hold, and model a
hold's life (pending -> approved / denied / timed out) with a closed cause
vocabulary. No I/O, no proxy coupling, no trace writes — everything here is
testable with plain bytes and dicts, and the channel aspect (the proxy hook)
composes these pieces.

Two honesty rules shape this module:

- **Never hold on doubt.** A frame that is not a single `tools/call` REQUEST
  (notification, response, batch, garbage) is forwarded untouched, and a
  `params.name` that is not a string yields no tool name. A hold is a state
  change the proxy makes; doubt must never manufacture one. Every parse here
  is structural and never raises.
- **A default is not a declaration.** `triggers_for` reads the tri-state
  vocabulary from `belay.declared` — only `declared-true` on `destructiveHint`
  or `openWorldHint` triggers a hold. The MCP spec's fail-safe defaults
  (`destructiveHint: true`, `openWorldHint: true` when omitted) are exactly the
  declarations that must NOT trigger one.

Batch JSON-RPC frames (arrays) are **never held**: holding one would require
rewriting the frame to split it, which the proxy cannot do — they are
forwarded untouched.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from belay.declared import DECLARED_TRUE

#: The annotations that trigger a hold when declared true. `readOnlyHint` and
#: `idempotentHint` describe the tool's contract with the caller; `destructiveHint`
#: and `openWorldHint` are the ones that put state the human cares about at risk.
TRIGGER_ANNOTATIONS = ("destructiveHint", "openWorldHint")

#: The closed resolution vocabulary: a hold that is not pending has exactly one
#: of these causes, and nothing else is ever written there.
APPROVED = "APPROVED"
DENIED = "DENIED"
APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
APPROVAL_SHUTDOWN = "APPROVAL_SHUTDOWN"
RESOLUTION_CAUSES = (APPROVED, DENIED, APPROVAL_TIMEOUT, APPROVAL_SHUTDOWN)

#: The human decision vocabulary, for the two causes that carry one.
DECISION_APPROVE = "approve"
DECISION_DENY = "deny"
HUMAN_DECISIONS = (DECISION_APPROVE, DECISION_DENY)

#: Pending holds are capped, mirroring `trace.py`'s `_REQUEST_INDEX_MAX`: the
#: request index is monotone, so it is bounded by eviction rather than drained.
#: Large enough that no real session evicts a hold whose reply is still awaited;
#: small enough that a long-lived proxy cannot grow without bound. The oldest
#: pending hold goes when the table is full, never the newest — the newest is
#: the one a reply is most likely still in flight for.
_PENDING_MAX = 4096


def _load(frame: bytes) -> Any:
    """Parse a frame copy, or None on any unreadable input — never raise."""
    try:
        return json.loads(frame)
    except ValueError:
        return None


def is_tools_call(frame: bytes) -> bool:
    """True exactly for a single JSON-RPC `tools/call` REQUEST.

    Structural only: a dict with `method == "tools/call"` and an `id` key
    (string, int, or null — JSON-RPC 2.0 permits null). Notifications (no
    `id`), responses (no `method`), batches (arrays), other methods, and
    unparseable bytes are all False, never raising: the hook runs on every c2s
    frame, so a raise would kill the direction it is guarding.
    """
    if not isinstance(frame, bytes):
        return False
    message = _load(frame)
    if not isinstance(message, dict):
        return False
    return message.get("method") == "tools/call" and "id" in message


def tool_name(frame: bytes) -> Optional[str]:
    """The `params.name` of a `tools/call` request, or None on any doubt.

    A non-string or absent `params.name` yields None, never a hold on doubt.
    `params` that is not an object (JSON-RPC 2.0 permits positional params)
    likewise yields None.
    """
    if not isinstance(frame, bytes):
        return None
    message = _load(frame)
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    name = params.get("name")
    return name if isinstance(name, str) else None


def request_id(frame: bytes) -> Any:
    """The JSON-RPC `id` of a `tools/call` request (string, int, null, or None).

    Absent and `null` both read as None; callers pair this with `is_tools_call`,
    which guarantees the key was present, so the two are never conflated.
    """
    if not isinstance(frame, bytes):
        return None
    message = _load(frame)
    if not isinstance(message, dict):
        return None
    return message.get("id")


def triggers_for(facts: Any) -> list[str]:
    """The declared-true trigger annotations among `facts`, in a fixed order.

    `facts` is the annotations.py shape — `{annotation: {"state": tri-state}}`
    — so the live cache (aspect 2) feeds `triggers_for` directly. Every
    tri-state except `declared-true` yields no trigger; a missing annotation,
    a non-dict entry, an absent dict, and `readOnlyHint`/`idempotentHint` (not
    trigger annotations) all yield no trigger.
    """
    if not isinstance(facts, dict):
        return []
    return [
        annotation
        for annotation in TRIGGER_ANNOTATIONS
        if isinstance(facts.get(annotation), dict)
        and facts[annotation].get("state") == DECLARED_TRUE
    ]


def make_hold_id(tool: str, seq: int) -> str:
    """`<seq>-<tool-slug>`: deterministic, unique per `seq`, filesystem-safe.

    The slug follows the `_safe_case_id` discipline (`corpus/add.py:122`): any
    character that is not alphanumeric / `-` / `_` / `.` becomes `_`, so an
    awkward tool name cannot escape a directory or name an unwriteable path. A
    tool name that leaves no alphanumeric character (empty, `..`, `///`) falls
    back to `tool` so the id never carries an empty segment.
    """
    slug = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in tool)
    if not any(c.isalnum() for c in slug):
        slug = "tool"
    return f"{seq}-{slug}"


@dataclass
class Hold:
    """One `tools/call` held pending a human decision.

    `cause` is None while pending and exactly one of `RESOLUTION_CAUSES` once
    resolved — the closed vocabulary. `decision` is the human's call when one
    was made (`approve` / `deny`); timeout and shutdown resolutions carry no
    decision. `waited` is seconds pending, from the injected clock.
    """

    hold_id: str
    request_id: Any
    tool: str
    triggers: tuple[str, ...]
    timeout: float
    deadline: float
    created_at: float
    cause: Optional[str] = None
    decision: Optional[str] = None
    waited: Optional[float] = None

    def expired(self, now: float) -> bool:
        """True once `now` has reached the deadline — the timeout owns it."""
        return now >= self.deadline

    def resolve(self, cause: str, *, decision: Optional[str] = None, now: float) -> None:
        """Resolve this hold once, with a closed cause; refuse a second resolution.

        Raises a named `ValueError` when the cause is outside `RESOLUTION_CAUSES`
        or the hold already carries a cause — a resolved hold never re-resolves.
        """
        if self.cause is not None:
            raise ValueError(
                f"hold {self.hold_id} already resolved ({self.cause}); "
                "refusing a second resolution"
            )
        if cause not in RESOLUTION_CAUSES:
            raise ValueError(
                f"hold {self.hold_id}: {cause!r} is not a closed resolution cause"
            )
        self.cause = cause
        self.decision = decision
        self.waited = now - self.created_at


class HoldRegistry:
    """Pending holds, bounded; every time-shaped decision is a function of `clock`.

    `clock` is the monotonic-clock seam: `register` reads it once to set
    `created_at` and `deadline`, and every resolution path reads time through
    it (or through an explicit `now`, which defaults to the clock). A test
    injects a fake clock and gets exact, repeatable decisions; the channel
    aspect injects the same seam with the real `time.monotonic`.

    At `_PENDING_MAX` the oldest pending hold is evicted — never the newest,
    the one a reply is most likely still in flight for — and resolved as
    `APPROVAL_SHUTDOWN` so nothing pending silently disappears: every hold this
    registry ever created is either pending or carries a closed cause.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._pending: dict[str, Hold] = {}
        self._seq = 0

    def _now(self, now: Optional[float]) -> float:
        return self._clock() if now is None else now

    def register(
        self,
        request_id: Any,
        tool: str,
        triggers: tuple[str, ...],
        timeout: float = 300.0,
    ) -> Hold:
        """Open a new pending hold; evict the oldest pending hold at the cap."""
        if not isinstance(tool, str) or not tool:
            raise ValueError(
                f"refusing to hold a call with tool {tool!r}: a hold needs a name"
            )
        if len(self._pending) >= _PENDING_MAX:
            oldest_id = next(iter(self._pending))
            oldest = self._pending.pop(oldest_id)
            oldest.resolve(APPROVAL_SHUTDOWN, now=self._clock())
        now = self._clock()
        hold = Hold(
            hold_id=make_hold_id(tool, self._seq),
            request_id=request_id,
            tool=tool,
            triggers=tuple(triggers),
            timeout=timeout,
            deadline=now + timeout,
            created_at=now,
        )
        self._seq += 1
        self._pending[hold.hold_id] = hold
        return hold

    def resolve(self, hold_id: str, decision: str, now: Optional[float] = None) -> Hold:
        """A human decision on a pending hold; refuse late or unknown resolutions.

        Only a decision observed before the deadline resolves — once the
        deadline is reached the timeout owns the resolution, so a late "approve"
        is refused by name rather than silently accepted. `decision` must be
        `approve` or `deny`; anything else is refused.
        """
        now = self._now(now)
        hold = self._pending.get(hold_id)
        if hold is None:
            raise ValueError(f"unknown hold {hold_id!r}; nothing was resolved")
        if hold.expired(now):
            raise ValueError(
                f"hold {hold_id} deadline reached; the timeout owns the resolution"
            )
        if decision not in HUMAN_DECISIONS:
            raise ValueError(
                f"hold {hold_id}: {decision!r} is not a human decision "
                f"({DECISION_APPROVE} / {DECISION_DENY})"
            )
        cause = APPROVED if decision == DECISION_APPROVE else DENIED
        hold.resolve(cause, decision=decision, now=now)
        self._pending.pop(hold_id)
        return hold

    def sweep(self, now: Optional[float] = None) -> list[Hold]:
        """Resolve every pending hold whose deadline has passed as `APPROVAL_TIMEOUT`."""
        now = self._now(now)
        timed_out = [hold for hold in self._pending.values() if hold.expired(now)]
        for hold in timed_out:
            hold.resolve(APPROVAL_TIMEOUT, now=now)
            self._pending.pop(hold.hold_id)
        return timed_out

    def close_all(self, now: Optional[float] = None) -> list[Hold]:
        """Resolve every pending hold as `APPROVAL_SHUTDOWN` (the operator closes the gate).

        Shutdown wins even over an already-reached deadline: the operator's
        explicit close is the reason, and the sweep afterwards finds nothing
        pending to re-resolve.
        """
        now = self._now(now)
        closed = list(self._pending.values())
        for hold in closed:
            hold.resolve(APPROVAL_SHUTDOWN, now=now)
        self._pending.clear()
        return closed

    def pending(self) -> list[Hold]:
        """The unresolved holds, oldest first."""
        return list(self._pending.values())

    def __len__(self) -> int:
        return len(self._pending)