"""The default scope: does the common case need zero configuration?

This suite is the falsifiable half of the claim in `scope.py`'s docstring. The
claim is not "the profile is reasonable" — it is that a real MCP server, given
nothing but a workspace, runs. If it does not, the user widens the scope by hand
and the boundary becomes user-authored, which is the risk this module exists to
retire.

So the tests are shaped as pairs wherever they can be: the default works, **and**
the thing the default does would be needed — `test_..._is_load_bearing` runs the
same child without the redirect and observes the denial that a user would have
been handed instead. A default nobody can prove necessary is a default nobody can
prove correct.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from belay.sandbox import seatbelt
from belay.sandbox.scope import DefaultScope, default_scope

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")


def _write_to(target: str) -> list[str]:
    """A child that writes one byte to `target`, reporting the refusal if refused."""
    return ["/bin/sh", "-c", f'echo hi > "{target}"']


def _run(command, scope: DefaultScope, *, wrap: bool = True) -> seatbelt.SandboxResult:
    return seatbelt.run(
        scope.wrap(command) if wrap else list(command),
        scope=scope.write_roots,
        network=seatbelt.NetworkPolicy.deny_all(),
    )


# --- The scope resolves to what the kernel will actually match ----------------


def test_the_workspace_is_realpathed(tmp_path: Path) -> None:
    """A scope that is not realpathed grants nothing. See `seatbelt._resolved_scope`.

    `/tmp` is a symlink to `private/tmp`, so a workspace reached through it must
    still resolve to the path the kernel matches the profile against.
    """
    link = tmp_path / "link"
    real = tmp_path / "real"
    real.mkdir()
    link.symlink_to(real)

    scope = default_scope(link)

    assert scope.snapshot_root == os.path.realpath(str(real))
    assert not Path(scope.snapshot_root).is_symlink()


def test_the_tmpdir_is_realpathed_and_granted_but_never_snapshotted(tmp_path: Path) -> None:
    """The two scopes are different scopes, and this is where that is stated.

    Three claims, each load-bearing for a different reason. Unresolved, the profile
    would not match it and the grant would silently be nothing. Outside
    `write_roots`, the server dies on its first temp file. Inside `snapshot_root`,
    every turn's state diff carries the server's temp churn and a unix socket in
    there makes every turn `unrestorable` — which is why it is *outside* the
    workspace rather than a subtree someone remembers to exclude.
    """
    scope = default_scope(tmp_path)

    assert scope.tmpdir == os.path.realpath(scope.tmpdir)
    assert Path(scope.tmpdir).is_dir()
    assert scope.tmpdir in scope.write_roots
    assert not Path(scope.tmpdir).is_relative_to(scope.snapshot_root), (
        "the temp dir is inside the tree the gate snapshots"
    )


def test_the_tmpdir_is_owner_only(tmp_path: Path) -> None:
    """It sits in a directory shared with the whole machine, and the child's
    scratch — which may be the agent's data — goes in it."""
    scope = default_scope(tmp_path)

    assert oct(Path(scope.tmpdir).stat().st_mode & 0o777) == "0o700"


def test_the_tmpdir_exists_before_the_child_starts(tmp_path: Path) -> None:
    """`realpath` cannot resolve a path that is not there, and a child handed a
    `TMPDIR` that does not exist fails for a reason that looks like a denial."""
    scope = default_scope(tmp_path)
    assert Path(scope.tmpdir).is_dir()


def test_a_workspace_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        default_scope(tmp_path / "nope")


# --- The tmpdir is a predictable path, so adopting one is a decision ----------
#
# The name is `belay-tmp-<sha256(realpath(workspace))[:16]>`: a pure, documented
# function of the workspace, and therefore knowable by anyone who knows where the
# agent works. Whatever is at that path is `realpath`ed into `write_roots` and
# lands in the profile as `(allow file-write* (subpath ...))`. That makes this the
# one path in Belay whose resolution decides what the sandbox grants — so it is
# adopted only when it is provably ours, and refused loudly otherwise.
#
# `launch.py` already asserts the *profile's* mode is exactly 0o600 for this
# reasoning. These are the same rigour one call earlier, on the input that decides
# what the profile says.
#
# Bounded, and stated precisely: on stock macOS `gettempdir()` is the per-user
# `/var/folders/.../T` (mode 0700), so an attacker must already share the uid. It
# is NOT bounded when `TMPDIR` is unset or points at world-writable `/tmp` — CI,
# containers, cron, launchd. The contained server cannot mount this itself (it can
# only write inside its own grant), so it is a local same-user / misconfigured
# TMPDIR issue rather than an agent escape.


