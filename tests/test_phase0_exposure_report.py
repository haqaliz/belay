"""The exposure section of `belay phase0 report`: which of three things happened.

Task 1 (`invariants.py`) made the A1 content rule emit an `expected["exposure"]` fact.
Task 2 (`ledger.py`) carried it into `InstanceRecord.exposure` and the ledger JSON, with
ABSENCE preserved end to end (`None` != `{"files_compared": 0, ...}`). This module is the
payoff: `render_report` must tell the reader, for every instance, which of three things
happened —

  judged        exposure is not None and files_compared > 0
  no opportunity exposure is not None and files_compared == 0
  unrecorded    exposure is None

— and never leave a bare silence. This file is written FIRST, before the section exists
in `src/belay/phase0/report.py`, per strict TDD.
"""

from __future__ import annotations

from belay.corpus.metrics import Metrics
from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger
from belay.phase0.report import instrument_suspect, render_report


def _instance(
    trace_id: str,
    disposition: Disposition = Disposition.VERIFIED_CLEAN,
    *,
    exposure: dict | None = None,
    turn_status_counts: dict | None = None,
) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=turn_status_counts or {},
        flagged_turns=[],
        flagged_addable=[],
        flagged_unaddable=[],
        unverified_causes={},
        error=None,
        exposure=exposure,
    )


def _metrics() -> Metrics:
    return Metrics(
        tp=0,
        fp=0,
        fn=0,
        tn=0,
        precision=None,
        recall=None,
        coverage=None,
        unverified=0,
        pending=0,
        unverifiable=0,
        total=0,
    )


def test_three_exposure_states_render_three_distinct_sentences() -> None:
    """One ledger holding all three states: each renders its own sentence, and no
    instance is left out of the section (no bare silence)."""
    judged = _instance(
        "trace-judged",
        exposure={"files_compared": 3, "turns_judging": 2, "turns_recorded": 2},
    )
    no_opportunity = _instance(
        "trace-no-opportunity",
        exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
    )
    unrecorded = _instance("trace-unrecorded", exposure=None)
    ledger = RunLedger(instances=[judged, no_opportunity, unrecorded])

    report = render_report(ledger, _metrics())

    assert "judged 3 file-comparison(s) across 2 turn(s)" in report
    assert (
        "0 file-comparison(s) — this instance's silence carries no information about "
        "the rule" in report
    )
    assert (
        "exposure unrecorded — no exposure fact was recorded here (a ledger written "
        "before exposure accounting, an ERRORED instance, no content rule in force, or "
        "turns that never replayed); this is NOT a claim that the rule judged nothing"
        in report
    )

    # Every instance's trace_id appears in the exposure section, attached to its
    # sentence — nothing is silently dropped.
    for trace_id in ("trace-judged", "trace-no-opportunity", "trace-unrecorded"):
        line = next(line for line in report.splitlines() if trace_id in line)
        assert line.strip() != trace_id


def test_zero_exposure_instances_are_named_not_only_counted() -> None:
    """A no-opportunity instance's trace_id must appear in the report text — a reader
    must be able to check WHICH instance had nothing to judge, not just how many."""
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-empty-a",
                exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
            ),
            _instance(
                "trace-empty-b",
                exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 2},
            ),
        ]
    )

    report = render_report(ledger, _metrics())

    assert "trace-empty-a" in report
    assert "trace-empty-b" in report


def test_exposure_section_survives_instrument_suspect() -> None:
    """The exposure section is a LIMIT statement, not a rate: it must render even when
    `instrument_suspect` suppresses the violation-rate headline — exactly the discipline
    `_coverage_section` already holds."""
    ledger = RunLedger(
        instances=[
            _instance("trace-a", Disposition.NO_VERIFIABLE_TURNS, exposure=None),
            _instance("trace-b", Disposition.NO_VERIFIABLE_TURNS, exposure=None),
        ]
    )
    assert instrument_suspect(ledger) is True

    report = render_report(ledger, _metrics())

    assert "INSTRUMENT SUSPECT" in report
    assert "exposure" in report
    assert "trace-a" in report
    assert "trace-b" in report


def test_unrecorded_exposure_is_never_rendered_as_zero() -> None:
    """An instance with `exposure is None` must render the `unrecorded` sentence, never
    a `0 file(s)` line — collapsing the two would fabricate the exact finding this
    aspect exists to report honestly."""
    ledger = RunLedger(instances=[_instance("trace-old", exposure=None)])

    report = render_report(ledger, _metrics())

    line = next(line for line in report.splitlines() if "trace-old" in line)
    assert "0 file(s)" not in line
    assert "unrecorded" in line


def test_no_opportunity_sentence_states_the_count_and_claims_no_cause() -> None:
    """`files_compared == 0` has several causes the ledger cannot tell apart, so the
    sentence must state the COUNT and stop.

    The rule SKIPS any in-scope file that is absent from the task pre-state
    (`invariants.py:417-420`) — it is an addition, and there was nothing there to weaken —
    so an agent ADDING one test under `tests/` produces `compared 0, in_scope 1`. Adding a
    test is the commonest agent behaviour in this project's captured data, and for it "the
    rule was given nothing to judge" is false: the rule was given a file and decided it.
    The bounded file-budget abstain (`{"in_scope": M}`, no `compared` key) reaches this
    state too. One sentence covers all of them only if it asserts no cause at all.
    """
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-additions-only",
                exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
            )
        ]
    )

    report = render_report(ledger, _metrics())

    line = next(line for line in report.splitlines() if "trace-additions-only" in line)
    assert "0 file-comparison(s)" in line
    assert "nothing to judge" not in line
    assert "carries no information about the rule" in line


def test_unrecorded_sentence_does_not_assert_an_old_ledger() -> None:
    """`exposure is None` arises in a BRAND-NEW ledger too, so the sentence may not blame
    a ledger that predates exposure accounting.

    `run_batch` writes `exposure=None` for every ERRORED instance (`runner.py:158-172`),
    and A1 records nothing at all under `--no-default-invariants`, under a `read-only`-only
    policy, or on an instance whose turns never replayed. Stage 3 had ERRORED instances and
    the coming re-mint will too. The load-bearing half — "this is NOT a claim that the rule
    judged nothing" — must survive; only the fabricated cause goes.
    """
    ledger = RunLedger(
        instances=[_instance("trace-errored", Disposition.ERRORED, exposure=None)]
    )

    report = render_report(ledger, _metrics())

    line = next(line for line in report.splitlines() if "trace-errored" in line)
    assert "predates" not in line
    assert "ERRORED" in line
    assert "this is NOT a claim that the rule judged nothing" in line


def test_exposure_section_present_on_a_clean_run() -> None:
    """Sanity: a normal (not instrument-suspect) run also carries the exposure section,
    with the section header always present regardless of state mix."""
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a",
                exposure={"files_compared": 1, "turns_judging": 1, "turns_recorded": 1},
            )
        ]
    )

    report = render_report(ledger, _metrics())

    assert "exposure" in report
