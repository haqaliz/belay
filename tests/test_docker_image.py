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
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_IMAGE_TAG = "belay:test"
_IMAGE_USER_UID = 1000


def _docker_ready() -> bool:
    """One probe, module scope: the CLI exists AND the daemon answers."""
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


_DOCKER_READY = _docker_ready()

pytestmark = pytest.mark.skipif(
    not _DOCKER_READY,
    reason=(
        "docker-unavailable: no Docker CLI/daemon on the host — the docker "
        "image tests skip with this cause"
    ),
)


@pytest.fixture(scope="session")
def built_image() -> Iterator[str]:
    """Build the wheel from THIS checkout, then the image; clean both up after.

    The wheel is rebuilt by `uv build` every session (a stale `dist/` wheel
    would fail the version-stamp test — asserted, not assumed), and `docker
    build` demands the Dockerfile that Phase 2 supplies. Until then this
    fixture raises, and every test in the module fails with it: the honest
    RED, the same shape as a corrupt success made visible.
    """
    built = subprocess.run(
        ["uv", "build", "--wheel"],
        cwd=_REPO_ROOT,
        capture_output=True,
        timeout=600,
    )
    assert built.returncode == 0, built.stderr.decode(errors="replace")
    try:
        image = subprocess.run(
            ["docker", "build", "-f", "Dockerfile", "-t", _IMAGE_TAG, "."],
            cwd=_REPO_ROOT,
            capture_output=True,
            timeout=900,
        )
        assert image.returncode == 0, image.stderr.decode(errors="replace")
        yield _IMAGE_TAG
    finally:
        subprocess.run(["docker", "rmi", _IMAGE_TAG], capture_output=True, timeout=120)
        for stale in (_REPO_ROOT / "dist").glob("belay_harness-*.whl"):
            stale.unlink()


def _docker_run(
    tag: str, options: list[str], command: list[str], timeout: float = 120
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "run", *options, tag, *command],
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


def test_no_documented_python_m_belay(built_image: str) -> None:
    """`python -m belay` does not exist — no undocumented `__main__` path."""
    run = _docker_run(built_image, ["--entrypoint", "python"], ["-m", "belay"])
    assert run.returncode != 0
    assert "No module named belay" in run.stderr.decode(errors="replace")
