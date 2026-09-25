"""surface-threading: the author's sub-cause rides every surface that shows the cause.

`author-abstention` put `sub_cause` / `sub_cause_detail` into a `NO_CHECK_AUTHOR`
verdict's `expected` dict, but every serializer copied named keys only and every text
renderer printed `[cause]` only, so the reason died at the surface
(`docs/planning/claim-axis-legibility/surface-threading/spec.md`). This module pins:

1. the three record shapers — `claim_record` (`verify --json`), `_claim_summary` (the
   phase0 ledger) and `claim_case` (the corpus) — carry the two keys, LAST, exactly when
   the verdict's `expected` carries `sub_cause`, and are byte-identical to before on a
   FAIL, on every other UNVERIFIED cause, and on a `NO_CHECK_AUTHOR` verdict stored
   before the sub-cause existed (AC 1);
2. the text renderers name `[NO_CHECK_AUTHOR/<SUB>]` and still end `— never PASS`, and a
   record without a sub-cause renders exactly as before (AC 2).

The sub-cause refines the reason and never the status: nothing here moves a verdict.
"""

from __future__ import annotations

import pytest

from belay.phase0.runner import _claim_summary
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_CHECK_DID_NOT_EXECUTE,
    CAUSE_CLAIM_UNCLASSIFIABLE,
    CAUSE_FINAL_STATE_UNOBSERVABLE,
    CAUSE_NO_CHECK_AUTHOR,
    CAUSE_NO_CLAIM_RECORDED,
    SUB_CAUSE_AUTHOR_DECLINED,
    SUB_CAUSE_AUTHOR_TIMED_OUT,
    Abstention,
    Check,
    claim_case,
)
from belay.verify.json import claim_record
from belay.verify.verdict import Status, Verdict

CHECK = Check(source="pytest -q", argv=("sh", "-c", "pytest -q"))


def _no_author(abstention):
    """A `NO_CHECK_AUTHOR` verdict as the evaluator builds it, with this abstention."""
    return claims._unverified(
        CAUSE_NO_CHECK_AUTHOR,
        claim_seq=3,
        detail="the check author returned no executable check",
        abstention=abstention,
    )


def _fail():
    return Verdict(
        "A3", "claim", Status.FAIL,
        observed=1, expected="exit 0",
        message="A3 claim re-derivation FAIL — pytest -q · exit 1",
    )


# --- (1) the record shapers (AC 1) -----------------------------------------------------


def test_claim_record_carries_the_sub_cause_last() -> None:
    verdict = _no_author(Abstention(SUB_CAUSE_AUTHOR_TIMED_OUT, "no reply within 60s"))
    record = claim_record(verdict)
    assert record == {
        "axis": "A3",
        "kind": "claim",
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
        "sub_cause": "AUTHOR_TIMED_OUT",
        "sub_cause_detail": "no reply within 60s",
    }
    assert list(record)[-2:] == ["sub_cause", "sub_cause_detail"]


def test_claim_summary_carries_the_sub_cause_last() -> None:
    verdict = _no_author(Abstention(SUB_CAUSE_AUTHOR_DECLINED, ""))
    summary = _claim_summary(verdict, None)
    assert summary == {
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
        "sub_cause": "AUTHOR_DECLINED",
        "sub_cause_detail": "",
    }
    assert list(summary)[-2:] == ["sub_cause", "sub_cause_detail"]


def test_claim_case_carries_the_sub_cause_last() -> None:
    verdict = _no_author(Abstention(SUB_CAUSE_AUTHOR_TIMED_OUT, "no reply within 60s"))
    case = claim_case(verdict)
    assert case == {
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
        "sub_cause": "AUTHOR_TIMED_OUT",
        "sub_cause_detail": "no reply within 60s",
    }
    assert list(case)[-2:] == ["sub_cause", "sub_cause_detail"]


def _shapers(verdict):
    return {
        "claim_record": claim_record(verdict, check=CHECK),
        "_claim_summary": _claim_summary(verdict, CHECK),
        "claim_case": claim_case(verdict, check=CHECK),
    }


_OTHER_CAUSES = [
    CAUSE_NO_CLAIM_RECORDED,
    CAUSE_CLAIM_UNCLASSIFIABLE,
    CAUSE_FINAL_STATE_UNOBSERVABLE,
    CAUSE_CHECK_DID_NOT_EXECUTE,
]


@pytest.mark.parametrize("cause", _OTHER_CAUSES)
def test_other_causes_carry_no_sub_cause_keys(cause) -> None:
    verdict = claims._unverified(cause, claim_seq=3, detail="x")
    for name, record in _shapers(verdict).items():
        assert "sub_cause" not in record, (name, record)
        assert "sub_cause_detail" not in record, (name, record)


def test_fail_carries_no_sub_cause_keys() -> None:
    for name, record in _shapers(_fail()).items():
        assert "sub_cause" not in record, (name, record)
        assert "sub_cause_detail" not in record, (name, record)


def test_a_pre_sub_cause_no_check_author_verdict_is_byte_identical() -> None:
    """A `NO_CHECK_AUTHOR` verdict with no `sub_cause` in `expected` — what a verdict
    looked like before this unit — shapes exactly as it did then."""
    verdict = claims._unverified(
        CAUSE_NO_CHECK_AUTHOR, claim_seq=3, detail="the check author returned no check"
    )
    assert "sub_cause" not in verdict.expected
    assert claim_record(verdict) == {
        "axis": "A3",
        "kind": "claim",
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
    }
    old = {
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
    }
    assert _claim_summary(verdict, None) == old
    assert claim_case(verdict) == old

