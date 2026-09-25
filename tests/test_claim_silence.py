"""silence-record: D3 silence is a named, sibling record — never absence, never a PASS.

`evaluate_claim` returns `None` both when no author is configured and when the authored
check exited 0 (D3 silence), so every surface that stored or omitted `claim` collapsed
*checked and silent* into *never checked*. This module pins the sibling `claim_silence`
record that separates them (`docs/planning/claim-axis-legibility/silence-record/spec.md`):

1. the PREMISE the surfaces derive silence from — with an author configured, the
   evaluator returns `None` exactly when the check's exit code was 0 (AC 1);
2. the record's shape and its place in the `verify --json` document (AC 2);
3. `claim` keeps its exact meaning — an A3 verdict exists — and the two are mutually
   exclusive; the record carries NO `status` key, by construction (R-A).
"""

from __future__ import annotations

import pytest

from belay.verify import claims
from belay.verify.claims import Check
from belay.verify import json as verify_json
from belay.verify.json import VerifyReport

from test_verify_claims import ROWS, _use_runner

CHECK = Check(source="pytest -q", argv=("sh", "-c", "pytest -q"))


# --- (1) the premise pin (AC 1) --------------------------------------------------------


class _ExitSpy:
    """Wraps the row's runner and records the exit code it answered, if it was reached."""

    def __init__(self, inner):
        self._inner = inner
        self.exit_codes: list = []

    def run(self, check, *, workspace, timeout):
        result = self._inner.run(check, workspace=workspace, timeout=timeout)
        self.exit_codes.append(result.exit_code)
        return result


@pytest.mark.parametrize("row", sorted(r for r in ROWS if r != "author-absent"))
def test_evaluator_returns_none_only_on_exit_zero(row, tmp_path, monkeypatch):
    """With a non-`None` author, `evaluate_claim` returns `None` ⇔ the check exited 0.

    Every surface derives silence from this — *the evaluator was called, returned
    `None`, and the recorder holds a check* — so the inference is locked here rather
    than assumed: a new evaluator branch that returns `None` for anything else fails.
    """
    kwargs = _use_runner(monkeypatch, dict(ROWS[row](tmp_path)))
    spy = _ExitSpy(claims.runner)
    monkeypatch.setattr(claims, "runner", spy)

    result = claims.evaluate_claim(**kwargs)

    exited_zero = spy.exit_codes == [0]
    assert (result is None) == exited_zero, (row, result, spy.exit_codes)


# --- (2) the record and its place in the document (AC 2) -------------------------------


def test_claim_silence_record_shape() -> None:
    """The record is exactly axis/kind/check — the check that ran and its exit 0 — and
    carries NO `status` key: silence is never a verdict, so it cannot be read as one."""
    record = verify_json.claim_silence_record(CHECK)

    assert record == {
        "axis": "A3",
        "kind": "claim",
        "check": {"source": "pytest -q", "exit_code": 0},
    }
    assert "status" not in record
    assert "cause" not in record


def _report(**kwargs) -> VerifyReport:
    base = dict(
        trace="t.jsonl",
        turns=[],
        aggregate={},
        coverage={},
        exposure={},
        trajectory=None,
        claim=None,
        error=None,
    )
    base.update(kwargs)
    return VerifyReport(**base)


def test_verify_report_key_order() -> None:
    """`claim_silence` sits after where `claim` would, before `error`; absent when unset."""
    doc = _report(claim_silence=verify_json.claim_silence_record(CHECK)).as_dict()
    keys = list(doc)
    assert "claim" not in doc
    assert keys.index("trajectory") < keys.index("claim_silence") < keys.index("error"), keys

    absent = _report().as_dict()
    assert "claim_silence" not in absent


# --- (3) `verify --json` through the REAL CLI, stubbed engine seams (AC 2) -------------

import json  # noqa: E402

from belay import cli  # noqa: E402
from belay.verify import turn as turn_module  # noqa: E402

from test_verify_claim_surfaces import (  # noqa: E402
    _canned_verifier,
    _claim_author_cmd,
    _edit_trace,
    _stub_claim_seams,
)


def _verify_json(tmp_path, capsys, *extra: str) -> dict:
    trace_path = _edit_trace(tmp_path, claim="all tests pass")
    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            *extra,
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0, doc
    return doc


def test_verify_json_names_d3_silence(tmp_path, monkeypatch, capsys):
    """The check exits 0: no `claim` (no verdict exists), and the sibling record says
    the axis ran — the exact check source, exit 0, and no status."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=0)

    doc = _verify_json(tmp_path, capsys, "--claim-author", _claim_author_cmd())

    assert "claim" not in doc, doc
    assert doc["claim_silence"] == {
        "axis": "A3",
        "kind": "claim",
        "check": {"source": "pytest -q", "exit_code": 0},
    }
    keys = list(doc)
    assert keys.index("trajectory") < keys.index("claim_silence") < keys.index("error"), keys


def test_verify_json_no_author_carries_no_silence(tmp_path, monkeypatch, capsys):
    """No author: the axis never ran, so there is nothing to be silent about."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    monkeypatch.delenv("BELAY_CLAIM_AUTHOR", raising=False)

    doc = _verify_json(tmp_path, capsys)

    assert "claim" not in doc and "claim_silence" not in doc, doc


def test_verify_json_no_claim_axis_carries_no_silence(tmp_path, monkeypatch, capsys):
    """`--no-claim-axis` wins over an author whose check would exit 0: never ran."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=0)

    doc = _verify_json(
        tmp_path, capsys, "--no-claim-axis", "--claim-author", _claim_author_cmd()
    )

    assert "claim" not in doc and "claim_silence" not in doc, doc


def test_verify_json_turn_n_carries_no_silence(tmp_path, monkeypatch, capsys):
    """`--turn 0`: A3 is instance-level, never evaluated on partial facts — no record."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=0)

    doc = _verify_json(
        tmp_path, capsys, "--turn", "0", "--claim-author", _claim_author_cmd()
    )

    assert "claim" not in doc and "claim_silence" not in doc, doc


@pytest.mark.parametrize(
    ("exit_code", "error", "status"),
    [(1, False, "FAIL"), (1, True, "UNVERIFIED")],
)
def test_verify_json_a_verdict_carries_no_silence(
    tmp_path, monkeypatch, capsys, exit_code, error, status
):
    """A FAIL or an UNVERIFIED claim is a verdict: `claim` present, `claim_silence`
    absent — the two are mutually exclusive."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=exit_code)

    doc = _verify_json(
        tmp_path, capsys, "--claim-author", _claim_author_cmd(error=error)
    )

    assert doc["claim"]["status"] == status, doc
    assert "claim_silence" not in doc, doc
