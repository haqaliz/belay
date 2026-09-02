"""A3 evaluator tests: the decision table, the never-PASS property, the seams.

Every row of the decision table (`docs/planning/claim-re-derivation-a3/evaluator/plan_20260902.md`
§2) is a test: author absent -> None; no claim record -> UNVERIFIED `NO_CLAIM_RECORDED`;
non-VERIFICATION claim -> UNVERIFIED `CLAIM_UNCLASSIFIABLE`; unobservable final state ->
UNVERIFIED `FINAL_STATE_UNOBSERVABLE`; no check from the author -> UNVERIFIED
`NO_CHECK_AUTHOR`; a check that did not execute -> UNVERIFIED `CHECK_DID_NOT_EXECUTE`
(message names timeout-vs-launch); non-zero exit -> FAIL carrying the check source and the
real exit code; exit 0 -> silence, asserted explicitly (D3 — silence is not PASS).

All tests are deterministic and substrate-free: the final-state replay is stubbed
(monkeypatch pattern of `tests/test_corpus_trajectory_run.py:89-109`) and the runner seam
(`claims.runner`) is a fake. No model call anywhere — the author and runner are injectable
seams by construction.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from belay.replay.engine import REPLAYED, UNVERIFIED as REPLAY_UNVERIFIED, TurnReplay
from belay.replay.reader import Skip
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_CHECK_DID_NOT_EXECUTE,
    CAUSE_CLAIM_UNCLASSIFIABLE,
    CAUSE_FINAL_STATE_UNOBSERVABLE,
    CAUSE_NO_CHECK_AUTHOR,
    CAUSE_NO_CLAIM_RECORDED,
    Check,
    CheckResult,
)
from belay.verify.verdict import Status

CHECK = Check(source="pytest -q", argv=("sh", "-c", "pytest -q"))


# --- the fakes: deterministic authors and runners through the seams ----------------------


class FakeAuthor:
    """The author seam, deterministic: returns the configured check, or None / raises."""

    def __init__(self, check: Check | None, *, raises: type[Exception] | None = None):
        self._check = check
        self._raises = raises
        self.calls: list[tuple[Any, ...]] = []

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        self.calls.append((claim_text, classification, turns, final_state_files))
        if self._raises is not None:
            raise self._raises(f"author failed: {self._raises.__name__}")
        return self._check


class FakeRunner:
    """The runner seam, deterministic: returns the configured result, or raises."""

    def __init__(self, result: CheckResult | None, *, raises: type[Exception] | None = None):
        self._result = result
        self._raises = raises
        self.calls: list[tuple[Any, ...]] = []

    def run(self, check, *, workspace, timeout):
        self.calls.append((check, workspace, timeout))
        if self._raises is not None:
            raise self._raises(f"runner failed: {self._raises.__name__}")
        return self._result


def _use_runner(monkeypatch: pytest.MonkeyPatch, kwargs: dict) -> dict:
    """Pop the row's runner (when it has one) onto the `claims.runner` seam."""
    runner = kwargs.pop("runner", None)
    if runner is not None:
        monkeypatch.setattr(claims, "runner", runner)
    return kwargs


# --- the decision-table row inputs, shared by the row tests and the property test -------


def _claim_skip(text: str | None = "all tests pass", *, seq: int = 21) -> list[Skip]:
    """A claim skip, the way the reader records one: `text` absent (never "") when None."""
    record: dict = {} if text is None else {"text": text}
    return [Skip(reason="unknown kind 'claim'", seq=seq, kind="claim", record=record)]


def _frame(seq: int, direction: str, message: dict) -> dict:
    """One trace frame record, the way the writer emits one: `raw` is base64 of the bytes."""
    raw = base64.b64encode(json.dumps(message).encode("ascii")).decode("ascii")
    return {"v": 1, "kind": "frame", "seq": seq, "dir": direction, "raw": raw}


def _tool_call_frames(tool: str, *, call_id: int = 2, start_seq: int = 1) -> list[dict]:
    """A correlatable `tools/call` request+response pair for the final-turn replay."""
    request = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {}},
    }
    response = {
        "jsonrpc": "2.0",
        "id": call_id,
        "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
    }
    return [_frame(start_seq, "c2s", request), _frame(start_seq + 1, "s2c", response)]


def _stub_replay(
    monkeypatch: pytest.MonkeyPatch, *, status: str = REPLAYED, workspace: str | None = "/unused"
) -> list[dict]:
    """Stub the final-turn replay, recording what the evaluator asked it to do."""
    seen: list[dict] = []

    def fake(records, n, **kwargs):
        seen.append({"n": n, **kwargs})
        return TurnReplay(turn_index=n, status=status, workspace=workspace, reinvoked=True)

    monkeypatch.setattr(claims, "replay_turn", fake)
    return seen


