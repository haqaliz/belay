"""The join: a server started by the proxy is CONTAINED, not merely snapshotted.

Until this suite existed, C2's two halves were both real and never met.
`belay.sandbox.seatbelt` could contain a process and `belay.sandbox.gate` could
snapshot a turn's pre-state, and `python -m belay.proxy` did the second and not
the first — `BELAY_SANDBOX_SCOPE` named a boundary nothing enforced. The tests
here are what makes that variable's name true, and they are the reason C2 exists
at all: per `CLAUDE.md`, the sandbox is not only containment, it is the A1 verdict
axis, and an axis that is not on the path grounds nothing.

**Three tests, and none of them means anything alone.**

`test_a_tools_call_that_escapes_the_scope_is_contained_and_recorded` is the one
that proves the point. `test_a_tools_call_that_writes_inside_the_scope_succeeds`
is its positive control: without it, a sandbox that killed the server outright —
or one that never ran it — would pass the first test perfectly. And
`test_without_a_scope_the_same_escape_lands` is the ablation: it runs the same
server, at the same path, with the sandbox off, and watches the write succeed. It
is what stops the first test passing because of a typo'd path or a fixture that
quietly stopped writing.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import read_trace

from belay.sandbox.scope import default_scope

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")

PROBE = Path(__file__).parent / "fixtures" / "probe_server.py"

INITIALIZE = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
TOOLS_CALL = b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"probe"}}'

DENIED = "Operation not permitted"


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "sub").mkdir(parents=True)
    (workspace / "keep.txt").write_bytes(b"keep")
    return workspace


def proxied(server: Path) -> list[str]:
    return [sys.executable, "-m", "belay.proxy", sys.executable, str(server)]


def gated_env(workspace: Path, tmp_path: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["BELAY_SANDBOX_SCOPE"] = str(workspace)
    env["BELAY_SNAPSHOT_DIR"] = str(tmp_path / "snaps")
    env["BELAY_TRACE_DIR"] = str(tmp_path / "trace")
    env.update(extra)
    return env


def drive(env: dict[str, str], turns: int = 1, server: Path = PROBE) -> None:
    """Run the proxy and step a client through `turns` calls, one write at a time.

    Stepped rather than batched: a client that sends everything in one write has
    the whole conversation cross before the first reply comes back, and every
    assertion about what a *turn* saw would then be an assertion about a race.
    """
    proc = subprocess.Popen(
        proxied(server),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(INITIALIZE + b"\n")
        proc.stdin.flush()
        assert proc.stdout.readline(), "no reply to initialize - the rig is broken"
        for _ in range(turns):
            proc.stdin.write(TOOLS_CALL + b"\n")
            proc.stdin.flush()
            assert proc.stdout.readline(), "no reply to tools/call - the rig is broken"
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def denials_in(trace_dir: Path) -> list[dict]:
    return [r for r in read_trace(trace_dir) if r["kind"] == "denial"]


def call_handles(trace_dir: Path) -> list[dict]:
    return [
        record["state_handle"]
        for record in read_trace(trace_dir)
        if record["kind"] == "frame"
        and record["dir"] == "c2s"
        and base64.b64decode(record["raw"]) == TOOLS_CALL
    ]


# --- Part A: the server really is contained ----------------------------------


def test_a_tools_call_that_escapes_the_scope_is_contained_and_recorded(tmp_path):
    """The test C2 exists for: a real proxy run, a real turn, a real refusal.

    The server is handed a path outside the workspace and told to write to it on
    every `tools/call`. Three things must all be true, and each covers a different
    way the other two could lie: the file must not exist (the kernel refused it),
    the trace must carry a `denial` naming that exact path (Belay saw the refusal
    rather than merely benefiting from it), and — in the positive control below —
    the same server writing *inside* the scope must succeed.
    """
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "escaped.txt"

    drive(gated_env(workspace, tmp_path, BELAY_TEST_WRITE_PATH=str(outside)))

    assert not outside.exists(), (
        "the server wrote outside its scope: the proxy did not contain it"
    )
    denials = denials_in(tmp_path / "trace")
    assert [d["path"] for d in denials] == [str(outside)], (
        f"the refusal was not recorded as a denial naming its path; got {denials!r}"
    )
    assert denials[0]["inferred"] is True
    assert denials[0]["source"] == "child-stderr"
    assert DENIED in denials[0]["detail"]


def test_a_tools_call_that_writes_inside_the_scope_succeeds(tmp_path):
    """The positive control. Without it, a sandbox that murders everything passes.

    Same server, same fixture, same code path — the only difference is which side
    of the boundary the path is on. If this fails, the test above proves that
    Belay broke the server, not that Belay contained it.
    """
    workspace = make_workspace(tmp_path)
    inside = workspace / "written.txt"

    drive(gated_env(workspace, tmp_path, BELAY_TEST_WRITE_PATH=str(inside)))

    assert inside.read_bytes() == b"escaped", "the scope was too tight for legitimate work"
    assert denials_in(tmp_path / "trace") == []


def test_without_a_scope_the_same_escape_lands(tmp_path):
    """The ablation. With the sandbox off, the write the sandbox refuses succeeds.

    This is what makes the containment test's assertion mean "the kernel refused
    it" rather than "the fixture stopped writing" or "the path was wrong". A
    containment claim with no ablation behind it is a claim about a test, not
    about a boundary.
    """
    make_workspace(tmp_path)  # side effect: lay down the workspace the drive writes from
    outside = tmp_path / "escaped.txt"

    env = os.environ.copy()
    env.pop("BELAY_SANDBOX_SCOPE", None)
    env["BELAY_TEST_WRITE_PATH"] = str(outside)

    drive(env)

    assert outside.read_bytes() == b"escaped", (
        "the unsandboxed proxy did not let the write through - the containment "
        "test above would pass for a reason that has nothing to do with the sandbox"
    )


# --- Part B: the write scope and the snapshot scope are not the same thing ----


def test_the_tmpdir_is_writable_but_never_enters_a_snapshot(tmp_path):
    """The distinction Part B is about, measured on a real run.

    The server calls `tempfile.mkstemp()` on every turn — the thing the stdlib
    does without being asked, and the reason a sandboxed `$TMPDIR` exists at all.
    Two claims, and the second is the one the threat model asked for:

    1. The temp file lands (the scope did not break the server), and
    2. it is nowhere in any turn's snapshot (temp churn does not pollute a state
       diff).

    The workspace mark is the anti-vacuity half: turn 2's snapshot must contain
    turn 1's mark, or "no temp file in the snapshot" would be satisfied by a
    snapshot that captured nothing.
    """
    workspace = make_workspace(tmp_path)
    scope = default_scope(workspace)

    drive(
        gated_env(
            workspace,
            tmp_path,
            BELAY_TEST_TEMP_FILE="1",
            BELAY_TEST_WORKSPACE_MARK=str(workspace),
        ),
        turns=2,
    )

    temp_files = sorted(Path(scope.tmpdir).glob("probe-*"))
    assert len(temp_files) == 2, f"the server could not write a temp file: {temp_files!r}"

    snaps = sorted((tmp_path / "snaps").iterdir())
    assert len(snaps) == 2, f"expected one snapshot per turn, found {snaps!r}"
    assert (snaps[1] / "mark-0").exists(), (
        "turn 2's snapshot is missing turn 1's mark - it captured nothing, and "
        "the assertion below would hold vacuously"
    )
    for snap in snaps:
        assert not list(snap.rglob("probe-*")), (
            f"a temp file reached {snap}: TMPDIR is inside the snapshot scope, and "
            f"every state diff now carries the server's temp churn"
        )
    assert [h["status"] for h in call_handles(tmp_path / "trace")] == ["present", "present"]


def test_a_unix_socket_in_the_tmpdir_does_not_make_the_turn_unrestorable(tmp_path):
    """The hazard `THREAT_MODEL.md:328-340` predicted, proven resolved.

    `substrate.guard` refuses a tree containing a socket, by name and on purpose —
    a copied socket is an empty file where a live endpoint was. So if `$TMPDIR`
    sat inside the snapshotted tree, a server that opens a unix socket in its temp
    directory would report `unrestorable` on **every single turn**: the honesty
    contract working exactly as designed, and Belay useless for that server.

    It is resolved by construction rather than by luck: the temp directory is not
    in the snapshot scope, so `guard` never sees the socket. The assertion that
    the socket is real and outside the snapshot root is what keeps this test from
    passing on a server that quietly failed to bind one.
    """
    workspace = make_workspace(tmp_path)
    scope = default_scope(workspace)

    drive(gated_env(workspace, tmp_path, BELAY_TEST_SOCKET_NAME="probe.sock"))

    sock = Path(scope.tmpdir) / "probe.sock"
    assert sock.is_socket(), "the server never bound a socket - this test proves nothing"
    assert not sock.is_relative_to(workspace), (
        "the socket is inside the snapshotted tree; `guard` will refuse every turn"
    )
    handles = call_handles(tmp_path / "trace")
    assert [h["status"] for h in handles] == ["present"], (
        f"a socket in the server's temp dir poisoned the turn: {handles!r}"
    )


# --- Part A, the other half: an unsandboxed run is still C1's byte pump -------


def test_no_scope_means_a_plain_popen(monkeypatch, tmp_path):
    """With nothing configured, the argv reaching `Popen` is the user's, verbatim.

    Asserted at the composition root rather than end-to-end, because "the same
    code path, zero overhead" is a claim about what was *not* added, and an
    end-to-end run cannot see the absence of a wrapper — only the argv can.
    """
    from belay import proxy

    seen: dict = {}

    def fake_run(command, capture=None, before_frame=None, stderr_capture=None):
        seen.update(
            command=command,
            capture=capture,
            before_frame=before_frame,
            stderr_capture=stderr_capture,
        )
        return 0

    monkeypatch.setattr(proxy, "run", fake_run)
    monkeypatch.delenv("BELAY_SANDBOX_SCOPE", raising=False)
    monkeypatch.delenv("BELAY_TRACE_DIR", raising=False)

    assert proxy.main(["srv", "--flag"]) == 0

    assert seen == {
        "command": ["srv", "--flag"],
        "capture": None,
        "before_frame": None,
        "stderr_capture": None,
    }


def test_a_scope_puts_sandbox_exec_in_front_of_the_command(monkeypatch, tmp_path):
    """The composition, stated as argv: `sandbox-exec -f <profile> env TMPDIR=... <cmd>`.

    `seatbelt.run` cannot be reused for this — it is run-to-completion, and the
    proxy needs a long-lived child with live pipes — so the profile is built and
    the argv is composed instead. The profile itself is `build_profile`'s, not a
    second copy of the policy.
    """
    from belay import proxy
    from belay.sandbox import seatbelt

    workspace = make_workspace(tmp_path)
    seen: dict = {}

    def fake_run(command, capture=None, before_frame=None, stderr_capture=None):
        seen.update(command=command, profile=Path(command[2]).read_text())
        seen["mode"] = oct(Path(command[2]).stat().st_mode & 0o777)
        seen["before_frame"] = before_frame
        seen["stderr_capture"] = stderr_capture
        return 0

    monkeypatch.setattr(proxy, "run", fake_run)
    monkeypatch.setenv("BELAY_SANDBOX_SCOPE", str(workspace))
    monkeypatch.setenv("BELAY_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("BELAY_TRACE_DIR", str(tmp_path / "trace"))

    assert proxy.main([sys.executable, "srv.py"]) == 0

    scope = default_scope(workspace)
    assert seen["command"][:2] == [seatbelt.SANDBOX_EXEC, "-f"]
    assert seen["command"][3:] == scope.wrap([sys.executable, "srv.py"])
    assert seen["mode"] == "0o600", "a writable profile is a policy anyone can rewrite"
    assert f'(subpath "{scope.snapshot_root}")' in seen["profile"]
    assert f'(subpath "{scope.tmpdir}")' in seen["profile"]
    assert seen["before_frame"] is not None, "a scope must still install the turn gate"
    assert seen["stderr_capture"] is not None, "a scope must still watch for denials"


def test_the_profile_does_not_outlive_the_run(monkeypatch, tmp_path):
    """A profile left behind is a policy on disk with nothing owning it."""
    from belay import proxy

    workspace = make_workspace(tmp_path)
    seen: dict = {}

    def fake_run(command, capture=None, before_frame=None, stderr_capture=None):
        seen["profile_path"] = command[2]
        return 0

    monkeypatch.setattr(proxy, "run", fake_run)
    monkeypatch.setenv("BELAY_SANDBOX_SCOPE", str(workspace))
    monkeypatch.setenv("BELAY_SNAPSHOT_DIR", str(tmp_path / "snaps"))

    proxy.main(["srv"])

    assert not Path(seen["profile_path"]).exists()
