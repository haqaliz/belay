"""The launch seam: the profile's lifetime, and the network policy's vocabulary.

`tests/test_proxy_containment.py` proves the boundary holds on a real run. This
file covers the two things that run cannot show: what happens when the sandbox
**cannot** be applied, and what policy is applied when nobody says.

The theme of both is the same rule `seatbelt.py` is written against — **never
claim a boundary we do not enforce**. Off macOS there is no boundary to apply, so
the run is refused rather than quietly spawned bare. And the network boundary is
*absent by default and said to be absent*, rather than claimed and unenforced.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from belay.sandbox import launch, seatbelt
from belay.snapshot.bth1 import UnsupportedPlatform

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")


# --- A sandbox that cannot be applied is refused, never dropped --------------


def test_off_macos_a_requested_sandbox_refuses_rather_than_running_bare(monkeypatch, tmp_path):
    """The one failure mode that must never degrade quietly.

    A proxy that answered "no sandbox here" by spawning the server unsandboxed
    would produce a run that reads exactly like a contained one — same trace, same
    snapshots, same handles, no boundary. That is the failure this project exists
    to catch, committed by us. `seatbelt.run` already raises off Darwin for the
    same reason; this asserts the proxy's spawn path inherits it rather than
    growing its own opinion.
    """
    monkeypatch.setattr(launch.sys, "platform", "linux")

    with pytest.raises(UnsupportedPlatform, match="Refusing rather than"):
        with launch.contained(["srv"], workspace=tmp_path, network=launch.network_policy(None)):
            pass


def test_the_proxy_reports_an_unappliable_sandbox_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    """And the refusal reaches the operator as a failure, not a traceback."""
    from belay import proxy

    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.setenv("BELAY_SANDBOX_SCOPE", str(tmp_path))
    monkeypatch.setenv("BELAY_SNAPSHOT_DIR", str(tmp_path / "snaps"))

    assert proxy.main(["srv"]) == 2
    assert "cannot contain anything on 'linux'" in capsys.readouterr().err


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


# --- The profile file is a security boundary, not a temp file ----------------


def test_the_profile_is_owner_only_and_removed(tmp_path):
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
