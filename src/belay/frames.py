"""Reading a frame's message back out of a trace record. One implementation.

Every derivation starts the same way: take a record, undo the base64, parse the
JSON, and cope with the frames that will not survive that. This module is the one
place that happens.

**It returns `(message, cause)`, and the cause is the reason this module exists.**
Four modules used to do this decode themselves, and the two that returned the
message alone — silently dropping the reason it was missing — were exactly the two
whose gap records were weakest. That is not a coincidence: a helper that makes it
easy to discard why something failed will have that reason discarded. A caller
here has to name the cause or visibly ignore it.

A cause is a fact about a frame, not an error. "This frame could not be read" and
"there was nothing here" are different, and a reader that cannot tell them apart
will eventually report the second when it means the first — which is the shape of
every false PASS this project exists to prevent.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

# Forwarded whole, observed short. Whatever we parse from this is a fragment, so
# we do not parse it: half a message read as if it were the message is worse than
# an acknowledged gap.
TRUNCATED = "truncated: the observed copy exceeded MAX_FRAME and is incomplete"


def message_of(record: dict) -> tuple[Optional[Any], Optional[str]]:
    """The frame's message, or `(None, cause)` naming why there isn't one.

    The message may be any JSON value: a conforming peer sends an object, but a
    non-conforming one can send a string, an array (a JSON-RPC batch) or a bare
    number, and all of those are successfully read. `None` means we could not
    read it at all — never that it read as something unexpected. Callers that
    need an object must check for one; that shape is their business, not this
    module's.
    """
    if record.get("truncated"):
        return None, TRUNCATED
    try:
        return json.loads(base64.b64decode(record["raw"])), None
    except ValueError as exc:  # invalid JSON, or bytes that are not UTF-8
        return None, f"unparseable: {type(exc).__name__}: {exc}"
