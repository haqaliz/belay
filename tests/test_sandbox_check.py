"""`belay sandbox check` — the self-test, and the limits of what it can conclude.

Two questions, and they are not equally answerable:

- *Does the substrate work on this machine?* — answerable. Run it and see.
- *Is the scope too tight for this server?* — **only refutable, never confirmed.**

The second is why most of this file exists. A check that ran a server for two
seconds, saw nothing, and printed "the scope is fine" would be a false PASS with a
CLI in front of it — the exact shape this project was built to catch. It can find
a problem; it cannot certify the absence of one, and it has to say so in the one
place a user will read.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from belay import cli

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")


def _check(argv: list[str], capsys) -> tuple[int, str]:
    rc = cli.main(argv)
    return rc, capsys.readouterr().out


# --- Question 1: does the substrate work here? -------------------------------


def test_check_verifies_the_substrate_by_using_it(tmp_path: Path, capsys) -> None:
    """Probed, never declared — the same rule `ClonefileBackend.capabilities` follows."""
    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path)], capsys)

    assert rc == 0, out
    assert "sandbox-exec" in out
    assert "clonefile-apfs" in out


def test_the_substrate_probe_catches_a_sandbox_that_enforces_nothing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """The ablation that keeps "probed by using it" from becoming a figure of speech.

    Building a profile is **string formatting** — `seatbelt.build_profile` returns
    text, and text enforces nothing. An earlier draft of this command called that
    "profile compiles ok" and would have said so on a machine with no working
    sandbox at all.

    The ablation deliberately swaps in `/usr/bin/true`: a binary that **exists**
    (so the existence check still passes and cannot be what fails this test) and
    that ignores its arguments entirely. The probe must notice — here by its
    positive control, since a sandbox that runs nothing also produces no escape.

    A test using a *nonexistent* path would pass without the probe executing
    anything, which is right-verdict-wrong-reason and would let the overclaim back
    in unnoticed.
    """
    from belay.sandbox import seatbelt

    monkeypatch.setattr(seatbelt, "SANDBOX_EXEC", "/usr/bin/true")

    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path)], capsys)

    assert rc == 1, out
    assert "containment" in out
    assert "PROBLEM" in out


def test_a_profile_that_does_not_compile_fails_the_check(tmp_path: Path, capsys, monkeypatch) -> None:
    """The profile must reach the actual compiler, and a bad one must fail for real.

    This is the direct falsification of the old "profile compiles ok" line, which
    was printed by the mere act of building a string and so could not fail. Feed
    the probe SBPL that cannot parse: if the profile is genuinely handed to
    `sandbox-exec`, the run dies and the check reports a problem. If the check ever
    goes green here again, something has gone back to inspecting text instead of
    executing it.
    """
    from belay.sandbox import seatbelt

    monkeypatch.setattr(seatbelt, "build_profile", lambda **kwargs: "(this is not valid sbpl\n")

    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path)], capsys)

    assert rc == 1, out
    assert "containment" in out
    assert "PROBLEM" in out


def test_the_substrate_probe_confirms_containment_actually_holds(tmp_path: Path, capsys) -> None:
    """"Does the substrate work here?" means "does it *contain*?", not "does it run?".

    Seatbelt is deprecated. The failure mode worth catching is not a missing binary
    — it is a `sandbox-exec` that runs the command and enforces nothing. Only an
    attempted escape can tell those apart, so the probe attempts one.
    """
    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path)], capsys)

    assert rc == 0, out
    assert "containment" in out


def test_check_passes_with_no_server_to_run(tmp_path: Path, capsys) -> None:
    """The substrate half must be usable on its own: a user debugging "does Belay
    work on this laptop" has no server to hand yet."""
    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path)], capsys)

    assert rc == 0
    assert "no server command" in out


def test_check_reports_the_scope_it_would_use(tmp_path: Path, capsys) -> None:
    """Including the temp dir: it is the surprising half of the default, and the
    thing a user will otherwise find in their tree and not recognise."""
    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path)], capsys)

    scope_root = str(Path(tmp_path).resolve())
    assert scope_root in out
    assert ".belay-tmp" in out


# --- Question 2: is the scope too tight for THIS server? ---------------------


def test_check_is_green_for_a_server_that_stays_in_scope(tmp_path: Path, capsys) -> None:
    rc, out = _check(
        [
            "sandbox",
            "check",
            "--scope",
            str(tmp_path),
            "--",
            "/bin/sh",
            "-c",
            'echo hi > "$TMPDIR/f"',
        ],
        capsys,
    )

    assert rc == 0, out
    assert "no denials" in out


def test_check_reports_the_denied_path(tmp_path: Path, capsys) -> None:
    """The exact path, because widening has to be a diagnosis rather than a guess."""
    outside = tmp_path.parent / "denied-me.txt"

    rc, out = _check(
        [
            "sandbox",
            "check",
            "--scope",
            str(tmp_path),
            "--",
            "/bin/sh",
            "-c",
            f'echo hi > "{outside}"',
        ],
        capsys,
    )

    assert rc == 1
    assert str(outside) in out


