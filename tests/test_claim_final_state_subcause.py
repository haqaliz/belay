"""A3 evaluator: a `FINAL_STATE_UNOBSERVABLE` verdict carries which of four reasons applied.

`_unverified` refuses a sub-cause under any cause but its own (`SUB_CAUSES_BY_CAUSE`), and
`evaluate_claim` records which of the four reasons left no final state to run a check
against: no turn, the replay raised, the last turn did not replay, or it replayed with no
workspace. The sub-cause refines the reason, never the status: every case is still
UNVERIFIED `FINAL_STATE_UNOBSERVABLE`, never PASS. The rows and stub seams are reused from
`tests/test_verify_claims.py`, not copied.
"""

from __future__ import annotations

import pytest

from belay.replay.engine import REPLAYED, TurnReplay
from belay.replay.engine import UNVERIFIED as REPLAY_UNVERIFIED
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_CLAIM_UNCLASSIFIABLE,
    CAUSE_FINAL_STATE_UNOBSERVABLE,
    CAUSE_NO_CHECK_AUTHOR,
    SUB_CAUSE_AUTHOR_RAISED,
    SUB_CAUSE_FINAL_STATE_NO_TURN,
    SUB_CAUSE_FINAL_STATE_NO_WORKSPACE,
    SUB_CAUSE_FINAL_STATE_NOT_REPLAYED,
    SUB_CAUSE_FINAL_STATE_REPLAY_RAISED,
    Abstention,
)
from belay.verify.verdict import Status
from test_verify_claims import ROWS, _assert_unverified, _stub_replay, _tool_call_frames


# --- the mismatch guard in `_unverified` ------------------------------------------------


def test_final_state_cause_refuses_an_author_sub_cause() -> None:
    with pytest.raises(ValueError, match="AUTHOR_RAISED"):
        claims._unverified(
            CAUSE_FINAL_STATE_UNOBSERVABLE, detail="x",
            abstention=Abstention(SUB_CAUSE_AUTHOR_RAISED, ""),
        )


def test_no_check_author_refuses_a_final_state_sub_cause() -> None:
    with pytest.raises(ValueError, match="FINAL_STATE_NO_TURN"):
        claims._unverified(
            CAUSE_NO_CHECK_AUTHOR, detail="x",
            abstention=Abstention(SUB_CAUSE_FINAL_STATE_NO_TURN, ""),
        )


def test_a_cause_outside_the_map_refuses_any_abstention() -> None:
    with pytest.raises(ValueError):
        claims._unverified(
            CAUSE_CLAIM_UNCLASSIFIABLE, detail="x",
            abstention=Abstention(SUB_CAUSE_FINAL_STATE_NO_TURN, ""),
        )


def test_a_matching_pair_builds_with_detail_in_the_message() -> None:
    verdict = claims._unverified(
        CAUSE_FINAL_STATE_UNOBSERVABLE, detail="x", claim_seq=3,
        abstention=Abstention(SUB_CAUSE_FINAL_STATE_REPLAY_RAISED, "OSError"),
    )
    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["sub_cause"] == SUB_CAUSE_FINAL_STATE_REPLAY_RAISED
    assert verdict.expected["sub_cause_detail"] == "OSError"
    assert "(FINAL_STATE_REPLAY_RAISED: OSError)" in verdict.message


def test_a_matching_pair_with_no_detail_has_a_bare_suffix() -> None:
    verdict = claims._unverified(
        CAUSE_FINAL_STATE_UNOBSERVABLE, detail="x",
        abstention=Abstention(SUB_CAUSE_FINAL_STATE_NO_TURN, ""),
    )
    assert verdict.expected["sub_cause_detail"] == ""
    assert "(FINAL_STATE_NO_TURN)" in verdict.message


def test_an_abstention_free_unverified_stays_legal() -> None:
    verdict = claims._unverified(CAUSE_FINAL_STATE_UNOBSERVABLE, detail="x")
    assert "sub_cause" not in verdict.expected


# --- the producer: each of the four reasons, through the real `evaluate_claim` ----------


def _final_state_kwargs(tmp_path, *, records=None):
    kwargs = dict(ROWS["final-state-unobservable"](tmp_path))
    if records is not None:
        kwargs["records"] = records
    return kwargs


def _assert_final_state(verdict, sub_cause: str) -> None:
    _assert_unverified(verdict, cause=CAUSE_FINAL_STATE_UNOBSERVABLE)
    assert verdict.message.endswith("never PASS")
    assert verdict.expected["sub_cause"] == sub_cause
    assert "claim_seq" in verdict.expected
    assert "classification" in verdict.expected


