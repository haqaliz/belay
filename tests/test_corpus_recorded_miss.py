"""A corpus case can DECLARE that its stored verdict records a MISS, not a catch.

The failure corpus can only ever be built from FLAGGED turns (`belay phase0 run` ingests
FAIL turns and nothing else), so a violation the detector MISSES can never become a case
by the normal path -- the corpus structurally cannot measure recall. This is the schema
half of fixing that: a case gains a `recorded_miss` field so a human can bank a known-missed
violation as a case whose `expected.reduced_status` is the CLEAN verdict the engine actually
produced, with a declaration recording that the clean verdict is a miss, not a pass.

Presence is the declaration -- `recorded_miss` absent means undeclared, a normal case,
byte-for-byte today's behaviour. This is the same rule `task_prestate` established in
`corpus-task-prestate`, and this file's first test pins that precedent verbatim: nothing
about loading, round-tripping, or the payload of an undeclared case may change.

`CASE_SCHEMA_VERSION` moves 2 -> 3 because a v3 case read by pre-v3 code would silently
misclassify a declared miss as a normal case -- certifying blindness as a pass, the exact
defect this aspect exists to remove.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from belay.corpus.case import CASE_SCHEMA_VERSION, Case, load_case, write_case
from belay.corpus.curate import set_label
from belay.corpus.run import (
    MATCH,
    MISS_CLOSED,
    REGRESSION,
    SKIP,
    STILL_MISSED,
    CaseResult,
    CorpusRun,
    classify_case,
)
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict


def _full_case() -> Case:
    """A case with every pre-existing field populated, nothing left to a default."""
    return Case(
        id="cheat-run-0007",
        target_turn_index=3,
        expected={
            "reduced_status": "PASS",
            "sub_verdicts": [
                {"axis": "A1", "kind": "invariant", "status": "PASS"},
                {"axis": "A2", "kind": "effect", "status": "PASS"},
            ],
        },
        human_label="true-positive",
        invariants=[{"scope": "tests/", "rule": "no-assertion-weakening"}],
        server_command=["python", "editor_server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-08-03T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


def test_a_case_without_the_declaration_loads_and_behaves_exactly_as_today(
    tmp_path: Path,
) -> None:
    """Absent `recorded_miss` -> undeclared, byte-for-byte today's round trip."""
    case = _full_case()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case
    assert loaded.recorded_miss is None

    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()


def test_declaration_requires_a_non_empty_note(tmp_path: Path) -> None:
    """A `recorded_miss` with a non-empty note round-trips and loads back unchanged."""
    case = Case(
        **{
            **_full_case().__dict__,
            "recorded_miss": {"note": "pytest-5227 t11/t13: unflagged, testing/ scope miss"},
        }
    )
    write_case(tmp_path, case)

    loaded = load_case(tmp_path)
    assert loaded.recorded_miss == {
        "note": "pytest-5227 t11/t13: unflagged, testing/ scope miss"
    }

    stored = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert stored["recorded_miss"] == {
        "note": "pytest-5227 t11/t13: unflagged, testing/ scope miss"
    }


@pytest.mark.parametrize(
    "bad_note",
    [
        pytest.param("", id="empty-string"),
        pytest.param(None, id="missing-key"),
        pytest.param(7, id="non-string"),
    ],
)
def test_declaration_with_missing_or_empty_note_is_rejected(
    tmp_path: Path, bad_note: object
) -> None:
    """A note that is absent, empty, or not a string -> named ValueError.

    Mirrors `curate.py`'s `root_cause` requirement for a `true-positive` label: a human
    asserting "the engine missed something here" must say what."""
    write_case(tmp_path, _full_case())
    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    if bad_note is None:
        data["recorded_miss"] = {}
    else:
        data["recorded_miss"] = {"note": bad_note}
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="recorded_miss"):
        load_case(tmp_path)


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("a miss happened", id="bare-string"),
        pytest.param(["a miss happened"], id="a-list"),
        pytest.param(7, id="an-int"),
    ],
)
def test_malformed_declaration_raises_a_named_value_error(
    tmp_path: Path, malformed: object
) -> None:
    """A `recorded_miss` that is not an object at all -> named ValueError."""
    write_case(tmp_path, _full_case())
    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["recorded_miss"] = malformed
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="recorded_miss"):
        load_case(tmp_path)


def test_a_declaration_on_an_already_fail_case_is_a_contradiction(tmp_path: Path) -> None:
    """A "miss" whose recorded verdict is already FAIL was caught, not missed.

    Fail-closed beats a case that means nothing: this must raise at load, not silently
    accept a declaration that contradicts the verdict it decorates.
    """
    case = _full_case()
    case = Case(
        **{
            **case.__dict__,
            "expected": {
                "reduced_status": "FAIL",
                "sub_verdicts": [{"axis": "A1", "kind": "invariant", "status": "FAIL"}],
            },
            "recorded_miss": {"note": "a miss that was actually caught"},
        }
    )
    write_case(tmp_path, case)

    with pytest.raises(ValueError, match="recorded_miss"):
        load_case(tmp_path)


def test_payload_omits_the_declaration_when_unset(tmp_path: Path) -> None:
    """Asserted on serialized BYTES: an unset declaration must not appear as `null`."""
    write_case(tmp_path, _full_case())

    raw_bytes = (tmp_path / "case.json").read_bytes()
    assert b"recorded_miss" not in raw_bytes


def test_declaration_is_not_a_required_field(tmp_path: Path) -> None:
    """A v2 case (schema_version 2, written before `recorded_miss` existed) still loads.

    `_REQUIRED_FIELDS` is closed and fail-closed -- a required new field would reject
    every case already sitting in `corpus/local/`.
    """
    from belay.corpus.case import _REQUIRED_FIELDS

    assert "recorded_miss" not in _REQUIRED_FIELDS

    case = Case(**{**_full_case().__dict__, "schema_version": 2})
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert "recorded_miss" not in data
    assert data["schema_version"] == 2

    loaded = load_case(tmp_path)
    assert loaded.recorded_miss is None
    assert loaded.schema_version == 2


