"""`NOT_COVERED` — a sub-verdict-only status that must never survive the reduction.

`UNVERIFIED` today carries two different statements: *"we tried to check this and could
not"* and *"this was never inside what Belay claims to check"*. `NOT_COVERED` splits the
second one off. The whole safety of that split rests on one property, and it is the
property this file exists to pin:

    **`NOT_COVERED` can be the status of a sub-verdict. It can never be the status of a
    turn.**

That is not a stylistic preference. Three downstream readers fold "not FAIL" into a
decided non-detection or into a denominator:

- `corpus/metrics.py:139-152` — anything that is not FAIL scores `positive=False`, i.e. a
  DECIDED NON-DETECTION. The module docstring at :24-27 explicitly forbids that fold for a
  status that means "outside coverage".
- `corpus/case.py:164-169` — a fail-closed load raises on an unknown reduced status.
- `phase0/ledger.py:109-114` — `total_turns()` sums every value with no key validation, so
  an older reader would silently fold an unknown status into its denominator.

If `NOT_COVERED` could reach `reduced_status`, each of those becomes a silent false PASS.
So the reduction *filters it out before ranking*, and an all-`NOT_COVERED` set reduces to
`UNVERIFIED` — never to `NOT_COVERED`, and never to `PASS`. Giving it a merely-losing rank
would have been the false-PASS shape: `reduce([NOT_COVERED])` would return it.

The first test is exhaustive over the status enum on purpose. A sampled example would pass
against an ordering that leaks the new status in some unenumerated combination, and a
missed enumeration here is exactly how this change becomes a false PASS.
"""

from __future__ import annotations

import itertools

from belay import cli
from belay.verify.verdict import Status, Verdict, reduce

#: The severity the reduction is expected to preserve for the four scored statuses.
#: Deliberately re-declared here rather than imported from `verdict._RANK`: a test that
#: reads the implementation's own ordering cannot catch that ordering being wrong.
_EXPECTED_RANK = {
    Status.PASS: 0,
    Status.WARN: 1,
    Status.UNVERIFIED: 2,
    Status.FAIL: 3,
}


def _verdict(status: Status, *, axis: str = "A2", kind: str = "replay") -> Verdict:
    return Verdict(
        axis=axis,
        kind=kind,
        status=status,
        observed=None,
        expected=None,
        message="",
    )


def _all_combinations(max_len: int = 3):
    """Every ordering, with repetition, of every status, up to `max_len` sub-verdicts.

    `itertools.product(..., repeat=n)` — not `combinations` — because it covers orderings
    AND multiplicities, so a reduction that is sensitive to position or to a duplicate is
    caught too. Length 3 over the whole enum is enough to place NOT_COVERED first, last,
    and in the middle of every pairing of the four scored statuses.
    """
    statuses = list(Status)
    for n in range(1, max_len + 1):
        yield from itertools.product(statuses, repeat=n)


# --------------------------------------------------------------------------- criterion 1


def test_not_covered_is_never_a_reduced_status() -> None:
    """EXHAUSTIVE over the status enum: no input makes `reduce` return NOT_COVERED.

    This is the guarantee the three downstream readers named in the module docstring
    depend on. It is asserted over every ordering, with repetition, of every member of
    `Status` up to three sub-verdicts, plus the empty set — not over a chosen example.
    """
    assert reduce([]) is not Status.NOT_COVERED
    for combo in _all_combinations():
        result = reduce([_verdict(s) for s in combo])
        assert result is not Status.NOT_COVERED, (
            f"reduce({[s.value for s in combo]}) leaked NOT_COVERED as a turn status"
        )


def test_reduce_agrees_with_the_expected_ordering_on_every_combination() -> None:
    """EXHAUSTIVE: filtering NOT_COVERED out must not perturb the surviving ordering.

    For every combination: drop the NOT_COVERED entries, and whatever remains must reduce
    exactly as it would have on its own, by the independently-declared rank above. Empty
    after the filter is UNVERIFIED. This is what makes the change additive rather than a
    quiet re-ranking of the statuses that were already there.
    """
    for combo in _all_combinations():
        scored = [s for s in combo if s is not Status.NOT_COVERED]
        expected = (
            max(scored, key=lambda s: _EXPECTED_RANK[s]) if scored else Status.UNVERIFIED
        )
        assert reduce([_verdict(s) for s in combo]) is expected, (
            f"reduce({[s.value for s in combo]}) disagreed with the expected ordering"
        )


# --------------------------------------------------------------------------- criterion 2


def test_not_covered_never_reads_as_pass() -> None:
    """At the verdict level: NOT_COVERED is its own status, and never stands in for PASS.

    Two separate claims. (a) The enum member is distinct and serializes under its own name
    — `Status` has a `str` mixin, so a surface that prints the value must print
    "NOT_COVERED", not something a reader could mistake for a pass. (b) EXHAUSTIVE: a
    reduction returns PASS only when a PASS sub-verdict was genuinely present, so no
    quantity of NOT_COVERED can manufacture one.
    """
    assert Status.NOT_COVERED is not Status.PASS
    assert Status.NOT_COVERED.value == "NOT_COVERED"
    assert "PASS" not in Status.NOT_COVERED.value

    for combo in _all_combinations():
        if reduce([_verdict(s) for s in combo]) is Status.PASS:
            assert Status.PASS in combo, (
                f"reduce({[s.value for s in combo]}) manufactured a PASS from no PASS"
            )