def _squattable_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private temp root, and the exact path `default_scope` will pick in it.

    The path is learned by *calling* `default_scope`, never by recomputing the
    digest here: a test that reimplemented the naming rule would keep passing if
    production stopped following it, and would be proving its own arithmetic. That
    the first call's answer is still the second call's answer IS the predictability
    the attack needs — so the rig demonstrates it rather than asserting it.
    """
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmproot))
    workspace = tmp_path / "ws"
    workspace.mkdir()

    predicted = Path(default_scope(workspace).tmpdir)
    os.rmdir(predicted)  # the attacker gets there first, next run
    return predicted


def test_a_symlink_at_the_predicted_tmpdir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The squat: plant a link at the known name and the profile follows it.

    Without the check this is not a near miss — `os.makedirs(..., exist_ok=True)`
    validates nothing about a path that already exists (`mode=` is ignored
    outright), `realpath` then dutifully resolves the link, and the sandbox grants
    the contained server write access to a directory the attacker chose.
    """
    predicted = _squattable_tmpdir(tmp_path, monkeypatch)
    elsewhere = tmp_path / "attacker-chosen"
    elsewhere.mkdir(mode=0o700)
    predicted.symlink_to(elsewhere)

    with pytest.raises(ValueError, match="refusing to adopt"):
        default_scope(tmp_path / "ws")


def test_a_file_at_the_predicted_tmpdir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not every squat is a link, and a plain file must not be mistaken for one:
    it is refused for what it is, so the diagnostic names the real obstacle."""
    predicted = _squattable_tmpdir(tmp_path, monkeypatch)
    predicted.write_bytes(b"not a directory")

    with pytest.raises(ValueError, match="refusing to adopt"):
        default_scope(tmp_path / "ws")


def test_a_widened_tmpdir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real directory, ours, but group/world writable.

    `os.makedirs(..., mode=0o700, exist_ok=True)` silently ignores `mode` on a
    path that exists, so this is what "adopted with a mode we never checked" looks
    like: everything the child writes to its scratch — which is the agent's data —
    readable and replaceable by anyone on the box.
    """
    predicted = _squattable_tmpdir(tmp_path, monkeypatch)
    predicted.mkdir(mode=0o777)
    os.chmod(predicted, 0o777)  # defeat any umask: the point is the mode on disk

    with pytest.raises(ValueError, match="refusing to adopt"):
        default_scope(tmp_path / "ws")


