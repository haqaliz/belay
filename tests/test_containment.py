"""Does the Seatbelt sandbox actually contain an escape, and is the denial recorded?

Every assertion here is about a claim Belay would otherwise be making on trust.
The escape matrix is the security claim; the positive controls are what stop the
matrix from passing for the wrong reason.

**Read this before adding a vector.** A test that asserts only "the file was not
written" passes against a sandbox that kills the process at launch, against a
sandbox that denies everything including the user's own work, and against a typo
in the command that made the write never run. All three are indistinguishable
from containment if the only evidence is an absent file. So every vector asserts
the process ran, tried, and was refused: exact rc, exact stderr, absent file, and
a recorded denial naming the path.
"""

from __future__ import annotations

import shlex
import socket
import sys
import threading
from pathlib import Path

import pytest

from belay.sandbox.seatbelt import (
    NetworkPolicy,
    UnsupportedPlatform,
    build_profile,
    run,
)
from belay.trace import TraceWriter

from conftest import read_trace

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Seatbelt is macOS-only; the module raises elsewhere"
)


def _scope_and_outside(tmp_path: Path) -> tuple[Path, Path]:
    """Two real directories, both realpath'd.

    `tmp_path` sits under /private/var/folders on macOS, but resolving both ends
    anyway keeps the fixture honest about M3 rather than accidentally correct.
    """
    scope = Path(str((tmp_path / "scope").resolve()))
    outside = Path(str((tmp_path / "outside").resolve()))
    scope.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)
    return scope, outside


def _denials(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("kind") == "denial"]


# Each vector: (id, build_command, target_that_must_not_exist, path_the_child_reports)
def _vectors(scope: Path, outside: Path) -> dict[str, tuple[list[str], Path, str]]:
    return {
        "direct_write": (
            ["/bin/sh", "-c", f"echo pwned > {outside}/direct.txt"],
            outside / "direct.txt",
            f"{outside}/direct.txt",
        ),
        "dotdot_traversal": (
            ["/bin/sh", "-c", f"cd {scope} && echo pwned > ../outside/trav.txt"],
            outside / "trav.txt",
            # The child reports the path AS IT WROTE IT - relative. Recording an
            # absolute path here would mean resolving it against a cwd we are
            # guessing at, which is precision the mechanism does not give us.
            "../outside/trav.txt",
        ),
        "symlink_out": (
            ["/bin/sh", "-c", f"echo pwned > {scope}/link/sym.txt"],
            outside / "sym.txt",
            f"{scope}/link/sym.txt",
        ),
        "mv_out": (
            ["/bin/sh", "-c", f"mv {scope}/movable.txt {outside}/moved.txt"],
            outside / "moved.txt",
            f"{outside}/moved.txt",
        ),
        "grandchild_write": (
            # The sandbox is inherited across fork/exec. An MCP shell server is
            # mostly a process spawner, so a boundary that held only for the
            # direct child would be worthless in the shape we actually ship.
            ["/bin/sh", "-c", f"/bin/sh -c 'echo pwned > {outside}/grand.txt'"],
            outside / "grand.txt",
            f"{outside}/grand.txt",
        ),
    }


@pytest.mark.parametrize(
    "vector",
    ["direct_write", "dotdot_traversal", "symlink_out", "mv_out", "grandchild_write"],
)
def test_escape_vector_is_contained_and_recorded(tmp_path: Path, vector: str) -> None:
    """A2 - the escape matrix. Four assertions per vector, and all four are load-bearing."""
    scope, outside = _scope_and_outside(tmp_path)
    (scope / "link").symlink_to(outside)
    (scope / "movable.txt").write_text("seed\n")

    command, target, reported = _vectors(scope, outside)[vector]

    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        result = run(command, scope=scope, network=NetworkPolicy.deny_all(), trace=writer)
    finally:
        writer.close()

    assert not target.exists(), f"{vector}: escaped the sandbox and wrote {target}"
    # NOT 134, NOT 137: those are the process being killed before it could act,
    # which would make the absent file above prove nothing at all.
    assert result.rc == 1, f"{vector}: expected rc=1 (the child tried and was refused), got {result.rc}"
    assert "Operation not permitted" in result.stderr.decode(), (
        f"{vector}: stderr does not show a refusal: {result.stderr!r}"
    )

    denials = _denials(read_trace(tmp_path / "trace"))
    assert len(denials) == 1, f"{vector}: expected exactly one denial record, got {denials!r}"
    assert denials[0]["path"] == reported, (
        f"{vector}: denial recorded {denials[0]['path']!r}, child reported {reported!r}"
    )
    assert denials[0]["op"] == "file-write"


