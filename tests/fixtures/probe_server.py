"""A fake MCP server that probes the boundary it is run inside, on every `tools/call`.

`mutating_server.py` answers "did the snapshot outrun the server?". This one
answers the questions Task 9 joins the two halves for: **is the server actually
contained, does it still get a usable temp directory, and does what it leaves
there reach the snapshot?**

Every behaviour is opt-in through the environment, so one fixture can be the
contained side of a containment test and the positive control of the same test
without the two differing in anything but a path:

- ``BELAY_TEST_WRITE_PATH`` — on each `tools/call`, write to this path. If the
  write is refused, report it in the shape a Unix tool reports one
  (``prog: subject: Operation not permitted``), because that is the only shape
  `seatbelt._denials_from_stderr` can infer a denial from, and inferring from
  the child's own words is all Belay ever gets (Seatbelt reports to the system
  log, not to the child). **The reply is identical either way** — a server whose
  reply admitted the refusal would let a test conclude "contained" from a
  cooperative server rather than from the kernel.
- ``BELAY_TEST_WORKSPACE_MARK`` — on each `tools/call`, drop `mark-<n>` here, so
  a later turn's snapshot has something from an earlier turn to have captured.
  Without it, "the snapshot does not contain the temp file" could pass on a
  snapshot that captured nothing at all.
- ``BELAY_TEST_TEMP_FILE`` — on each `tools/call`, call `tempfile.mkstemp()`.
  Through the stdlib on purpose: setting `$TMPDIR` and then asserting on `$TMPDIR`
  would prove only that a variable can be set. This is the call a real server
  makes without being asked to.
- ``BELAY_TEST_SOCKET_NAME`` — bind a unix socket of this name in the temp
  directory, **at startup**, before any turn. `substrate.guard` refuses a tree
  containing a socket, by name, so the placement of this one decides whether
  every turn of this run is `unrestorable`. That is the hazard the threat model
  predicted; the test that drives this is what proves it resolved.

Replies are canned and ignore the request id. This fixture is deliberately NOT
used in a byte-identity comparison — `fake_server.py` is the one that must never
serialise at runtime — so a canned reply here costs nothing and keeps the server
from having an opinion about anything the tests assert on.
"""

import json
import os
import socket
import sys
import tempfile

REPLY_INITIALIZE = (
    b'{"result":{"protocolVersion":"2025-11-25","capabilities":{},'
    b'"serverInfo":{"name":"probe","version":"1"}},"jsonrpc":"2.0","id":1}\n'
)

REPLY_TOOLS_LIST = (
    b'{"result":{"tools":[{"name":"probe","inputSchema":{"type":"object"}}]},'
    b'"jsonrpc":"2.0","id":2}\n'
)

REPLY_TOOLS_CALL = b'{"result":{"content":[{"type":"text","text":"probed"}]},"jsonrpc":"2.0","id":3}\n'


def _report(path: str, exc: OSError) -> None:
    """Say we were refused, in the words a denial can be inferred from."""
    detail = os.strerror(exc.errno) if exc.errno is not None else str(exc)
    print(f"probe-server: {path}: {detail}", file=sys.stderr, flush=True)


def _probe(turn: int) -> None:
    target = os.environ.get("BELAY_TEST_WRITE_PATH")
    if target:
        try:
            with open(target, "wb") as handle:
                handle.write(b"escaped")
        except OSError as exc:
            _report(target, exc)

    mark = os.environ.get("BELAY_TEST_WORKSPACE_MARK")
    if mark:
        with open(os.path.join(mark, f"mark-{turn}"), "wb") as handle:
            handle.write(b"mark")

    if os.environ.get("BELAY_TEST_TEMP_FILE"):
        handle_fd, path = tempfile.mkstemp(prefix="probe-")
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(b"temp churn")
        print(f"probe-server: temp {path}", file=sys.stderr, flush=True)


def _bind_socket() -> None:
    name = os.environ.get("BELAY_TEST_SOCKET_NAME")
    if not name:
        return
    path = os.path.join(tempfile.gettempdir(), name)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(path)
    except OSError as exc:
        _report(path, exc)
        return
    sock.listen(1)
    # Never closed, never unlinked: a server holding a live socket in its temp
    # directory for the whole run is exactly the case being tested.
    print(f"probe-server: socket {path}", file=sys.stderr, flush=True)


def main() -> None:
    _bind_socket()
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    turn = 0

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")

        if method == "tools/call":
            _probe(turn)
            turn += 1
            stdout.write(REPLY_TOOLS_CALL)
            stdout.flush()
        elif method == "initialize":
            stdout.write(REPLY_INITIALIZE)
            stdout.flush()
        elif method == "tools/list":
            stdout.write(REPLY_TOOLS_LIST)
            stdout.flush()


if __name__ == "__main__":
    main()
