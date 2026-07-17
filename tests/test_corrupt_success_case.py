"""S1: `corrupt_success_case` — an A1 FAIL shaped as an ingestable failure-corpus case.

A1 is the axis that catches corrupt success; the failure corpus (moat #2, capability C6)
is where each catch becomes a labeled datum that sharpens detection over time. This is the
seam between them: a PURE function that shapes a TurnVerdict's A1 FAIL into a case dict C6
can later persist. It owns the SHAPE only — no storage, no format beyond the fields the A1
sub-verdict already grounds. A verdict with no A1 FAIL yields None (nothing corrupt to log).

Platform-independent: it reads a composed TurnVerdict, so it needs no replay/sandbox.
"""

from __future__ import annotations

from belay.snapshot.bth1 import FieldDiff
from belay.verify.invariants import Invariant, corrupt_success_case, evaluate_invariant
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict


def _a1_fail_verdict() -> TurnVerdict:
    """A TurnVerdict whose A1 invariant sub-verdict FAILs on a real evaluated delta.

    Grounds the case on an actual `evaluate_invariant` FAIL (a write under a read-only
    `tests/` scope), not a hand-forged Verdict, so the shaped dict is pinned to the real
    sub-verdict fields (`expected`, `observed`, `message`).
    """
    inv = Invariant(scope=b"tests/", rule="read-only")
    delta = [FieldDiff(path=b"tests/test_auth.py", field="content", left=b"a", right=b"b")]
    a1 = evaluate_invariant(inv, delta, turn_index=3)
    assert a1.status is Status.FAIL, a1  # guard: the fixture must actually be a FAIL
    result = Verdict("A2", "replay", Status.PASS, observed=None, expected=None, message="ok")
    effect = Verdict("A2", "effect", Status.PASS, observed=[], expected=None, message="ok")
    return TurnVerdict(
        turn_index=3, tool_name="edit_file", status=Status.FAIL,
        sub_verdicts=[result, effect, a1],
    )


def test_corrupt_success_case_shapes_the_a1_fail():
    """An A1-FAIL TurnVerdict -> a case dict carrying rule, scope, turn, tool, paths, message."""
    case = corrupt_success_case(_a1_fail_verdict())

    assert case is not None
    assert case["rule"] == "read-only"
    assert case["scope"] == "tests/"
    assert case["turn_index"] == 3
    assert case["tool_name"] == "edit_file"
    assert case["violating_paths"] == ["tests/test_auth.py"]
    assert "tests/test_auth.py" in case["message"]


def test_no_a1_fail_is_no_case():
    """A verdict with no A1 FAIL (A1 PASS, or no A1 at all) -> None: nothing corrupt to log."""
    inv = Invariant(scope=b"src/", rule="read-only")
    delta = [FieldDiff(path=b"tests/test_auth.py", field="content", left=b"a", right=b"b")]
    a1_pass = evaluate_invariant(inv, delta, turn_index=0)  # write outside src/ -> PASS
    assert a1_pass.status is Status.PASS

    passing = TurnVerdict(
        turn_index=0, tool_name="edit_file", status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "replay", Status.PASS, observed=None, expected=None, message="ok"),
            a1_pass,
        ],
    )
    assert corrupt_success_case(passing) is None

    # And a verdict carrying no A1 sub-verdict at all is likewise None.
    no_a1 = TurnVerdict(
        turn_index=0, tool_name="edit_file", status=Status.PASS,
        sub_verdicts=[Verdict("A2", "replay", Status.PASS, observed=None, expected=None, message="ok")],
    )
    assert corrupt_success_case(no_a1) is None