def test_the_same_write_inside_scope_succeeds(tmp_path: Path) -> None:
    """A3 - the sandbox permits the work it is supposed to permit.

    Without this, every containment assertion above is satisfied by a profile
    that denies everything, and Belay would ship a sandbox that breaks its user's
    own MCP server while looking rigorous.
    """
    scope, _ = _scope_and_outside(tmp_path)
    target = scope / "inside.txt"

    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        result = run(
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


def test_a_real_interpreter_runs_to_completion_inside_the_sandbox(tmp_path: Path) -> None:
    """A3 - the profile does not strangle a real runtime at launch.

    An MCP server is an interpreter, not a shell builtin, so this is the shape we
    actually ship. It is a general liveness control and NOT the mach-lookup
    guard - see the test below, which is, and which was separated out only after
    mutation testing showed this one passes happily with mach-lookup removed.
    """
    scope, _ = _scope_and_outside(tmp_path)

    result = run(
        [sys.executable, "-c", "print('the interpreter reached its own code')"],
        scope=scope,
        network=NetworkPolicy.deny_all(),
    )

    assert result.rc == 0, f"a real interpreter could not start under the profile: {result.stderr!r}"
    assert "the interpreter reached its own code" in result.stdout.decode()


@pytest.mark.skipif(
    not Path("/usr/bin/python3").exists(), reason="stock macOS python3 shim not present"
)
def test_the_stock_python3_shim_survives_the_profile(tmp_path: Path) -> None:
    """A3 - the mach-lookup guard, and the ONE test that actually holds that line.

    MEASURED by mutation, not assumed. Removing `(allow mach-lookup)` from the
    profile leaves EVERY escape vector green, leaves `/bin/sh` green, leaves
    Homebrew python and node green - and breaks exactly this: `/usr/bin/python3`
    exits **72** without ever running its own code, because the xcrun shim cannot
    reach the bootstrap server to resolve `DARWIN_USER_TEMP_DIR` via `confstr`.

    That asymmetry is the whole trap. A profile can be broken in a way that only
    a stock `python3 -m some_mcp_server` reveals, while a containment suite built
    on `/bin/sh` reports total success. This test is what makes mach-lookup's
    presence a checked fact rather than a line nobody dares touch.

    (Recorded because the brief predicted otherwise: `/bin/sh` dying at rc=134
    SIGABRT without mach-lookup did NOT reproduce on this machine at any point.)
    """
    scope, _ = _scope_and_outside(tmp_path)

    result = run(
        ["/usr/bin/python3", "-c", "print('the shim reached its own code')"],
        scope=scope,
        network=NetworkPolicy.deny_all(),
    )

    assert result.rc == 0, (
        f"the stock python3 shim could not start under the profile (rc={result.rc}); "
        f"if this is 72, (allow mach-lookup) is missing: {result.stderr!r}"
    )
    assert "the shim reached its own code" in result.stdout.decode()


def test_scope_given_through_a_symlink_behaves_identically(tmp_path: Path) -> None:
    """A9 - M3. /tmp is a symlink to private/tmp; an unresolved subpath grants nothing.

    MEASURED: a profile granting `(subpath "/tmp/x")` denies a write to /tmp/x
    itself. Belay would be handing users a policy that silently denies their own
    work while looking correct on the page.
    """
    real = Path("/private/tmp") / f"belay-a9-{tmp_path.name}"
    real.mkdir(parents=True, exist_ok=True)
    through_symlink = Path("/tmp") / real.name
    try:
        result = run(
            ["/bin/sh", "-c", f"echo ok > {through_symlink}/a.txt"],
            scope=through_symlink,
            network=NetworkPolicy.deny_all(),
        )
        assert result.rc == 0, (
            f"scope given as /tmp/... was not resolved, so the profile granted nothing: {result.stderr!r}"
        )
        assert (real / "a.txt").read_text() == "ok\n"

        # ... and the profile text itself names the resolved path, which is the
        # actual mechanism rather than a happy accident downstream.
        assert f'(subpath "{real}")' in build_profile(
            scope=through_symlink, network=NetworkPolicy.deny_all()
        )
    finally:
        for child in real.glob("*"):
            child.unlink()
        real.rmdir()


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
    "s=socket.socket(); s.settimeout(5)\n"
    "try:\n"
    "    s.connect((sys.argv[1], int(sys.argv[2]))); print('CONNECT_OK')\n"
    "except PermissionError as e:\n"
    "    print('DENIED', e); sys.exit(3)\n"
)