def test_our_own_tmpdir_is_adopted_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control, and it is not a formality.

    Idempotence is why the name is a digest in the first place: a `TMPDIR` that
    moved between turns would strand the previous turn's files somewhere the
    server had already been told about. A refusal that fired on Belay's own
    directory would break every second run — so "refuse what is not ours" must
    mean exactly that, and no more.
    """
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmproot))
    workspace = tmp_path / "ws"
    workspace.mkdir()

    first = default_scope(workspace)
    Path(first.tmpdir, "scratch").write_bytes(b"the previous turn's file")
    second = default_scope(workspace)

    assert second.tmpdir == first.tmpdir
    assert Path(second.tmpdir, "scratch").read_bytes() == b"the previous turn's file"


# --- The zero-config claim ---------------------------------------------------


def test_a_child_writes_to_its_tmpdir_under_the_default_scope(tmp_path: Path) -> None:
    scope = default_scope(tmp_path)

    result = _run(["/bin/sh", "-c", 'echo hi > "$TMPDIR/scratch"'], scope)

    assert result.rc == 0, result.stderr.decode(errors="replace")
    assert result.denials == ()
    assert (Path(scope.tmpdir) / "scratch").read_bytes() == b"hi\n"


def test_the_sandboxed_tmpdir_is_load_bearing(tmp_path: Path) -> None:
    """The ablation. Without the redirect the same child is REFUSED.

    This is the test that turns the default from a preference into a mechanism:
    the real `$TMPDIR` is `/var/folders/...`, outside any workspace, so a server
    that writes a temp file — which is most of them — dies unless someone widens
    the scope by hand. That hand-widening is R3.
    """
    scope = default_scope(tmp_path)

    # No `wrap`: the child inherits the machine's real TMPDIR, outside the scope.
    result = _run(["/bin/sh", "-c", 'echo hi > "$TMPDIR/scratch"'], scope, wrap=False)

    assert result.rc != 0
    assert result.denials, "expected the real TMPDIR to be refused by the profile"
    assert not Path(result.denials[0].path or "").is_relative_to(scope.snapshot_root)


def test_python_tempfile_lands_in_the_sandboxed_tmpdir(tmp_path: Path) -> None:
    """The mechanism has to work through the stdlib a real server actually calls.

    `tempfile` consults `TMPDIR`, `TEMP` and `TMP` in that order — testing the
    env var directly would prove only that we can set a variable.
    """
    scope = default_scope(tmp_path)
    program = "import tempfile; h, p = tempfile.mkstemp(); print(p)"

    result = _run([sys.executable, "-c", program], scope)

    assert result.rc == 0, result.stderr.decode(errors="replace")
    assert Path(result.stdout.decode().strip()).is_relative_to(scope.tmpdir)


def test_the_stock_python3_shim_runs_under_the_default_scope(tmp_path: Path) -> None:
    """`python3 -m some_mcp_server` is the shape we ship in front of.

    `seatbelt.py` keeps `(allow mach-lookup)` for this child specifically; this
    asserts the default scope does not undo that from the other side.
    """
    scope = default_scope(tmp_path)

    result = _run(["/usr/bin/python3", "-c", "import tempfile; print(tempfile.mkdtemp())"], scope)

    assert result.rc == 0, result.stderr.decode(errors="replace")
    assert Path(result.stdout.decode().strip()).is_relative_to(scope.tmpdir)


def test_a_child_writes_to_the_workspace_itself(tmp_path: Path) -> None:
    scope = default_scope(tmp_path)

    result = _run(_write_to(f"{scope.snapshot_root}/file.txt"), scope)

    assert result.rc == 0, result.stderr.decode(errors="replace")
    assert (Path(scope.snapshot_root) / "file.txt").read_bytes() == b"hi\n"


# --- The default is still a boundary -----------------------------------------


def test_the_default_scope_still_contains_a_write_outside_it(tmp_path: Path) -> None:
    """A default wide enough to run everything would contain nothing.

    The point of the sandboxed TMPDIR is that the scope did NOT have to grow to
    cover `/var/folders`, and this is the half of that sentence a widened profile
    would silently lose.
    """
    outside = tmp_path.parent / "outside.txt"
    scope = default_scope(tmp_path)

    result = _run(_write_to(str(outside)), scope)

    assert result.rc != 0
    assert not outside.exists()


def test_the_real_tmpdir_is_not_granted_by_the_default(tmp_path: Path) -> None:
    """Redirecting `TMPDIR` must not be confused with allowing the real one."""
    scope = default_scope(tmp_path)
    real_tmp = os.path.realpath(os.environ.get("TMPDIR", "/tmp"))

    result = _run(_write_to(f"{real_tmp}/belay-should-not-write"), scope)

    assert result.rc != 0
    assert not Path(f"{real_tmp}/belay-should-not-write").exists()


def test_a_denial_records_the_exact_path(tmp_path: Path) -> None:
    """Never silently widen: a refusal is contained AND named, which is what makes
    widening a diagnosis rather than a guessing game."""
    outside = tmp_path.parent / "diagnosable.txt"
    scope = default_scope(tmp_path)

    result = _run(_write_to(str(outside)), scope)

    assert [d.path for d in result.denials] == [str(outside)]


def test_the_scope_is_not_widened_by_the_env_wrapper(tmp_path: Path) -> None:
    """`wrap` sets the environment and nothing else. If it could also alter the
    profile, the two halves of this module could disagree and only one is enforced.

    The profile grants exactly the two roots the scope names — the workspace and
    the temp directory — and nothing the wrapper exports can add a third.
    """
    scope = default_scope(tmp_path)

    profile = seatbelt.build_profile(
        scope=scope.write_roots, network=seatbelt.NetworkPolicy.deny_all()
    )

    assert profile.count("file-write*") == 2
    assert f'(subpath "{scope.snapshot_root}")' in profile
    assert f'(subpath "{scope.tmpdir}")' in profile


# --- The wrapper itself ------------------------------------------------------


def test_wrap_exports_every_variable_the_stdlib_consults(tmp_path: Path) -> None:
    scope = default_scope(tmp_path)

    result = _run(["/bin/sh", "-c", 'echo "$TMPDIR|$TMP|$TEMP"'], scope)

    assert result.stdout.decode().strip() == "|".join([scope.tmpdir] * 3)


def test_wrap_leaves_the_command_intact(tmp_path: Path) -> None:
    """The wrapper prefixes; it must never reorder or drop an argument."""
    scope = default_scope(tmp_path)

    wrapped = scope.wrap(["srv", "--flag", "value with spaces", "-"])

    assert wrapped[-4:] == ["srv", "--flag", "value with spaces", "-"]


def test_belay_names_its_own_binaries_absolutely() -> None:
    """`$PATH` must not be able to choose which binary *Belay* runs.

    Scoped precisely, because the threat model is: this covers the three binaries
    Belay itself picks. It says nothing about the **server command**, which is
    resolved through `$PATH` by design — `npx` and `python` must resolve normally.
    A poisoned `$PATH` therefore runs a different server, sandboxed; it cannot
    substitute the sandbox itself.
    """
    from belay.sandbox import scope as scope_module
    from belay.sandbox import seatbelt
    from belay.snapshot import substrate

    assert scope_module._ENV == "/usr/bin/env"
    assert seatbelt.SANDBOX_EXEC == "/usr/bin/sandbox-exec"
    # substrate's ACL repair shells out; addressed absolutely for the same reason.
    assert '"/bin/chmod"' in Path(substrate.__file__).read_text().replace("'", '"')


def test_two_scopes_on_one_workspace_agree(tmp_path: Path) -> None:
    """The default must be a function of the workspace, not of when it was called:
    a `TMPDIR` that moved between turns would strand the previous turn's files."""
    assert default_scope(tmp_path).tmpdir == default_scope(tmp_path).tmpdir