def test_no_turn(tmp_path, monkeypatch) -> None:
    seen = _stub_replay(monkeypatch)
    verdict = claims.evaluate_claim(**_final_state_kwargs(tmp_path))
    _assert_final_state(verdict, SUB_CAUSE_FINAL_STATE_NO_TURN)
    assert verdict.expected["sub_cause_detail"] == ""
    assert seen == []  # the replay seam was never reached


def test_replay_raised_records_the_type_name_only(tmp_path, monkeypatch) -> None:
    def boom(records, n, **kwargs):
        raise RuntimeError("secret\nmultiline")

    monkeypatch.setattr(claims, "replay_turn", boom)
    verdict = claims.evaluate_claim(
        **_final_state_kwargs(tmp_path, records=_tool_call_frames("read_file"))
    )
    _assert_final_state(verdict, SUB_CAUSE_FINAL_STATE_REPLAY_RAISED)
    assert verdict.expected["sub_cause_detail"] == "RuntimeError"
    assert "secret" not in verdict.message


def _fake_replay(monkeypatch, *, status, cause=None, workspace=None) -> None:
    def fake(records, n, **kwargs):
        return TurnReplay(
            turn_index=n, status=status, cause=cause, workspace=workspace, reinvoked=True
        )

    monkeypatch.setattr(claims, "replay_turn", fake)


def test_not_replayed_records_status_and_cause(tmp_path, monkeypatch) -> None:
    _fake_replay(monkeypatch, status=REPLAY_UNVERIFIED, cause="server exited early")
    verdict = claims.evaluate_claim(
        **_final_state_kwargs(tmp_path, records=_tool_call_frames("read_file"))
    )
    _assert_final_state(verdict, SUB_CAUSE_FINAL_STATE_NOT_REPLAYED)
    detail = verdict.expected["sub_cause_detail"]
    assert detail == f"{REPLAY_UNVERIFIED}: server exited early"


def test_not_replayed_without_a_cause_records_the_status_alone(tmp_path, monkeypatch) -> None:
    _stub_replay(monkeypatch, status=REPLAY_UNVERIFIED)
    verdict = claims.evaluate_claim(
        **_final_state_kwargs(tmp_path, records=_tool_call_frames("read_file"))
    )
    _assert_final_state(verdict, SUB_CAUSE_FINAL_STATE_NOT_REPLAYED)
    assert verdict.expected["sub_cause_detail"] == REPLAY_UNVERIFIED


def test_not_replayed_detail_is_one_bounded_line(tmp_path, monkeypatch) -> None:
    _fake_replay(monkeypatch, status=REPLAY_UNVERIFIED, cause="line one\n" + "x" * 500)
    verdict = claims.evaluate_claim(
        **_final_state_kwargs(tmp_path, records=_tool_call_frames("read_file"))
    )
    detail = verdict.expected["sub_cause_detail"]
    assert "\n" not in detail
    assert len(detail) <= 200


def test_not_replayed_detail_cut_keeps_a_multibyte_cause_valid(tmp_path, monkeypatch) -> None:
    _fake_replay(monkeypatch, status=REPLAY_UNVERIFIED, cause="é" * 500)
    verdict = claims.evaluate_claim(
        **_final_state_kwargs(tmp_path, records=_tool_call_frames("read_file"))
    )
    detail = verdict.expected["sub_cause_detail"]
    assert len(detail) <= 200
    detail.encode("utf-8")  # a split character would not survive this round trip
    assert detail.endswith("…")


def test_no_workspace(tmp_path, monkeypatch) -> None:
    _stub_replay(monkeypatch, status=REPLAYED, workspace=None)
    verdict = claims.evaluate_claim(
        **_final_state_kwargs(tmp_path, records=_tool_call_frames("read_file"))
    )
    _assert_final_state(verdict, SUB_CAUSE_FINAL_STATE_NO_WORKSPACE)
    assert verdict.expected["sub_cause_detail"] == ""


def test_a_caller_supplied_workspace_bypasses_all_four(tmp_path, monkeypatch) -> None:
    seen = _stub_replay(monkeypatch, status=REPLAY_UNVERIFIED)
    kwargs = _final_state_kwargs(tmp_path)
    kwargs["workspace"] = tmp_path
    verdict = claims.evaluate_claim(**kwargs)
    assert seen == []
    expected = verdict.expected if verdict is not None and isinstance(verdict.expected, dict) else {}
    assert expected.get("cause") != CAUSE_FINAL_STATE_UNOBSERVABLE
    assert "sub_cause" not in expected
