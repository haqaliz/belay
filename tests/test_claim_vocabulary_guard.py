"""The A3 closed-vocabulary guard: the claim causes and the author sub-causes are pinned.

A reader of a stored A3 verdict buckets on `expected["cause"]` — and, for
`NO_CHECK_AUTHOR`, on `expected["sub_cause"]` — without re-reading the trace. That only
works while both vocabularies stay CLOSED: a new value must arrive together with a
registered producer (`tests/test_verify_author_abstention.py`,
`tests/test_verify_claims_subcause.py`) and a renderer, never silently. So the sets are
pinned here as literals; widening either one means editing this file, on purpose.

The sub-cause refines WHY an author abstained. It never changes the status: every
sub-cause is still UNVERIFIED `NO_CHECK_AUTHOR`, never PASS, never FAIL.
"""

from __future__ import annotations

import dataclasses

import pytest

from belay.verify import claims
from belay.verify.claims import (
    SUB_CAUSE_AUTHOR_DECLINED,
    SUB_CAUSE_AUTHOR_EXITED_NONZERO,
    SUB_CAUSE_AUTHOR_NOT_LAUNCHED,
    SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED,
    SUB_CAUSE_AUTHOR_OUTPUT_OVER_CAP,
    SUB_CAUSE_AUTHOR_RAISED,
    SUB_CAUSE_AUTHOR_REPORTED_ERROR,
    SUB_CAUSE_AUTHOR_TIMED_OUT,
    SUB_CAUSES,
    Abstention,
)

PINNED_CAUSES = {
    "CAUSE_CHECK_DID_NOT_EXECUTE",
    "CAUSE_CLAIM_UNCLASSIFIABLE",
    "CAUSE_FINAL_STATE_UNOBSERVABLE",
    "CAUSE_NO_CHECK_AUTHOR",
    "CAUSE_NO_CLAIM_RECORDED",
}

PINNED_SUB_CAUSES = {
    "AUTHOR_RAISED",
    "AUTHOR_DECLINED",
    "AUTHOR_NOT_LAUNCHED",
    "AUTHOR_TIMED_OUT",
    "AUTHOR_EXITED_NONZERO",
    "AUTHOR_OUTPUT_OVER_CAP",
    "AUTHOR_OUTPUT_MALFORMED",
    "AUTHOR_REPORTED_ERROR",
}


def test_claim_causes_are_the_pinned_five() -> None:
    exported = {name for name in claims.__all__ if name.startswith("CAUSE_")}
    assert exported == PINNED_CAUSES


def test_sub_causes_are_the_pinned_eight() -> None:
    assert set(SUB_CAUSES) == PINNED_SUB_CAUSES
    assert isinstance(SUB_CAUSES, frozenset)


def test_each_sub_cause_constant_names_its_own_value() -> None:
    constants = {
        SUB_CAUSE_AUTHOR_RAISED,
        SUB_CAUSE_AUTHOR_DECLINED,
        SUB_CAUSE_AUTHOR_NOT_LAUNCHED,
        SUB_CAUSE_AUTHOR_TIMED_OUT,
        SUB_CAUSE_AUTHOR_EXITED_NONZERO,
        SUB_CAUSE_AUTHOR_OUTPUT_OVER_CAP,
        SUB_CAUSE_AUTHOR_OUTPUT_MALFORMED,
        SUB_CAUSE_AUTHOR_REPORTED_ERROR,
    }
    assert constants == PINNED_SUB_CAUSES
    exported = {name for name in claims.__all__ if name.startswith("SUB_CAUSE_")}
    assert exported == {f"SUB_CAUSE_{value}" for value in PINNED_SUB_CAUSES}
    assert "SUB_CAUSES" in claims.__all__
    assert "Abstention" in claims.__all__


def test_abstention_is_frozen_with_two_fields() -> None:
    abstention = Abstention(SUB_CAUSE_AUTHOR_TIMED_OUT, "no reply within 60s")
    assert [field.name for field in dataclasses.fields(Abstention)] == ["sub_cause", "detail"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        abstention.detail = "changed"  # type: ignore[misc]


def test_abstention_rejects_a_sub_cause_outside_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="NOT_A_SUB_CAUSE"):
        Abstention("NOT_A_SUB_CAUSE", "")
