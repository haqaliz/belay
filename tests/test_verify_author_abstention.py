"""A3 author abstention: `SubprocessAuthor` records WHY it produced no check.

`SubprocessAuthor.author_check` turns every failure into one `None` — the evaluator reads
that as UNVERIFIED `NO_CHECK_AUTHOR` — and that contract is unchanged here: every case
below still returns `None`, and nothing raises. What is new is the side channel:
`last_abstention` names the failure from the closed sub-cause vocabulary
(`belay.verify.claims.SUB_CAUSES`) with a bounded one-line detail, reset at the start of
every call so it never describes an earlier invocation.

Every stub is an inline `python -c` script — no fixture files, no network, no model. The
one wall-clock-sensitive test injects a 0.2 s timeout against a 5 s sleep (25x margin).
"""

from __future__ import annotations

import sys

from belay.verify import author
from belay.verify.claims import (
    SUB_CAUSE_AUTHOR_EXITED_NONZERO,
    SUB_CAUSE_AUTHOR_NOT_LAUNCHED,
    SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED,
    SUB_CAUSE_AUTHOR_OUTPUT_OVER_CAP,
    SUB_CAUSE_AUTHOR_REPORTED_ERROR,
    SUB_CAUSE_AUTHOR_TIMED_OUT,
    Abstention,
    Check,
    _one_line,
)
from belay.verify.trajectory import TurnFact

TURNS = [
    TurnFact(
        turn_index=0, request_seq=1, tool_name="read_file",
        replayed=True, is_error=False, command_line=None,
    )
]
MIB = 1024 * 1024
VALID = '{"source": "s", "argv": ["true"]}'


def _py_author(code: str, *, timeout: float = 5.0) -> author.SubprocessAuthor:
    return author.SubprocessAuthor((sys.executable, "-c", code), timeout=timeout)


def _stdout_author(text: str) -> author.SubprocessAuthor:
    return _py_author(f"import sys; sys.stdout.write({text!r})")


def _call(subject: author.SubprocessAuthor):
    return subject.author_check(
        "all tests pass", classification="VERIFICATION", turns=TURNS,
        final_state_files=["app.py"],
    )


def _assert_abstained(subject: author.SubprocessAuthor, sub_cause: str, detail: str) -> None:
    assert _call(subject) is None  # the return value is exactly today's
    assert subject.last_abstention == Abstention(sub_cause, detail)


# --- each failure shape names its own sub-cause (spec AC 1, 2) -----------------------


def test_nonzero_exit_names_the_code_and_last_stderr_line() -> None:
    _assert_abstained(
        _py_author(
            'import sys; sys.stderr.write("x\\nAuthorTimeoutError: boom\\n"); sys.exit(1)'
        ),
        SUB_CAUSE_AUTHOR_EXITED_NONZERO,
        "exit 1: AuthorTimeoutError: boom",
    )


def test_nonzero_exit_with_empty_stderr_names_only_the_code() -> None:
    _assert_abstained(
        _py_author("import sys; sys.exit(1)"), SUB_CAUSE_AUTHOR_EXITED_NONZERO, "exit 1"
    )


def test_timeout_is_split_from_launch_failure_and_names_the_timeout() -> None:
    subject = _py_author("import time; time.sleep(5)", timeout=0.2)
    assert _call(subject) is None
    assert subject.last_abstention is not None
    assert subject.last_abstention.sub_cause == SUB_CAUSE_AUTHOR_TIMED_OUT
    assert "0.2" in subject.last_abstention.detail


def test_nonexistent_executable_is_not_launched() -> None:
    _assert_abstained(
        author.SubprocessAuthor(("/nonexistent/belay-author",)),
        SUB_CAUSE_AUTHOR_NOT_LAUNCHED,
        "FileNotFoundError",
    )


def test_invalid_json_is_malformed() -> None:
    _assert_abstained(
        _stdout_author("not json"), SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED, "invalid JSON"
    )


def test_non_object_payload_is_malformed() -> None:
    _assert_abstained(
        _stdout_author("[1]"), SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED, "not an object"
    )


def test_non_string_source_is_malformed() -> None:
    _assert_abstained(
        _stdout_author('{"source": 1, "argv": []}'),
        SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED,
        "bad source",
    )


def test_non_string_argv_token_is_malformed() -> None:
    _assert_abstained(
        _stdout_author('{"source": "s", "argv": ["ok", 2]}'),
        SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED,
        "bad argv",
    )


def test_reported_error_carries_the_authors_reason() -> None:
    _assert_abstained(
        _stdout_author('{"error": "model declined"}'),
        SUB_CAUSE_AUTHOR_REPORTED_ERROR,
        "model declined",
    )


def test_unparseable_output_past_the_cap_is_over_cap() -> None:
    subject = _py_author(f'import sys; sys.stdout.write("a" * {MIB + 10})')
    assert _call(subject) is None
    assert subject.last_abstention is not None
    assert subject.last_abstention.sub_cause == SUB_CAUSE_AUTHOR_OUTPUT_OVER_CAP
    assert str(MIB) in subject.last_abstention.detail


# --- a produced check leaves no abstention; the channel resets (spec AC 2, 3, 4) -------


def test_valid_check_returns_the_check_and_no_abstention() -> None:
    subject = _stdout_author(VALID)
    assert _call(subject) == Check(source="s", argv=("true",))
    assert subject.last_abstention is None


def test_last_abstention_resets_on_the_next_call() -> None:
    subject = _stdout_author("nope")
    assert _call(subject) is None
    assert subject.last_abstention is not None
    subject.command = (sys.executable, "-c", f"import sys; sys.stdout.write({VALID!r})")
    assert _call(subject) == Check(source="s", argv=("true",))
    assert subject.last_abstention is None


def test_parseable_prefix_past_the_cap_still_returns_the_check() -> None:
    subject = _py_author(f'import sys; sys.stdout.write({VALID!r} + " " * {MIB})')
    assert _call(subject) == Check(source="s", argv=("true",))
    assert subject.last_abstention is None


# --- the detail is one bounded printable line (spec AC 6) ---------------------------------


def test_long_stderr_line_is_cut_to_200_chars_with_an_ellipsis() -> None:
    subject = _py_author('import sys; sys.stderr.write("e" * 500 + "\\n"); sys.exit(1)')
    assert _call(subject) is None
    detail = subject.last_abstention.detail
    assert detail.startswith("exit 1: eee")
    assert len(detail) == 200
    assert detail.endswith("…")


def test_reported_error_is_collapsed_to_one_printable_line() -> None:
    _assert_abstained(
        _stdout_author('{"error": "line one\\n\\tline\\u0007 two"}'),
        SUB_CAUSE_AUTHOR_REPORTED_ERROR,
        "line one line two",
    )


def test_one_line_collapses_whitespace_and_drops_control_chars() -> None:
    assert _one_line("  a\r\n b\x1b\x00c\t ") == "a bc"
    assert _one_line("x" * 10, limit=5) == "xxxx…"
    assert _one_line("x" * 5, limit=5) == "xxxxx"
    assert _one_line("") == ""
