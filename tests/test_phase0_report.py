"""Phase-0 report renderer: the violation rate + the instrument-suspect guard.

Task 1 built `RunLedger` (pure data + derived counts). This module turns a `RunLedger`
plus a `belay.corpus.metrics.Metrics` into the published "number" — with honesty guards
as teeth: a run whose traces captured ~no verifiable turns must NEVER read as a clean 0%
violation rate (the R6 false-zero defense), and a 0 denominator must NEVER become 1.0 or
a bare 0%. UNVERIFIED must never render as PASS, and must never enter the violation
numerator.

This file is written FIRST, before `src/belay/phase0/report.py` exists, per strict TDD.
"""

from __future__ import annotations

from belay.corpus.metrics import Metrics
from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger
from belay.phase0.report import instrument_suspect, render_report, violation_rate


def _instance(
    trace_id: str,
    disposition: Disposition,
    *,
    turn_status_counts: dict | None = None,
    flagged_turns: list | None = None,
    flagged_addable: list | None = None,
    flagged_unaddable: list | None = None,
    unverified_causes: dict | None = None,
    error: str | None = None,
) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=turn_status_counts or {},
        flagged_turns=flagged_turns or [],
        flagged_addable=flagged_addable or [],
        flagged_unaddable=flagged_unaddable or [],
        unverified_causes=unverified_causes or {},
        error=error,
    )


def _metrics(**overrides) -> Metrics:
    """A `Metrics` with sane defaults, fields overridable per test."""
    base = dict(
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
    base.update(overrides)
    return Metrics(**base)


def _all_no_verifiable_ledger() -> RunLedger:
    """Every instance is NO_VERIFIABLE_TURNS: nothing was ever verifiable."""
    return RunLedger(
        instances=[
            _instance("trace-a", Disposition.NO_VERIFIABLE_TURNS),
            _instance("trace-b", Disposition.NO_VERIFIABLE_TURNS),
            _instance("trace-c", Disposition.NO_VERIFIABLE_TURNS),
        ]
    )


def test_instrument_suspect_all_no_verifiable_blocks_zero_percent_headline() -> None:
    """(1) THE TEETH: all-NO_VERIFIABLE_TURNS -> instrument_suspect True, report says so,
    and the report contains NO violation-rate percentage headline (never a fake 0%)."""
    ledger = _all_no_verifiable_ledger()
    metrics = _metrics()

    assert instrument_suspect(ledger) is True

    report = render_report(ledger, metrics)

    assert "INSTRUMENT SUSPECT" in report
    assert "0%" not in report
    assert "violation rate =" not in report


def _mixed_ledger() -> RunLedger:
    """Some CLEAN, some FLAGGED, some NO_VERIFIABLE — not instrument-suspect."""
    return RunLedger(
        instances=[
            _instance("trace-clean-1", Disposition.VERIFIED_CLEAN),
            _instance("trace-clean-2", Disposition.VERIFIED_CLEAN),
            _instance("trace-clean-3", Disposition.VERIFIED_CLEAN),
            _instance("trace-flagged", Disposition.VERIFIED_FLAGGED),
            _instance("trace-no-verifiable", Disposition.NO_VERIFIABLE_TURNS),
        ]
    )


def test_mixed_ledger_violation_rate_excludes_no_verifiable() -> None:
    """(2) violation_rate == flagged/(clean+flagged); report shows that denominator
    explicitly; no_verifiable count does not appear in it."""
    ledger = _mixed_ledger()
    metrics = _metrics()

    # denominator = 3 clean + 1 flagged = 4; violating = 1
    assert violation_rate(ledger) == 1 / 4
    assert instrument_suspect(ledger) is False

    report = render_report(ledger, metrics)

    assert "violation rate = 1/4" in report
    assert "INSTRUMENT SUSPECT" not in report


def test_empty_ledger_violation_rate_is_none_and_not_instrument_suspect() -> None:
    """(3) An EMPTY ledger (no instances at all): violation_rate is None (nothing to
    compute), and instrument_suspect is False — no instances is not the same claim as
    "instances ran and caught nothing verifiable"."""
    ledger = RunLedger(instances=[])

    assert violation_rate(ledger) is None
    assert instrument_suspect(ledger) is False

    report = render_report(ledger, _metrics())
    assert "n/a" in report
    assert "INSTRUMENT SUSPECT" not in report


def test_unverified_appears_only_in_its_own_section_never_in_violation_numerator() -> None:
    """(4) UNVERIFIED turns inside a VERIFIED_FLAGGED instance do not change the
    violation numerator/denominator, and UNVERIFIED never appears folded into the
    violation-rate line — only in its own by-cause section."""
    flagged_with_unverified = _instance(
        "trace-flagged",
        Disposition.VERIFIED_FLAGGED,
        turn_status_counts={"PASS": 1, "FAIL": 1, "WARN": 0, "UNVERIFIED": 2},
        flagged_turns=[1],
        flagged_addable=[1],
        unverified_causes={"timeout": 2},
    )
    clean = _instance("trace-clean", Disposition.VERIFIED_CLEAN)
    ledger = RunLedger(instances=[flagged_with_unverified, clean])

    assert ledger.violating_instances() == 1
    assert violation_rate(ledger) == 1 / 2

    report = render_report(ledger, _metrics())
    assert "violation rate = 1/2" in report
    assert "timeout: 2" in report
    # The UNVERIFIED bucket must not be attached to the violation-rate line itself.
    violation_line = next(line for line in report.splitlines() if "violation rate" in line)
    assert "UNVERIFIED" not in violation_line
    assert "timeout" not in violation_line


def test_fp_rate_from_precision_and_na_when_precision_is_none() -> None:
    """(5) tp=4, fp=1 (precision == 0.8) -> FP-rate shown as its fraction "1/5 = 20.0%",
    consistent with every other rate this module prints (numerator/denominator alongside
    the percentage); precision is None -> n/a, never a fabricated 0.0/1.0."""
    ledger = _mixed_ledger()

    report_with_precision = render_report(ledger, _metrics(tp=4, fp=1, precision=0.8))
    fp_line_with_precision = next(
        line for line in report_with_precision.splitlines() if "FP-rate" in line
    )
    assert "1/5" in fp_line_with_precision
    assert "20.0%" in fp_line_with_precision

    report_without_precision = render_report(ledger, _metrics(precision=None))
    fp_line = next(
        line for line in report_without_precision.splitlines() if "FP-rate" in line
    )
    assert "n/a" in fp_line


def test_render_report_is_deterministic() -> None:
    """(6) Same (ledger, metrics) in -> identical string out, every time."""
    ledger = _mixed_ledger()
    metrics = _metrics(tp=3, fp=1, precision=0.75)

    first = render_report(ledger, metrics)
    second = render_report(ledger, metrics)

    assert first == second
