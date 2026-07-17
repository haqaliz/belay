"""The verdict contract for the whole engine: the reduction, and its one structural guard.

C4 is the first grounded verdict. Everything it returns is a `Verdict`, and A1 (C5) and
A3 (C8) slot into the SAME reduction later. The reduction is worst-status-wins, but the
ordering is not arbitrary: **UNVERIFIED must rank above PASS and WARN**. A turn with one
sub-check we could not verify and one that passed is UNVERIFIED, never PASS — that is the
honesty contract ("UNVERIFIED is never rendered as PASS") turned into the shape of the code,
not a convention layered on top.

The first test below is the structural guard. It is written to fail against the exact
mistake — an ordering that ranks UNVERIFIED below PASS — because that mistake reports a
turn you could not verify as clean, which is the one false pass this project exists to
prevent.
"""

from __future__ import annotations

from belay.verify.verdict import Status, Verdict, reduce


def _verdict(status: Status, *, axis: str = "A2", kind: str = "replay") -> Verdict:
    return Verdict(
        axis=axis,
        kind=kind,
        status=status,
        observed=None,
        expected=None,
        message="",
    )


def test_unverified_outranks_pass_structural_guard() -> None:
    """reduce([PASS, UNVERIFIED]) == UNVERIFIED — the whole project in one assertion.

    Against a naive ordering that ranks UNVERIFIED below PASS this reduces to PASS, and a
    turn Belay could not verify is reported clean. This test must fail loudly against that
    ordering before it passes.
    """
    result = reduce([_verdict(Status.PASS), _verdict(Status.UNVERIFIED)])
    assert result == Status.UNVERIFIED


def test_fail_beats_pass() -> None:
    assert reduce([_verdict(Status.PASS), _verdict(Status.FAIL)]) == Status.FAIL


def test_fail_is_worst_even_over_unverified() -> None:
    assert reduce([_verdict(Status.UNVERIFIED), _verdict(Status.FAIL)]) == Status.FAIL


def test_all_pass_reduces_to_pass() -> None:
    assert reduce([_verdict(Status.PASS), _verdict(Status.PASS)]) == Status.PASS


def test_warn_outranks_pass() -> None:
    assert reduce([_verdict(Status.WARN), _verdict(Status.PASS)]) == Status.WARN


def test_empty_is_unverified_not_pass() -> None:
    """Nothing checked is not a pass. An empty verdict set means we verified nothing."""
    assert reduce([]) == Status.UNVERIFIED


def test_reduction_is_axis_agnostic() -> None:
    """A1 slots in unchanged: a FAIL on any axis wins; the reduction never special-cases A2.

    And an A3 WARN alongside an A2 PASS downgrades to WARN — worst-wins already gives A3 its
    "downgrade only, never promote" property with no A3-specific code.
    """
    a1_fail = _verdict(Status.FAIL, axis="A1", kind="invariant")
    a2_pass = _verdict(Status.PASS, axis="A2", kind="replay")
    assert reduce([a1_fail, a2_pass]) == Status.FAIL

    a3_warn = _verdict(Status.WARN, axis="A3", kind="claim")
    assert reduce([a3_warn, a2_pass]) == Status.WARN


def test_verdict_round_trips_its_fields() -> None:
    diff = {"path": "/notes/1", "before": "a", "after": "b"}
    expected = {"annotation": "readOnlyHint", "paths": ["/notes/1"]}
    v = Verdict(
        axis="A2",
        kind="effect",
        status=Status.FAIL,
        observed=diff,
        expected=expected,
        message="readOnlyHint tool mutated /notes/1",
    )
    assert v.axis == "A2"
    assert v.kind == "effect"
    assert v.status == Status.FAIL
    assert v.observed == diff
    assert v.expected == expected
    assert v.message == "readOnlyHint tool mutated /notes/1"
