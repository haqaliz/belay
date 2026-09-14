"""The approval gate's deny primitive in the proxy — phases 1-3 unit tests.

Phase 4 (the composition root) and the subprocess-level tests are a later
task, so nothing here spawns a proxy. These drive the pieces the composition
root will wire: `_FrameHold`'s suppress contract, `BoundedPeek`'s
delivered-stream consistency, and `_LockedChunkWriter`'s frame-atomic client
writes.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from belay.proxy import (
    BoundedPeek,
    ObservationDesync,
    _FrameHold,
    _pump,
    _write_all,
    run,
)


# --- helpers ----------------------------------------------------------------


class _Fd:
    """The minimal file-like run() needs: a fileno."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd


def _read_all(fd: int) -> bytes:
    data = b""
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            return data
        data += chunk


def drive(hook, chunks, on_capture_error=None):
    """Feed chunks through a `_FrameHold` into a pipe.

    Returns (what reached the peer, the per-call suppression reports).
    """
    src_r, src_w = os.pipe()
    held = _FrameHold(hook, "c2s", on_capture_error)
    reports = []
    try:
        for chunk in chunks:
            reports.append(held(src_w, chunk))
    finally:
        os.close(src_w)
        peer = _read_all(src_r)
        os.close(src_r)
    return peer, reports


def collect(chunks, suppressions=None):
    """Feed (chunk, suppressed) pairs into a BoundedPeek; return what it emitted."""
    seen = []
    peek = BoundedPeek(lambda frame, truncated: seen.append((frame, truncated)))
    for i, chunk in enumerate(chunks):
        peek.feed(chunk, suppressions[i] if suppressions else ())
    return seen


# --- Phase 1: the suppress contract -----------------------------------------


def test_a_false_hook_suppresses_the_frame_and_reports_it():
    def deny(frame, direction):
        return False

    peer, reports = drive(deny, [b'{"id":1}\n'])
    assert peer == b""
    assert reports == [[b'{"id":1}']]


def test_a_true_hook_forwards_verbatim_and_reports_nothing():
    frame = b'{"id":1,"params":{"s":"caf\\u00e9"}}'

    def allow(frame, direction):
        return True

    peer, reports = drive(allow, [frame + b"\n"])
    assert peer == frame + b"\n"
    assert reports == [[]]


def test_suppression_of_a_frame_spanning_two_calls():
    def deny(frame, direction):
        return False

    peer, reports = drive(deny, [b'{"id":', b'1}\n'])
    assert peer == b""
    assert reports == [[], [b'{"id":1}']]


def test_a_suppressed_middle_frame_leaves_the_others_verbatim():
    def deny_only_2(frame, direction):
        return frame != b'{"id":2}'

    frames = [b'{"id":1}', b'{"id":2}', b'{"id":3}']
    peer, reports = drive(deny_only_2, [b"\n".join(frames) + b"\n"])
    assert peer == frames[0] + b"\n" + frames[2] + b"\n"
    assert reports == [[b'{"id":2}']]


def test_a_raising_hook_is_named_the_frame_is_forwarded_and_the_direction_survives():
    errors = []

    def boom(frame, direction):
        raise RuntimeError("boom")

    peer, reports = drive(boom, [b'{"id":1}\n', b'{"id":2}\n'], errors.append)
    assert peer == b'{"id":1}\n{"id":2}\n'
    assert reports == [[], []]
    assert [type(e) for e in errors] == [RuntimeError, RuntimeError]


def test_a_none_returning_hook_forwards_unchanged():
    def none(frame, direction):
        return None

    peer, reports = drive(none, [b'{"id":1}\n'])
    assert peer == b'{"id":1}\n'
    assert reports == [[]]


def test_a_bare_newline_is_never_ruled_on_even_by_a_denying_hook():
    def deny(frame, direction):
        return False

    peer, reports = drive(deny, [b"\n", b'{"id":1}\n'])
    assert peer == b"\n"
    assert reports == [[], [b'{"id":1}']]


# --- Phase 2: the observer sees the delivered stream -------------------------


def test_feed_drops_a_fully_suppressed_frame():
    seen = collect([b'{"a":1}\n{"b":2}\n'], [[b'{"a":1}']])
    assert seen == [(b'{"b":2}', False)]


def test_feed_drops_a_suppressed_frame_spanning_two_chunks():
    seen = collect(
        [b'{"id', b'":1}\n{"id":2}\n'],
        [[], [b'{"id":1}']],
    )
    assert seen == [(b'{"id":2}', False)]


def test_multiple_suppressions_in_one_feed_apply_in_order():
    seen = collect(
        [b'{"id":1}\n{"id":2}\n{"id":3}\n'],
        [[b'{"id":1}', b'{"id":3}']],
    )
    assert seen == [(b'{"id":2}', False)]


def test_a_suppression_mismatching_the_stream_kills_observation():
    seen = []
    peek = BoundedPeek(lambda frame, truncated: seen.append((frame, truncated)))
    with pytest.raises(ObservationDesync):
        peek.feed(b'{"id":1}\n', [b'{"id":99}'])
    # the delivered frame was observed before the desync was named
    assert seen == [(b'{"id":1}', False)]


def test_a_suppression_mismatching_the_buffer_prefix_kills_observation():
    peek = BoundedPeek(lambda frame, truncated: None)
    peek.feed(b'{"id', ())
    with pytest.raises(ObservationDesync):
        peek.feed(b'":1}\n', [b'{"id":99}'])


def test_pump_observes_the_delivered_stream_when_the_hook_suppresses():
    def deny_only_2(frame, direction):
        return frame != b'{"id":2}'

    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    seen = []
    peek = BoundedPeek(lambda frame, truncated: seen.append((frame, truncated)))
    held = _FrameHold(deny_only_2, "c2s")
    try:
        _write_all(src_w, b'{"id":1}\n{"id":2}\n{"id":3}\n')
        os.close(src_w)
        _pump(src_r, dst_w, peek, None, held)
    finally:
        os.close(src_r)
        os.close(dst_w)

    assert _read_all(dst_r) == b'{"id":1}\n{"id":3}\n'
    assert seen == [(b'{"id":1}', False), (b'{"id":3}', False)]


def test_pump_observed_stream_equals_the_delivered_stream_across_writes():
    def deny_only_2(frame, direction):
        return frame != b'{"id":2}'

    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    seen = []
    peek = BoundedPeek(lambda frame, truncated: seen.append((frame, truncated)))
    held = _FrameHold(deny_only_2, "c2s")
    try:
        for part in (b'{"id":1', b'}\n{"id":2', b'}\n{"id":3}\n'):
            _write_all(src_w, part)
        os.close(src_w)
        _pump(src_r, dst_w, peek, None, held)
    finally:
        os.close(src_r)
        os.close(dst_w)

    assert _read_all(dst_r) == b'{"id":1}\n{"id":3}\n'
    assert seen == [(b'{"id":1}', False), (b'{"id":3}', False)]