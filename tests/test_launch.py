"""The launch seam: the policy's lifetime, the backend dispatch, and the network
vocabulary.

`tests/test_proxy_containment.py` proves the boundary holds on a real run. This
file covers the two things that run cannot show: what happens when the sandbox
**cannot** be applied, and what policy is applied when nobody says.

The theme of both is the same rule the backends are written against — **never
claim a boundary we do not enforce**. On a platform with no sandbox
implementation the run is refused rather than quietly spawned bare — that is
the honest re-scope of the old "linux raises" assertions: the raise pins to a
platform with NO implementation (win32 here), and Linux is asserted directly.
And the network boundary is *absent by default and said to be absent*, rather
than claimed and unenforced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.sandbox import launch, seatbelt
from belay.snapshot.bth1 import UnsupportedPlatform

_DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt-only: Seatbelt is macOS-only")
_LINUX = pytest.mark.skipif(sys.platform != "linux", reason="landlock-seccomp-only: the Landlock+seccomp sandbox is Linux-only")
_SIMULATED_LINUX = pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason="linux-simulated: simulates a Linux box that is not this one",
)


def _require_landlock() -> None:
    if sys.platform.startswith("linux"):
        from belay.sandbox import linux

        if linux.landlock_abi() is None:
            pytest.skip("landlock-unavailable: Landlock is unavailable on this kernel")


# --- A sandbox that cannot be applied is refused, never dropped --------------


def test_an_unsupported_platform_refuses_rather_than_running_bare(monkeypatch, tmp_path):
    """The one failure mode that must never degrade quietly.

    A proxy that answered "no sandbox here" by spawning the server unsandboxed
    would produce a run that reads exactly like a contained one — same trace, same
    snapshots, same handles, no boundary. That is the failure this project exists
    to catch, committed by us. `backend_for` raises off any platform with no
    implementation (win32 stands in for all of them); this asserts the proxy's
    spawn path inherits that refusal rather than growing its own opinion.
    """
    monkeypatch.setattr(launch.sys, "platform", "win32")

    with pytest.raises(UnsupportedPlatform, match="Refusing rather than"):
        with launch.contained(["srv"], workspace=tmp_path, network=launch.network_policy(None)):
            pass


def test_the_proxy_reports_an_unappliable_sandbox_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    """And the refusal reaches the operator as a failure, not a traceback."""
    from belay import proxy

    monkeypatch.setattr(launch.sys, "platform", "win32")
    monkeypatch.setenv("BELAY_SANDBOX_SCOPE", str(tmp_path))
    monkeypatch.setenv("BELAY_SNAPSHOT_DIR", str(tmp_path / "snaps"))

    assert proxy.main(["srv"]) == 2
    assert "cannot contain anything on 'win32'" in capsys.readouterr().err


@_SIMULATED_LINUX
def test_linux_without_landlock_refuses_with_the_named_cause(monkeypatch, tmp_path):
    """On a Linux box whose kernel cannot contain, the refusal names the cause
    (Landlock unavailable) — and it is still a refusal, never a bare spawn. Runs
    on macOS with the platform simulated, because that is the machine that cannot
    contain: the syscall probe returns None here."""
    monkeypatch.setattr(launch.sys, "platform", "linux")

    with pytest.raises(UnsupportedPlatform, match="[Ll]andlock"):
        with launch.contained(["srv"], workspace=tmp_path, network=launch.network_policy(None)):
            pass


@_SIMULATED_LINUX
def test_the_proxy_refuses_linux_without_landlock_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    from belay import proxy

    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.setenv("BELAY_SANDBOX_SCOPE", str(tmp_path))
    monkeypatch.setenv("BELAY_SNAPSHOT_DIR", str(tmp_path / "snaps"))

    assert proxy.main(["srv"]) == 2
    assert "landlock" in capsys.readouterr().err.lower()


# --- The network policy is a decision, and it is stated ----------------------


def test_the_default_network_policy_is_deny_all(tmp_path):
    """A proxied run that says nothing gets the boundary, not the hole.

    `allow-all` was the tempting default — it never breaks a server — and it is
    the one this repo already refuses: `seatbelt` has no default at all, and
    `test_allow_all_is_not_the_default_and_must_be_asked_for` says why. A default
    that contained nothing on this axis while the variable was named
    `BELAY_SANDBOX_*` would be the overclaim, and the failure it causes is the
    honest direction: a server denied a network says so, loudly, and one env var
    fixes it. A server silently permitted to reach the internet says nothing.

    What makes this affordable is `build_profile`'s unix-socket line: `deny-all`
    denies IP without killing a server that opens a socket in its own temp dir
    (`tests/test_containment.py`, the unix-socket group).
    """
    assert launch.network_policy(None).mode == "deny-all"
    assert "(allow network*)" not in seatbelt.build_profile(
        scope=tmp_path, network=launch.network_policy(None)
    )


@_DARWIN
def test_the_network_policy_is_one_env_var_away(tmp_path):
    assert launch.network_policy("allow-all").mode == "allow-all"
    assert "(allow network*)" in seatbelt.build_profile(
        scope=tmp_path, network=launch.network_policy("allow-all")
    )

    ports = launch.network_policy("allow-ports:8080,9000")
    assert ports.ports == (8080, 9000)
    assert '(allow network-outbound (remote ip "localhost:8080"))' in seatbelt.build_profile(
        scope=tmp_path, network=ports
    )


@pytest.mark.parametrize(
    "spec",
    [
        "allow-hosts:example.com",  # the thing Seatbelt cannot compile at all
        "allow-ports",  # a mode naming no ports grants nothing
        "allow-ports:https",
        "deny",
    ],
)
def test_a_network_policy_belay_cannot_enforce_is_refused(spec):
    """Refused at the env var, for the same reason `NetworkPolicy` is a closed enum:
    a mode we accept and cannot compile is a boundary the user believes in and
    nothing applies."""
    with pytest.raises(ValueError):
        launch.network_policy(spec)


def test_the_policy_file_is_owner_only_and_removed(tmp_path):
    """Shared by both backends: the macOS SBPL profile and the Linux JSON policy
    are each written owner-only by `mkstemp` and unlinked on the way out — a
    writable policy is a policy the contained process can rewrite."""
    _require_landlock()
    (tmp_path / "workspace").mkdir()

    with launch.contained(
        ["srv"], workspace=tmp_path / "workspace", network=launch.network_policy(None)
    ) as spawn:
        path = Path(spawn.profile_path)
        assert oct(path.stat().st_mode & 0o777) == "0o600", (
            "a writable profile is a policy the contained process can rewrite"
        )
        assert path.read_text() == spawn.profile

    assert not path.exists()


@_DARWIN
def test_the_argv_puts_the_sandbox_outside_the_env_wrapper(tmp_path):
    """`sandbox-exec` must contain the `env` that redirects TMPDIR, not the other
    way round: a wrapper outside the sandbox is a wrapper the sandbox never sees."""
    (tmp_path / "workspace").mkdir()

    with launch.contained(
        ["srv", "--flag"], workspace=tmp_path / "workspace", network=launch.network_policy(None)
    ) as spawn:
        assert spawn.argv[0] == seatbelt.SANDBOX_EXEC
        assert spawn.argv[3] == "/usr/bin/env"
        assert spawn.argv[-2:] == ["srv", "--flag"]


@_LINUX
def test_the_linux_argv_puts_the_launcher_outside_the_env_wrapper(tmp_path):
    """The Linux pin, mirroring the macOS one: the launcher (which installs the
    filters) must contain the `env` that redirects TMPDIR — the argv Popen
    spawns IS the contained process."""
    _require_landlock()
    (tmp_path / "workspace").mkdir()

    with launch.contained(
        ["srv", "--flag"], workspace=tmp_path / "workspace", network=launch.network_policy(None)
    ) as spawn:
        assert spawn.argv[:3] == [sys.executable, "-m", "belay.sandbox.linux"]
        assert spawn.argv[3].endswith(".json")
        assert spawn.argv[4] == "--"
        assert spawn.argv[5] == "/usr/bin/env"
        assert spawn.argv[-2:] == ["srv", "--flag"]

        policy = json.loads(spawn.profile)
        assert policy["version"] == 1
        assert policy["network"] == "deny-all"


@_DARWIN
def test_the_profile_grants_both_write_roots_and_snapshots_only_one(tmp_path):
    """The Part B invariant, at the seam where the two scopes are handed out."""
    (tmp_path / "workspace").mkdir()

    with launch.contained(
        ["srv"], workspace=tmp_path / "workspace", network=launch.network_policy(None)
    ) as spawn:
        assert set(spawn.scope.write_roots) == {spawn.scope.snapshot_root, spawn.scope.tmpdir}
        assert f'(subpath "{spawn.scope.snapshot_root}")' in spawn.profile
        assert f'(subpath "{spawn.scope.tmpdir}")' in spawn.profile
        assert not Path(spawn.scope.tmpdir).is_relative_to(spawn.scope.snapshot_root)


@_LINUX
def test_the_linux_policy_grants_both_write_roots_and_snapshots_only_one(tmp_path):
    """The same invariant on the Linux policy: the JSON names both write roots,
    and the snapshot root is one of them."""
    _require_landlock()
    (tmp_path / "workspace").mkdir()

    with launch.contained(
        ["srv"], workspace=tmp_path / "workspace", network=launch.network_policy(None)
    ) as spawn:
        policy = json.loads(spawn.profile)
        assert set(policy["write_roots"]) == set(spawn.scope.write_roots)
        assert spawn.scope.snapshot_root in policy["write_roots"]
        assert not Path(spawn.scope.tmpdir).is_relative_to(spawn.scope.snapshot_root)