def test_check_marks_a_denial_as_inferred(tmp_path: Path, capsys) -> None:
    """The record's provenance travels with it. We saw the child complain; we did
    not see the kernel deny. A CLI that dropped that distinction would be making a
    claim the engine deliberately does not."""
    outside = tmp_path.parent / "denied-me-too.txt"

    _, out = _check(
        ["sandbox", "check", "--scope", str(tmp_path), "--", "/bin/sh", "-c", f"echo hi > {outside}"],
        capsys,
    )

    assert "inferred" in out
    assert "child-stderr" in out


def test_check_fails_a_server_that_dies_without_a_denial(tmp_path: Path, capsys) -> None:
    """The failure mode measured in `test_the_filesystem_server_fixture_would_notice_a_tight_scope`.

    A child can be killed by the scope and leave **no** denial record: `tempfile`
    catches every `EPERM` itself and reports its own error, printing nothing we can
    infer from. So a non-zero exit is a finding in its own right. A check that
    keyed only on denial records would call this run clean.
    """
    rc, out = _check(
        ["sandbox", "check", "--scope", str(tmp_path), "--", "/bin/sh", "-c", "exit 3"],
        capsys,
    )

    assert rc == 1
    assert "exited 3" in out
    assert "without reporting a denial" in out


# --- The shape a real stdio server actually has ------------------------------


def test_a_server_still_running_at_the_end_of_the_sample_is_not_a_fault(
    tmp_path: Path, capsys
) -> None:
    """This is the **normal** case, not an edge case.

    A real MCP stdio server blocks on stdin waiting for a client that this
    command never provides. It will always still be running when the sample ends.
    If that were reported as a failure, `sandbox check` would fail against every
    server anyone actually runs, which is the only shape it is for.
    """
    rc, out = _check(
        [
            "sandbox",
            "check",
            "--scope",
            str(tmp_path),
            "--seconds",
            "0.5",
            "--",
            "/bin/sh",
            "-c",
            "sleep 30",
        ],
        capsys,
    )

    assert rc == 0, out
    assert "still running" in out


def test_a_denial_is_reported_even_when_the_server_keeps_running(tmp_path: Path, capsys) -> None:
    """A server denied at startup that carries on serving must not pass.

    The refusal already happened; the process outliving our sample does not
    un-happen it. Reporting this run clean would be a false PASS on the one
    signal this command exists to surface.
    """
    outside = tmp_path.parent / "denied-then-hung.txt"

    rc, out = _check(
        [
            "sandbox",
            "check",
            "--scope",
            str(tmp_path),
            "--seconds",
            "0.5",
            "--",
            "/bin/sh",
            "-c",
            f"echo hi > {outside}; sleep 30",
        ],
        capsys,
    )

    assert str(outside) in out
    assert rc == 1


# --- What the check must never claim ----------------------------------------


def test_check_does_not_read_silence_as_sufficiency(tmp_path: Path, capsys) -> None:
    """The honesty assertion, and the reason this is `check` and not `verify`.

    A server that ran cleanly for a few seconds has proven that it started, not
    that its scope is sufficient — the denial it hits on turn 400 is still coming.
    This is C2's version of the rule that UNVERIFIED is never rendered as PASS, and
    it is pinned by a test for the same reason: prose drifts, a test does not.
    """
    _, out = _check(
        ["sandbox", "check", "--scope", str(tmp_path), "--", "/bin/sh", "-c", "true"],
        capsys,
    )

    assert "not proof" in out
    assert "only what this run touched" in out


def test_check_never_widens_the_scope_itself(tmp_path: Path, capsys) -> None:
    """It diagnoses. It does not fix. A tool that widened the boundary to make its
    own error go away would be authoring the invariant — the thing the default
    scope exists to prevent."""
    outside = tmp_path.parent / "still-denied.txt"

    _check(
        ["sandbox", "check", "--scope", str(tmp_path), "--", "/bin/sh", "-c", f"echo hi > {outside}"],
        capsys,
    )

    assert not outside.exists()


# --- Usage -------------------------------------------------------------------


def test_a_missing_scope_is_a_usage_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["sandbox", "check"])
    assert exc.value.code == 2


def test_a_scope_that_does_not_exist_is_refused(tmp_path: Path, capsys) -> None:
    rc, out = _check(["sandbox", "check", "--scope", str(tmp_path / "nope")], capsys)

    assert rc == 2
    assert "does not exist" in out


def test_the_cli_is_reachable_as_a_module() -> None:
    """`python -m belay.cli` works whether or not the console script is installed."""
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "sandbox", "check", "--help"],
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert b"--scope" in completed.stdout
