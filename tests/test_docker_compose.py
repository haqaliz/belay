"""`docker compose` is the other install path, and it must be the SAME engine.

Aspect A3 (`docs/planning/docker-selfhost/compose-docs/`). The compose file is
deliberately small: one service, the engine, invoked as `docker compose run --rm
belay <args>`. The C7 live console is the service that will join it, and until
C7 exists it is named in a COMMENT and nothing else — a service that resolves to
an image nobody built would break `docker compose up` for every reader, which is
a worse first impression than an honest absence.

What the tests hold it to: the file parses and resolves under the real compose
CLI; the resolved service runs the same `belay` entrypoint the A1 contract pins;
and the console is still a comment. That last one is the regression guard — the
temptation, when C7 lands elsewhere, is to add its service here first.

Gate: `docker compose version` (the v2 plugin), probed once. A host with the
Docker CLI but no compose plugin skips with the same named cause the other two
docker modules use — never fails, never fakes a pass.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import DOCKER_IMAGE_TAG, docker_available

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
_SERVICE = "belay"


def _compose_available() -> bool:
    """The daemon answers AND the v2 compose plugin is installed."""
    if not docker_available():
        return False
    try:
        probe = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, timeout=30
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _compose_available(),
    reason=(
        "docker-unavailable: no Docker CLI/daemon on the host — the docker "
        "image tests skip with this cause"
    ),
)


def _compose(*args: str, timeout: float = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def test_compose_config_resolves(built_image: str) -> None:
    """The file parses, and it resolves to the image the session fixture built.

    `docker compose config` is compose's own validator: an undefined service, an
    unresolvable interpolation or a malformed key fails here rather than in a
    reader's terminal. Pinning `image:` to the built tag is what keeps the compose
    path and the `docker run` path talking about ONE artifact — the alternative,
    letting compose name its own image, would silently verify a different build.
    """
    run = _compose("config")
    assert run.returncode == 0, run.stderr
    assert re.search(rf"^\s*{_SERVICE}:", run.stdout, re.MULTILINE), run.stdout
    assert built_image in run.stdout, run.stdout


def test_compose_run_reaches_the_same_cli(built_image: str) -> None:
    """`docker compose run --rm belay --help` is the `docker run` surface, exactly."""
    run = _compose("run", "--rm", _SERVICE, "--help")
    assert run.returncode == 0, run.stderr
    for subcommand in ("sandbox", "replay", "verify", "corpus", "phase0", "interop"):
        assert subcommand in run.stdout, run.stdout


def test_the_console_is_named_but_not_shipped() -> None:
    """C7's service is a comment. A broken service must never ship in its place.

    Read as text, not through compose, precisely because compose would resolve a
    commented service to nothing and tell us nothing. The claim is about what a
    reader opening the file sees: exactly one service key, and the console named
    as the thing that will join it.
    """
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    services = re.findall(r"^  ([a-z0-9-]+):", text, re.MULTILINE)
    assert services == [_SERVICE], services
    assert "console" in text.lower(), "the C7 console is not named as the future service"


def test_compose_pins_the_same_tag_the_image_tests_build() -> None:
    """One tag, written once in the compose file and once in `tests/conftest.py`.

    If these drift, `docker compose config` still passes and the compose tests
    quietly exercise a stale image — the failure mode this asserts away.
    """
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    assert f"image: {DOCKER_IMAGE_TAG}" in text, text