# --- A real filesystem MCP server, given nothing but a workspace --------------


@pytest.mark.sdk
def test_a_filesystem_mcp_server_runs_under_the_default_scope(tmp_path: Path) -> None:
    """The whole point of Part A, end to end and with no hand-tuning.

    The server is a real MCP SDK server over real stdio (see
    `tests/fixtures/filesystem_server.py`) doing what a filesystem server does:
    an atomic write via a temp file and a rename. It is handed a workspace and
    nothing else — no scope flag, no TMPDIR, no profile edit. If this test needs
    an argument added to keep passing, the zero-config claim is false and the
    README must stop making it.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scope = default_scope(workspace)
    server = Path(__file__).parent / "fixtures" / "filesystem_server.py"

    result = seatbelt.run(
        scope.wrap([sys.executable, str(server), scope.snapshot_root]),
        scope=scope.write_roots,
        network=seatbelt.NetworkPolicy.deny_all(),
        timeout=30.0,
    )

    assert result.rc == 0, result.stderr.decode(errors="replace")
    assert result.denials == (), f"the default scope was too tight: {result.denials}"
    assert (Path(scope.snapshot_root) / "written.txt").read_bytes() == b"written by the server"


@pytest.mark.sdk
def test_the_filesystem_server_fixture_would_notice_a_tight_scope(tmp_path: Path) -> None:
    """Anti-vacuity for the test above: the same server, without the redirect, dies.

    Without this, a server that never touched a temp file would make the
    zero-config claim pass by doing nothing at all.

    **Read the assertion carefully — it is the interesting part.** The server does
    not die with a denial we can see. `tempfile` probes each candidate directory,
    catches the `EPERM` from every one, and raises its own aggregate error naming
    the list it tried. Nothing prints `Operation not permitted`, so
    `seatbelt._denials_from_stderr` infers **no denial**: `result.denials` is
    empty while the scope is unambiguously the cause of death.

    That is why this asserts on the failure rather than on a denial record, and it
    is the concrete reason `sandbox check` cannot report "no denials" as "the scope
    fits" — see `test_check_does_not_read_silence_as_sufficiency`.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scope = default_scope(workspace)
    server = Path(__file__).parent / "fixtures" / "filesystem_server.py"

    result = seatbelt.run(
        [sys.executable, str(server), scope.snapshot_root],
        scope=scope.write_roots,
        network=seatbelt.NetworkPolicy.deny_all(),
        timeout=30.0,
    )

    assert result.rc != 0
    assert not (Path(scope.snapshot_root) / "written.txt").exists()
    assert b"No usable temporary directory" in result.stderr
    # The scope killed it, and left no denial record behind to say so.
    assert result.denials == ()
