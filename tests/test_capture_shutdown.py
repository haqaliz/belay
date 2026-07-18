"""The capture branch's shutdown: what happens to bytes at the edges of a run.

Every test here pins one property: **bytes that crossed Belay either reach the
trace or leave a named cause behind.** Never neither. A frame that vanishes while
the trace still reads as a clean, complete capture is a false-completeness claim,
which is the exact failure this project exists to catch — so it must not happen
inside the product.

Three edges, all of them "the stream ended and something was still in flight":
forwarding died mid-chunk, the stream ended mid-frame, and the proxy stopped
observing while the client was still writing.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from belay.proxy import BoundedPeek, _pump, run


class Sink:
    """A CaptureSink that only remembers. Structural, like the real one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.observed: list[tuple[str, bytes]] = []
        self.errors: list[tuple[str, BaseException]] = []

    def observer(self, direction: str):
        def observe(frame: bytes, truncated: bool) -> None:
            with self._lock:
                self.observed.append((direction, frame))

        return observe

    def capture_error(self, direction: str, cause: BaseException) -> None:
        with self._lock:
            self.errors.append((direction, cause))


class Fd:
    """A stdio stand-in: the pumps only ever ask for a file descriptor."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd


def test_a_chunk_that_fails_to_forward_is_observed_and_the_failure_is_named():
    """C-2: the chunk is already out of the source pipe when forwarding dies.

    Returning here drops bytes that Belay has already taken custody of, and says
    nothing about why. The bytes existed; the trace must say so, and must say why
    forwarding stopped.
    """
    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    os.write(src_w, b'{"a":1}\n')
    os.close(src_w)
    os.close(dst_r)  # the destination is gone: the forward will EPIPE

    seen: list[tuple[bytes, bool]] = []
    causes: list[BaseException] = []
    _pump(src_r, dst_w, BoundedPeek(lambda f, t: seen.append((f, t))), causes.append)
    os.close(dst_w)

    assert seen == [(b'{"a":1}', False)]
    assert len(causes) == 1, f"expected exactly one named cause, got {causes!r}"
    assert isinstance(causes[0], OSError)


def test_a_trailing_partial_frame_at_eof_is_named_not_dropped():
    """I-2: the stream ended mid-frame. Those bytes were forwarded to the peer.

    Mid-stream this buffer is correct — more is coming. At EOF nothing more is
    coming, and the same silence becomes data loss.
    """
    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    os.write(src_w, b'{"a":1}\n{"partial"')
    os.close(src_w)

    seen: list[tuple[bytes, bool]] = []
    causes: list[BaseException] = []
    _pump(src_r, dst_w, BoundedPeek(lambda f, t: seen.append((f, t))), causes.append)
    os.close(dst_w)
    os.close(dst_r)

    # The complete frame still lands as a frame: a partial frame is not a frame,
    # so the residue is named rather than promoted into one.
    assert seen == [(b'{"a":1}', False)]
    assert len(causes) == 1, f"expected exactly one named cause, got {causes!r}"
    assert "mid-frame" in str(causes[0])
    # `{"partial"` is 10 bytes: the cause must say how much went unrecorded.
    assert "10 bytes" in str(causes[0])


def test_a_clean_eof_names_nothing():
    """The counterpart: a stream that ended ON a frame boundary lost nothing.

    Without this, the test above would pass just as well against a pump that
    cried loss on every EOF.
    """
    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    os.write(src_w, b'{"a":1}\n')
    os.close(src_w)

    seen: list[tuple[bytes, bool]] = []
    causes: list[BaseException] = []
    _pump(src_r, dst_w, BoundedPeek(lambda f, t: seen.append((f, t))), causes.append)
    os.close(dst_w)
    os.close(dst_r)

    assert seen == [(b'{"a":1}', False)]
    assert causes == []


def _rig(monkeypatch) -> tuple[int, Sink]:
    """Wire a real client stdin pipe into run()'s stdio. Returns (client_w, sink)."""
    client_r, client_w = os.pipe()
    out_r, out_w = os.pipe()
    monkeypatch.setattr(sys, "stdin", Fd(client_r))
    monkeypatch.setattr(sys, "stdout", Fd(out_w))
    return client_w, Sink()


def test_the_shutdown_rig_observes_a_frame_while_the_proxy_is_live(monkeypatch):
    """Anti-vacuity for the test below: the same rig, and the frame IS observed.

    Without this, "nothing was observed" could just mean the rig never delivered
    anything to observe.
    """
    client_w, sink = _rig(monkeypatch)
    os.write(client_w, b'{"early":1}\n')

    run(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.readline())"],
        capture=sink,
    )

    assert ("c2s", b'{"early":1}') in sink.observed
    assert ("s2c", b'{"early":1}') in sink.observed


def test_a_frame_the_client_sends_after_run_returns_is_never_observed(monkeypatch):
    """C-1: run() returns while the c2s daemon may still be reading the client.

    main() closes the writer at exactly the point run() returns. A frame observed
    after that goes to a closed fd, degrades to a stderr line nobody parses, and
    leaves a trace with a matched open/close pair and no capture_error — a
    capture that reads as complete and is not.

    So the property is not "the late frame is recorded" (it cannot be: the window
    has closed). It is that run() has **stopped observing** before it returns, so
    the window's close means what the format says it means: we observed
    everything up to it.
    """
    client_w, sink = _rig(monkeypatch)

    run([sys.executable, "-c", "pass"], capture=sink)

    # main()'s `finally: writer.close()` runs here.
    os.write(client_w, b'{"late":1}\n')
    time.sleep(0.5)  # give the daemon every chance to read and observe it

    assert sink.observed == [], (
        "the capture branch observed a frame after run() returned, i.e. after the "
        f"writer was closed: {sink.observed!r}"
    )
    assert sink.errors == [], f"and named a cause into a closed writer: {sink.errors!r}"
