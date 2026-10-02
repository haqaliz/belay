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

from belay.verify import claims
from belay.verify.claims import (
    CAUSE_CLAIM_UNCLASSIFIABLE,
    CAUSE_FINAL_STATE_UNOBSERVABLE,
    CAUSE_NO_CHECK_AUTHOR,
    SUB_CAUSE_AUTHOR_RAISED,
    SUB_CAUSE_FINAL_STATE_NO_TURN,
    SUB_CAUSE_FINAL_STATE_REPLAY_RAISED,
    Abstention,
)
from belay.verify.verdict import Status


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