# --------------------------------------------------------------------------- criterion 3


def test_reduce_of_only_not_covered_is_unverified() -> None:
    """The empty-after-filter case: UNVERIFIED, never NOT_COVERED and never PASS.

    A turn whose every sub-check was outside coverage verified nothing, and
    nothing-verified is not a pass — the same reasoning as `reduce([])`, which
    `tests/test_verdict.py:59-61` already pins.
    """
    for n in (1, 2, 3):
        only_not_covered = [_verdict(Status.NOT_COVERED) for _ in range(n)]
        assert reduce(only_not_covered) is Status.UNVERIFIED


# --------------------------------------------------------------------------- criterion 5


def test_the_network_dimension_never_softens_a_readonly_fail() -> None:
    """A NOT_COVERED sub-verdict alongside a FAIL leaves the turn FAILing.

    The reduction-level statement of the guard in `tests/test_verify_network.py:168-186`:
    reclassifying the unobservable network dimension must never buy a real violation any
    leniency, whatever order the sub-verdicts arrive in.
    """
    a2_fail = _verdict(Status.FAIL, kind="effect")
    not_covered = _verdict(Status.NOT_COVERED, kind="network")

    assert reduce([a2_fail, not_covered]) is Status.FAIL
    assert reduce([not_covered, a2_fail]) is Status.FAIL
    assert reduce([_verdict(Status.PASS), not_covered, a2_fail]) is Status.FAIL


def test_not_covered_never_masks_an_unverified() -> None:
    """The honest abstention still wins over a pass — the coverage split changes nothing.

    A turn that genuinely could not be verified stays UNVERIFIED even when another
    dimension was outside coverage. Losing this would restore the false pass the whole
    ordering exists to prevent.
    """
    not_covered = _verdict(Status.NOT_COVERED, kind="network")
    assert reduce([_verdict(Status.PASS), _verdict(Status.UNVERIFIED), not_covered]) is (
        Status.UNVERIFIED
    )


# --------------------------------------------------------------------------- criterion 6


def test_reference_server_turn_reduces_to_pass() -> None:
    """The outcome, at the unit level: the reference-server shape is a PASS.

    A replayed turn against `@modelcontextprotocol/server-filesystem`: replay reproduced,
    the filesystem effect conformed, and the only remaining dimension is the
    `openWorldHint: false` promise Belay structurally cannot observe. That turn is a PASS
    *on what Belay actually verifies* — with the coverage boundary still visible as a
    sub-verdict, which is what keeps the PASS honest.

    (The end-to-end form of this lands with phase 3, where `network_subverdict` begins
    emitting NOT_COVERED; this pins the reduction it depends on.)
    """
    sub_verdicts = [
        _verdict(Status.PASS, kind="replay"),
        _verdict(Status.PASS, kind="effect"),
        _verdict(Status.NOT_COVERED, kind="network"),
    ]
    assert reduce(sub_verdicts) is Status.PASS


# ------------------------------------------------------- the CLI's duplicate ordering


def test_cli_worst_stays_in_lockstep_with_reduce() -> None:
    """`cli._worst` is a SECOND hand-rolled rank dict and it decides the exit code.

    `cli.py:550` exits 0 only when `_worst` is PASS, so a divergence between the two
    orderings is a divergence between the printed verdict and the process's answer. It is
    fed turn statuses, which can never be NOT_COVERED after this change — the filter there
    is defensive, and it is asserted EXHAUSTIVELY against the same combinations.
    """
    for combo in _all_combinations():
        turns = [_verdict(s) for s in combo]
        worst = cli._worst(turns, Status)
        assert worst is not Status.NOT_COVERED
        assert worst is reduce(turns)

    assert cli._worst([], Status) is Status.UNVERIFIED
    assert cli._worst([_verdict(Status.NOT_COVERED)], Status) is Status.UNVERIFIED


def test_a_run_whose_only_non_pass_sub_verdicts_are_not_covered_exits_zero() -> None:
    """The exit code, end to end in shape: coverage boundaries do not fail a run.

    Two reference-server-shaped turns — clean replay, clean effect, an unobservable
    network promise — each reduce to PASS, so the worst status across the run is PASS and
    `cli.py:550`'s `0 if worst is Status.PASS else 1` yields **0**. If NOT_COVERED were
    ranked instead of filtered, this run would exit 1 and every reference-server user's CI
    would be red for a dimension Belay never claimed to check.
    """

    class _Turn:
        def __init__(self, status: Status) -> None:
            self.status = status

    turn_status = reduce(
        [
            _verdict(Status.PASS, kind="replay"),
            _verdict(Status.PASS, kind="effect"),
            _verdict(Status.NOT_COVERED, kind="network"),
        ]
    )
    assert turn_status is Status.PASS

    worst = cli._worst([_Turn(turn_status), _Turn(turn_status)], Status)
    exit_code = 0 if worst is Status.PASS else 1  # mirrors cli.py:550
    assert exit_code == 0
