"""Anti-vacuity guard: proves the fake server is still hostile.

**Repo norm, not a one-off: every differential test in this repo needs an
anti-vacuity guard.** A differential compares two runs and asserts they match (or
don't). If the thing under comparison degenerates - the fixture emits nothing, both
sides go empty - the comparison still passes, and proves nothing. A green suite that
proves nothing is exactly the corrupt-success failure mode Belay exists to catch, so
it must never be allowed to happen inside Belay's own tests.

This is real history, not hypothesis: during prototyping this differential passed
vacuously. The fake server had a syntax error, both runs emitted nothing, and empty
compared equal to empty. Green, and worthless.

`test_differential.py` guards against the fixture emitting *nothing*. This file
guards the complementary risk: the fixture still runs, still emits four frames, but
has been quietly *sanitised* - someone "tidies" the canned bytes, the escapes and
scrambled key order go away, and the byte-identity assertion becomes a comparison of
two boring streams that any naive re-serialising proxy would also pass.

Asserts on the bytes the fixture actually EMITS, not on its source. Source can
contain every hostile byte while the process emits nothing at all.
"""

from __future__ import annotations

import sys

from conftest import FIXTURE, run_over_pipes

# The literal bytes c-a-f-\-u-0-0-e-9: a JSON \uXXXX escape for é, NOT the encoded
# character. Written as an escaped backslash rather than pasted, because pasting the
# real character is the exact corruption being guarded against.
UNICODE_ESCAPE = b"caf\\u00e9"


def test_fixture_still_carries_hostile_bytes():
    lines = run_over_pipes([sys.executable, str(FIXTURE)])

    assert lines, (
        "fixture emitted nothing - every differential built on it now passes "
        "vacuously by comparing empty to empty (this exact failure already "
        "happened once, via a syntax error in the fake server)"
    )
    blob = b"\n".join(lines)

    assert UNICODE_ESCAPE in blob, (
        f"fixture lost its {UNICODE_ESCAPE!r} escape - the differential is now "
        "vacuous against any proxy that re-encodes text, because there is no "
        "escape left to normalise"
    )
    assert b'"isError":null' in blob, (
        'fixture lost its explicit \'"isError":null\' - the differential can no '
        "longer catch a proxy that drops null-valued fields or respaces them"
    )
    assert b"belayFuture" in blob, (
        "fixture lost its unknown top-level field 'belayFuture' - the differential "
        "can no longer catch a proxy that validates frames against a fixed schema "
        "and silently strips fields it does not recognise"
    )
    assert b"notifications/tools/list_changed" in blob, (
        "fixture lost its interleaved unsolicited notification - the differential "
        "can no longer catch a proxy modelled as strict request/response, which "
        "would drop or reorder server-originated messages"
    )

    tools_call = next((line for line in lines if b"belayFuture" in line), None)
    assert tools_call is not None, (
        "fixture no longer emits a frame carrying 'belayFuture' - the key-order "
        "guard below has nothing to inspect"
    )
    assert tools_call.index(b'"params"') < tools_call.index(b'"method"'), (
        "fixture lost its scrambled key order ('params' no longer precedes "
        "'method') - the differential is now vacuous against any proxy that "
        "rebuilds frames in a canonical key order:\n"
        f"  {tools_call!r}"
    )
