"""How Belay records a boolean flag the wire may or may not have carried.

One idea, in one place, because two different parts of the protocol need it and
getting it wrong in either has the same consequence.

**A default is not a declaration.** The MCP spec supplies a value for several
flags when the wire omits them: tool annotations default to `readOnlyHint:
false` / `destructiveHint: true` / `idempotentHint: false` / `openWorldHint:
true`, and an absent `isError` is *assumed* false. Those assumptions are correct
for deciding how to *treat* a message. They are wrong to record, because they
erase the difference between **the peer said false** and **the peer said
nothing** — and the trace is the evidence a later verdict is grounded in.

Concretely: an un-annotated tool recorded as `readOnlyHint: false` licenses the
reasoning *"it mutated, and it never claimed read-only, therefore fine -> PASS"*.
The tool declared nothing. The only honest verdict is UNVERIFIED. The PASS was
manufactured here, by this layer, out of a default — which is why **no spec
default appears anywhere in this package**, not even as a constant. There is
deliberately nothing here for a future edit to reach for.

The fourth state, `declared-non-boolean`, is for the wire as it is rather than as
it should be. Servers are third-party code, and one that sends
`readOnlyHint: "yes"` has declared *something*: recording `not-declared` would
lose the declaration, and recording `declared-true` would invent a boolean it
never sent. The raw value rides along so a reader can see exactly what arrived.
"""

from __future__ import annotations

from typing import Any

DECLARED_TRUE = "declared-true"
DECLARED_FALSE = "declared-false"
NOT_DECLARED = "not-declared"
DECLARED_NON_BOOLEAN = "declared-non-boolean"

STATES = (DECLARED_TRUE, DECLARED_FALSE, NOT_DECLARED, DECLARED_NON_BOOLEAN)


def declared_state(value: Any, present: bool) -> dict:
    """Record what the wire said about a flag, and nothing more.

    `present` is passed separately rather than inferred from a sentinel: `null`
    is a value a server really sends, and it is not the same as absence.
    """
    if not present:
        return {"state": NOT_DECLARED}
    # `is True` / `is False`, never truthiness: `1` and `"yes"` are not booleans,
    # and coercing them here would fabricate a declaration the peer never made.
    if value is True:
        return {"state": DECLARED_TRUE}
    if value is False:
        return {"state": DECLARED_FALSE}
    return {"state": DECLARED_NON_BOOLEAN, "declared_value": value}
