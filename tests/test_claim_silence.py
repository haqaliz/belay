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


# --- (4) the phase0 ledger records D3 silence (AC 5) -----------------------------------

from belay.phase0.ledger import (  # noqa: E402
    Disposition,
    InstanceRecord,
    RunLedger,
    _REQUIRED_INSTANCE_FIELDS,
    from_json,
    to_json,
)
from belay.trace import append_claim_record  # noqa: E402

from test_phase0_claim import (  # noqa: E402
    CHECK as PHASE0_CHECK,
    FixedAuthor,
    FixedRunner,
    _batch,
    _stub_replay as _stub_phase0_replay,
    _write_gated_trace,
)

SILENCE = {"axis": "A3", "kind": "claim", "check": {"source": "pytest -q", "exit_code": 0}}


def _instance(trace_id: str, **kwargs) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=kwargs.pop("disposition", Disposition.VERIFIED_CLEAN),
        turn_status_counts=kwargs.pop("turn_status_counts", {"PASS": 2}),
        flagged_turns=[],
        flagged_addable=[],
        flagged_unaddable=[],
        unverified_causes={},
        error=None,
        **kwargs,
    )


def test_ledger_round_trips_claim_silence() -> None:
    """A recorded silence survives `to_json` / `from_json` exactly, and `claim` stays
    `None` beside it — the two are mutually exclusive."""
    ledger = RunLedger(instances=[_instance("trace-silent", claim_silence=dict(SILENCE))])

    rebuilt = from_json(json.loads(json.dumps(to_json(ledger))))

    inst = rebuilt.instances[0]
    assert inst.claim_silence == SILENCE
    assert inst.claim is None
    assert "claim_silence" not in _REQUIRED_INSTANCE_FIELDS


def test_ledger_without_claim_silence_is_byte_identical() -> None:
    """An old-shaped instance (no key) loads with `None` and re-serializes to the SAME
    bytes — old ledgers re-render byte-identically."""
    old = {
        "instances": [
            {
                "trace_id": "trace-x",
                "disposition": "VERIFIED_CLEAN",
                "turn_status_counts": {"PASS": 2},
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
                "not_covered_turns": {},
            }
        ]
    }

    rebuilt = from_json(old)

    assert rebuilt.instances[0].claim_silence is None
    assert json.dumps(to_json(rebuilt), sort_keys=False) == json.dumps(old)


def test_run_batch_records_silence_with_the_no_author_disposition(tmp_path, monkeypatch):
    """The check exits 0 through the REAL `run_batch` path: `claim` stays `None`,
    `claim_silence` names the check, and the disposition and counts equal a no-author
    run's — silence never flags, never counts."""
    _stub_phase0_replay(monkeypatch, tmp_path=tmp_path)
    monkeypatch.setattr(claims, "runner", FixedRunner(0))
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    silent = _batch(tmp_path, trace_path, claim_author=FixedAuthor(PHASE0_CHECK))
    absent = _batch(tmp_path, trace_path, claim_author=None)

    s, a = silent.instances[0], absent.instances[0]
    assert s.claim is None
    assert s.claim_silence == SILENCE
    assert a.claim_silence is None
    assert s.disposition is a.disposition is Disposition.VERIFIED_CLEAN
    assert s.turn_status_counts == a.turn_status_counts
    assert silent.violating_instances() == absent.violating_instances() == 0


def test_run_batch_disabled_axis_records_no_silence(tmp_path, monkeypatch):
    """`disable_claim_axis` with an exit-0 author: the axis never ran — no record."""
    _stub_phase0_replay(monkeypatch, tmp_path=tmp_path)
    monkeypatch.setattr(claims, "runner", FixedRunner(0))
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    ledger = _batch(
        tmp_path, trace_path,
        claim_author=FixedAuthor(PHASE0_CHECK), disable_claim_axis=True,
    )

    assert ledger.instances[0].claim_silence is None
