"""A3 author tests: the out-of-process BYOK check author contract.

`src/belay/verify/author.py` is the `CheckAuthor` implementation that shells out to a
user-supplied command (`BELAY_CLAIM_AUTHOR`, shlex-split): Belay writes one JSON object
to the command's stdin — `{"claim", "classification", "turns", "final_state_files"}` —
and the command answers on stdout with `{"source": ..., "argv": [...]}` (a check) or
`{"error": ...}` (an abstention). Nothing leaves the box; no model SDK, no network, no
vendor key — the wheel stays zero-dependency.

The failure posture is fail-closed and never-raising: `{"error": ...}`, a non-zero exit,
malformed stdout, a timeout, or output past the 1 MiB cap all yield `None` — which the
evaluator reads as `NO_CHECK_AUTHOR` (UNVERIFIED), never a guessed check. `author_from_env`
returns `None` (the axis is ABSENT) for an unset/blank/un-lexable variable — never a crash.

The deterministic CI fake is `tests/fixtures/fake_claim_author.py`: it validates the four
required stdin keys and answers with a fixed check, so a round-trip through it proves the
stdin contract end-to-end. The live model path is `tests/test_verify_author_live.py`,
`manual`-marked and never in CI.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from belay.verify import author
from belay.verify.claims import Check
from belay.verify.trajectory import TurnFact

FAKE_AUTHOR = Path(__file__).parent / "fixtures" / "fake_claim_author.py"

CLAIM = "all tests pass"
CLASSIFICATION = "VERIFICATION"
TURNS = [
    TurnFact(
        turn_index=0, request_seq=1, tool_name="read_file",
        replayed=True, is_error=False, command_line=None,
    )
]
FILES = ["app.py"]

CHECK = Check(source="echo ok", argv=("sh", "-c", "exit 0"))


def _py_author(code: str, *, timeout: float = 5.0) -> author.SubprocessAuthor:
    """One inline author command, no shell: `python -c <code>` straight through argv."""
    return author.SubprocessAuthor((sys.executable, "-c", code), timeout=timeout)


# --- the stdin/stdout contract, driven through the committed fake ------------------------


def test_fake_author_round_trips_the_stdin_contract() -> None:
    check = author.SubprocessAuthor((sys.executable, str(FAKE_AUTHOR))).author_check(
        CLAIM, classification=CLASSIFICATION, turns=TURNS, final_state_files=FILES
    )
    assert check == CHECK  # the fake validated the four required keys, then the check verbatim


def test_author_error_response_is_none() -> None:
    err = 'import sys, json; sys.stdout.write(json.dumps({"error": "no check"}))'
    assert _py_author(err).author_check(
        CLAIM, classification=CLASSIFICATION, turns=TURNS, final_state_files=FILES
    ) is None


def test_author_nonzero_exit_is_none() -> None:
    assert _py_author("import sys; sys.exit(3)").author_check(
        CLAIM, classification=CLASSIFICATION, turns=TURNS, final_state_files=FILES
    ) is None


def test_author_malformed_stdout_is_none() -> None:
    assert _py_author('import sys; sys.stdout.write("this is not json")').author_check(
        CLAIM, classification=CLASSIFICATION, turns=TURNS, final_state_files=FILES
    ) is None


def test_author_timeout_is_none() -> None:
    sleeper = _py_author("import time; time.sleep(30)", timeout=0.4)
    assert sleeper.author_check(
        CLAIM, classification=CLASSIFICATION, turns=TURNS, final_state_files=FILES
    ) is None  # the 30s sleep is the bound: far past the 0.4s timeout; no timing assertion


def test_author_output_past_the_cap_is_none() -> None:
    huge = (
        "import sys; "
        'sys.stdout.write(\'{"source": "\' + "x" * 2_000_000 + '
        '\'", "argv": ["sh", "-c", "exit 0"]}\')'
    )
    assert _py_author(huge).author_check(
        CLAIM, classification=CLASSIFICATION, turns=TURNS, final_state_files=FILES
    ) is None  # 2 MiB of valid JSON: capped at 1 MiB, the truncation is fail-closed


# --- configuration: BELAY_CLAIM_AUTHOR, absent never a crash ------------------------------


def test_author_from_env_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(author.AUTHOR_ENV, raising=False)
    assert author.author_from_env() is None  # the axis is ABSENT, not UNVERIFIED, not PASS


def test_author_from_env_blank_is_none() -> None:
    assert author.author_from_env({author.AUTHOR_ENV: "   "}) is None


def test_author_from_env_lexes_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_AUTHOR))}"
    monkeypatch.setenv(author.AUTHOR_ENV, command)
    configured = author.author_from_env()
    assert isinstance(configured, author.SubprocessAuthor)
    assert configured.command == (sys.executable, str(FAKE_AUTHOR))
    assert configured.timeout == author.AUTHOR_TIMEOUT


def test_author_from_env_unlexable_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(author.AUTHOR_ENV, 'python "unbalanced')
    assert author.author_from_env() is None  # absent, never a crash (cli.py:654-667 mirrors)