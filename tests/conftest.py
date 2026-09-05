"""Shared rig for the byte-level differential tests and the derivation tests.

`CLIENT_LINES` and `run_over_pipes` live here because three tests need the same
scripted client driven over the same real stdio pipes: the gate
(`test_differential.py`), its teeth (`test_teeth.py`), and the fixture's
anti-vacuity guard (`test_fixture_guard.py`). All three must feed byte-identical
input, or they stop being comparable to each other.

`trace_of` and `run_traced` serve the derivation tests, which need trace records
to derive from. Both go through the real `TraceWriter` rather than hand-building
record dicts: a derivation fed a fabricated envelope is only ever tested against
the fabricator's idea of the format, and would keep passing after the writer's
real output drifted away from it.

`built_image` lives here for a different reason: two modules now drive the
self-host image (`test_docker_image.py`, the A1 contract; `test_docker_inimage.py`,
the A2 in-image acceptance) and a session fixture defined in one of them would
build the image twice, or bind the second module to the first module's import
order. One session-scoped build, shared, is also the only way the two modules can
be talking about the same image at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "fake_server.py"

# Hostile key order, verbatim — the client is adversarial too.
CLIENT_LINES = [
    b'{"params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"t","version":"1"}},"method":"initialize","id":1,"jsonrpc":"2.0","belayFuture":"KEEP"}',
    b'{"jsonrpc":"2.0","method":"notifications/initialized","params":null}',
    b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
    b'{"params":{"name":"echo","arguments":{"s":"caf\\u00e9"}},"method":"tools/call","id":3,"jsonrpc":"2.0"}',
]


def run_over_pipes(
    cmd: list[str],
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
    lines: list[bytes] = CLIENT_LINES,
) -> list[bytes]:
    """Spawn `cmd` over real stdio pipes, feed it `lines`, return stdout lines as bytes.

    `lines` defaults to `CLIENT_LINES` so every existing caller is byte-identical; a
    fixture with its OWN scripted client (the claim-liar capture) passes its own.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    payload = b"\n".join(lines) + b"\n"
    stdout, stderr = proc.communicate(payload, timeout=timeout)
    returncode = proc.wait(timeout=timeout)
    if returncode != 0:
        raise RuntimeError(
            f"command {cmd!r} exited {returncode}\nstderr:\n{stderr.decode(errors='replace')}"
        )
    return [line for line in stdout.split(b"\n") if line]


def proxy_cmd(server: Path) -> list[str]:
    return [sys.executable, "-m", "belay.proxy", sys.executable, str(server)]


def read_trace(trace_dir: Path) -> list[dict]:
    traces = sorted(trace_dir.glob("*.jsonl"))
    assert len(traces) == 1, f"expected exactly one trace file, found {traces!r}"
    lines = traces[0].read_bytes().split(b"\n")
    return [json.loads(line) for line in lines if line]


def run_traced(tmp_path: Path, name: str, server: Path = FIXTURE) -> list[dict]:
    """Run the scripted client through the proxy and return the trace records."""
    trace_dir = tmp_path / name
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    run_over_pipes(proxy_cmd(server), env=env)
    return read_trace(trace_dir)


def trace_of(tmp_path: Path, frames: list[tuple]) -> list[dict]:
    """Record `frames` through the real writer and read the records back.

    Each frame is `(direction, raw_bytes)`, or `(direction, raw_bytes,
    truncated)`. For derivations whose input shape is the point of the test and
    which would need an implausible server to reach end-to-end.
    """
    from belay.trace import TraceWriter

    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for direction, raw, *rest in frames:
            writer.observer(direction)(raw, bool(rest[0]) if rest else False)
    finally:
        writer.close()
    return read_trace(tmp_path / "trace")


# --- the self-host image: one build per session, shared by both docker modules -------

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The tag both docker modules build and run. Fixed, so a leftover image from an
#: interrupted session is overwritten rather than accumulating.
DOCKER_IMAGE_TAG = "belay:test"

#: The uid the image's `belay` user owns. Asserted by the A1 contract tests and
#: used by the in-image module to reason about what the default user may write.
DOCKER_IMAGE_UID = 1000

def docker_available() -> bool:
    """One probe: the CLI exists AND the daemon answers."""
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


#: Set to a tag that already exists to make `built_image` ADOPT it: no build, and no
#: removal afterwards. There is exactly one caller, and it is the reason the knob
#: exists — `release.yml`'s `ghcr` job builds the image it is about to publish, has the
#: suite measure THAT image, and then pushes it. Left to build its own copy, the fixture
#: would measure an image it then deletes, and the job would publish an unmeasured one.
#: Unset (every local run, every CI job but that one) the behaviour below is unchanged.
_ADOPT_IMAGE_ENV = "BELAY_TEST_IMAGE"


@pytest.fixture(scope="session")
def built_image() -> Iterator[str]:
    """Build the image from a CLEAN checkout — no pre-built wheel — and clean up after.

    The `dist/` sweep before the build is the assertion, not housekeeping. The
    README asks a stranger with nothing but Docker to run `docker build -t belay .`,
    so the Dockerfile has to build the wheel itself; leaving a locally-built wheel
    lying around would let a broken multi-stage build pass here and fail for them.
    A stale wheel would also stamp the wrong version, which the version test would
    catch — but by then the quickstart is already wrong.

    **Adoption mode (`BELAY_TEST_IMAGE`) neither builds nor removes.** The sweep is
    skipped with it, and deliberately: a sweep run *after* somebody else's build proves
    nothing about that build. The property it protects is preserved at the only call
    site instead — the publish job's `docker build` is the whole build, run from a fresh
    checkout that never executed `uv build`, so `dist/` is empty there by construction
    and `test_the_build_needs_nothing_but_the_checkout_and_docker` still means what it
    says.
    """
    adopted = os.environ.get(_ADOPT_IMAGE_ENV)
    if adopted:
        yield adopted
        return

    for stale in (_REPO_ROOT / "dist").glob("belay_harness-*.whl"):
        stale.unlink()
    try:
        image = subprocess.run(
            ["docker", "build", "-f", "Dockerfile", "-t", DOCKER_IMAGE_TAG, "."],
            cwd=_REPO_ROOT,
            capture_output=True,
            timeout=900,
        )
        assert image.returncode == 0, image.stderr.decode(errors="replace")
        yield DOCKER_IMAGE_TAG
    finally:
        subprocess.run(
            ["docker", "rmi", DOCKER_IMAGE_TAG], capture_output=True, timeout=120
        )
