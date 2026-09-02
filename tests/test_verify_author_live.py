"""A3 live author gate: a real local model CLI, ONLY when the operator asks for it.

The manual gate (spec acceptance 5): the deterministic fake in
`tests/test_verify_author.py` proves the stdin/stdout contract in CI; this test drives the
REAL configured author — whatever local model CLI / script the operator points
`BELAY_CLAIM_AUTHOR` at (claude, ollama, their own script). It is `manual`-marked and
excluded by the default `addopts` (`pyproject.toml:87`), so it NEVER runs in CI and never
spends on a model by accident.

To run it: `BELAY_CLAIM_AUTHOR="<your local author command>" uv run pytest \
tests/test_verify_author_live.py -m manual -q` — the test skips with instructions when
`BELAY_CLAIM_AUTHOR` is unset, and FAILS if the configured command does not author a
check, so the gate has teeth for the operator who opts in.

This is a GATE, not a measurement: it proves the live path produces a check, never how
good the check is. The exit code of the authored check — and therefore any verdict — is
decided later, by the runner, against the materialized final state.
"""

from __future__ import annotations

import os

import pytest

from belay.verify.author import AUTHOR_ENV, author_from_env
from belay.verify.trajectory import TurnFact

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not (os.environ.get(AUTHOR_ENV) or "").strip(),
        reason=(
            f"{AUTHOR_ENV} is unset — set it to your local author command line and run "
            "with -m manual to drive the live author path (never CI, never a model spend "
            "by accident)"
        ),
    ),
]


def test_live_author_produces_a_check_from_the_configured_command() -> None:
    """The configured local model CLI answers the stdin contract with a real check."""
    configured = author_from_env()
    assert configured is not None, f"{AUTHOR_ENV} is set but could not be configured"
    check = configured.author_check(
        "all tests pass",
        classification="VERIFICATION",
        turns=[
            TurnFact(
                turn_index=0, request_seq=1, tool_name="run_process",
                replayed=True, is_error=False, command_line="pytest -q",
            )
        ],
        final_state_files=["app.py"],
    )
    assert check is not None, (
        "the configured author returned no check — an abstention is legal downstream "
        "(NO_CHECK_AUTHOR), but the LIVE GATE must see a check to prove the path works"
    )
    print(f"author authored: {check.source!r} argv={check.argv!r}")