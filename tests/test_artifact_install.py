"""The BUILT artifact installs and runs — the launch-readiness (L4) acceptance.

Every other CI job runs the source tree via `uv sync`; nothing installs the
*build* output, so a malformed wheel, a stale version stamp, or an accidentally
grown third-party dependency would pass every existing job and fail a stranger's
`pip install belay-harness`. This module is the artifact path, asserted end to
end from the wheel (and, S3, the sdist):

1. `uv build` from a clean checkout, into a tmp out-dir. The repo `dist/` must
   stay wheel-free — the docker clean-checkout property — so it is swept first
   (mirroring `tests/conftest.py`) and re-asserted clean after the build.
2. `pip install --no-index --no-deps` of the wheel into a fresh stdlib `venv`.
3. From the **installed** artifact: `belay --help` lists the CLI surface,
   `belay.__version__` equals the pyproject version (the stamp check lifted from
   `tests/test_docker_image.py`), importing the package pulls no third-party
   root into `sys.modules` (the zero-dep contract, asserted observationally
   rather than by `tests/test_import_guard.py`'s static walk), `belay sandbox
   check` probes the substrate, and a capture -> verify roundtrip produces a
   real PASS through the installed proxy and the installed verify CLI.
4. The sdist installs in a second venv and `belay --help` works (S3).

Everything is asserted through subprocesses so the subject under test is the
installed venv, never the test process's import graph or PATH. The module is
marked `install` and excluded from the default run (see `pyproject.toml`'s
`addopts`): it builds and installs, so it is slow, and it is selected in with
`-m install`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import venv
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.install


def _project_version() -> str:
    """The version pyproject.toml states — the truth the wheel must stamp."""
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml carries no version"
    return match.group(1)


def _make_venv(tmp_path_factory, name: str) -> Path:
    """A fresh stdlib venv with pip; its bin dir is what the tests drive."""
    root = tmp_path_factory.mktemp(name)
    venv.EnvBuilder(with_pip=True).create(root)
    return root / "bin"


@pytest.fixture(scope="session")
def built_artifacts(tmp_path_factory) -> tuple[Path, Path]:
    """Build the wheel and sdist from a CLEAN checkout, into a tmp out-dir.

    The repo `dist/` must stay wheel-free (the docker clean-checkout property,
    `tests/test_docker_image.py`), so a stale wheel is swept first — the same
    sweep `tests/conftest.py` performs before the docker build — and the dir is
    re-asserted clean AFTER the build, so a build that leaked into it fails this
    fixture rather than passing silently.
    """
    dist = _REPO_ROOT / "dist"
    for stale in dist.glob("belay_harness-*.whl"):
        stale.unlink()
    assert not list(dist.glob("belay_harness-*.whl")), "a stale wheel sat in repo dist/"
    out_dir = tmp_path_factory.mktemp("artifacts")
    build = subprocess.run(
        ["uv", "build", "--out-dir", str(out_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert not list(dist.glob("belay_harness-*.whl")), (
        "uv build wrote into the repo dist/; it must build into the tmp out-dir"
    )
    wheels = sorted(out_dir.glob("belay_harness-*.whl"))
    sdists = sorted(out_dir.glob("belay_harness-*.tar.gz"))
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists
    return wheels[0], sdists[0]


@pytest.fixture(scope="session")
def installed_wheel(built_artifacts, tmp_path_factory) -> tuple[Path, Path]:
    """The wheel installed into a fresh venv with `--no-index --no-deps` (no network)."""
    wheel, _sdist = built_artifacts
    venv_bin = _make_venv(tmp_path_factory, "wheel-venv")
    install = subprocess.run(
        [
            str(venv_bin / "python"),
            "-m", "pip", "install",
            "--no-index", "--no-deps", str(wheel),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    return venv_bin, wheel


def test_installed_cli_help_lists_the_surface(installed_wheel) -> None:
    """The installed `belay` entrypoint shows the full CLI surface."""
    venv_bin, _wheel = installed_wheel
    run = subprocess.run(
        [str(venv_bin / "belay"), "--help"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    for subcommand in ("sandbox", "replay", "verify", "corpus", "phase0", "interop"):
        assert subcommand in run.stdout


def test_version_stamps_from_the_installed_wheel(installed_wheel) -> None:
    """The installed package reports the version of THIS checkout's wheel."""
    venv_bin, _wheel = installed_wheel
    run = subprocess.run(
        [str(venv_bin / "python"), "-c", "import belay; print(belay.__version__)"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == _project_version()


def test_installed_package_pulls_no_third_party_imports(installed_wheel) -> None:
    """Importing the installed package adds no third-party root to sys.modules.

    A subprocess, so the assertion is about the installed venv's import graph,
    never the test process's. The baseline is taken BEFORE the import, so what is
    measured is what belay pulled in — not what the interpreter happens to start
    with (`sitecustomize`, `__main__`, and the like).
    """
    venv_bin, _wheel = installed_wheel
    code = (
        "import sys\n"
        "before = {n.split('.')[0] for n in sys.modules}\n"
        "import belay, belay.cli, belay.proxy, belay.verify\n"
        "pulled = {n.split('.')[0] for n in sys.modules} - before\n"
        "third_party = sorted(r for r in pulled if r not in sys.stdlib_module_names and r != 'belay')\n"
        "assert not third_party, f'belay pulled third-party imports: {third_party}'\n"
        "print('OK')\n"
    )
    run = subprocess.run(
        [str(venv_bin / "python"), "-c", code],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    assert "OK" in run.stdout


def test_sandbox_check_runs_from_the_installed_cli(installed_wheel, tmp_path) -> None:
    """`belay sandbox check` probes the substrate from the installed CLI.

    On macOS the mechanism is Seatbelt (`sandbox-exec`); on Linux, Landlock. A
    host without the mechanism reports its named cause, and this SKIPS carrying
    it verbatim — never a fabricated pass (the docker inimage precedent,
    `tests/test_docker_inimage.py`).
    """
    venv_bin, _wheel = installed_wheel
    scope = tmp_path / "scope"
    scope.mkdir()
    run = subprocess.run(
        [str(venv_bin / "belay"), "sandbox", "check", "--scope", str(scope)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    out = run.stdout + run.stderr
    if "sandbox-exec" in out and "PROBLEM" in out:
        pytest.skip(f"seatbelt-unavailable: no sandbox-exec on this host: {out.strip()}")
    if "landlock" in out and "unavailable" in out:
        pytest.skip(f"landlock-unavailable: the host kernel offers no Landlock: {out.strip()}")
    assert run.returncode == 0, out
    assert "substrate ok" in out


def test_capture_verify_roundtrip_from_the_installed_cli(installed_wheel, tmp_path) -> None:
    """Capture a real turn through the INSTALLED proxy, then verify it installed.

    The client spawns `sys.executable -m belay.proxy` (the venv's installed
    proxy); the gate snapshots the workspace; then the installed `belay verify`
    restores the pre-state into a scratch tree and re-invokes the server. The
    server script and its trace-wait helper go INTO the workspace, so replay's
    relocation of in-root absolute paths is what the server actually runs on —
    a server rooted outside the recorded workspace is honestly UNVERIFIED (the
    docker inimage reasoning).
    """
    venv_bin, _wheel = installed_wheel
    # realpath'd: the gate records the workspace's REALPATH as `source_root`, and
    # replay's relocation is lexical — a workspace under a symlinked tmp root
    # (macOS `/tmp` -> `/private/tmp`) would not lexically match and the replayed
    # write would be denied. pytest's basetemp is already realpath'd; this makes
    # the guarantee explicit rather than inherited from the runner's choice.
    ws = Path(os.path.realpath(tmp_path / "ws"))
    ws.mkdir()
    snap = tmp_path / "sn"
    snap.mkdir()
    trace_dir = tmp_path / "tr"
    trace_dir.mkdir()
    shutil.copy(_FIXTURES / "docker_roundtrip_server.py", ws / "server.py")
    shutil.copy(_FIXTURES / "docker_roundtrip_trace.py", ws / "docker_roundtrip_trace.py")

    env = os.environ.copy()
    env["BELAY_SANDBOX_SCOPE"] = str(ws)
    env["BELAY_SNAPSHOT_DIR"] = str(snap)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    capture = subprocess.run(
        [
            str(venv_bin / "python"),
            str(_FIXTURES / "docker_roundtrip_client.py"),
            str(ws / "server.py"),
            str(ws / "note.txt"),
        ],
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert (ws / "note.txt").exists()
    traces = sorted(trace_dir.glob("*.jsonl"))
    assert len(traces) == 1, traces

    verify = subprocess.run(
        [
            str(venv_bin / "belay"), "verify", str(traces[0]),
            "--manifest-dir", str(tmp_path / "sn.manifests"),
            "--server", str(venv_bin / "python"), str(ws / "server.py"),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    out = verify.stdout
    assert re.search(r"turn 0\s+write_note\s+PASS", out), out
    assert re.search(r"A2 replay\s+PASS\s+replayed reply reproduced the recorded reply", out), out
    assert re.search(r"A2 effect\s+PASS", out), out
    assert re.search(r"PASS\s+1", out), out
    assert re.search(r"FAIL\s+0", out), out
    assert re.search(r"UNVERIFIED\s+0", out), out
    assert "A2 PASS means THE TRACE REPRODUCES" in out
    assert "It does NOT mean the agent did the right thing." in out
    assert "No model is consulted." in out
    assert "NOT_COVERED" in out


def test_sdist_installs_and_runs(built_artifacts, tmp_path_factory) -> None:
    """The sdist installs in a fresh venv and `belay --help` works (S3).

    pip's build isolation needs to fetch the `hatchling` build backend, which
    `--no-index` refuses; the backend is therefore pre-installed into the venv
    from uv's own cache, and pip builds with `--no-build-isolation`. Both halves
    are offline: no index is ever consulted. No dev dependency is added — the
    build backend goes into a throwaway venv, never the project's groups.
    """
    _wheel, sdist = built_artifacts
    venv_bin = _make_venv(tmp_path_factory, "sdist-venv")
    backend = subprocess.run(
        [
            "uv", "pip", "install", "--python", str(venv_bin / "python"), "hatchling",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert backend.returncode == 0, backend.stdout + backend.stderr
    install = subprocess.run(
        [
            str(venv_bin / "python"),
            "-m", "pip", "install",
            "--no-index", "--no-build-isolation", str(sdist),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    run = subprocess.run(
        [str(venv_bin / "belay"), "--help"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