def test_schema_version_is_four_and_absent_still_means_one(tmp_path: Path) -> None:
    """The version bump, and the unversioned-means-1 precedent it must not disturb."""
    assert CASE_SCHEMA_VERSION == 4

    case = _full_case()
    write_case(tmp_path, case)
    assert load_case(tmp_path).schema_version == 4

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    del data["schema_version"]
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    assert load_case(tmp_path).schema_version == 1


# =====================================================================================
# Phase 2 -- `corpus run` stops inverting on a declared miss
# =====================================================================================
#
# `classify_case` compares the recomputed verdict against `expected` alone, so a case that
# DECLARES its stored verdict is a miss gets classified backwards in both directions:
#
#   - the engine still misses it  -> the sets are equal -> MATCH. The regression suite
#     certifies "the engine is still blind here" AS AGREEMENT.
#   - the detector is sharpened and now CATCHES it -> the sets differ -> REGRESSION, exit 1.
#     **CI goes red for a fix.**
#
# Two outcomes fix that, reachable ONLY for a declared case: `STILL_MISSED` (equal sets --
# the known state, exit 0, but never called agreement) and `MISS_CLOSED` (the ONE exempted
# transition -- the reduced status AND the A1 `invariant` sub-verdict both moving
# PASS -> FAIL, and nothing else diverging). Anything else stays a `REGRESSION`: the escape
# exempts exactly one transition and must never become a blanket exemption for declared cases.

#: The declaration itself. Presence is the claim; the note is what makes it auditable.
DECLARED = {"note": "pytest-5227 turns 11/13 -- fnmatch weakening the byte prefix missed"}


def _sub(axis: str, kind: str, status: Status) -> Verdict:
    return Verdict(axis, kind, status, None, None, f"{axis} {kind} {status.value}")


def _turn(status: Status, subs: list, cause: str | None = None) -> TurnVerdict:
    return TurnVerdict(
        turn_index=0, tool_name="edit_file", status=status, sub_verdicts=subs, cause=cause
    )


def _expected(reduced: str, subs: list) -> dict:
    """A stored `expected` dict, exactly the shape `corpus add` writes to case.json."""
    return {
        "reduced_status": reduced,
        "sub_verdicts": [{"axis": a, "kind": k, "status": s} for a, k, s in subs],
    }


#: The clean verdict a recorded-miss case banks: the engine saw nothing, and a human says
#: it should have. Used as both the stored `expected` and (unchanged) the still-blind recompute.
_MISSED_EXPECTED = _expected(
    "PASS", [("A1", "invariant", "PASS"), ("A2", "effect", "PASS"), ("A2", "replay", "PASS")]
)


def _missed_recompute() -> TurnVerdict:
    return _turn(
        Status.PASS,
        [
            _sub("A1", "invariant", Status.PASS),
            _sub("A2", "effect", Status.PASS),
            _sub("A2", "replay", Status.PASS),
        ],
    )


def _caught_recompute() -> TurnVerdict:
    """The same turn once a sharpened A1 rule CATCHES it -- the one exempted transition."""
    return _turn(
        Status.FAIL,
        [
            _sub("A1", "invariant", Status.FAIL),
            _sub("A2", "effect", Status.PASS),
            _sub("A2", "replay", Status.PASS),
        ],
    )


# --- the spine: a miss is not agreement ----------------------------------------------


def test_a_declared_miss_still_missed_does_not_classify_match() -> None:
    """Equal sets on a DECLARED case is `STILL_MISSED`, exit 0 -- never `MATCH`.

    MATCH means "the recorded verdict still reproduces, and that is what we want". On a
    recorded miss the recorded verdict is the engine being blind, so calling it MATCH
    certifies blindness as agreement. It is still exit 0 -- the known state is not a
    failure -- but it must be counted and named separately from agreement.
    """
    result = classify_case(_MISSED_EXPECTED, _missed_recompute(), recorded_miss=DECLARED)

    assert result.outcome == STILL_MISSED, result
    assert result.outcome != MATCH
    run = CorpusRun(results=[result])
    assert run.has_regression is False, "a still-open miss is the known state, not a failure"
    assert run.matches == 0, "a STILL_MISSED must not be folded into the MATCH count"
    assert run.still_missed == 1


# --- the spine: closing a miss is not a regression (stops CI going red for a fix) ------


def test_a_declared_miss_now_caught_does_not_classify_regression() -> None:
    """The reduced status and A1 `invariant` both moving PASS -> FAIL is `MISS_CLOSED`, exit 0.

    This is the criterion that stops CI going red for a fix: without it, sharpening the
    detector so it finally catches a banked miss breaks the build, and the regression suite
    punishes exactly the change the corpus exists to drive.
    """
    result = classify_case(_MISSED_EXPECTED, _caught_recompute(), recorded_miss=DECLARED)

    assert result.outcome == MISS_CLOSED, result
    assert result.outcome != REGRESSION
    run = CorpusRun(results=[result])
    assert run.has_regression is False, "a closed miss must not exit CI non-zero"
    assert run.matches == 0
    assert run.miss_closed == 1


# --- the escape is narrow: EXACTLY ONE transition, on a declared case ------------------


