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
