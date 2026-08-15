"""Does the Landlock+seccomp sandbox actually contain an escape, and is it recorded?

The Linux analogues of the macOS escape matrix (`tests/test_containment.py`),
with the same anti-vacuity discipline: every vector asserts the process ran,
tried, was refused — exact rc, the refusal marker in stderr, the target file
absent — AND that a `denial` record names the path. The markers differ from
macOS by decision (A1 measured it): filesystem refusals are Landlock's EACCES
("Permission denied"), network refusals are seccomp's EPERM ("Operation not
permitted"); the record shape is identical (`inferred: true, source:
"child-stderr"`).

These tests need a real Linux kernel with Landlock (kernel >= 5.13 with the
LSM enabled — measured working on the pinned ubuntu-24.04 CI image). They skip
everywhere else; the policy logic they prove is pinned platform-neutrally in
`tests/test_linux_policy.py`, which runs everywhere.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from belay.sandbox import launch, linux
from belay.sandbox.seatbelt import NetworkPolicy
from belay.trace import TraceWriter

from conftest import read_trace

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="landlock-seccomp-only: the Landlock+seccomp sandbox is Linux-only"
)


def _require_landlock() -> None:
    if linux.landlock_abi() is None:
        pytest.skip("landlock-unavailable: Landlock is unavailable on this kernel (landlock_abi() returned None)")


def _scope_and_outside(tmp_path: Path) -> tuple[Path, Path]:
    """Two real directories, both realpath'd."""
    scope = Path(str((tmp_path / "scope").resolve()))
    outside = Path(str((tmp_path / "outside").resolve()))
    scope.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)
    return scope, outside


def _denials(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("kind") == "denial"]


def _vectors(scope: Path, outside: Path) -> dict[str, tuple[list[str], Path, str]]:
    # The interpreter is /bin/bash, NOT /bin/sh: the exact-rc claim needs a
    # known interpreter, and Ubuntu's /bin/sh is dash, which exits 2 when a
    # redirection fails where bash exits 1 (measured on the first real Linux
    # run). The runner ships bash at /bin/bash; the marker + absent-target
    # assertions still discriminate even if it did not.
    return {
        "direct_write": (
            ["/bin/bash", "-c", f"echo pwned > {outside}/direct.txt"],
            outside / "direct.txt",
            f"{outside}/direct.txt",
        ),
        "dotdot_traversal": (
            ["/bin/bash", "-c", f"cd {scope} && echo pwned > ../outside/trav.txt"],
            outside / "trav.txt",
            # The child reports the path AS IT WROTE IT - relative, exactly as
            # on macOS; recording the resolved path would be guessing at a cwd.
            "../outside/trav.txt",
        ),
        "symlink_out": (
            ["/bin/bash", "-c", f"echo pwned > {scope}/link/sym.txt"],
            outside / "sym.txt",
            f"{scope}/link/sym.txt",
        ),
        "mv_out": (
            ["/bin/bash", "-c", f"mv {scope}/movable.txt {outside}/moved.txt"],
            outside / "moved.txt",
            f"{outside}/moved.txt",
        ),
        "grandchild_write": (
            ["/bin/bash", "-c", f"/bin/bash -c 'echo pwned > {outside}/grand.txt'"],
            outside / "grand.txt",
            f"{outside}/grand.txt",
        ),
    }


@pytest.mark.parametrize(
    "vector",
    ["direct_write", "dotdot_traversal", "symlink_out", "mv_out", "grandchild_write"],
)
def test_escape_vector_is_contained_and_recorded(tmp_path: Path, vector: str) -> None:
    """The escape matrix, mirror-for-mirror of the macOS one. Four assertions
    per vector, all load-bearing: absent target, exact rc, EACCES marker in
    stderr, and a denial record naming the path the child reported."""
    _require_landlock()
    scope, outside = _scope_and_outside(tmp_path)
    (scope / "link").symlink_to(outside)
    (scope / "movable.txt").write_text("seed\n")

    command, target, reported = _vectors(scope, outside)[vector]

    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        result = linux.run(command, scope=scope, network=NetworkPolicy.deny_all(), trace=writer)
    finally:
        writer.close()

    assert not target.exists(), f"{vector}: escaped the sandbox and wrote {target}"
    assert result.rc == 1, (
        f"{vector}: expected rc=1 (the child tried and was refused), got {result.rc}: "
        f"{result.stderr!r}"
    )
    assert b"Permission denied" in result.stderr, (
        f"{vector}: stderr does not show Landlock's EACCES refusal: {result.stderr!r}"
    )

    denials = _denials(read_trace(tmp_path / "trace"))
    assert len(denials) == 1, f"{vector}: expected exactly one denial record, got {denials!r}"
    assert denials[0]["path"] == reported, (
        f"{vector}: denial recorded {denials[0]['path']!r}, child reported {reported!r}"
    )
    assert denials[0]["op"] == "file-write"
    assert denials[0]["inferred"] is True
    assert denials[0]["source"] == "child-stderr"


