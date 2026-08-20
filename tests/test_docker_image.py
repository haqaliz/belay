"""The self-host image: build it, then hold its behavior to the documented contract.

Aspect A1 (`docs/planning/docker-selfhost/image/`). The image's entrypoint is
the real `belay` CLI; the MCP proxy is reachable as `python -m belay.proxy`;
the default user is a non-root `belay` (uid 1000) with root opt-in via
`--user root`; the working directory is the documented mount point; and
`python -m belay` deliberately does not exist.

Every assertion runs the built image through a fixed-arg `docker run`
subprocess and checks exit code plus stdout/stderr substrings — the same
style as the `sandbox check` launch tests, with the container in place of the
local interpreter. The fixture IS the build acceptance: it fails loudly until
a `Dockerfile` exists, so a missing Dockerfile reads as a failing suite, never
as a skipped one.

The platform gate is `docker info`, probed once at import: a host without a
Docker CLI or daemon skips the whole module with the named cause
`docker-unavailable` (README's platform coverage table) — never fails, never
fakes a pass.

The build itself is the session-scoped `built_image` fixture in
`tests/conftest.py`: `test_docker_inimage.py` drives the same image, and one
build shared between the two modules is the only way both are talking about the
same artifact.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import DOCKER_IMAGE_TAG, DOCKER_IMAGE_UID, docker_available

_REPO_ROOT = Path(__file__).resolve().parents[1]
_IMAGE_TAG = DOCKER_IMAGE_TAG
_IMAGE_USER_UID = DOCKER_IMAGE_UID

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason=(
        "docker-unavailable: no Docker CLI/daemon on the host — the docker "
        "image tests skip with this cause"
    ),
)


def _docker_run(
    tag: str, options: list[str], command: list[str], timeout: float = 120
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "run", "--rm", *options, tag, *command],
        capture_output=True,
        timeout=timeout,
    )


def _project_version() -> str:
    """The version pyproject.toml states — the truth the wheel must stamp."""
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml carries no version"
    return match.group(1)


def test_image_builds(built_image: str) -> None:
    """The fixture is the build acceptance; this names it."""
    assert built_image == _IMAGE_TAG


def test_the_build_needs_nothing_but_the_checkout_and_docker(built_image: str) -> None:
    """No `dist/` wheel exists — the image built its own, from source, in-build.

    This is the README quickstart's precondition, checked rather than hoped: a
    stranger who has cloned the repo and has Docker runs `docker build -t belay .`
    and gets a working image. A Dockerfile that `COPY`s a pre-built wheel works on
    the machine that just ran `uv build` and nowhere else — and it fails at
    `lstat /dist`, before any of this module's other assertions could notice.
    """
    assert not list((_REPO_ROOT / "dist").glob("belay_harness-*.whl"))


def test_belay_help_exits_zero(built_image: str) -> None:
    """The entrypoint is the belay CLI, and its help shows the full surface."""
    run = _docker_run(built_image, [], ["--help"])
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    out = run.stdout.decode(errors="replace")
    for subcommand in ("sandbox", "replay", "verify", "corpus", "phase0", "interop"):
        assert subcommand in out


def test_proxy_entrypoint_reachable(built_image: str) -> None:
    """`python -m belay.proxy` answers with a belay-shaped usage error.

    The proxy has no `--help` (`src/belay/proxy.py:530-533`): an empty argv
    prints its usage line and exits 2. That is the reachability proof — a
    module-not-found would say nothing about belay at all.
    """
    run = _docker_run(built_image, ["--entrypoint", "python"], ["-m", "belay.proxy"])
    assert run.returncode == 2, run.stdout.decode(errors="replace")
    err = run.stderr.decode(errors="replace")
    assert "belay.proxy" in err
    assert "No module named" not in err


def test_version_stamps_from_the_installed_wheel(built_image: str) -> None:
    """The image reports the version of the wheel built from THIS checkout."""
    run = _docker_run(
        built_image,
        ["--entrypoint", "python"],
        ["-c", "import belay; print(belay.__version__)"],
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.strip().decode() == _project_version()


def test_default_user_is_non_root(built_image: str) -> None:
    """Default processes run as the belay uid, not as root."""
    uid = _docker_run(built_image, ["--entrypoint", "id"], ["-u"])
    assert uid.returncode == 0, uid.stderr.decode(errors="replace")
    assert uid.stdout.strip() == str(_IMAGE_USER_UID).encode()

    whoami = _docker_run(built_image, ["--entrypoint", "whoami"], [])
    assert whoami.returncode == 0, whoami.stderr.decode(errors="replace")
    assert whoami.stdout.strip() == b"belay"


def test_root_is_opt_in(built_image: str) -> None:
    """Root is a one-flag choice (`--user root`), never the default."""
    run = _docker_run(
        built_image, ["--user", "root", "--entrypoint", "id"], ["-u"]
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.strip() == b"0"


def test_ownership_contract_both_ways(built_image: str) -> None:
    """A host-owned mount stays host-owned: the container user is denied, root is not.

    The reference point is the mount implementation, measured not assumed. On
    native Linux the container uid either owns the mount (host uid == 1000 —
    writes succeed) or does not (host uid != 1000 — denied with EACCES). On
    macOS Docker Desktop the virtiofs mount layer maps container writes to the
    host user, so uid 1000 writes succeed regardless of the host uid — the
    documented contract "the mounted workspace is writable by the container
    user" holds either way. The assertion is chosen from the substrate, never
    guessed, and root can write on every one of them.
    """
    mount = Path(tempfile.mkdtemp())
    write_probe = "echo probe > /data/probe.txt"

    if sys.platform == "darwin":
        # Docker Desktop (measured 2026-08-18, virtiofs): the mount layer
        # grants the container user writes against the host owner's access.
        denied = False
    else:
        denied = os.getuid() != _IMAGE_USER_UID
    run = _docker_run(
        built_image,
        ["-v", f"{mount}:/data", "--entrypoint", "sh"],
        ["-c", write_probe],
    )
    if denied:
        assert run.returncode != 0, run.stdout.decode(errors="replace")
        assert b"Permission denied" in run.stderr
    else:
        assert run.returncode == 0, run.stderr.decode(errors="replace")

    as_root = _docker_run(
        built_image,
        ["-v", f"{mount}:/data", "--user", "root", "--entrypoint", "sh"],
        ["-c", write_probe],
    )
    assert as_root.returncode == 0, as_root.stderr.decode(errors="replace")


def test_workdir_is_the_documented_mount_point(built_image: str) -> None:
    """Processes start in `/workspace`, the documented state mount point."""
    run = _docker_run(built_image, ["--entrypoint", "pwd"], [])
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.strip() == b"/workspace"


def test_the_workdir_is_writable_by_the_default_user(built_image: str) -> None:
    """`/workspace` belongs to the container user, so the documented commands work.

    `WORKDIR` creates the directory as root, and the image then drops to `belay`.
    Left that way, README's own first command —
    `docker run --rm belay sandbox check --scope /workspace` — exits 1 with
    "the probe never ran": the containment probe has to WRITE inside the scope to
    find out whether writes outside it are refused, and it could not. A boundary
    check that cannot run is the one thing worse than a boundary that fails, so the
    ownership is asserted rather than assumed.

    This says nothing about a bind mount at the same path: a mounted directory
    carries the HOST's ownership, which `test_ownership_contract_both_ways` covers.
    """
    probe = _docker_run(
        built_image, ["--entrypoint", "sh"], ["-c", "touch /workspace/probe"]
    )
    assert probe.returncode == 0, probe.stderr.decode(errors="replace")

    check = _docker_run(built_image, [], ["sandbox", "check", "--scope", "/workspace"])
    out = check.stdout.decode(errors="replace")
    assert check.returncode == 0, out + check.stderr.decode(errors="replace")
    assert "the probe never ran" not in out, out


def test_no_documented_python_m_belay(built_image: str) -> None:
    """`python -m belay` does not exist — no undocumented `__main__` path."""
    run = _docker_run(built_image, ["--entrypoint", "python"], ["-m", "belay"])
    assert run.returncode != 0
    assert "No module named belay" in run.stderr.decode(errors="replace")
