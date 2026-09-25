"""surface-threading M7: the sub-cause and the silence record, end to end through the real CLI.

The fakes in `test_verify_author_abstention.py` pin the vocabulary; this module pins that
the seam CARRIES it — `belay verify --json --claim-author <stub>` on the committed demo
capture, as an operator runs it, with five stub authors under
`tests/fixtures/claim_authors/` (the L7 / `--timeout` lesson: a surface's own tests
could not see what running it showed). Each run is a real process running the
`belay.cli:main` console-script entry point, replaying the demo's ~44 s `run_process`
turns for real (spec AC 6):

- exit 1 + a named stderr line -> `AUTHOR_EXITED_NONZERO`, the stderr line in the detail;
- sleep past the author timeout -> `AUTHOR_TIMED_OUT`;
- stdout not JSON -> `AUTHOR_OUTPUT_MALFORMED`;
- `{"error": ...}` -> `AUTHOR_REPORTED_ERROR`, the error string in the detail;
- a valid check that exits 0 -> `claim_silence` present, `claim` absent.

In all five, `turns`, `aggregate`, `trajectory` and the exit code equal the no-author
run's: a sub-cause and a silence record refine what the A3 axis SAYS, never a verdict.

**Cost control, and why the timeout is NOT injected.** Six real runs (one shared
no-author baseline + five stubs) at ~90–190 s each would cost ~13 min sequentially, so
the module fixture launches all six processes CONCURRENTLY and waits once (wall ≈ the
slowest run). Being separate processes, no monkeypatch can reach them — and none is
needed: the sleep stub simply outlasts the SHIPPED `AUTHOR_TIMEOUT` (60 s), so the
timeout observed is the one an operator gets, not a test-only 0.5 s. (The plan's
`author_from_env` patch would not have reached `--claim-author` anyway: that flag
constructs `SubprocessAuthor` directly in `_cmd_verify`.)

Darwin-gated like every capture test: replay re-invokes inside the Seatbelt sandbox.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from belay.verify.author import AUTHOR_TIMEOUT
from test_demo_capture import (
    REPLAY_TIMEOUT,
    SERVER,
    _DEMO_SUITE_CHECK,
    _capture_trace,
    _manifest_dir,
    _recorded_source_root,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the demo capture's re-execution runs inside the "
        "macOS Seatbelt sandbox; the Linux side is measured in tests/test_docker_inimage.py"
    ),
)

AUTHORS = Path(__file__).resolve().parent / "fixtures" / "claim_authors"

#: The real CLI, as the `belay` console script runs it (`belay.cli:main`), under the
#: interpreter running this suite — so the process imports the same package under test.
_BELAY = [sys.executable, "-c", "import sys; from belay.cli import main; sys.exit(main())"]

#: Each process's wall budget: seven replays at up to REPLAY_TIMEOUT would be far more,
#: but the capture's measured cost is ~90 s plus the A3 final-state replay, the check,
#: and (for the sleep stub) the author timeout; ten minutes is a hang detector.
_WALL = 600.0


def _author(script: str, *args: str) -> str:
    """The `--claim-author` string: ONE shell command line, as an operator types it."""
    return shlex.join([sys.executable, str(AUTHORS / script), *args])


def _stubs() -> dict[str, str]:
    return {
        "exit_nonzero": _author("exit_nonzero.py"),
        # Past the shipped author timeout, never an injected one.
        "sleep": _author("sleep.py", str(AUTHOR_TIMEOUT + 30)),
        "malformed": _author("malformed.py"),
        "error": _author("error.py"),
        "exit_zero": _author(
            "exit_zero.py", _DEMO_SUITE_CHECK.source, *_DEMO_SUITE_CHECK.argv
        ),
    }


def _argv(extra: list[str]) -> list[str]:
    """`belay verify --json` on the committed demo capture; `extra` sits before
    `--server`, which is `argparse.REMAINDER`."""
    return [
        *_BELAY,
        "verify",
        str(_capture_trace()),
        "--manifest-dir",
        str(_manifest_dir()),
        "--timeout",
        str(int(REPLAY_TIMEOUT)),
        "--json",
        *extra,
        "--server",
        sys.executable,
        str(SERVER),
        _recorded_source_root(),
    ]


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, tuple[int, dict]]:
    """Six real `belay verify --json` processes, launched together: the shared
    no-author baseline and one per stub. Returns name -> (exit code, document)."""
    out_dir = tmp_path_factory.mktemp("claim-e2e")
    plans = {"baseline": []}
    plans.update({name: ["--claim-author", cmd] for name, cmd in _stubs().items()})
    # An inherited BELAY_CLAIM_AUTHOR would give the baseline an author it must not have.
    env = {k: v for k, v in os.environ.items() if k != "BELAY_CLAIM_AUTHOR"}

    procs = {}
    for name, extra in plans.items():
        stdout = (out_dir / f"{name}.json").open("wb")
        stderr = (out_dir / f"{name}.err").open("wb")
        procs[name] = (
            subprocess.Popen(_argv(extra), stdout=stdout, stderr=stderr, env=env),
            stdout,
            stderr,
        )
    results = {}
    try:
        for name, (proc, stdout, stderr) in procs.items():
            rc = proc.wait(timeout=_WALL)
            stdout.close()
            stderr.close()
            text = (out_dir / f"{name}.json").read_text(encoding="utf-8")
            assert text.strip(), (
                f"{name}: empty stdout (rc {rc}); stderr: "
                + (out_dir / f"{name}.err").read_text(encoding="utf-8", errors="replace")
            )
            results[name] = (rc, json.loads(text))
    finally:
        for proc, stdout, stderr in procs.values():
            if proc.poll() is None:
                proc.kill()
            stdout.close()
            stderr.close()
    return results


def _assert_verdicts_equal_the_baseline(runs, name: str) -> dict:
    rc, doc = runs[name]
    base_rc, base = runs["baseline"]
    assert rc == base_rc == 0, (name, rc, base_rc)
    for key in ("turns", "aggregate", "trajectory"):
        assert doc[key] == base[key], (name, key)
    assert base["turns"] and all(t["status"] == "PASS" for t in base["turns"]), base
    return doc


def test_the_baseline_has_no_claim_and_no_silence(runs) -> None:
    rc, doc = runs["baseline"]
    assert rc == 0
    assert "claim" not in doc and "claim_silence" not in doc, doc


@pytest.mark.parametrize(
    "name, sub_cause, detail",
    [
        (
            "exit_nonzero",
            "AUTHOR_EXITED_NONZERO",
            "exit 1: AuthorTimeoutError: the model did not answer",
        ),
        ("sleep", "AUTHOR_TIMED_OUT", f"no reply within {AUTHOR_TIMEOUT:g}s"),
        ("malformed", "AUTHOR_OUTPUT_MALFORMED", "invalid JSON"),
        (
            "error",
            "AUTHOR_REPORTED_ERROR",
            "model declined: no executable check for this claim",
        ),
    ],
)
def test_an_abstaining_author_names_its_sub_cause(runs, name, sub_cause, detail) -> None:
    doc = _assert_verdicts_equal_the_baseline(runs, name)
    assert doc["claim"] == {
        "axis": "A3",
        "kind": "claim",
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
        "sub_cause": sub_cause,
        "sub_cause_detail": detail,
    }
    assert "claim_silence" not in doc, doc


def test_a_check_that_exits_zero_is_named_silence(runs) -> None:
    doc = _assert_verdicts_equal_the_baseline(runs, "exit_zero")
    assert "claim" not in doc, doc
    assert doc["claim_silence"] == {
        "axis": "A3",
        "kind": "claim",
        "check": {"source": _DEMO_SUITE_CHECK.source, "exit_code": 0},
    }