def test_the_same_write_inside_scope_succeeds(tmp_path: Path) -> None:
    """The positive control: without it, every containment assertion above is
    satisfied by a boundary that denies everything."""
    _require_landlock()
    scope, _ = _scope_and_outside(tmp_path)
    target = scope / "inside.txt"

    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        result = linux.run(
            ["/bin/sh", "-c", f"echo ok > {target}"],
            scope=scope,
            network=NetworkPolicy.deny_all(),
            trace=writer,
        )
    finally:
        writer.close()

    assert result.rc == 0, f"an allowed write failed: {result.stderr!r}"
    assert target.read_text() == "ok\n"
    assert _denials(read_trace(tmp_path / "trace")) == []


def _loopback_listener() -> tuple[int, threading.Thread, socket.socket]:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve() -> None:
        try:
            conn, _ = server.accept()
            conn.sendall(b"reached\n")
            conn.close()
        except OSError:
            return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server.getsockname()[1], thread, server


_CONNECT = (
    "import socket,sys\n"
    "try:\n"
    "    s=socket.socket(); s.settimeout(5)\n"
    "    s.connect((sys.argv[1], int(sys.argv[2]))); print('CONNECT_OK')\n"
    "except PermissionError as e:\n"
    "    print('DENIED', e); sys.exit(3)\n"
)


def test_deny_all_refuses_a_loopback_connection_with_a_live_listener(tmp_path: Path) -> None:
    """The listener is live, so a refusal is the sandbox and not an absent
    server. Under deny-all the seccomp filter refuses `socket(AF_INET)` itself
    — the child cannot even create the socket. The socket creation sits INSIDE
    the try (measured on the first real Linux run: created outside it, the
    refusal surfaced as an uncaught traceback and the DENIED path was
    unreachable)."""
    _require_landlock()
    scope, _ = _scope_and_outside(tmp_path)
    port, thread, server = _loopback_listener()
    try:
        denied = linux.run(
            [sys.executable, "-c", _CONNECT, "127.0.0.1", str(port)],
            scope=scope,
            network=NetworkPolicy.deny_all(),
        )
        assert denied.rc == 3, f"deny-all did not deny loopback: {denied.stdout!r}"
        assert b"DENIED" in denied.stdout
    finally:
        server.close()
        thread.join(timeout=2)


def test_allow_all_reaches_the_very_same_loopback_listener(tmp_path: Path) -> None:
    """The positive control for the network axis: same listener, same client,
    `allow-all` means NO network filter — the reachability above (and its
    denial) is the seccomp filter's doing, not the listener's absence."""
    _require_landlock()
    scope, _ = _scope_and_outside(tmp_path)
    port, thread, server = _loopback_listener()
    try:
        reached = linux.run(
            [sys.executable, "-c", _CONNECT, "127.0.0.1", str(port)],
            scope=scope,
            network=NetworkPolicy.allow_all(),
        )
        assert reached.rc == 0, f"loopback was not reachable under allow-all: {reached.stderr!r}"
        assert b"CONNECT_OK" in reached.stdout
    finally:
        server.close()
        thread.join(timeout=2)


