"""The capture branch: frames observed from a bounded copy of the stream.

These cover BoundedPeek in isolation. What they deliberately do NOT cover is the
data path: that byte-exactness is the differential test's job, and it stays that
way precisely because nothing here can reach the forwarded bytes.
"""

from __future__ import annotations

from belay.proxy import MAX_FRAME, BoundedPeek


def collect(chunks: list[bytes]) -> list[tuple[bytes, bool]]:
    seen: list[tuple[bytes, bool]] = []
    peek = BoundedPeek(lambda frame, truncated: seen.append((frame, truncated)))
    for chunk in chunks:
        peek.feed(chunk)
    return seen


def test_splits_newline_delimited_frames():
    assert collect([b'{"id":1}\n{"id":2}\n']) == [(b'{"id":1}', False), (b'{"id":2}', False)]


def test_reassembles_a_frame_split_across_chunks():
    # Pipe reads land on arbitrary boundaries, not frame boundaries.
    assert collect([b'{"id', b'":1}\n']) == [(b'{"id":1}', False)]


def test_emits_nothing_until_a_frame_is_complete():
    assert collect([b'{"id":1}']) == []


def test_ignores_blank_lines():
    assert collect([b"\n\n"]) == []


def test_observes_bytes_verbatim():
    hostile = b'{"params":{"s":"caf\\u00e9"},"isError":null,"belayFuture":"KEEP"}'
    assert collect([hostile + b"\n"]) == [(hostile, False)]


def test_oversized_frame_is_bounded_and_flagged():
    oversized = b"x" * (MAX_FRAME + 1024)
    assert collect([oversized + b"\n"]) == [(b"x" * MAX_FRAME, True)]


def test_recovers_after_an_oversized_frame():
    # The bound applies per frame; the next one must be observed intact.
    seen = collect([b"x" * (MAX_FRAME + 1), b"\n", b'{"id":2}\n'])
    assert seen[1] == (b'{"id":2}', False)