def _other_divergences() -> list:
    """Every near-miss of the exempted transition. Each must stay a REGRESSION."""
    return [
        pytest.param(
            _turn(
                Status.FAIL,
                [
                    _sub("A1", "invariant", Status.FAIL),
                    _sub("A2", "effect", Status.FAIL),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="an-A2-sub-verdict-also-moved",
        ),
        pytest.param(
            _turn(
                Status.WARN,
                [
                    _sub("A1", "invariant", Status.WARN),
                    _sub("A2", "effect", Status.PASS),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="the-move-is-to-WARN-not-FAIL",
        ),
        pytest.param(
            _turn(
                Status.UNVERIFIED,
                [
                    _sub("A1", "invariant", Status.UNVERIFIED),
                    _sub("A2", "effect", Status.PASS),
                    _sub("A2", "replay", Status.PASS),
                ],
                cause="no-task-prestate-manifest",
            ),
            id="UNVERIFIED-without-a-skip-cause",
        ),
        pytest.param(
            _turn(
                Status.FAIL,
                [
                    _sub("A1", "invariant", Status.PASS),
                    _sub("A2", "effect", Status.FAIL),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="only-A2-moved-A1-is-still-blind",
        ),
        pytest.param(
            _turn(
                Status.PASS,
                [
                    _sub("A1", "invariant", Status.FAIL),
                    _sub("A2", "effect", Status.PASS),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="A1-moved-but-the-reduced-status-did-not",
        ),
        pytest.param(
            _turn(
                Status.FAIL,
                [_sub("A2", "effect", Status.PASS), _sub("A2", "replay", Status.PASS)],
            ),
            id="the-A1-sub-verdict-vanished",
        ),
        # The next three are the shapes a `(axis, kind)`-keyed comparison silently accepts.
        # Undeclared, every one of them is a REGRESSION by exact equality; the declaration
        # must not buy an escape from the exact-equality rule itself.
        pytest.param(
            _turn(
                Status.FAIL,
                [
                    _sub("A2", "effect", Status.PASS),
                    _sub("A1", "invariant", Status.FAIL),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="the-exempted-pair-but-the-sub-verdict-list-is-REORDERED",
        ),
        pytest.param(
            _turn(
                Status.FAIL,
                [
                    _sub("A1", "invariant", Status.FAIL),
                    _sub("A1", "invariant", Status.FAIL),
                    _sub("A2", "effect", Status.PASS),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="the-A1-sub-verdict-is-DUPLICATED",
        ),
        pytest.param(
            _turn(
                Status.FAIL,
                [
                    _sub("A1", "invariant", Status.PASS),
                    _sub("A1", "invariant", Status.FAIL),
                    _sub("A2", "effect", Status.PASS),
                    _sub("A2", "replay", Status.PASS),
                ],
            ),
            id="TWO-CONTRADICTORY-A1-sub-verdicts-one-PASS-one-FAIL",
        ),
    ]


@pytest.mark.parametrize("recomputed", _other_divergences())
def test_any_other_divergence_on_a_declared_case_is_still_a_regression(
    recomputed: TurnVerdict,
) -> None:
    """The declaration exempts ONE transition, not the case.

    A blanket "a declared case never regresses" would turn every banked miss into a hole in
    the regression suite. Each parameter here is a near-miss of the exempted transition, and
    each must still break the build.
    """
    result = classify_case(_MISSED_EXPECTED, recomputed, recorded_miss=DECLARED)

    assert result.outcome == REGRESSION, result
    assert result.divergences, "a REGRESSION must name what diverged"
    assert CorpusRun(results=[result]).has_regression is True
    # and the declaration changed nothing here: each of these is a REGRESSION undeclared too,
    # so the declaration never buys an escape from the exact-equality rule itself.
    assert classify_case(_MISSED_EXPECTED, recomputed).outcome == REGRESSION


def test_an_a1_sub_verdict_appearing_from_nothing_is_a_regression() -> None:
    """`None -> FAIL` is not `PASS -> FAIL`, and the difference is deliberate.

    The exempted transition is a detector that reached PASS on this case reaching FAIL
    instead. An A1 `invariant` sub-verdict materialising where the stored verdict had none is
    a structural change to the axis set -- the engine now emits something it did not emit
    when the case was banked -- and this module already treats an axis appearing or vanishing
    as significant (`_divergences` matches on `(axis, kind)` precisely so it diverges against
    `None` rather than silently aligning by position). It does not arise on the real path: a
    recorded miss banks a verdict the A1 rule DID produce, at PASS.
    """
    expected = _expected("PASS", [("A2", "effect", "PASS"), ("A2", "replay", "PASS")])
    recomputed = _turn(
        Status.FAIL,
        [
            _sub("A1", "invariant", Status.FAIL),
            _sub("A2", "effect", Status.PASS),
            _sub("A2", "replay", Status.PASS),
        ],
    )

    result = classify_case(expected, recomputed, recorded_miss=DECLARED)
    assert result.outcome == REGRESSION, result
    flips = {(d.axis, d.kind, d.expected_status, d.got_status) for d in result.divergences}
    assert ("A1", "invariant", None, "FAIL") in flips, flips


def test_the_exempted_transition_starts_from_pass_not_from_any_status() -> None:
    """A stored A1 `invariant` that is not PASS is not a miss, so nothing can close.

    The rule patches `expected` and demands equality, so without an explicit PASS guard on the
    SOURCE status a stored `WARN` would be patched to `FAIL` and exempted too -- turning
    "PASS -> FAIL" into "anything -> FAIL". A recorded miss is specifically a CLEAN verdict a
    human adjudicated wrong; a WARN is the engine having already said something.
    """
    expected = _expected("PASS", [("A1", "invariant", "WARN"), ("A2", "effect", "PASS")])
    recomputed = _turn(
        Status.FAIL,
        [_sub("A1", "invariant", Status.FAIL), _sub("A2", "effect", Status.PASS)],
    )

    assert classify_case(expected, recomputed, recorded_miss=DECLARED).outcome == REGRESSION


def test_an_unknown_top_level_key_in_expected_cannot_reach_miss_closed() -> None:
    """A stored `expected` the patch does not carry through is a REGRESSION, not a close.

    `STILL_MISSED` compares against `expected` WHOLE, so an unknown extra top-level key can
    never reach it. `MISS_CLOSED` must be held to the same standard, or a case shaped in a way
    this module does not understand could reach the exempting outcome while being structurally
    unable to reach the non-exempting one -- the escape widening on exactly the cases nobody
    can read. Building the patch FROM `expected` closes that without asserting any schema:
    the unknown key rides into the patch, equality against the recompute fails, and the case
    breaks the build like every other divergence.
    """
    expected = {**_MISSED_EXPECTED, "some_future_field": {"written_by": "a later belay"}}

    assert classify_case(expected, _caught_recompute(), recorded_miss=DECLARED).outcome == (
        REGRESSION
    )
    # and the STILL_MISSED direction was already unreachable for such a case -- which is the
    # asymmetry this closes, stated as the test's own premise.
    assert classify_case(expected, _missed_recompute(), recorded_miss=DECLARED).outcome == (
        REGRESSION
    )


# --- a TWO-invariant policy: every A1 entry is part of the transition, or none of it -----
#
# A policy may declare more than one invariant, so a turn can carry more than one
# `("A1", "invariant")` sub-verdict. The rule patches EVERY one of them, so the guard has to
# ask about EVERY one of them: a guard that only asks whether SOME entry is PASS would let a
# second entry ride the exemption from any status at all -- the "anything -> FAIL" widening
# the single-entry test above exists to prevent, reintroduced one entry over.

_TWO_INVARIANT_CASES = [
    pytest.param(
        _expected(
            "PASS",
            [("A1", "invariant", "PASS"), ("A1", "invariant", "WARN"), ("A2", "effect", "PASS")],
        ),
        _turn(
            Status.FAIL,
            [
                _sub("A1", "invariant", Status.FAIL),
                _sub("A1", "invariant", Status.FAIL),
                _sub("A2", "effect", Status.PASS),
            ],
        ),
        REGRESSION,
        id="one-invariant-was-PASS-the-other-WARN-so-WARN-to-FAIL-rides-along",
    ),
    pytest.param(
        _expected(
            "PASS",
            [("A1", "invariant", "PASS"), ("A1", "invariant", "PASS"), ("A2", "effect", "PASS")],
        ),
        _turn(
            Status.FAIL,
            [
                _sub("A1", "invariant", Status.FAIL),
                _sub("A1", "invariant", Status.FAIL),
                _sub("A2", "effect", Status.PASS),
            ],
        ),
        MISS_CLOSED,
        id="both-invariants-were-PASS-and-both-moved-the-legitimate-close",
    ),
    pytest.param(
        _expected(
            "PASS",
            [("A1", "invariant", "PASS"), ("A1", "invariant", "PASS"), ("A2", "effect", "PASS")],
        ),
        _turn(
            Status.FAIL,
            [
                _sub("A1", "invariant", Status.FAIL),
                _sub("A1", "invariant", Status.PASS),
                _sub("A2", "effect", Status.PASS),
            ],
        ),
        REGRESSION,
        id="both-invariants-were-PASS-but-only-one-moved",
    ),
]


@pytest.mark.parametrize("expected, recomputed, want", _TWO_INVARIANT_CASES)
def test_every_a1_invariant_entry_is_part_of_the_transition_or_none_of_it(
    expected: dict, recomputed: TurnVerdict, want: str
) -> None:
    """Under a two-invariant policy the exemption is all-or-nothing on the A1 axis.

    The legitimate close is "the invariant axis moved PASS -> FAIL and nothing else did", so
    both entries moving together is `MISS_CLOSED`. A second entry that was not PASS, or that
    did not move, means something OTHER than the exempted transition happened, and the case
    breaks the build.
    """
    assert classify_case(expected, recomputed, recorded_miss=DECLARED).outcome == want


# --- SKIP still wins first ------------------------------------------------------------


def test_a_declared_case_with_an_environment_cause_is_still_a_skip() -> None:
    """An environment gap outranks the declaration: the case was not evaluated HERE.

    A recorded miss is identical on every box; "this box could not run the server" is not,
    and it is decided first, exactly as it is for an undeclared case.
    """
    from belay.replay.report import REPLAY_DID_NOT_ANSWER

    recomputed = _turn(Status.UNVERIFIED, [], cause=REPLAY_DID_NOT_ANSWER)
    result = classify_case(_MISSED_EXPECTED, recomputed, recorded_miss=DECLARED)

    assert result.outcome == SKIP, result
    assert result.skip_reason == REPLAY_DID_NOT_ANSWER


def test_skip_causes_is_unchanged() -> None:
    """`_SKIP_CAUSES` is a CLOSED set and this aspect does not widen it.

    The module docstring (`run.py:31-35`) forbids the cheap escape: a SKIP means "this box
    could not evaluate the case" -- an environment gap that differs between machines. A
    recorded miss is a property of the CASE, identical on every box, so filing it as a SKIP
    would let a real detector regression hide behind an environment excuse.
    """
    from belay.corpus.run import _SKIP_CAUSES
    from belay.replay.report import REPLAY_DID_NOT_ANSWER
    from belay.snapshot.substrate import UnrestorableCause

    assert _SKIP_CAUSES == frozenset(
        {REPLAY_DID_NOT_ANSWER, UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH.value}
    )
    assert len(_SKIP_CAUSES) == 2


# --- classification and human labels stay independent ---------------------------------


def test_classify_case_never_reads_the_human_label() -> None:
    """Structural: classification reads the DECLARATION and the verdicts, never the label.

    `corpus score` scores `human_label` independently. Coupling regression detection to the
    same field would corrupt both -- relabelling a case would silently move the regression
    suite, and the engine would have a path from its own output to a human adjudication.
    """
    params = inspect.signature(classify_case).parameters
    assert set(params) == {"expected", "recomputed", "case_id", "recorded_miss"}, params
    assert "human_label" not in params

    from belay.corpus import run as run_module

    reachable = [classify_case] + [
        getattr(run_module, name)
        for name in ("_recomputed_set", "_divergences", "_closes_the_miss")
    ]
    for fn in reachable:
        # the docstring is prose ABOUT the rule and may name the field; the CODE may not.
        code = inspect.getsource(fn).replace(fn.__doc__ or "\0", "")
        assert "human_label" not in code, fn.__name__


# --- an UNDECLARED case is bit-for-bit what it is today --------------------------------


def test_an_undeclared_case_classifies_bit_for_bit_as_today() -> None:
    """No declaration -> the two new outcomes are unreachable and nothing else moved.

    MATCH is EXACT dict equality of the whole recomputed set including the ordered
    sub-verdict list; the new branch must not weaken that.
    """
    still = classify_case(_MISSED_EXPECTED, _missed_recompute(), case_id="c")
    assert still == CaseResult(case_id="c", outcome=MATCH)

    caught = classify_case(_MISSED_EXPECTED, _caught_recompute(), case_id="c")
    assert caught.outcome == REGRESSION, "the exempted transition is NOT exempted undeclared"
    flips = {(d.axis, d.kind, d.expected_status, d.got_status) for d in caught.divergences}
    assert flips == {
        ("", "reduced_status", "PASS", "FAIL"),
        ("A1", "invariant", "PASS", "FAIL"),
    }, flips

    # the ordered sub-verdict list is still pinned exactly: same (axis, kind, status) triples,
    # reordered, is a REGRESSION and not a MATCH.
    reordered = _turn(
        Status.PASS,
        [
            _sub("A2", "replay", Status.PASS),
            _sub("A2", "effect", Status.PASS),
            _sub("A1", "invariant", Status.PASS),
        ],
    )
    assert classify_case(_MISSED_EXPECTED, reordered).outcome == REGRESSION


def test_the_new_outcomes_are_unreachable_without_a_declaration() -> None:
    """`recorded_miss=None` is the default, and it is the pre-Phase-2 behaviour verbatim."""
    assert inspect.signature(classify_case).parameters["recorded_miss"].default is None
    for recomputed in (_missed_recompute(), _caught_recompute()):
        outcome = classify_case(_MISSED_EXPECTED, recomputed).outcome
        assert outcome in (MATCH, REGRESSION, SKIP), outcome


# --- the exit contract ----------------------------------------------------------------


def test_has_regression_counts_only_regression() -> None:
    """The exit contract: only a REGRESSION exits non-zero, and only a MATCH is a match."""
    results = [
        CaseResult(case_id="m", outcome=MATCH),
        CaseResult(case_id="s", outcome=SKIP, skip_reason="off substrate"),
        CaseResult(case_id="miss", outcome=STILL_MISSED),
        CaseResult(case_id="closed", outcome=MISS_CLOSED),
    ]
    run = CorpusRun(results=results)
    assert run.has_regression is False
    assert run.matches == 1, "the new outcomes must not be folded into `matches`"
    assert run.skips == 1
    assert run.still_missed == 1
    assert run.miss_closed == 1
    assert run.regressions == 0

    regressed = CorpusRun(results=[*results, CaseResult(case_id="r", outcome=REGRESSION)])
    assert regressed.has_regression is True
    assert regressed.regressions == 1


# --- the CLI reports both new outcomes ------------------------------------------------


def test_corpus_run_reports_the_two_new_outcomes_and_exits_zero(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Driven through the REAL renderer: both outcomes are named per case and counted.

    Asserting against a format string written in the test would pass against the bug --
    twice in this repo a green test turned out to be checking its own stub.
    """
    from belay import cli

    (tmp_path / "corpus").mkdir()
    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir: CorpusRun(
            results=[
                CaseResult(case_id="trace-pytest-dev__pytest-5227-turn11", outcome=STILL_MISSED),
                CaseResult(
                    case_id="trace-pytest-dev__pytest-5227-turn13",
                    outcome=MISS_CLOSED,
                    divergences=list(
                        classify_case(
                            _MISSED_EXPECTED, _caught_recompute(), recorded_miss=DECLARED
                        ).divergences
                    ),
                ),
            ]
        ),
    )

    rc = cli.main(["corpus", "run", str(tmp_path / "corpus")])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert STILL_MISSED in out and MISS_CLOSED in out
    # each case is named beside its outcome, separated -- not fused into one token.
    assert f"trace-pytest-dev__pytest-5227-turn11 {STILL_MISSED}" in " ".join(out.split())
    assert f"trace-pytest-dev__pytest-5227-turn13 {MISS_CLOSED}" in " ".join(out.split())
    # and both are counted in the aggregate, separately from MATCH.
    aggregate = out.split("aggregate", 1)[1]
    assert f"{STILL_MISSED}" in aggregate and f"{MISS_CLOSED}" in aggregate
    assert "MATCH                 0" in aggregate
    assert "belay: no regressions" in out


def test_the_clean_exit_line_says_a_miss_is_still_open(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A run holding an open recorded miss must not sign off as an unqualified clean pass.

    "no regressions" is true and insufficient: the same line already qualifies itself with
    the SKIP count so partial coverage is never read as a full pass, and a STILL_MISSED is
    the same kind of admission -- the engine is known blind on that case.
    """
    from belay import cli

    (tmp_path / "corpus").mkdir()
    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir: CorpusRun(
            results=[
                CaseResult(case_id="kept", outcome=MATCH),
                CaseResult(case_id="open-miss", outcome=STILL_MISSED),
            ]
        ),
    )

    assert cli.main(["corpus", "run", str(tmp_path / "corpus")]) == 0
    out = capsys.readouterr().out
    assert "belay: no regressions (1 still missed)" in out, out


def test_a_green_run_can_contain_a_miss_that_is_no_longer_missed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The counterexample to "green means every recorded miss is still missed".

    That sentence was written into four places and it is FALSE, so it is pinned here in the
    only form that cannot drift: a run whose only declared case is `MISS_CLOSED` is green,
    and in it a recorded miss is precisely NOT still missed. Green means ONE thing -- no case
    REGRESSED -- which is `CorpusRun.has_regression` and nothing else. Anything a green run
    is read to certify beyond that has to be re-derived from the outcome counts, which is why
    they are printed.
    """
    from belay import cli

    (tmp_path / "corpus").mkdir()
    run = CorpusRun(
        results=[
            CaseResult(case_id="kept", outcome=MATCH),
            CaseResult(
                case_id="closed-miss",
                outcome=MISS_CLOSED,
                divergences=list(
                    classify_case(
                        _MISSED_EXPECTED, _caught_recompute(), recorded_miss=DECLARED
                    ).divergences
                ),
            ),
        ]
    )
    assert run.has_regression is False, "the exit contract is REGRESSION-only"
    assert run.still_missed == 0, "the declared case's miss CLOSED; nothing is still missed"
    monkeypatch.setattr("belay.corpus.run.run_corpus", lambda _dir: run)

    assert cli.main(["corpus", "run", str(tmp_path / "corpus")]) == 0
    out = capsys.readouterr().out
    assert "belay: no regressions" in out, out
    assert "still missed" not in out.rsplit("belay:", 1)[-1], out


def test_corpus_run_help_states_the_exit_contract_it_actually_has() -> None:
    """`belay corpus run --help` must not describe an exit contract the command lost.

    It used to say a case that no longer reproduces its per-sub-verdict set "exits NON-ZERO"
    and that "an all-MATCH/SKIP run exits 0". Both are now false for a case that declares a
    recorded miss, and a user reading --help would meet two outcome names it never mentioned.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "corpus", "run", "--help"],
        capture_output=True,
        timeout=30,
    )
    out = completed.stdout.decode(errors="replace").lower()

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert STILL_MISSED.lower() in out and MISS_CLOSED.lower() in out
    assert "recorded miss" in out, "help must say WHICH cases reach the two new outcomes"
    # the two sentences that are now false must be gone, not merely appended to.
    assert "all-match/skip" not in out
    assert "regression" in out and "exits 0" in out


def test_an_unrecognised_outcome_is_never_rendered_as_a_match(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The renderer's fallback must fail SAFE, not fail AGREEABLE.

    With three outcomes a catch-all `else: MATCH` was tolerable. With five it is a direction:
    an outcome this renderer has not been taught yet would be printed as agreement, which is
    the one thing this whole aspect exists to stop a corpus run from claiming. Print the
    outcome verbatim instead -- an unknown token a reader can grep beats a wrong word.
    """
    from belay import cli

    (tmp_path / "corpus").mkdir()
    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir: CorpusRun(
            results=[CaseResult(case_id="from-the-future", outcome="NOT_YET_INVENTED")]
        ),
    )

    assert cli.main(["corpus", "run", str(tmp_path / "corpus")]) == 0
    out = capsys.readouterr().out
    assert "NOT_YET_INVENTED" in out, out
    assert MATCH not in out.split("aggregate", 1)[0], "a case line must not claim MATCH"


# --- end-to-end, through the REAL run_case (darwin only) -------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_SERVER = FIXTURES / "weakening_editor_server.py"

STRONG_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)


def _edit_file_call(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _recorded_reply(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "result": {
                "content": [{"type": "text", "text": "edited tests/test_auth.py"}],
                "isError": False,
            },
        }
    ).encode()


def _trace(tmp_path: Path, name: str, frames: list) -> list:
    from belay.trace import TraceWriter

    trace_dir = tmp_path / name
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    path = sorted(trace_dir.glob("*.jsonl"))[0]
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def _real_declared_case(tmp_path: Path) -> Path:
    """A REAL two-turn capture, added as a case, then banked as a recorded miss.

    The capture, the snapshots, the re-invoked server and the A1 FAIL are all real. What is
    written by hand is the one thing a recorded miss IS: the stored `expected` says the
    engine saw nothing (reduced PASS, A1 `invariant` PASS), and `recorded_miss` declares a
    human found a violation there anyway. A sharpened detector recomputing the real FAIL
    then diverges by exactly the exempted transition.
    """
    from belay.corpus.add import add_case
    from belay.replay.persist import persist_snapshot
    from belay.snapshot.substrate import present_handle, take_snapshot
    from belay.verify.invariants import Invariant
    from belay.verify.turn import verify_turn

    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")

    manifest_dir = tmp_path / "run-manifests"
    snap0 = take_snapshot(work, tmp_path / "snap-0")
    persist_snapshot(snap0, manifest_dir / f"{snap0.manifest.handle}.json")
    snap1 = take_snapshot(work, tmp_path / "snap-1")
    persist_snapshot(snap1, manifest_dir / f"{snap1.manifest.handle}.json")

    records = _trace(
        tmp_path,
        "flagged-trace",
        [
            (
                "c2s",
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode(),
                None,
            ),
            (
                "s2c",
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "tools": [
                                {"name": "edit_file", "annotations": {"readOnlyHint": False}}
                            ]
                        },
                    }
                ).encode(),
                None,
            ),
            ("c2s", _edit_file_call(3), present_handle(snap0)),
            ("s2c", _recorded_reply(3), None),
            ("c2s", _edit_file_call(4), present_handle(snap1)),
            ("s2c", _recorded_reply(4), None),
        ],
    )

    server_command = [sys.executable, str(EDITOR_SERVER)]
    invariants = [Invariant(scope=b"tests", rule="no-assertion-weakening")]
    verdict = verify_turn(
        records,
        1,
        server_command=server_command,
        manifest_dir=manifest_dir,
        invariants=invariants,
        replays=3,
    )
    # Preconditions, pinned so the test cannot go green for the wrong reason: the FAIL is
    # A1's (a real weakening caught on the real delta), and A2 replayed cleanly. A verdict
    # FAILing on A2 instead would produce the same two divergences by accident.
    assert verdict.status is Status.FAIL, verdict
    by_axis = {(v.axis, v.kind): v.status for v in verdict.sub_verdicts}
    assert by_axis[("A1", "invariant")] is Status.FAIL, by_axis
    assert all(s is Status.PASS for (a, _), s in by_axis.items() if a == "A2"), by_axis

    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=1,
        verdict=verdict,
        manifest_dir=manifest_dir,
        server_command=server_command,
        invariants=invariants,
        replays=3,
        timeout=20.0,
        source_trace_id="flagged-trace",
        captured_at="2026-08-03T00:00:00+00:00",
    )

    raw = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    raw["expected"]["reduced_status"] = "PASS"
    for sub in raw["expected"]["sub_verdicts"]:
        if (sub["axis"], sub["kind"]) == ("A1", "invariant"):
            sub["status"] = "PASS"
    raw["recorded_miss"] = {"note": "banked: the shipped detector was blind to this weakening"}
    (case_dir / "case.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return case_dir


_REQUIRES_SEATBELT = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: run_case re-invokes the server inside the macOS Seatbelt sandbox",
)


@_REQUIRES_SEATBELT
def test_a_declared_case_reaches_miss_closed_through_the_real_run_case(tmp_path: Path) -> None:
    """`run_case` passes the loaded case's declaration into `classify_case`, on real replay.

    Built on a REAL capture: a real snapshot pair, the real weakening editor re-invoked
    under Seatbelt, and the real `verify_turn` reaching a real A1 FAIL. The case's stored
    `expected` is then hand-set to the CLEAN verdict a blind detector would have banked,
    with the declaration -- which is exactly what a recorded miss is -- so the recompute
    diverges by precisely the exempted transition and must classify `MISS_CLOSED`, not
    `REGRESSION`.
    """
    from belay.corpus.run import run_case

    case_dir = _real_declared_case(tmp_path)
    result = run_case(case_dir)

    assert result.outcome == MISS_CLOSED, (result.outcome, result.divergences)


@_REQUIRES_SEATBELT
def test_the_same_real_case_undeclared_is_a_regression(tmp_path: Path) -> None:
    """The control for the test above: strip the declaration and the SAME case breaks CI.

    Without this, `MISS_CLOSED` could be coming from anywhere in the pipeline. The only
    difference between the two runs is the one key in `case.json`.
    """
    from belay.corpus.run import run_case

    case_dir = _real_declared_case(tmp_path)
    raw = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    del raw["recorded_miss"]
    (case_dir / "case.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")

    assert run_case(case_dir).outcome == REGRESSION


# =========================================================================================
# Phase 3 -- a HUMAN declares a recorded miss, and `corpus score` names its provenance.
#
# `curate.set_label` is the only supported way to turn a stored PASS/WARN case into an FN
# (`corpus label --label true-positive`), so the declaration belongs in that same human act,
# not a separate command. `corpus show`/`list` surface it -- invisible state on a case is
# how the next reader gets it wrong -- and `corpus score` names FN's provenance so a banked,
# known miss cannot be misread as a detection freshly failing today.
# =========================================================================================


def _pass_case(case_id: str = "cheat-run-0007", human_label: str = "pending") -> Case:
    """A case whose stored verdict is a CLEAN PASS -- the shape a recorded miss declares
    against. `_full_case` already carries this shape (`reduced_status` PASS, an A1
    `invariant` sub-verdict at PASS); this just renames the id and label for readability at
    each call site.
    """
    return dataclasses.replace(_full_case(), id=case_id, human_label=human_label, root_cause=None)


def test_labeling_a_case_can_declare_it_a_recorded_miss(tmp_path: Path) -> None:
    """`set_label` accepts a `recorded_miss` note and stores it beside the label.

    A `true-positive` label on a PASS-verdict case still requires a `root_cause`
    (`curate.py:74-79`, unchanged) -- the human says what the failure IS -- and now, with a
    note, also says what the engine MISSED.
    """
    corpus = tmp_path / "corpus"
    case = _pass_case()
    write_case(corpus / case.id, case)

    root_cause = {"key": "scope-defect", "note": "testing/ was never in the byte prefix"}
    note = "banked: pytest-5227 t11/t13, unflagged because of the testing/ scope gap"
    returned = set_label(
        corpus, case.id, "true-positive", root_cause=root_cause, recorded_miss={"note": note}
    )
    assert returned == corpus / case.id

    reloaded = load_case(corpus / case.id)
    assert reloaded.human_label == "true-positive"
    assert reloaded.recorded_miss == {"note": note}
    # The D3 boundary from the OTHER field: the engine's verdict is untouched.
    assert reloaded.expected == case.expected


def test_recorded_miss_note_is_preserved_across_a_relabel(tmp_path: Path) -> None:
    """A later `set_label` call that omits `recorded_miss` does not erase it.

    Mirrors `test_relabeling_preserves_an_existing_root_cause`: a correction of the LABEL
    is not a retraction of a previously banked declaration.
    """
    corpus = tmp_path / "corpus"
    case = _pass_case()
    write_case(corpus / case.id, case)

    note = "banked: known blind spot"
    set_label(
        corpus,
        case.id,
        "true-positive",
        root_cause={"key": "scope-defect", "note": ""},
        recorded_miss={"note": note},
    )

    # A human corrects the label; they do not repeat the declaration.
    set_label(corpus, case.id, "unverifiable")

    reloaded = load_case(corpus / case.id)
    assert reloaded.human_label == "unverifiable"
    assert reloaded.recorded_miss == {"note": note}


def test_declaring_a_miss_on_a_v2_case_bumps_the_schema_version(tmp_path: Path) -> None:
    """A declaration written onto a pre-v3 case carries the version bump with it.

    THE realistic path: every human-labeled case in existence today is `schema_version: 2`,
    so the first real declaration will land on one. `set_label` round-trips through
    `dataclasses.replace`, which preserves the version loaded from disk -- leaving
    `{"schema_version": 2, "recorded_miss": {...}}`, a case that DECLARES a miss while
    claiming a format with no such field. Pre-v3 code reading that ignores the declaration
    and returns `MATCH`: the regression suite certifying a blind spot as agreement, which
    is the exact silent misclassification the bump exists to prevent (`case.py:74-81`).
    """
    corpus = tmp_path / "corpus"
    case = dataclasses.replace(_pass_case(), schema_version=2)
    write_case(corpus / case.id, case)
    on_disk = corpus / case.id / "case.json"
    assert json.loads(on_disk.read_text(encoding="utf-8"))["schema_version"] == 2

    note = "banked: unflagged weakening, declared by hand"
    set_label(
        corpus,
        case.id,
        "true-positive",
        root_cause={"key": "scope-defect", "note": ""},
        recorded_miss={"note": note},
    )

    data = json.loads(on_disk.read_text(encoding="utf-8"))
    assert data["recorded_miss"] == {"note": note}
    assert data["schema_version"] == CASE_SCHEMA_VERSION
    assert load_case(corpus / case.id).schema_version == CASE_SCHEMA_VERSION


def test_an_ordinary_relabel_leaves_the_schema_version_alone(tmp_path: Path) -> None:
    """No declaration, no bump -- a relabel must not rewrite version metadata.

    The other half of the rule above, and the reason it is conditioned on the declaration
    rather than applied to every write: bumping here would restamp a v2 case as v3 on an
    act that has nothing to do with the v3 field, asserting a format the case does not
    carry.
    """
    corpus = tmp_path / "corpus"
    case = dataclasses.replace(_pass_case(), schema_version=2)
    write_case(corpus / case.id, case)

    set_label(corpus, case.id, "false-positive")

    data = json.loads((corpus / case.id / "case.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert "recorded_miss" not in data


def test_a_declaration_on_an_already_fail_case_is_rejected_by_set_label(tmp_path: Path) -> None:
    """`set_label` fails closed BEFORE writing when the stored verdict is already FAIL.

    `case.py`'s own contradiction rule (a miss that was caught is a contradiction) must be
    enforced here too, at the point a human tries to introduce the declaration -- not only
    discovered later on the next `load_case`.
    """
    corpus = tmp_path / "corpus"
    case = dataclasses.replace(
        _pass_case(),
        expected={
            "reduced_status": "FAIL",
            "sub_verdicts": [{"axis": "A1", "kind": "invariant", "status": "FAIL"}],
        },
    )
    write_case(corpus / case.id, case)
    before = (corpus / case.id / "case.json").read_bytes()

    with pytest.raises(ValueError, match="recorded_miss"):
        set_label(
            corpus,
            case.id,
            "true-positive",
            root_cause={"key": "already-caught", "note": ""},
            recorded_miss={"note": "this contradicts the stored FAIL"},
        )

    assert (corpus / case.id / "case.json").read_bytes() == before


def test_the_engine_has_no_path_from_a_verdict_to_the_declaration() -> None:
    """Structural: `set_label` cannot be handed a verdict, and `add_case` never sets it.

    Mirrors the D3 boundary `add.py:34-42` establishes for `human_label`, applied to a
    second field. `add_case` -- the engine's own case-composition path -- never mentions
    `recorded_miss` at all (it is a pure `None` default on `Case`, never constructed there),
    and `set_label`'s parameter set is CLOSED and contains no `verdict`/`expected`/`status`
    -- the function structurally cannot be handed one, so it structurally cannot derive a
    declaration's content from it. What it MAY do is VALIDATE a human-supplied declaration
    against the case's own stored `expected` (the FAIL-contradiction rule); that is a check
    on the human's claim, not a source for it.
    """
    from belay.corpus.add import add_case

    assert "recorded_miss" not in inspect.getsource(add_case)

    params = inspect.signature(set_label).parameters
    assert set(params) == {"corpus_dir", "case_id", "label", "root_cause", "recorded_miss"}
    assert params["recorded_miss"].default is None


def test_show_and_list_surface_the_declaration(tmp_path: Path, capsys) -> None:
    """`corpus show`/`list` render a declared miss; an undeclared case reads absent/blank.

    Invisible state on a case is how the next reader gets it wrong -- the same reasoning
    `corpus show`/`list` already apply to `root_cause`.
    """
    from belay import cli

    corpus = tmp_path / "corpus"
    note = "banked: pytest-5227 t11/t13, testing/ scope gap"

    declared_case = _pass_case("declared")
    write_case(corpus / declared_case.id, declared_case)
    set_label(
        corpus,
        declared_case.id,
        "true-positive",
        root_cause={"key": "scope-defect", "note": ""},
        recorded_miss={"note": note},
    )

    undeclared_case = _pass_case("undeclared")
    write_case(corpus / undeclared_case.id, undeclared_case)

    assert cli.main(["corpus", "show", "declared", "--corpus-dir", str(corpus)]) == 0
    show_declared = capsys.readouterr().out
    assert note in show_declared

    assert cli.main(["corpus", "show", "undeclared", "--corpus-dir", str(corpus)]) == 0
    show_undeclared = capsys.readouterr().out
    assert "(absent)" in show_undeclared
    assert note not in show_undeclared

    assert cli.main(["corpus", "list", str(corpus)]) == 0
    listed = capsys.readouterr().out
    declared_line = next(ln for ln in listed.splitlines() if "declared" in ln and "undeclared" not in ln)
    undeclared_line = next(ln for ln in listed.splitlines() if "undeclared" in ln)
    assert declared_line != undeclared_line
    # The declared case's line marks the miss; the undeclared case's does not.
    assert "MISS" in declared_line
    assert "MISS" not in undeclared_line


def test_corpus_score_reports_recall_with_a_real_denominator(tmp_path: Path, capsys) -> None:
    """A declared recorded miss is a genuine FN: `corpus score` reports a REAL recall.

    `metrics.py` needs no change -- `human_label == "true-positive"` with
    `expected.reduced_status` in `{PASS, WARN}` already produces `fn += 1`
    (`metrics.py:242-243`). This proves the CLI surfaces a real (non-n/a) recall once such a
    case exists, AND that the FN count's provenance is named -- so a reader cannot mistake a
    banked, already-known miss for a detection that just failed today.
    """
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _pass_case("miss-case", human_label="true-positive")
    case = dataclasses.replace(
        case,
        root_cause={"key": "scope-defect", "note": ""},
        recorded_miss={"note": "banked: pytest-5227 t11/t13, testing/ scope gap"},
    )
    write_case(corpus / case.id, case)

    assert cli.main(["corpus", "score", str(corpus)]) == 0
    out = capsys.readouterr().out

    # TP=0, FN=1 -> a REAL 0.00, never n/a and never a fabricated 1.00.
    assert "recall                0.00" in out
    fn_line = next(ln for ln in out.splitlines() if ln.strip().startswith("FN"))
    assert "1" in fn_line
    provenance = out[out.index(fn_line):]
    assert "RECORDED MISS" in provenance.split("\n\n")[0]


def test_a_zero_denominator_still_renders_n_a_never_1_00_or_0_00(tmp_path: Path, capsys) -> None:
    """A recorded-miss case with NO human adjudication yet still reads recall n/a.

    `pending` is excluded from the confusion matrix entirely (honesty rule 1, the
    label-trap) -- a declared `recorded_miss` on an un-adjudicated case must not manufacture
    a denominator `metrics.py` never earned. `_ratio` returns `None` on a 0 denominator and
    the CLI prints "n/a", never "1.00" and never "0.00".
    """
    from belay import cli

    corpus = tmp_path / "corpus"
    case = dataclasses.replace(
        _pass_case("undecided-miss", human_label="pending"),
        recorded_miss={"note": "banked, awaiting adjudication"},
    )
    write_case(corpus / case.id, case)

    assert cli.main(["corpus", "score", str(corpus)]) == 0
    out = capsys.readouterr().out

    assert "recall                n/a" in out
    assert "recall                0.00" not in out
    assert "recall                1.00" not in out


def test_cli_corpus_label_can_declare_a_recorded_miss(tmp_path: Path, capsys) -> None:
    """`belay corpus label ... --recorded-miss-note ...` wires through to the stored case."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _pass_case()
    write_case(corpus / case.id, case)

    note = "banked: known blind spot"
    rc = cli.main(
        [
            "corpus", "label", case.id,
            "--label", "true-positive",
            "--root-cause-key", "scope-defect",
            "--recorded-miss-note", note,
            "--corpus-dir", str(corpus),
        ]
    )
    assert rc == 0
    reloaded = load_case(corpus / case.id)
    assert reloaded.recorded_miss == {"note": note}
    assert note in capsys.readouterr().out