def test_a_contained_server_may_open_a_unix_socket(tmp_path: Path) -> None:
    """The AF_UNIX half of the seccomp decision, proven: a server may LISTEN on
    a unix socket inside its scope under deny-all — `socket(AF_UNIX)` is the
    one domain the filter allows, exactly like the macOS `network-bind` grant."""
    _require_landlock()
    base = Path(tempfile.mkdtemp(prefix="belay-s-")).resolve()
    scope, outside = base / "s", base / "o"
    scope.mkdir()
    outside.mkdir()
    try:
        sock = scope / "server.sock"

        result = linux.run(
            [
                sys.executable,
                "-c",
                f"import socket; s=socket.socket(socket.AF_UNIX); s.bind({str(sock)!r}); s.listen(1)",
            ],
            scope=scope,
            network=NetworkPolicy.deny_all(),
        )
        assert result.rc == 0, result.stderr.decode(errors="replace")
        assert sock.is_socket()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_an_uncaught_network_denial_is_recorded_with_a_network_op(tmp_path: Path) -> None:
    """A child that does not catch the refusal reports it to stderr, and the
    denial record carries the network op — seccomp's EPERM is distinguishable
    from the filesystem EACCES."""
    _require_landlock()
    scope, _ = _scope_and_outside(tmp_path)
    port, thread, server = _loopback_listener()
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        result = linux.run(
            [
                sys.executable,
                "-c",
                "import socket,sys\ns=socket.socket(); s.connect((sys.argv[1], int(sys.argv[2])))\n",
                "127.0.0.1",
                str(port),
            ],
            scope=scope,
            network=NetworkPolicy.deny_all(),
            trace=writer,
        )
    finally:
        server.close()
        thread.join(timeout=2)
        writer.close()

    assert result.rc == 1, result.stderr.decode(errors="replace")
    assert b"Operation not permitted" in result.stderr
    denials = _denials(read_trace(tmp_path / "trace"))
    assert len(denials) == 1
    assert denials[0]["op"] == "network"
    assert denials[0]["inferred"] is True
    assert denials[0]["source"] == "child-stderr"


def test_allow_ports_is_a_named_cause_refusal(tmp_path: Path) -> None:
    """M7, at the API: `allow-ports` cannot mean on Linux what it means on
    macOS (Landlock's net domain has no address scope), so it is refused with
    a name — before anything spawns."""
    _require_landlock()
    scope, _ = _scope_and_outside(tmp_path)

    with pytest.raises(linux.NetworkPolicyUnsupported, match="port"):
        linux.run(["true"], scope=scope, network=NetworkPolicy.allow_ports([8080]))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(linux.NetworkPolicyUnsupported):
        with launch.contained(
            ["srv"], workspace=workspace, network=launch.network_policy("allow-ports:8080")
        ):
            pass


def test_a_real_interpreter_runs_to_completion_inside_the_boundary(tmp_path: Path) -> None:
    """The liveness control: the boundary must not strangle a real runtime at
    launch — an MCP server is an interpreter, not a shell builtin."""
    _require_landlock()
    scope, _ = _scope_and_outside(tmp_path)

    result = linux.run(
        [sys.executable, "-c", "print('the interpreter reached its own code')"],
        scope=scope,
        network=NetworkPolicy.deny_all(),
    )

    assert result.rc == 0, (
        f"a real interpreter could not start under the boundary: {result.stderr!r}"
    )
    assert b"the interpreter reached its own code" in result.stdout


def test_launch_contained_yields_the_linux_argv_and_runs_it_contained(tmp_path: Path) -> None:
    """Spec criterion 3: `launch.contained` composes the Linux argv — the
    launcher — and spawning that argv runs the command contained. The policy
    file is the `profile`: owner-only, and gone after the block."""
    _require_landlock()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with launch.contained(
        ["/bin/bash", "-c", f"echo pwned > {outside}/x.txt"],
        workspace=workspace,
        network=launch.network_policy(None),
    ) as spawn:
        assert spawn.argv[:3] == [sys.executable, "-m", "belay.sandbox.linux"]
        assert "--" in spawn.argv

        policy = json.loads(spawn.profile)
        assert policy["version"] == 1
        assert set(policy["write_roots"]) == set(spawn.scope.write_roots)
        assert policy["network"] == "deny-all"

        path = Path(spawn.profile_path)
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        assert path.read_text() == spawn.profile

        denied = subprocess.run(spawn.argv, capture_output=True)
        assert denied.returncode == 1, denied.stderr.decode(errors="replace")
        assert b"Permission denied" in denied.stderr

    assert not path.exists()
    assert not (outside / "x.txt").exists()


def test_launch_contained_positive_control(tmp_path: Path) -> None:
    """And the same argv does NOT refuse the server's own work: a write inside
    the workspace (via the wrapped `env` that redirects TMPDIR into scope)
    succeeds."""
    _require_landlock()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with launch.contained(
        ["/bin/sh", "-c", 'echo ok > "$TMPDIR/ok.txt"'],
        workspace=workspace,
        network=launch.network_policy(None),
    ) as spawn:
        ok = subprocess.run(spawn.argv, capture_output=True)

    assert ok.returncode == 0, ok.stderr.decode(errors="replace")