ROWS: dict[str, Callable[[Path], dict[str, Any]]] = {
    # | author is None | None (absent) |
    "author-absent": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=None,
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"),
    ),
    # | no claim record | UNVERIFIED NO_CLAIM_RECORDED |
    "no-claim-record": lambda tmp_path: dict(
        records=[], skips=[], verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"),
    ),
    # | classification != VERIFICATION | UNVERIFIED CLAIM_UNCLASSIFIABLE |
    "claim-unclassifiable": lambda tmp_path: dict(
        records=[], skips=_claim_skip("task done"), verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"),
    ),
    # | final state unobservable | UNVERIFIED FINAL_STATE_UNOBSERVABLE |
    "final-state-unobservable": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"),
    ),
    # | author returns None | UNVERIFIED NO_CHECK_AUTHOR |
    "no-check-author": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=FakeAuthor(None),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"), workspace=tmp_path,
    ),
    # | runner exit_code None, timeout | UNVERIFIED CHECK_DID_NOT_EXECUTE |
    "check-did-not-execute-timeout": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"), workspace=tmp_path,
        runner=FakeRunner(CheckResult(None, "", "timed out after 3.0s")),
    ),
    # | runner exit_code None, launch failure | UNVERIFIED CHECK_DID_NOT_EXECUTE |
    "check-did-not-execute-launch": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"), workspace=tmp_path,
        runner=FakeRunner(CheckResult(None, "", "could not launch: no such binary")),
    ),
    # | exit non-zero | FAIL |
    "exit-nonzero": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"), workspace=tmp_path,
        runner=FakeRunner(CheckResult(3, "boom", None)),
    ),
    # | exit 0 | None (silence) |
    "exit-zero": lambda tmp_path: dict(
        records=[], skips=_claim_skip(), verdicts={}, author=FakeAuthor(CHECK),
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"), workspace=tmp_path,
        runner=FakeRunner(CheckResult(0, "clean", None)),
    ),
}


# --- the decision table, one behavior per test ------------------------------------------

#: Every A3 verdict is axis/kind/status-stamped the same way; the rows differ only in cause.
def _assert_unverified(verdict, *, cause: str) -> None:
    assert verdict is not None
    assert verdict.axis == "A3"
    assert verdict.kind == "claim"
    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == cause
    assert cause in verdict.message
    assert "never PASS" in verdict.message


def test_author_absent_is_absent(tmp_path):
    assert claims.evaluate_claim(**ROWS["author-absent"](tmp_path)) is None


def test_no_claim_record_is_unverified(tmp_path):
    _assert_unverified(
        claims.evaluate_claim(**ROWS["no-claim-record"](tmp_path)),
        cause=CAUSE_NO_CLAIM_RECORDED,
    )


def test_claim_classified_not_verification_is_unverified_and_names_the_shape(tmp_path):
    verdict = claims.evaluate_claim(**ROWS["claim-unclassifiable"](tmp_path))
    _assert_unverified(verdict, cause=CAUSE_CLAIM_UNCLASSIFIABLE)
    assert verdict.expected["classification"] == "COMPLETION"
    assert "COMPLETION" in verdict.message


def test_claim_record_without_text_is_unclassified(tmp_path):
    kwargs = dict(ROWS["claim-unclassifiable"](tmp_path))
    kwargs["skips"] = _claim_skip(None)
    verdict = claims.evaluate_claim(**kwargs)
    _assert_unverified(verdict, cause=CAUSE_CLAIM_UNCLASSIFIABLE)
    assert "no text" in verdict.message


def test_final_state_unobservable_when_no_turn_exists(tmp_path, monkeypatch):
    seen = _stub_replay(monkeypatch)
    verdict = claims.evaluate_claim(**ROWS["final-state-unobservable"](tmp_path))
    _assert_unverified(verdict, cause=CAUSE_FINAL_STATE_UNOBSERVABLE)
    assert seen == []  # nothing to replay: the replay seam must not be reached


def test_final_state_unobservable_when_final_turn_does_not_replay(tmp_path, monkeypatch):
    kwargs = dict(ROWS["final-state-unobservable"](tmp_path))
    kwargs["records"] = _tool_call_frames("read_file")
    seen = _stub_replay(monkeypatch, status=REPLAY_UNVERIFIED)
    verdict = claims.evaluate_claim(**kwargs)
    _assert_unverified(verdict, cause=CAUSE_FINAL_STATE_UNOBSERVABLE)
    assert seen  # the last turn existed and replay WAS attempted, and still abstained


