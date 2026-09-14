"""The approval gate's deny primitive in the proxy — phases 1-4 tests.

The unit tests drive `_FrameHold`'s suppress contract, `BoundedPeek`'s
delivered-stream consistency, and `_LockedChunkWriter`'s frame-atomic client
writes. The e2e section below spawns the real proxy over real stdio pipes
against a scripted server that records its stdin, answers `tools/list` with a
tool declaring `destructiveHint: true`, and echoes calls back — the
composition-root contract (env validation, the hook chain, the refusal, the
shutdown resolution) pinned from the outside.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from belay.proxy import (
    BoundedPeek,
    ObservationDesync,
    _FrameHold,
    _LockedChunkWriter,
    _pump,
    _write_all,
    run,
)
from conftest import read_trace

#: The scripted server: records every line it reads to `argv[1]`, answers
#: `tools/list` with ONE tool declaring `destructiveHint: true`, and echoes
#: `tools/call` results. With `argv[2] == "exit-after-two"` it exits after
#: answering initialize + tools/list — the shutdown test's server, which must
#: leave while a hold is parked.
APPROVAL_SERVER = r"""
import json, sys
log = open(sys.argv[1], "a", encoding="utf-8")
exit_after = len(sys.argv) > 2 and sys.argv[2] == "exit-after-two"
def emit(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()
answered = 0
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if not isinstance(msg, dict):
        continue
    log.write(line)
    log.flush()
    if msg.get("method") == "initialize":
        emit({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "approval-server", "version": "1"}}})
        answered += 1
    elif msg.get("method") == "tools/list":
        emit({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [{"name": "blast", "inputSchema": {"type": "object", "properties": {}}, "annotations": {"destructiveHint": True}}]}})
        answered += 1
    elif msg.get("method") == "tools/call":
        emit({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": "echo"}]}})
    elif "id" in msg:
        emit({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
    if exit_after and answered >= 2:
        break
"""

CLIENT = [
    b'{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{}},"id":1}',
    b'{"jsonrpc":"2.0","method":"notifications/initialized","params":null}',
    b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
    b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"blast","arguments":{}},"id":3}',
]

#: A client that never calls the destructive tool — the dormant-gate control.
CLIENT_NO_CALL = CLIENT[:3]


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


def approval_env(trace_dir, approval_dir, timeout=None):
    """The env an approval-gated run needs: trace dir ALWAYS (M16), approval
    dir, and an optional timeout — with ambient approval vars scrubbed."""
    env = os.environ.copy()
    env.pop("BELAY_APPROVAL_DIR", None)
    env.pop("BELAY_APPROVAL_TIMEOUT", None)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    env["BELAY_APPROVAL_DIR"] = str(approval_dir)
    if timeout is not None:
        env["BELAY_APPROVAL_TIMEOUT"] = str(timeout)
    return env


def trace_only_env(trace_dir):
    env = os.environ.copy()
    env.pop("BELAY_APPROVAL_DIR", None)
    env.pop("BELAY_APPROVAL_TIMEOUT", None)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    return env


def run_proxy(server_args, env, client=CLIENT, timeout=15.0):
    """Spawn the real proxy over real pipes; feed `client`; return the outcome.

    `timeout` is the shutdown bound every test asserts against: a run that
    waits out the 300s approval deadline instead of exiting is a hang, and
    `communicate` turns it into a TimeoutExpired failure rather than a 15-minute
    test.
    """
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", *server_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    payload = b"\n".join(client) + b"\n"
    stdout, stderr = proc.communicate(payload, timeout=timeout)
    elapsed = time.monotonic() - started
    return {
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed": elapsed,
    }


def run_proxy_phased(server_args, env, timeout=15.0):
    """The realistic client: handshake and `tools/list` first, WAIT for the
    server's tools/list answer, then call the destructive tool and close.

    A real client never pipelines a call ahead of the tool definitions it needs
    to make it — and the gate's facts are read at hold time, so the call must
    arrive after the cache has them. Pipelining would test the race, not the
    gate.
    """
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", *server_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        proc.stdin.write(b"\n".join(CLIENT[:3]) + b"\n")
        proc.stdin.flush()
        first = []
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            first.append(line)
            if b'"id": 2' in line or b'"id":2' in line:
                break
        proc.stdin.write(CLIENT[3] + b"\n")
        proc.stdin.flush()
        proc.stdin.close()
        stdout_rest = proc.stdout.read()
        stderr = proc.stderr.read()
        proc.wait(timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
    elapsed = time.monotonic() - started
    # The client's full stream: everything read before the call (the handshake
    # and the tools/list answer) plus whatever came after it.
    return {
        "returncode": proc.returncode,
        "stdout": b"".join(first) + stdout_rest,
        "stderr": stderr,
        "elapsed": elapsed,
    }


def server_cmd(tmp_path, mode=None):
    """The scripted server's argv: `python -c SCRIPT log [mode]`."""
    log = tmp_path / "server-stdin.log"
    argv = [sys.executable, "-c", APPROVAL_SERVER, str(log)]
    if mode is not None:
        argv.append(mode)
    return argv, log


def server_lines(log) -> list[bytes]:
    return [line for line in log.read_bytes().split(b"\n") if line]


def refusal_lines(stdout: bytes) -> list[dict]:
    """Every JSON-RPC error with the approval data, in stream order."""
    out = []
    for line in stdout.split(b"\n"):
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("error", {}).get("data", {}).get("belay"):
            out.append(message)
    return out


def write_decision(approval_dir, hold_id, decision, reason=None):
    decisions = approval_dir / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    body = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    (decisions / f"{hold_id}.json").write_text(json.dumps(body))


def trace_records(trace_dir):
    return read_trace(trace_dir)


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


# --- Phase 3: frame-atomic client writes under a shared lock -----------------


def test_without_the_lock_a_refusal_can_land_inside_a_frame():
    """The control: the same slow write, no lock, interleaves."""
    dst_r, dst_w = os.pipe()
    half1_written = threading.Event()
    refusal_done = threading.Event()

    def slow_inner(fd, chunk):
        half = len(chunk) // 2
        _write_all(fd, chunk[:half])
        half1_written.set()
        refusal_done.wait(timeout=5)
        _write_all(fd, chunk[half:])

    chunk = b"{" + b"x" * 64 + b"}\n"

    def refusal_writer():
        half1_written.wait(timeout=5)
        os.write(dst_w, b'{"refusal":1}\n')
        refusal_done.set()

    t = threading.Thread(target=refusal_writer)
    t.start()
    slow_inner(dst_w, chunk)
    t.join()
    os.close(dst_w)

    half = len(chunk) // 2
    assert _read_all(dst_r) == chunk[:half] + b'{"refusal":1}\n' + chunk[half:]


def test_the_locked_writer_keeps_a_refusal_out_of_a_frame():
    dst_r, dst_w = os.pipe()
    lock = threading.Lock()
    half1_written = threading.Event()

    def slow_inner(fd, chunk):
        half = len(chunk) // 2
        _write_all(fd, chunk[:half])
        half1_written.set()
        time.sleep(0.2)
        _write_all(fd, chunk[half:])

    wrapped = _LockedChunkWriter(slow_inner, lock)
    chunk = b"{" + b"x" * 64 + b"}\n"

    def refusal_writer():
        half1_written.wait(timeout=5)
        with lock:
            os.write(dst_w, b'{"refusal":1}\n')

    t = threading.Thread(target=refusal_writer)
    t.start()
    wrapped(dst_w, chunk)
    t.join()
    os.close(dst_w)

    assert _read_all(dst_r) == chunk + b'{"refusal":1}\n'


def test_locked_writer_flush_is_a_noop_when_the_inner_has_no_flush():
    wrapped = _LockedChunkWriter(_write_all, threading.Lock())
    wrapped.flush(12345)  # must not raise, must not invent a flush


def test_locked_writer_flush_delegates_to_a_frame_hold():
    dst_r, dst_w = os.pipe()
    held = _FrameHold(lambda frame, direction: True, "s2c")
    wrapped = _LockedChunkWriter(held, threading.Lock())

    wrapped(dst_w, b'{"id":1')  # partial: held, not forwarded
    wrapped.flush(dst_w)
    os.close(dst_w)

    assert _read_all(dst_r) == b'{"id":1'


def test_run_with_a_peer_lock_stays_byte_identical(monkeypatch):
    client_r, client_w = os.pipe()
    out_r, out_w = os.pipe()
    monkeypatch.setattr(sys, "stdin", _Fd(client_r))
    monkeypatch.setattr(sys, "stdout", _Fd(out_w))

    os.write(client_w, b'{"id":1}\n')
    os.close(client_w)

    status = run(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        peer_lock=threading.Lock(),
    )
    assert status == 0
    os.close(out_w)
    os.close(client_r)

    assert _read_all(out_r) == b'{"id":1}\n'


# --- Phase 4: the composition root (subprocess-level e2e) --------------------


def test_approval_dir_without_trace_dir_is_refused_at_startup(tmp_path):
    env = os.environ.copy()
    env.pop("BELAY_APPROVAL_DIR", None)
    env.pop("BELAY_APPROVAL_TIMEOUT", None)
    env["BELAY_APPROVAL_DIR"] = str(tmp_path / "approval")
    env.pop("BELAY_TRACE_DIR", None)

    outcome = run_proxy(server_cmd(tmp_path)[0], env)
    assert outcome["returncode"] == 2
    assert b"belay:" in outcome["stderr"]


def test_an_unusable_approval_dir_is_refused_at_startup(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where a directory is needed")
    env = approval_env(tmp_path / "trace", blocker)

    outcome = run_proxy(server_cmd(tmp_path)[0], env)
    assert outcome["returncode"] == 2
    assert b"belay:" in outcome["stderr"]


def test_an_invalid_approval_timeout_is_refused_at_startup(tmp_path):
    env = approval_env(tmp_path / "trace", tmp_path / "approval", timeout="soon")
    env["BELAY_APPROVAL_TIMEOUT"] = "not-a-number"

    outcome = run_proxy(server_cmd(tmp_path)[0], env)
    assert outcome["returncode"] == 2
    assert b"belay:" in outcome["stderr"]


def test_a_dormant_gate_is_byte_identical_to_a_no_approval_run(tmp_path):
    """The differential: the same client against the same destructive server,
    once without the approval env and once with it. Nothing triggers — the
    client never calls the destructive tool — so the approval machinery must be
    byte-invisible on the wire and leave the approval dir untouched."""
    server, log = server_cmd(tmp_path)
    no_approval = run_proxy(server, trace_only_env(tmp_path / "trace-a"), client=CLIENT_NO_CALL)
    assert no_approval["returncode"] == 0

    approval_dir = tmp_path / "approval"
    gated = run_proxy(server, approval_env(tmp_path / "trace-b", approval_dir), client=CLIENT_NO_CALL)
    assert gated["returncode"] == 0
    assert gated["stdout"] == no_approval["stdout"]
    assert gated["elapsed"] < 15.0
    assert list((approval_dir / "requests").iterdir()) == []
    assert list((approval_dir / "decisions").iterdir()) == []


def test_a_denied_call_never_reaches_the_server_and_answers_with_a_refusal(tmp_path):
    approval_dir = tmp_path / "approval"
    write_decision(approval_dir, "0-blast", "deny", reason="not now")
    server, log = server_cmd(tmp_path)
    env = approval_env(tmp_path / "trace", approval_dir)

    outcome = run_proxy_phased(server, env)
    assert outcome["returncode"] == 0
    assert outcome["elapsed"] < 15.0  # completed on client EOF: no hang

    # The client's stream carries one refusal, with the request's own id.
    refusals = refusal_lines(outcome["stdout"])
    assert len(refusals) == 1, f"expected exactly one refusal, got {refusals!r}"
    assert refusals[0]["id"] == 3
    approval = refusals[0]["error"]["data"]["belay"]["approval"]
    assert approval["hold_id"] == "0-blast"
    assert approval["decision"] == "deny"
    assert approval["cause"] == "DENIED"
    assert refusals[0]["error"]["message"] == "approval gate denied blast"

    # The server's stdin never saw the request.
    lines = server_lines(log)
    assert any(b'"method":"tools/list"' in line for line in lines)
    assert not any(b'"method":"tools/call"' in line for line in lines)

    # The trace records the hold and the decision, decision before refusal.
    records = trace_records(tmp_path / "trace")
    kinds = [r["kind"] for r in records]
    assert kinds.count("approval_hold") == 1
    assert kinds.count("approval_decision") == 1
    decision = next(r for r in records if r["kind"] == "approval_decision")
    assert decision["cause"] == "DENIED"
    assert decision["decision"] == "deny"
    assert decision["hold_id"] == "0-blast"


def test_an_approved_call_reaches_the_server_and_returns_byte_identically(tmp_path):
    server, log = server_cmd(tmp_path)
    no_approval = run_proxy_phased(server, trace_only_env(tmp_path / "trace-a"))
    assert no_approval["returncode"] == 0

    approval_dir = tmp_path / "approval"
    write_decision(approval_dir, "0-blast", "approve", reason="go")
    env = approval_env(tmp_path / "trace-b", approval_dir)

    outcome = run_proxy_phased(server, env)
    assert outcome["returncode"] == 0
    assert outcome["elapsed"] < 15.0
    # The response stream is byte-identical to the ungated run: an approved
    # call is exactly the call that would have happened anyway.
    assert outcome["stdout"] == no_approval["stdout"]

    # The request reached the server byte-identically.
    blast = next(line for line in server_lines(log) if b'"method":"tools/call"' in line)
    assert blast == CLIENT[3]

    records = trace_records(tmp_path / "trace-b")
    decision = next(r for r in records if r["kind"] == "approval_decision")
    assert decision["cause"] == "APPROVED"
    assert decision["decision"] == "approve"


def test_shutdown_with_a_pending_hold_resolves_APPROVAL_SHUTDOWN(tmp_path):
    """The client sends a destructive call and closes; the server exits after
    its second answer, leaving the hold parked. The run must exit within the
    shutdown bounds (the server's own exit — NOT the 300s approval deadline),
    and the pending hold's decision must be APPROVAL_SHUTDOWN."""
    server, log = server_cmd(tmp_path, mode="exit-after-two")
    approval_dir = tmp_path / "approval"
    env = approval_env(tmp_path / "trace", approval_dir)

    outcome = run_proxy_phased(server, env)
    assert outcome["returncode"] == 0
    assert outcome["elapsed"] < 15.0, (
        f"run took {outcome['elapsed']:.1f}s — a parked hold must not hold up "
        "shutdown beyond the server's own exit"
    )

    # The call was suppressed (never reached the server) and the shutdown
    # resolution was recorded.
    assert not any(b'"method":"tools/call"' in line for line in server_lines(log))
    records = trace_records(tmp_path / "trace")
    decisions = [r for r in records if r["kind"] == "approval_decision"]
    assert len(decisions) == 1, f"exactly one decision, got {decisions!r}"
    assert decisions[0]["cause"] == "APPROVAL_SHUTDOWN"
    assert decisions[0]["hold_id"] == "0-blast"