def test_loopback_is_reachable_while_real_egress_is_denied(tmp_path: Path) -> None:
    """A3 - the network positive control, both halves under ONE profile.

    Without the reachable half, an unplugged network passes the egress test
    forever. The listener is host-side and trusted: the sandboxed process is only
    ever the client, and is never granted network-inbound (VERIFIED in the spike:
    `(local ip "localhost:*")` does NOT confine the bind address, only the port).
    """
    scope, _ = _scope_and_outside(tmp_path)
    port, thread, server = _loopback_listener()
    try:
        policy = NetworkPolicy.allow_ports([port])

        reached = run(
            [sys.executable, "-c", _CONNECT, "127.0.0.1", str(port)],
            scope=scope,
            network=policy,
        )
        assert reached.rc == 0, f"loopback was not reachable under allow-ports: {reached.stderr!r}"
        assert "CONNECT_OK" in reached.stdout.decode()

        # Same profile, real external host. 1.1.1.1 is the verified-denied
        # vector. NOT this machine's own LAN IP: the spike measured that
        # self-addressed traffic is delivered over the loopback path by the
        # kernel regardless of sandboxing, so it succeeds and would make this
        # assertion fail for a reason that is not a sandbox leak.
        egress = run(
            [sys.executable, "-c", _CONNECT, "1.1.1.1", "80"],
            scope=scope,
            network=policy,
        )
        assert egress.rc == 3, f"egress to a real external host was not denied: {egress.stdout!r}"
        assert "DENIED" in egress.stdout.decode()
    finally:
        server.close()
        thread.join(timeout=2)


def test_deny_all_denies_the_very_same_loopback_connection(tmp_path: Path) -> None:
    """A3 - proves the grant is the CAUSE of the reachability above.

    Same listener, same client, same everything except the policy. If this
    connected too, the test above would be measuring nothing.
    """
    scope, _ = _scope_and_outside(tmp_path)
    port, thread, server = _loopback_listener()
    try:
        denied = run(
            [sys.executable, "-c", _CONNECT, "127.0.0.1", str(port)],
            scope=scope,
            network=NetworkPolicy.deny_all(),
        )
        assert denied.rc == 3, f"deny-all did not deny loopback: {denied.stdout!r}"
    finally:
        server.close()
        thread.join(timeout=2)


def test_a_port_outside_the_allowlist_is_denied(tmp_path: Path) -> None:
    """A3 - allow-ports scopes BY PORT, and the denied port has a live listener.

    MEASURED before being relied on. The live listener is the point: a refused
    connection to a port where nothing listens proves nothing about the sandbox.
    """
    scope, _ = _scope_and_outside(tmp_path)
    allowed_port, thread_a, server_a = _loopback_listener()
    other_port, thread_b, server_b = _loopback_listener()
    try:
        result = run(
            [sys.executable, "-c", _CONNECT, "127.0.0.1", str(other_port)],
            scope=scope,
            network=NetworkPolicy.allow_ports([allowed_port]),
        )
        assert result.rc == 3, (
            f"a port outside the allowlist was reachable (listener was live): {result.stdout!r}"
        )
    finally:
        server_a.close()
        server_b.close()
        thread_a.join(timeout=2)
        thread_b.join(timeout=2)


def test_network_policy_rejects_a_hostname_allowlist() -> None:
    """A8 - refuse at the API rather than accept-and-not-enforce.

    `(remote ip "1.1.1.1:*")` is a COMPILE ERROR: 'host must be * or localhost in
    network address'. Accepting a hostname and quietly dropping it would be
    claiming a boundary we do not enforce, which is the one thing CLAUDE.md
    forbids outright - and the user would believe traffic was confined to their
    allowlist while it was in fact confined to nothing.
    """
    for rejected in ("api.example.com", "1.1.1.1", "localhost:8080", "1.1.1.1:80"):
        with pytest.raises(ValueError, match="host"):
            NetworkPolicy.allow_ports([rejected])  # type: ignore[list-item]


def test_network_mode_is_a_closed_enum() -> None:
    with pytest.raises(ValueError, match="allow-hosts"):
        NetworkPolicy(mode="allow-hosts")


def test_network_policy_is_recorded_as_a_fact(tmp_path: Path) -> None:
    """M9 - a fact, not a verdict. C2 does not decide replayability; C4 does."""
    scope, _ = _scope_and_outside(tmp_path)
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        run(["/bin/sh", "-c", "true"], scope=scope, network=NetworkPolicy.deny_all(), trace=writer)
    finally:
        writer.close()

    policies = [r for r in read_trace(tmp_path / "trace") if r.get("kind") == "network_policy"]
    assert len(policies) == 1
    assert policies[0]["policy"] == "deny-all"
    verdict_shaped = {"PASS", "WARN", "FAIL", "UNVERIFIED", "replayable", "verdict"}
    assert not verdict_shaped & set(map(str, policies[0].values())) | verdict_shaped & set(
        policies[0]
    ), f"C2 wrote something verdict-shaped: {policies[0]!r}"