def test_final_state_materializes_from_the_replayed_last_turn(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("print(1)", encoding="utf-8")
    records = _tool_call_frames("read_file")
    seen = _stub_replay(monkeypatch, workspace=str(ws))
    author = FakeAuthor(CHECK)
    runner = FakeRunner(CheckResult(0, "clean", None))
    monkeypatch.setattr(claims, "runner", runner)
    result = claims.evaluate_claim(
        records=records, skips=_claim_skip(), verdicts={}, author=author,
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"),
    )
    assert result is None
    assert seen  # the final turn was replayed exactly once, against the stored server
    assert author.calls[0][3] == ["app.py"]  # the author saw the replayed workspace's files
    assert runner.calls[0][1] == Path(ws)  # and the check ran in that workspace


@pytest.mark.parametrize(
    ("tool", "expected_command"),
    [
        ("run_process", ("node", "shell.js")),
        ("read_file", ("node", "fs.js")),
    ],
)
def test_final_turn_shell_routing(tmp_path, monkeypatch, tool, expected_command):
    records = _tool_call_frames(tool)
    seen = _stub_replay(monkeypatch, workspace=str(tmp_path))
    author = FakeAuthor(CHECK)
    monkeypatch.setattr(claims, "runner", FakeRunner(CheckResult(0, "clean", None)))
    result = claims.evaluate_claim(
        records=records, skips=_claim_skip(), verdicts={}, author=author,
        manifest_dir=tmp_path / "m", server_command=("node", "fs.js"),
        shell_server_command=("node", "shell.js"),
    )
    assert result is None
    assert seen[0]["server_command"] == expected_command


def test_author_returning_no_check_is_unverified(tmp_path):
    _assert_unverified(
        claims.evaluate_claim(**ROWS["no-check-author"](tmp_path)),
        cause=CAUSE_NO_CHECK_AUTHOR,
    )


def test_author_raising_is_unverified_not_a_crash(tmp_path):
    kwargs = dict(ROWS["no-check-author"](tmp_path))
    kwargs["author"] = FakeAuthor(None, raises=RuntimeError)
    _assert_unverified(
        claims.evaluate_claim(**kwargs), cause=CAUSE_NO_CHECK_AUTHOR,
    )


def test_runner_exit_none_names_timeout(tmp_path, monkeypatch):
    kwargs = _use_runner(monkeypatch, dict(ROWS["check-did-not-execute-timeout"](tmp_path)))
    verdict = claims.evaluate_claim(**kwargs)
    _assert_unverified(verdict, cause=CAUSE_CHECK_DID_NOT_EXECUTE)
    assert "timed out" in verdict.message


def test_runner_exit_none_names_launch_failure(tmp_path, monkeypatch):
    kwargs = _use_runner(monkeypatch, dict(ROWS["check-did-not-execute-launch"](tmp_path)))
    verdict = claims.evaluate_claim(**kwargs)
    _assert_unverified(verdict, cause=CAUSE_CHECK_DID_NOT_EXECUTE)
    assert "could not launch" in verdict.message


def test_runner_raising_is_unverified_not_a_crash(tmp_path, monkeypatch):
    kwargs = dict(ROWS["check-did-not-execute-timeout"](tmp_path))
    kwargs["runner"] = FakeRunner(None, raises=OSError)
    kwargs = _use_runner(monkeypatch, kwargs)
    _assert_unverified(
        claims.evaluate_claim(**kwargs), cause=CAUSE_CHECK_DID_NOT_EXECUTE,
    )


def test_exit_nonzero_is_fail_carrying_source_and_exit_code(tmp_path, monkeypatch):
    kwargs = _use_runner(monkeypatch, dict(ROWS["exit-nonzero"](tmp_path)))
    verdict = claims.evaluate_claim(**kwargs)
    assert verdict is not None
    assert verdict.axis == "A3"
    assert verdict.kind == "claim"
    assert verdict.status is Status.FAIL
    assert verdict.observed == 3
    assert verdict.expected == "exit 0"
    assert CHECK.source in verdict.message
    assert "exit 3" in verdict.message


def test_exit_zero_is_silence_never_pass(tmp_path, monkeypatch):
    kwargs = _use_runner(monkeypatch, dict(ROWS["exit-zero"](tmp_path)))
    assert claims.evaluate_claim(**kwargs) is None


# --- the property: evaluate_claim can never emit PASS (spec acceptance 2) ---------------


@pytest.mark.parametrize("row", sorted(ROWS))
def test_evaluate_claim_never_emits_pass(row, tmp_path, monkeypatch):
    kwargs = _use_runner(monkeypatch, dict(ROWS[row](tmp_path)))
    result = claims.evaluate_claim(**kwargs)
    assert result is None or result.status is not Status.PASS


# --- the seams: author and runner are injectable, no model call (spec acceptance 6) -----


def test_author_and_runner_are_injectable_seams(tmp_path, monkeypatch):
    author = FakeAuthor(CHECK)
    runner = FakeRunner(CheckResult(0, "clean", None))
    monkeypatch.setattr(claims, "runner", runner)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x", encoding="utf-8")
    (ws / "sub").mkdir()
    (ws / "sub" / "b.txt").write_text("y", encoding="utf-8")

    result = claims.evaluate_claim(
        records=[], skips=_claim_skip(), verdicts={}, author=author,
        manifest_dir=tmp_path / "m", server_command=("node", "s.js"), workspace=ws,
    )
    assert result is None  # the fakes decided everything; nothing else was consulted

    assert len(author.calls) == 1
    claim_text, classification, turns, files = author.calls[0]
    assert claim_text == "all tests pass"
    assert classification == "VERIFICATION"
    assert turns == []
    assert files == ["a.txt", "sub", "sub/b.txt"]

    assert len(runner.calls) == 1
    check, workspace, timeout = runner.calls[0]
    assert check is CHECK
    assert workspace == ws
    assert timeout == claims.CHECK_TIMEOUT