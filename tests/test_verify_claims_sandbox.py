"""A3 real-runner smoke: the `ContainedRunner` on the host substrate.

`tests/test_verify_claims.py` proves the decision table with stub authors and fake
runners; this file proves the REAL runner — the one production uses — inside the actual
Seatbelt sandbox: a real check process in a real workspace (exit codes), a real timeout
kill, and a real launch failure. Everything here re-spawns a process inside `contained`,
so it is darwin-gated like `tests/test_demo_capture.py:284-290`: Seatbelt is the macOS
backend, and the Linux side of this smoke is measured in-container by the docker job.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from belay.replay.reader import Skip
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_CHECK_DID_NOT_EXECUTE,
    Check,
    ContainedRunner,
)
from belay.verify.verdict import Status

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the real contained A3 check runner spawns inside the "
        "macOS Seatbelt sandbox; the Linux side is measured in tests/test_docker_inimage.py"
    ),
)


def _claim_skip() -> list[Skip]:
    return [
        Skip(reason="unknown kind 'claim'", seq=21, kind="claim",
             record={"text": "all tests pass"})
    ]


class _Author:
    """The minimal author seam: hand back exactly the check the test asks for."""

    def __init__(self, check: Check):
        self._check = check

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return self._check


def test_contained_runner_reports_the_real_exit_code(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("present", encoding="utf-8")
    result = ContainedRunner().run(
        Check(
            source="test -f marker.txt && exit 3 || exit 7",
            argv=("sh", "-c", "test -f marker.txt && exit 3 || exit 7"),
        ),
        workspace=tmp_path,
        timeout=10,
    )
    assert result.exit_code == 3  # the check RAN, in the workspace, and decided 3 — not 7
    assert result.error is None


def test_contained_runner_timeout_kills_and_names_the_cause(tmp_path: Path) -> None:
    check = Check(source="sleep 30", argv=("sh", "-c", "sleep 30"))
    verdict = claims.evaluate_claim(
        records=[], skips=_claim_skip(), verdicts={}, author=_Author(check),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"),
        workspace=tmp_path, timeout=1.0,
    )
    assert verdict is not None
    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == CAUSE_CHECK_DID_NOT_EXECUTE
    assert "timed out" in verdict.message
    assert check.source in verdict.message


def test_contained_runner_launch_failure_is_did_not_execute(tmp_path: Path) -> None:
    result = ContainedRunner().run(
        Check(source="run in a missing workspace", argv=("sh", "-c", "exit 0")),
        workspace=tmp_path / "does-not-exist",
        timeout=5,
    )
    assert result.exit_code is None
    assert "could not launch" in (result.error or "")