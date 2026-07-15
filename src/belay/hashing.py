"""Content hashes for trace frames: one over the bytes, one over their meaning.

Two hashes, because they answer different questions and neither can answer both.

`hash_raw` is over the bytes exactly as received. It is the identity of the
octets and it is never wrong, but it is too strict to compare across peers: two
servers can send semantically identical JSON with different key order or
whitespace and disagree on `hash_raw`.

`hash_canonical` is over a canonical form, so it survives that re-ordering. It
is the one that can say "the replay produced the same message". It is also the
weaker claim, because canonicalisation necessarily discards.

Both are stored. Canonicalising and discarding the original would be lossy in
exactly the direction that matters: the difference between the raw bytes and the
canonical form is itself a class of divergence the replay verdict exists to
catch, and a trace that has thrown it away cannot be asked about it later.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

# Versioned because the canonical form is part of the interchange contract: a
# reader comparing two `hash_canonical` values must know they were produced by
# the same rules, and a future v2 must be distinguishable rather than silently
# incompatible.
CANONICAL_FORM = "belay/jcs-v1"


def hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_hash(frame: bytes) -> Optional[str]:
    """Hash `frame`'s canonical form, or return None if it has none.

    `belay/jcs-v1` follows RFC 8785 (JSON Canonicalization Scheme) *semantics*:
    sorted keys, no insignificant whitespace, UTF-8 output. It is a subset, and
    these are its known divergences from RFC 8785:

    - **Numbers are not canonicalised.** RFC 8785 requires every number be
      serialised as an ECMAScript double. We emit Python's repr, so a large
      integer keeps a precision an RFC 8785 implementation would round away, and
      some exponent forms differ. Two Belay traces agree with each other; a
      Belay hash and a third-party RFC 8785 hash may not.
    - **Keys sort by Unicode code point, not UTF-16 code unit.** Python's
      `sort_keys` orders by code point. The two agree for every key in the Basic
      Multilingual Plane and disagree only when a key contains an astral
      character (U+10000 and above), which RFC 8785 would sort by its surrogate
      pair and therefore order before U+E000..U+FFFF.
    - **Non-finite numbers are accepted.** `NaN` and `Infinity` are not JSON at
      all, but Python's parser takes them and we do not police the wire.
    - **Duplicate object keys collapse** to the last occurrence, per Python's
      parser. RFC 8785 leaves this undefined.

    Every one of these is a reason to keep `hash_raw`, which has no such caveats.

    Returns None when the frame is not valid JSON — including when it is not
    valid UTF-8, which a non-conforming server can and does emit. An absent
    canonical form is an honest answer; a fabricated one is not, so this never
    falls back to hashing something else and calling it canonical.
    """
    try:
        parsed = json.loads(frame)
    except ValueError:  # JSONDecodeError, and UnicodeDecodeError for non-UTF-8
        return None
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_bytes(canonical.encode("utf-8"))
