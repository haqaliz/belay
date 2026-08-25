"""`docker compose` is the other install path, and it must be the SAME engine.

Aspect A3 (`docs/planning/docker-selfhost/compose-docs/`), extended by the
live-console aspect `compose-healthcheck`. The compose file holds exactly two
services: the engine, invoked as `docker compose run --rm belay <args>`, and
the C7 live console — built from this checkout (its image bundles the engine
wheel built in-image, so verify/replay inside the console container run THIS
engine), served on the loopback with a healthcheck, and sharing the engine's
state mount so the traces and snapshots the engine writes are what the console
reads.

What the tests hold it to: the file parses and resolves under the real compose
CLI; the resolved engine service runs the same `belay` entrypoint the A1
contract pins; and the console is a shipped service, not a comment. That last
one is the regression guard — the temptation, when C7 lands elsewhere, is to
name it in a comment and never declare it.

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


def test_the_console_service_ships_with_a_healthcheck() -> None:
    """C7's service is declared: `console:` builds and carries a healthcheck.

    Read as text, not through compose — compose would resolve a missing service
    to nothing and tell us nothing. The claim is about what a reader opening the
    file sees: exactly two services, and the console built from THIS checkout —
    its Dockerfile lives in `console/` and shares the build context with the
    engine sources, because the console image bundles the engine wheel built
    in-image — with a healthcheck against its `/health` endpoint, a loopback
    port mapping, and the same state mount as the engine service, so the traces
    and snapshots the engine writes are what the console reads.
    """
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    services = re.findall(r"^  ([a-z0-9-]+):", text, re.MULTILINE)
    assert services == [_SERVICE, "console"], services

    engine_block, console_block = text.split("  console:", 1)
    assert "context: ." in console_block, "the console builds from the checkout root"
    assert "dockerfile: console/Dockerfile" in console_block
    assert "healthcheck:" in console_block
    assert "127.0.0.1:8080:8080" in console_block, "loopback-only, never the LAN"
    assert "./workspace:/workspace" in engine_block
    assert "./workspace:/workspace" in console_block
    assert "BELAY_CONSOLE_TRACE_DIR" in console_block
    assert "BELAY_SNAPSHOT_DIR" in console_block


def test_the_console_image_builds_and_reports_health_with_the_engine() -> None:
    """The console image BUILDS from this checkout and its /health is honest.

    The flipped declaration test above asserts the service exists in the file;
    this one proves the image behind it builds and that its health endpoint
    carries the bundled engine's version — `{"ok": true, "engine": "X.Y.Z"}` —
    which is the in-image proof that the console container runs THIS checkout's
    engine (the wheel is built in-image, exactly like the engine image). A
    broken `console/Dockerfile` passes the declaration test and fails here.
    """
    tag = "belay:console-test"
    build = subprocess.run(
        ["docker", "build", "-f", "console/Dockerfile", "-t", tag, "."],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=900,
    )
    assert build.returncode == 0, build.stderr[-4000:]

    run = subprocess.run(
        ["docker", "run", "--rm", "-d", "--name", "belay-console-test", "-p", "127.0.0.1:18080:8080", tag],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    try:
        import json
        import time

        health = ""
        for _ in range(30):
            probe = subprocess.run(
                ["curl", "-s", "http://127.0.0.1:18080/health"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
            )
            health = probe.stdout
            try:
                if json.loads(health).get("ok") is True:
                    break
            except (ValueError, TypeError):
                pass
            time.sleep(1)
        payload = json.loads(health)
        assert payload.get("ok") is True, health
        assert payload.get("engine") == _project_version(), health
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "belay-console-test"],
            capture_output=True,
            timeout=60,
        )


def _project_version() -> str:
    """The version pyproject.toml states — what the bundled engine must report."""
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml carries no version"
    return match.group(1)


def test_compose_pins_the_same_tag_the_image_tests_build() -> None:
    """One tag, written once in the compose file and once in `tests/conftest.py`.

    If these drift, `docker compose config` still passes and the compose tests
    quietly exercise a stale image — the failure mode this asserts away.
    """
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    assert f"image: {DOCKER_IMAGE_TAG}" in text, text