def test_denial_records_state_their_own_provenance(tmp_path: Path) -> None:
    """The denial is INFERRED from the child's failure, and must say so.

    Seatbelt does not hand us a structured 'I denied X' event. A record that read
    as though the kernel told us would be a false precision claim - committed by
    the project whose entire thesis is that claims must be grounded.
    """
    scope, outside = _scope_and_outside(tmp_path)
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        run(
            ["/bin/sh", "-c", f"echo pwned > {outside}/x.txt"],
            scope=scope,
            network=NetworkPolicy.deny_all(),
            trace=writer,
        )
    finally:
        writer.close()

    denial = _denials(read_trace(tmp_path / "trace"))[0]
    assert denial["inferred"] is True
    assert denial["source"] == "child-stderr"
    # The verbatim line is the ground truth; `path` is derived from it.
    assert "Operation not permitted" in denial["detail"]


def test_a_clean_exit_records_no_denial(tmp_path: Path) -> None:
    """Anti-vacuity: the recorder must not simply always write a denial."""
    scope, _ = _scope_and_outside(tmp_path)
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        run(["/bin/sh", "-c", "echo fine"], scope=scope, network=NetworkPolicy.deny_all(), trace=writer)
    finally:
        writer.close()
    assert _denials(read_trace(tmp_path / "trace")) == []


def test_a_nonzero_exit_that_is_not_a_denial_records_no_denial(tmp_path: Path) -> None:
    """rc=1 alone is not a denial. Most programs exit 1 for their own reasons."""
    scope, _ = _scope_and_outside(tmp_path)
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        result = run(
            ["/bin/sh", "-c", "echo 'ordinary failure' >&2; exit 1"],
            scope=scope,
            network=NetworkPolicy.deny_all(),
            trace=writer,
        )
    finally:
        writer.close()
    assert result.rc == 1
    assert _denials(read_trace(tmp_path / "trace")) == []


def test_run_without_a_trace_still_contains(tmp_path: Path) -> None:
    """Containment is the sandbox's job and does not depend on the recorder."""
    scope, outside = _scope_and_outside(tmp_path)
    result = run(
        ["/bin/sh", "-c", f"echo pwned > {outside}/no-trace.txt"],
        scope=scope,
        network=NetworkPolicy.deny_all(),
    )
    assert result.rc == 1
    assert not (outside / "no-trace.txt").exists()


def test_scope_must_exist(tmp_path: Path) -> None:
    """realpath() only resolves components that exist.

    A scope that does not exist cannot be resolved, so the profile would be built
    from an unresolved path - the exact M3 failure, arriving silently.
    """
    with pytest.raises(ValueError, match="does not exist"):
        run(["/bin/sh", "-c", "true"], scope=tmp_path / "nope", network=NetworkPolicy.deny_all())


def test_profile_has_the_verified_shape(tmp_path: Path) -> None:
    """The profile is VERIFIED WORKING as a whole; pin the load-bearing lines."""
    scope, _ = _scope_and_outside(tmp_path)
    profile = build_profile(scope=scope, network=NetworkPolicy.deny_all())
    for line in (
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow file-read*)",
        f'(allow file-write* (subpath "{scope}"))',
        "(deny network*)",
    ):
        assert line in profile, f"missing from the verified profile: {line}"


def test_a_scope_containing_a_quote_cannot_break_out_of_the_profile(tmp_path: Path) -> None:
    """A path is attacker-influenced data being pasted into a policy language.

    Unescaped, `"` would terminate the string and the rest of the path would be
    read as SBPL - a policy injection into the thing enforcing the policy.
    """
    scope = Path(str(tmp_path.resolve())) / 'we"ird'
    scope.mkdir()
    profile = build_profile(scope=scope, network=NetworkPolicy.deny_all())
    assert '(allow file-write* (subpath "' + str(scope).replace('"', '\\"') + '"))' in profile

    target = scope / "ok.txt"
    result = run(
        ["/bin/sh", "-c", f"echo ok > {shlex.quote(str(target))}"],
        scope=scope,
        network=NetworkPolicy.deny_all(),
    )
    assert result.rc == 0, f"a legitimate quoted path was broken by escaping: {result.stderr!r}"
    assert target.read_text() == "ok\n"


def test_allow_all_is_not_the_default_and_must_be_asked_for(tmp_path: Path) -> None:
    scope, _ = _scope_and_outside(tmp_path)
    assert "(allow network*)" in build_profile(scope=scope, network=NetworkPolicy.allow_all())
    assert "(allow network*)" not in build_profile(scope=scope, network=NetworkPolicy.deny_all())


def test_unsupported_platform_is_raised_not_silently_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Elsewhere, raise. A no-op sandbox that returns success is a false claim of containment."""
    scope, _ = _scope_and_outside(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatform, match="macOS-only"):
        run(["/bin/sh", "-c", "true"], scope=scope, network=NetworkPolicy.deny_all())
