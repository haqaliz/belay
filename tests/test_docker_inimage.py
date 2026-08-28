"""The image runs the REAL thing: the suite, the sandbox, and a whole verify roundtrip.

Aspect A2 (`docs/planning/docker-selfhost/container-ci/`). A1 proved the image's
*contract* — the entrypoint, the user, the version stamp. That says nothing about
whether Belay's substrate claims survive containerisation, and
`docs/technical/THREAT_MODEL.md` is explicit that they must be re-measured on any
image rather than inherited: Landlock is the HOST kernel's, Docker layers its own
seccomp profile under Belay's, and an overlayfs upper layer has no reflink.

So this module re-runs the measurement inside the container:

1. **The whole suite**, in a throwaway dev container — and its skip report is
   machine-checked, because "green" only means anything while every skip still
   names a cause. This is the criterion that carries PRD acceptances 1–3: the
   Landlock+seccomp escape matrix (`test_linux_containment.py`) and the
   copy-fidelity snapshot round-trips (`test_linux_snapshot.py`) are inside it.
2. **`belay sandbox check`**, the probe that decides the boundary by *using* it —
   a write outside the scope and an `AF_INET` socket, both refused by the kernel.
3. **A capture → verify roundtrip**, end to end, entirely inside the container: a
   real gated proxy run over real stdio, a real snapshot, then `belay verify`
   re-executing the recorded call against its restored pre-state. The trace is
   GENERATED in-container and never mounted — committed run data is gitignored
   under the no-raw-data-egress guardrail, and a mounted trace would prove
   nothing about the image's own capture path anyway.

**What CI can and cannot assert (the claim split, `prd.md`).** These tests assert
the LINUX-HOST path: on the pinned `ubuntu-24.04` runner the container's kernel is
the runner's. On a macOS host the same tests run against Docker Desktop's Linux VM
kernel — a different substrate, which is why the README carries the macOS-host
re-probe as a manual step and CI never asserts it.

The platform gate is `docker info` (shared with `test_docker_image.py`): no CLI or
daemon skips the module with the named cause `docker-unavailable`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import docker_available

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason=(
        "docker-unavailable: no Docker CLI/daemon on the host — the docker "
        "image tests skip with this cause"
    ),
)

#: Everything the suite needs beyond the stdlib and the installed wheel, MEASURED
#: by running `python -m pytest` in the container and extending the list until it
#: imported (2026-08-20, python:3.12-slim): `pytest` for the runner itself, and
#: `mcp` for the `sdk`-marked tests that drive the real MCP SDK client. Pinned to
#: the same version `pyproject.toml`'s dev group pins, so the in-image run and the
#: host run are the same suite. Installed into the THROWAWAY dev container only —
#: never into the runtime image, whose zero-dependency contract is the point.
_DEV_DEPS = ("pytest", "mcp==1.28.1")

#: Every named cause the in-container suite is allowed to skip under. Two families:
#: the macOS-only causes (Seatbelt, clonefile, BSD file flags, the darwin ACL and
#: python3 shim paths) which can never execute on Linux, and the substrate causes
#: the PRD admits for a container — `reflink-unavailable` (overlayfs has no
#: FICLONE, so the copy path is the path) and `landlock-unavailable` (a pre-5.13
#: HOST kernel; the image cannot supply one). `docker-unavailable` is this module
#: and its A1 sibling skipping themselves — there is no docker daemon inside the
#: container, and recursion is not the acceptance. `linux-simulated` marks the
#: tests that fake a Linux box that is not this one. `no-git-checkout` is the
#: committed-capture completeness guard (`test_demo_assets.py`), which reads the git
#: index to assert nothing under `demo/capture/` is ignored or untracked: the copy
#: below excludes `./.git` by design, so inside the container there is no index to
#: read. It is a fact about where the suite runs from, never a platform fact, which
#: is why it is registered here and not in README's platform coverage table.
#:
#: An unknown cause FAILs. So does an unnamed one: the skip report is the honesty
#: surface, and a bare `pytest.skip()` inside a green run is exactly how coverage
#: quietly disappears.
_ALLOWED_SKIP_CAUSES = frozenset(
    {
        "seatbelt-only",
        "replay-reinvokes-seatbelt",
        "darwin-acl",
        "bsd-file-flags",
        "macos-python3-shim",
        "linux-simulated",
        "reflink-unavailable",
        "landlock-unavailable",
        "docker-unavailable",
        "no-git-checkout",
    }
)

#: The in-container copy excludes the host virtualenv and the git history: the
#: first is a macOS-built tree that would shadow the installed wheel with
#: platform-wrong binaries, the second is large and irrelevant. Everything else
#: travels, so the suite in the container is the suite in the repo.
_COPY_EXCLUDES = ("./.venv", "./.git")


def _sh(
    image: str, script: str, mounts: list[str], timeout: float = 1800
) -> subprocess.CompletedProcess[str]:
    """Run `script` with `sh` inside the built image, as the image's default user."""
    return subprocess.run(
        ["docker", "run", "--rm", *mounts, "--entrypoint", "sh", image, "-c", script],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def _copy_checkout() -> str:
    excludes = " ".join(f"--exclude={path}" for path in _COPY_EXCLUDES)
    return (
        f"mkdir -p /tmp/work && tar -C /checkout {excludes} -cf - . "
        "| tar -C /tmp/work -xf -"
    )


def _skip_causes(report: str) -> list[tuple[str, str]]:
    """Every `SKIPPED` line in a `-rs` report, as `(cause, location)` pairs.

    A pytest skip line reads `SKIPPED [n] <path>:<line>: <reason>`; the repo's
    convention is that every reason opens with a lowercase-hyphenated cause and a
    colon. A line whose reason does NOT open that way yields the cause `""`, which
    is not in the allowed set and so fails — an unnamed skip must never read as an
    allowed one.
    """
    causes: list[tuple[str, str]] = []
    for line in report.splitlines():
        if not line.startswith("SKIPPED ["):
            continue
        _count, _, rest = line.partition("] ")
        location, _, reason = rest.partition(": ")
        head = reason.split(": ", 1)[0]
        causes.append((head if re.fullmatch(r"[a-z0-9-]+", head) else "", location))
    return causes


def test_full_suite_runs_green_inside_the_image(built_image: str) -> None:
    """The repo's own suite, run in the container, green — with every skip named.

    The dev deps go into a throwaway container, never the image. The checkout is
    COPIED out of a read-only mount rather than run in place, so a container
    process cannot write a cache or an artifact back into the host tree (as root
    on native Linux, that would leave root-owned files behind).

    This one test carries three PRD acceptances, because the suite carries them:
    the escape matrix and the snapshot round-trips are modules inside this run.
    The assertion that keeps it from being a rubber stamp is the skip report —
    a green run whose skips grew a new unnamed cause is not a green run.
    """
    install = (
        "pip install --no-cache-dir --quiet --user " + " ".join(f"'{d}'" for d in _DEV_DEPS)
    )
    run = _sh(
        built_image,
        "set -e; "
        f"{install}; "
        f"{_copy_checkout()}; "
        "cd /tmp/work && python -m pytest tests/ -q -rs",
        ["-v", f"{_REPO_ROOT}:/checkout:ro"],
    )
    assert run.returncode == 0, run.stdout[-8000:] + run.stderr[-4000:]

    summary = run.stdout.strip().splitlines()[-1]
    assert "failed" not in summary and "error" not in summary, summary
    passed = re.search(r"(\d+) passed", summary)
    assert passed is not None, summary
    # A collection that quietly shrank to a handful would satisfy every assertion
    # above. The suite was 1829 collected when this was measured; the floor is a
    # sanity bound, not a target.
    assert int(passed.group(1)) > 1500, summary

    skips = _skip_causes(run.stdout)
    assert skips, "no skip report parsed — the -rs output shape changed"
    unknown = {(cause, where) for cause, where in skips if cause not in _ALLOWED_SKIP_CAUSES}
    assert not unknown, f"skips with unnamed or unknown causes: {sorted(unknown)}"


def test_sandbox_check_decides_the_boundary_in_image(built_image: str) -> None:
    """`belay sandbox check` probes the container's real substrate by USING it.

    Not a capability report read off the kernel version: the check writes outside
    the scope and opens an `AF_INET` socket, and reports what the kernel did. That
    is the re-measurement `THREAT_MODEL.md` demands of any new image.

    Landlock belongs to the HOST kernel, which no image can supply. On a pre-5.13
    host the probe refuses with its named cause and this test SKIPS carrying that
    cause verbatim — never a bare pass, and never a fabricated one.
    """
    run = _sh(built_image, "mkdir -p /tmp/scope && belay sandbox check --scope /tmp/scope", [], timeout=300)
    out = run.stdout + run.stderr
    if "landlock-unavailable" in out or "landlock" in out and "unavailable" in out:
        pytest.skip(f"landlock-unavailable: the host kernel offers no Landlock: {out.strip()}")

    assert run.returncode == 0, out
    assert re.search(r"platform\s+linux \(ok\)", run.stdout), run.stdout
    assert re.search(r"landlock\s+kernel ABI \d+ \(ok\)", run.stdout), run.stdout
    assert re.search(r"containment\s+ok \(a write outside the scope was refused\)", run.stdout), (
        run.stdout
    )
    assert re.search(r"seccomp\s+ok \(an AF_INET socket was refused\)", run.stdout), run.stdout
    assert "substrate ok" in out


def test_capture_and_verify_roundtrip_in_image(built_image: str) -> None:
    """Capture a real turn through the gated proxy, then verify it by re-execution.

    Every step happens inside the container: a sequenced stdio client drives
    `python -m belay.proxy` in front of a deterministic MCP server, the gate
    snapshots the workspace before the `tools/call` reaches the server, the server
    writes one file, and `belay verify` restores that pre-state into a scratch tree
    and re-invokes. Nothing is mounted but the two fixture scripts — the trace, the
    snapshot and the manifest are all made here.

    The server script is copied INTO the workspace on purpose. Replay relocates a
    turn's in-root absolute paths into the scratch restore; a server command rooted
    outside the recorded workspace cannot be relocated and is honestly UNVERIFIED
    (`engine.UNROOTABLE_SERVER_COMMAND`). Putting the server in the scope is what
    makes a real PASS reachable rather than an abstention that merely looks clean.
    """
    run = _sh(
        built_image,
        "set -e; "
        "mkdir -p /tmp/rt/ws; "
        # Both files go INTO the workspace: the server, and the trace-wait helper
        # it imports (a script's own directory is what lands on sys.path, and the
        # server runs from the workspace, not from /fixtures).
        "cp /fixtures/docker_roundtrip_server.py /tmp/rt/ws/server.py; "
        "cp /fixtures/docker_roundtrip_trace.py /tmp/rt/ws/; "
        "export BELAY_SANDBOX_SCOPE=/tmp/rt/ws "
        "BELAY_SNAPSHOT_DIR=/tmp/rt/sn BELAY_TRACE_DIR=/tmp/rt/tr; "
        "python /fixtures/docker_roundtrip_client.py /tmp/rt/ws/server.py /tmp/rt/ws/note.txt; "
        "test -f /tmp/rt/ws/note.txt; "
        "belay verify /tmp/rt/tr/*.jsonl --manifest-dir /tmp/rt/sn.manifests "
        "--server python /tmp/rt/ws/server.py",
        ["-v", f"{_FIXTURES}:/fixtures:ro"],
        timeout=600,
    )
    assert run.returncode == 0, run.stdout[-6000:] + run.stderr[-4000:]

    out = run.stdout
    assert re.search(r"turn 0\s+write_note\s+PASS", out), out
    assert re.search(r"A2 replay\s+PASS\s+replayed reply reproduced the recorded reply", out), out
    assert re.search(r"A2 effect\s+PASS", out), out
    assert re.search(r"PASS\s+1", out), out
    assert re.search(r"FAIL\s+0", out), out
    assert re.search(r"UNVERIFIED\s+0", out), out

    # The coverage line travels with the status — the rule a PASS is only honest
    # under (`_VERIFY_COVERAGE`, `src/belay/cli.py`).
    assert "A2 PASS means THE TRACE REPRODUCES" in out
    assert "It does NOT mean the agent did the right thing." in out
    assert "No model is consulted." in out
    # And the one dimension the container does not close either: network egress.
    assert "NOT_COVERED" in out
