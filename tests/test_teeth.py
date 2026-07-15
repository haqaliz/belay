"""Teeth for the gate: proves `test_differential.py` can actually fail.

A passing test proves nothing until you have watched it fail on the thing it
targets. `test_differential.py` asserts the proxy is byte-identical to a direct
connection — but a differential that cannot detect a corrupting proxy is a green
light that means nothing. This test supplies the missing half: it runs the same
scripted client through a proxy that is byte-infidel *and nothing else wrong*
(`fixtures/sdk_proxy.py`), and asserts the comparison catches it.

**Do not delete this as redundant with the differential.** It is the executable
form of the rule "the MCP SDK can never sit on the forwarding path": Belay must
forward raw bytes, never parse-and-re-serialise them. It fails the moment someone
reaches for the SDK, or a `json.dumps`, to "clean up" the proxy. The differential
going green is only evidence *because* this test is also green.

Never assert byte fidelity against a hand-written expected string here: that
tests the fixture, not the proxy. The direct run is the only source of truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

from conftest import FIXTURE, run_over_pipes

SDK_PROXY = Path(__file__).parent / "fixtures" / "sdk_proxy.py"

# The tools/call reply: the richest frame the fixture emits (scrambled key order,
# a \uXXXX escape, an explicit null, an unknown field, and a non-conforming shape).
TOOLS_CALL_FRAME = 3

# The fixture emits this explicit null with NO space after the colon. A parse +
# re-serialise round-trip cannot preserve it: json.dumps' default separators put a
# space after every colon, so `"isError":null` comes back as `"isError": null`.
#
# This — not escape normalisation — is the corruption a plain json.dumps actually
# commits. The é escape survives it, because json.dumps defaults to
# ensure_ascii=True and re-escapes the character on the way out; key order survives
# too, because dicts preserve insertion order. The real MCP SDK would additionally
# normalise the escape and reorder keys. Whitespace is the corruption common to
# every parse-and-re-serialise implementation, so it is what this test pins.
UNSPACED_NULL = b'"isError":null'


def _describe(direct: list[bytes], naive: list[bytes]) -> str:
    lines = []
    for i in range(max(len(direct), len(naive))):
        d = direct[i] if i < len(direct) else b"<missing>"
        n = naive[i] if i < len(naive) else b"<missing>"
        lines.append(f"  frame {i} [{'DIFFERS' if d != n else 'same'}]")
        lines.append(f"    direct: {d!r}")
        lines.append(f"    naive : {n!r}")
    return "\n".join(lines)


def test_differential_rejects_a_reserializing_proxy(tmp_path):
    direct_lines = run_over_pipes([sys.executable, str(FIXTURE)])

    # Anti-vacuity, same reasoning as the differential: if the fixture emits
    # nothing, empty-vs-empty compares equal and this test would report "the
    # differential failed to detect corruption" when the real fault is a broken
    # fixture. Fail with the true diagnosis instead.
    assert direct_lines, (
        "fixture emitted nothing - this test cannot prove the differential has "
        "teeth when there are no bytes to corrupt"
    )
    assert len(direct_lines) == 4, (
        f"fixture emitted {len(direct_lines)} lines, expected exactly 4 - the "
        "fixture's shape changed and this test's frame indices are stale"
    )

    naive_lines = run_over_pipes(
        [sys.executable, str(SDK_PROXY), sys.executable, str(FIXTURE)]
    )

    # The naive proxy must fail ONLY on byte fidelity. If it drops frames, crashes on
    # the non-conforming frame, or swallows the interleaved notification, then any
    # difference this test finds is proof of a broken fixture, not proof that the
    # differential detects re-serialisation.
    assert len(naive_lines) == len(direct_lines), (
        f"the naive proxy forwarded {len(naive_lines)} frames but the server sent "
        f"{len(direct_lines)} - it is failing for the WRONG reason (dropping or "
        "duplicating frames, not just re-serialising them), so this test proves "
        f"nothing about the differential:\n{_describe(direct_lines, naive_lines)}"
    )

    # Specifically WHICH frame differs. A bare `direct != naive` would also be
    # satisfied by two empty lists or a crashed proxy.
    assert direct_lines[TOOLS_CALL_FRAME] != naive_lines[TOOLS_CALL_FRAME], (
        "the tools/call reply survived a parse + re-serialise round-trip "
        "BYTE-IDENTICAL, so the differential cannot detect a proxy that rebuilds "
        "frames instead of forwarding them - the gate in test_differential.py is "
        "now a green light that proves nothing:\n"
        f"{_describe(direct_lines, naive_lines)}"
    )

    # ...and a concrete, named corruption, so this test still means something if the
    # frame indices drift.
    assert UNSPACED_NULL in b"".join(direct_lines), (
        f"fixture no longer emits {UNSPACED_NULL!r} - this test's concrete "
        "corruption check is stale (see test_fixture_guard.py)"
    )
    assert UNSPACED_NULL not in b"".join(naive_lines), (
        f"the re-serialised stream still contains {UNSPACED_NULL!r}, which "
        "json.dumps' default separators cannot produce - sdk_proxy.py has stopped "
        "actually re-serialising, so this test is no longer proving the "
        "differential has teeth"
    )
