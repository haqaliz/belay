"""One population from many stage ledgers: the dedup rule, and both denominators.

The banked Phase-0 data is **24 captures over 17 distinct trace ids** — `flask-4045` was
minted three times and five instances twice. There is no merge anywhere in
`belay.phase0`, and `RunLedger.instances` is a bare list every aggregate is computed over,
so a naive concatenation double-counts every shared `trace_id`. This module pins the
merge that does not.

Two facts decide the whole design, and getting either wrong silently corrupts the number:

**A capture's `trace_id` is NOT unique across stages.** It comes from the trace file stem,
so the `s2` and `s3` captures of `pallets__flask-4992` share the id
`trace-pallets__flask-4992` while being genuinely different observations with different
turn counts. So a CAPTURE is `(label, trace_id)` and an INSTANCE is `trace_id`; without the
caller-supplied stage label the population silently collapses two real observations into
one.

**No merged `InstanceRecord` is ever synthesized.** Summing `turn_status_counts` across two
captures of one instance would count that instance's turns twice while the instance counts
once, making the per-turn FAIL rate meaningless. Capture-level records stay the ground
truth; the instance level is a VIEW over them.

This file is written FIRST, before `src/belay/phase0/population.py` exists, per strict TDD.
"""

from __future__ import annotations

import json

import pytest

from belay import cli
from belay.phase0.ledger import (
    DetectorIdentity,
    Disposition,
    InstanceRecord,
    RunLedger,
    to_json,
)
from belay.phase0.population import LabeledLedger, Population
from belay.phase0.report import render_population_report


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
    not_covered_turns: dict | None = None,
    exposure: dict | None = None,
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
        not_covered_turns=not_covered_turns or {},
        exposure=exposure,
    )


def _ledger(*instances: InstanceRecord, detector: DetectorIdentity | None = None) -> RunLedger:
    return RunLedger(instances=list(instances), detector=detector)


# --- (1) the dedup rule: one instance minted twice is ONE instance, TWO captures --------


def test_same_instance_across_stages_counts_once() -> None:
    """A `trace_id` captured in two stages counts ONCE as an instance, TWICE as a capture.

    This is the exact shape of the banked data: `pallets__flask-4992` was minted in `s2`
    (17 turns) and again in `s3` (20 turns). A naive concatenation of the two ledgers would
    report a denominator of 2 for one instance — inflating the denominator, deflating the
    rate, and doing it silently. Per-TURN totals stay over captures, because all 37 turns
    were really verified.
    """
    s2 = _ledger(
        _instance(
            "trace-pallets__flask-4992",
            Disposition.VERIFIED_CLEAN,
            turn_status_counts={"PASS": 17},
        )
    )
    s3 = _ledger(
        _instance(
            "trace-pallets__flask-4992",
            Disposition.VERIFIED_CLEAN,
            turn_status_counts={"PASS": 20},
        )
    )

    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    assert population.instance_count() == 1
    assert population.instance_denominator() == 1
    assert population.capture_count() == 2
    # Per-turn statistics stay over CAPTURES: 37 turns really were verified.
    assert population.total_turns() == 37


# --- (7) capture identity is (label, trace_id), not trace_id ---------------------------


def test_capture_identity_uses_label_and_trace_id() -> None:
    """Two captures sharing a `trace_id` under DIFFERENT labels remain TWO captures.

    The subtlest failure in this unit: keying captures on `trace_id` alone would drop one
    of the two genuine observations of `flask-4992` — quietly discarding real verified
    turns rather than double-counting them. Keying on the pair keeps both. Two captures
    sharing a `trace_id` under the SAME label are a duplicate input, not two observations,
    and are a named error.
    """
    shared = "trace-pallets__flask-4992"
    s2 = _ledger(_instance(shared, Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 17}))
    s3 = _ledger(_instance(shared, Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 20}))

    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    assert {capture.key for capture in population.captures} == {("s2", shared), ("s3", shared)}

    # The same label twice is a duplicate INPUT, and must be named rather than merged.
    with pytest.raises(ValueError) as excinfo:
        Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s2", s3)])
    assert "s2" in str(excinfo.value)

    # And so is the same trace_id twice INSIDE one labeled ledger.
    with pytest.raises(ValueError) as duplicate_within:
        Population.from_labeled(
            [
                LabeledLedger(
                    "s2",
                    _ledger(
                        _instance(shared, Disposition.VERIFIED_CLEAN),
                        _instance(shared, Disposition.VERIFIED_FLAGGED),
                    ),
                )
            ]
        )
    assert shared in str(duplicate_within.value)


# --- (2) worst-verdict-wins on the violation question ----------------------------------


def test_worst_verdict_wins_across_captures() -> None:
    """CLEAN in one stage + FLAGGED in another ⇒ the instance is VIOLATING.

    Conservative in the direction of not hiding a violation: the stage that flagged
    observed something real, and a later clean stage does not un-observe it. The cost —
    this can inflate the rate — is paid for by naming the instance in the disagreement
    list, never by reducing it silently.
    """
    s2 = _ledger(_instance("trace-x", Disposition.VERIFIED_CLEAN))
    s3 = _ledger(_instance("trace-x", Disposition.VERIFIED_FLAGGED, flagged_turns=[3]))

    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    assert population.violating_instances() == ("trace-x",)
    assert population.instance_denominator() == 1
    assert population.instance_count() == 1
    assert [view.trace_id for view in population.disagreements()] == ["trace-x"]


# --- (3) an ERRORED capture is not evidence of a violation -----------------------------


def test_errored_capture_is_not_evidence_of_violation() -> None:
    """ERRORED + CLEAN ⇒ in the denominator, NOT violating. ERRORED alone ⇒ OUT.

    "Worst" is defined over the VIOLATION question, not over badness. A capture that
    errored is not evidence of a violation and not evidence of cleanliness either — it is
    no evidence at all. So the instance rides on the stage that actually ran, and an
    instance that errored in EVERY stage was never verified and cannot enter a denominator
    it contributed no observation to. It is also not a disagreement: an abstention does not
    contradict a verdict.
    """
    s2 = _ledger(
        _instance("trace-partly", Disposition.ERRORED, error="server died"),
        _instance("trace-never", Disposition.ERRORED, error="server died"),
    )
    s3 = _ledger(_instance("trace-partly", Disposition.VERIFIED_CLEAN))

    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    by_id = {view.trace_id: view for view in population.instances()}
    assert by_id["trace-partly"].in_denominator() is True
    assert by_id["trace-partly"].is_violating() is False
    assert by_id["trace-never"].in_denominator() is False
    assert by_id["trace-never"].is_violating() is False

    assert population.instance_count() == 2
    assert population.instance_denominator() == 1
    assert population.violating_instances() == ()
    # An abstention beside a verdict is not a disagreement.
    assert population.disagreements() == ()


# --- (6) merging is order-independent --------------------------------------------------


def test_merge_is_order_independent() -> None:
    """Either merge order yields an EQUAL population, not merely equal aggregates.

    Equality of the whole value is the stronger claim and the one that matters: it makes
    the rendered report byte-identical too, so the order stage ledgers happen to be listed
    in can never change the published number or the text around it.
    """
    s2 = _ledger(
        _instance("trace-b", Disposition.VERIFIED_FLAGGED, turn_status_counts={"FAIL": 2}),
        _instance("trace-a", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 5}),
    )
    s3 = _ledger(
        _instance("trace-a", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 7}),
        _instance("trace-c", Disposition.ERRORED, error="boom"),
    )

    forward = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])
    backward = Population.from_labeled([LabeledLedger("s3", s3), LabeledLedger("s2", s2)])

    assert forward == backward
    assert forward.capture_count() == backward.capture_count() == 4
    assert forward.instance_count() == backward.instance_count() == 3
    assert forward.instance_denominator() == backward.instance_denominator() == 2
    assert forward.violating_instances() == backward.violating_instances() == ("trace-b",)
    assert forward.total_turns() == backward.total_turns() == 14


# --- (4) the reduction is auditable: a disagreeing instance is NAMED --------------------


def test_disagreeing_instances_are_named() -> None:
    """The report NAMES each disagreeing instance and BOTH of its outcomes.

    Worst-verdict-wins can inflate the rate, and that is acceptable only because the
    reduction is visible: a reader must be able to see which instance was counted violating
    on the strength of one stage while another stage called it clean, and check that call.
    A silent reduction would be a number nobody can audit.
    """
    s2 = _ledger(
        _instance("trace-disputed", Disposition.VERIFIED_CLEAN),
        _instance("trace-agreed", Disposition.VERIFIED_CLEAN),
    )
    s3 = _ledger(
        _instance("trace-disputed", Disposition.VERIFIED_FLAGGED, flagged_turns=[4]),
        _instance("trace-agreed", Disposition.VERIFIED_CLEAN),
    )
    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    report = render_population_report(population)

    disagreement_line = next(line for line in report.splitlines() if "trace-disputed" in line)
    assert "s2" in disagreement_line
    assert "s3" in disagreement_line
    assert "VERIFIED_CLEAN" in disagreement_line
    assert "VERIFIED_FLAGGED" in disagreement_line
    assert "worst-verdict-wins" in disagreement_line
    # The instance the stages AGREED on is not listed as a DISAGREEMENT. Narrowed from a
    # whole-report substring check (fix round 1) to the disagreement block specifically: the
    # whole-report check was a proxy for this section, and it broke the moment a legitimate
    # OTHER section (exposure) started naming every instance too, including agreed ones for
    # reasons that have nothing to do with disagreement. Scoping to the block keeps this
    # test exactly as strict about the property it actually exists to pin.
    disagreement_block = report.split("disagreements", 1)[1].split("\n\n", 1)[0]
    assert "trace-agreed" not in disagreement_block


def test_a_population_without_disagreements_says_so() -> None:
    """No disagreement is stated in words, never left as an empty section.

    An absent section reads as "the question was not asked". The whole point of naming
    disagreements is that a reader can tell a reduction happened; "none" is a result.
    """
    s2 = _ledger(_instance("trace-a", Disposition.VERIFIED_CLEAN))
    s3 = _ledger(_instance("trace-a", Disposition.VERIFIED_CLEAN))
    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    report = render_population_report(population)

    assert "no disagreement" in report


# --- (5) both denominators, each labeled with what it counts ---------------------------


def test_both_denominators_are_reported() -> None:
    """Instances (the HEADLINE) and captures (alongside), each labeled with what it counts.

    The two denominators are different numbers over the same data and neither is wrong —
    they answer different questions. What would be wrong is printing one unlabeled, so a
    reader cannot tell whether "3" means three instances or three captures. `flask-4992`
    minted twice must count once as an instance and twice as a capture, and the report has
    to say which is which in words.
    """
    s2 = _ledger(
        _instance("trace-dup", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 17}),
        _instance(
            "trace-flagged",
            Disposition.VERIFIED_FLAGGED,
            turn_status_counts={"PASS": 3, "FAIL": 1},
        ),
    )
    s3 = _ledger(
        _instance("trace-dup", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 20})
    )
    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    report = render_population_report(population)

    # 2 instances (trace-dup once, trace-flagged once), 1 violating -> the headline.
    headline = next(line for line in report.splitlines() if "1/2" in line)
    assert "INSTANCE" in headline
    assert "50.0%" in headline

    # 3 captures, 1 of them flagged -> the alongside rate, explicitly NOT the headline.
    alongside = next(line for line in report.splitlines() if "1/3" in line)
    assert "CAPTURE" in alongside
    assert "33.3%" in alongside

    # Both counts appear with the noun they count, and turns stay over captures (17+4+20).
    size_line = next(line for line in report.splitlines() if "population size" in line)
    assert "3 capture(s)" in size_line
    assert "2 instance(s)" in size_line
    assert "41 turn(s)" in size_line


def test_empty_population_reports_na_never_a_bare_zero_or_hundred() -> None:
    """A zero denominator is `n/a` on BOTH rates — never a bare 0% and never a 100%.

    The same discipline `belay.corpus.metrics._ratio` and `phase0.report._ratio` already
    apply: an empty denominator has no rate, and a conjured one reads as a measurement that
    was never taken.
    """
    population = Population.from_labeled([LabeledLedger("s2", _ledger())])

    report = render_population_report(population)

    assert "n/a" in report
    assert "0.0%" not in report
    assert "100.0%" not in report


# --- the detector, still visible after a merge ------------------------------------------


def test_population_report_states_each_stages_detector() -> None:
    """Merging is exactly where a stale detector would disappear — so it is named per stage.

    A population can mix a ledger written by the REPLACED `tests/` read-only rule with one
    written by today's `no-assertion-weakening`, and the merged number would then be a
    number no single detector produced. An unrecorded detector must stay `unrecorded` on
    this surface too, by stage, rather than being averaged into silence.
    """
    stale = _ledger(_instance("trace-old", Disposition.VERIFIED_CLEAN))
    current = _ledger(
        _instance("trace-new", Disposition.VERIFIED_CLEAN),
        detector=DetectorIdentity(
            rules=(("tests", "no-assertion-weakening"),), version="belay 0.10.0"
        ),
    )
    population = Population.from_labeled(
        [LabeledLedger("s2", stale), LabeledLedger("s3", current)]
    )

    report = render_population_report(population)

    stale_line = next(line for line in report.splitlines() if line.strip().startswith("s2:"))
    assert "unrecorded" in stale_line
    assert "no-assertion-weakening" not in stale_line

    current_block = report.split("s3:")[1]
    assert "no-assertion-weakening" in current_block
    assert "belay 0.10.0" in current_block


# --- (8) exposure: per-instance ANY-reduction, per-capture sum, both reported ----------


def test_instance_is_exposed_if_any_capture_judged_a_file() -> None:
    """An instance is EXPOSED iff ANY of its captures judged >= 1 file — the ANY-reduction.

    `trace-x`'s `s2` capture recorded exposure but judged nothing in scope; its `s3`
    capture judged one file. Mirroring `is_violating`'s worst-verdict-wins reduction
    (`population.py:137-146`), the instance is exposed on the strength of the capture that
    found something, not averaged down by the capture that found nothing.
    """
    s2 = _ledger(
        _instance(
            "trace-x",
            Disposition.VERIFIED_CLEAN,
            exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
        )
    )
    s3 = _ledger(
        _instance(
            "trace-x",
            Disposition.VERIFIED_CLEAN,
            exposure={"files_compared": 1, "turns_judging": 1, "turns_recorded": 1},
        )
    )
    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    view = population.instances()[0]
    assert view.is_exposed() is True
    assert view.exposure_unrecorded() is False
    assert view.trace_id == "trace-x"


def test_instance_exposure_is_unrecorded_only_when_no_capture_recorded_it() -> None:
    """UNRECORDED iff NO capture recorded exposure at all — never merely "no files found".

    `trace-old` predates exposure accounting in both stages: `exposure is None` on every
    capture. That is a DIFFERENT claim from `trace-empty`, whose single capture DID record
    exposure and found nothing in scope — the "no opportunity" state, not "unrecorded".
    Collapsing the two would fabricate a measurement for a ledger that never took one.
    """
    old_s2 = _ledger(_instance("trace-old", Disposition.VERIFIED_CLEAN))
    old_s3 = _ledger(_instance("trace-old", Disposition.VERIFIED_CLEAN))
    empty = _ledger(
        _instance(
            "trace-empty",
            Disposition.VERIFIED_CLEAN,
            exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
        )
    )
    population = Population.from_labeled(
        [LabeledLedger("s2", old_s2), LabeledLedger("s3", old_s3)]
    )
    empty_population = Population.from_labeled([LabeledLedger("s2", empty)])

    old_view = population.instances()[0]
    assert old_view.trace_id == "trace-old"
    assert old_view.exposure_unrecorded() is True
    assert old_view.is_exposed() is False

    empty_view = empty_population.instances()[0]
    assert empty_view.exposure_unrecorded() is False
    assert empty_view.is_exposed() is False


def test_population_report_prints_the_exposure_merge_rule() -> None:
    """The exposure merge rule is PRINTED, beside the dedup rule — not merely documented.

    The dedup rule is printed in the output rather than left to a docstring
    (`population.py:342-351`/`report.py:342-351`), and this aspect owes exposure the same
    discipline: a reader who cannot see the reduction on the page cannot audit it.
    """
    population = Population.from_labeled(
        [LabeledLedger("s2", _ledger(_instance("trace-a", Disposition.VERIFIED_CLEAN)))]
    )

    report = render_population_report(population)

    assert "per INSTANCE, reduce by ANY" in report
    assert "per CAPTURE" in report
    assert "SUMMED" in report or "sum" in report.lower()


def test_captures_disagreeing_on_exposure_are_reduced_by_the_stated_rule() -> None:
    """One instance, one capture judged a file, one recorded nothing — BOTH numbers reported.

    Per-instance: `trace-y` reduces to EXPOSED (ANY-reduction). Per-capture: the totals are
    SUMMED across both captures without dedup, matching `total_turns()`'s discipline — the
    same instance's two captures both contribute their own `files_compared`.
    """
    s2 = _ledger(
        _instance(
            "trace-y",
            Disposition.VERIFIED_CLEAN,
            exposure={"files_compared": 2, "turns_judging": 1, "turns_recorded": 1},
        )
    )
    s3 = _ledger(
        _instance(
            "trace-y",
            Disposition.VERIFIED_CLEAN,
            exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
        )
    )
    population = Population.from_labeled([LabeledLedger("s2", s2), LabeledLedger("s3", s3)])

    assert tuple(v.trace_id for v in population.instances() if v.is_exposed()) == ("trace-y",)
    assert population.total_files_compared() == 2
    assert population.exposure_capture_count() == 2

    report = render_population_report(population)
    exposure_line = next(line for line in report.splitlines() if "trace-y" in line and "judged" in line)
    assert "judged" in exposure_line

    alongside_line = next(
        line for line in report.splitlines() if "file(s)" in line and "capture" in line.lower()
    )
    assert "2" in alongside_line


def test_unrecorded_instances_are_named_individually_not_only_counted() -> None:
    """Fix round 1: UNRECORDED instances are named INDIVIDUALLY, sorted — like Task 3's
    single-ledger report, and unlike this population report's first cut, which reported
    them as a count only.

    Every ledger in `runs/` predates this aspect, so a population built from banked data
    puts every instance in the unrecorded bucket today — a reader of the published
    headline must be able to check exactly WHICH instances carried no information, not just
    how many, or the headline's biggest caveat becomes unauditable the moment it matters.
    """
    s2 = _ledger(
        _instance("trace-b-unrecorded", Disposition.VERIFIED_CLEAN),
        _instance("trace-a-unrecorded", Disposition.VERIFIED_CLEAN),
    )
    population = Population.from_labeled([LabeledLedger("s2", s2)])

    report = render_population_report(population)

    exposure_section = report.split("exposure (", 1)[1].split("\n\n", 1)[0]
    a_line = next(line for line in exposure_section.splitlines() if "trace-a-unrecorded" in line)
    b_line = next(line for line in exposure_section.splitlines() if "trace-b-unrecorded" in line)
    assert "exposure unrecorded" in a_line
    assert "exposure unrecorded" in b_line
    # Never conflated with a measured zero.
    assert "0 file(s)" not in a_line
    assert "0 file(s)" not in b_line
    # Sorted by trace_id, matching every other named section on this page.
    assert exposure_section.index("trace-a-unrecorded") < exposure_section.index(
        "trace-b-unrecorded"
    )


def test_control_exposure_is_surfaced_with_the_same_three_states() -> None:
    """Fix round 1: a control's exposure state is shown in the controls block too.

    A control that came back VERIFIED_CLEAN could mean the rule looked and found nothing
    wrong, or that the rule had nothing to look at — the identical false-zero distinction
    this whole aspect exists to make visible, and it lands squarely on the page's
    control-integrity story. Reuses the SAME wording constants as the exposure section —
    never a fourth phrasing.
    """
    population = Population.from_labeled(
        [
            LabeledLedger(
                "s3",
                _ledger(
                    _instance(
                        "trace-control__judged",
                        Disposition.VERIFIED_CLEAN,
                        exposure={"files_compared": 1, "turns_judging": 1, "turns_recorded": 1},
                    ),
                    _instance(
                        "trace-control__no-opportunity",
                        Disposition.VERIFIED_CLEAN,
                        exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
                    ),
                    _instance("trace-control__unrecorded", Disposition.VERIFIED_CLEAN),
                ),
            )
        ]
    )

    report = render_population_report(population)
    controls_block = report.split("controls:", 1)[1]
    lines = controls_block.splitlines()

    def _lines_for(trace_id: str) -> str:
        """This control's own line plus its immediately-following exposure line(s)."""
        start = next(i for i, line in enumerate(lines) if trace_id in line)
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("trace-")),
            len(lines),
        )
        return "\n".join(lines[start:end])

    assert "judged 1 file(s) across 1 turn(s)" in _lines_for("trace-control__judged")
    assert "0 file(s) compared" in _lines_for("trace-control__no-opportunity")
    unrecorded_span = _lines_for("trace-control__unrecorded")
    assert "exposure unrecorded" in unrecorded_span
    assert "0 file(s)" not in unrecorded_span


# --- `belay phase0 combine LABEL=PATH ...` — the CLI over the population ----------------


def _write_ledger(path, ledger: RunLedger) -> str:
    path.write_text(json.dumps(to_json(ledger), indent=2), encoding="utf-8")
    return str(path)


def test_phase0_combine_merges_labeled_ledgers_and_reports_both_denominators(
    tmp_path, capsys
) -> None:
    """`phase0 combine s2=... s3=...` prints the population report and exits 0.

    The command exists because the banked data is several stage ledgers, and there is no
    other way to ask "what is the number over all of them" without concatenating by hand —
    which double-counts every instance minted twice.
    """
    s2 = _write_ledger(
        tmp_path / "s2.json",
        _ledger(
            _instance("trace-dup", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 17}),
            _instance(
                "trace-flagged", Disposition.VERIFIED_FLAGGED, turn_status_counts={"FAIL": 1}
            ),
        ),
    )
    s3 = _write_ledger(
        tmp_path / "s3.json",
        _ledger(
            _instance("trace-dup", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 20})
        ),
    )

    rc = cli.main(["phase0", "combine", f"s2={s2}", f"s3={s3}"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "3 capture(s) over 2 instance(s)" in out, out
    assert "1/2" in out, out
    assert "1/3" in out, out


def test_phase0_combine_malformed_pair_is_a_named_error(tmp_path, capsys) -> None:
    """A `LABEL=PATH` argument without an `=` is NAMED, never silently skipped.

    A silently dropped input is the worst outcome available here: the command would print a
    smaller, wrong population that looks exactly like a correct one.
    """
    ledger = _write_ledger(tmp_path / "s2.json", _ledger())

    rc = cli.main(["phase0", "combine", ledger])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert "LABEL=PATH" in out, out
    assert ledger in out, out


def test_phase0_combine_repeated_label_is_a_named_error(tmp_path, capsys) -> None:
    """The same label twice is a duplicated input, and is named rather than merged."""
    first = _write_ledger(tmp_path / "a.json", _ledger())
    second = _write_ledger(tmp_path / "b.json", _ledger())

    rc = cli.main(["phase0", "combine", f"s2={first}", f"s2={second}"])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert "s2" in out, out


def test_phase0_combine_missing_or_corrupt_ledger_is_fail_closed(tmp_path, capsys) -> None:
    """A missing or corrupt input ledger is fail-closed, exactly as `phase0 report` is.

    A population silently short one ledger reports a number over a population nobody chose.
    """
    missing = tmp_path / "nope.json"
    rc = cli.main(["phase0", "combine", f"s2={missing}"])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "belay:" in out, out

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{ not valid json", encoding="utf-8")
    rc2 = cli.main(["phase0", "combine", f"s2={corrupt}"])
    out2 = capsys.readouterr().out
    assert rc2 == 2, out2
    assert "belay:" in out2, out2


def test_phase0_combine_does_not_change_phase0_report(tmp_path, capsys) -> None:
    """`phase0 report` on ONE ledger is untouched by the existence of `combine`.

    Criterion 13: the single-ledger contract is additive-only. `report` still renders the
    single-ledger report — violation rate, coverage, UNVERIFIED-by-cause, FP-rate — and
    never the population report's dedup wording.
    """
    path = tmp_path / "s2.json"
    _write_ledger(path, _ledger(_instance("trace-a", Disposition.VERIFIED_CLEAN)))

    rc = cli.main(["phase0", "report", str(path), "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "violation rate = 0/1" in out, out
    assert "dedup rule" not in out, out
    assert "per CAPTURE" not in out, out


# --- controls: not instances, and a FAILing one is not a void --------------------------


def test_controls_excluded_from_headline_rate() -> None:
    """A control changes NEITHER the headline numerator nor its denominator.

    A control is a known-answer instance run to check the instrument, not a task the agent
    was measured on. Folding it into the headline mixes "did the agent violate?" with "did
    the instrument work?" — and because controls are known-clean by construction, including
    them drags the rate toward zero by exactly the number of controls that were run.
    """
    without_control = Population.from_labeled(
        [
            LabeledLedger(
                "s3",
                _ledger(
                    _instance("trace-a", Disposition.VERIFIED_FLAGGED, flagged_turns=[1]),
                    _instance("trace-b", Disposition.VERIFIED_CLEAN),
                ),
            )
        ]
    )
    with_control = Population.from_labeled(
        [
            LabeledLedger(
                "s3",
                _ledger(
                    _instance("trace-a", Disposition.VERIFIED_FLAGGED, flagged_turns=[1]),
                    _instance("trace-b", Disposition.VERIFIED_CLEAN),
                    _instance("trace-control__flask-read-only", Disposition.VERIFIED_CLEAN),
                ),
            )
        ]
    )

    measured = with_control.measured()
    assert measured.instance_denominator() == without_control.instance_denominator() == 2
    assert measured.violating_instances() == without_control.violating_instances() == ("trace-a",)

    headline = next(
        line for line in render_population_report(with_control).splitlines() if "HEADLINE" in line
    )
    assert "1/2" in headline
    assert "50.0%" in headline


def test_control_id_is_recognised_behind_the_trace_stem_prefix() -> None:
    """A control is recognised as `trace-control__…`, which is the shape on real ledgers.

    A ledger's `trace_id` is the TRACE FILE'S STEM, and the mint bridge names each capture
    `trace-<instance_id>.jsonl`. So the `control__` convention never appears at position 0
    of a real `trace_id` — a plain `startswith("control__")` would treat EVERY real control
    as an ordinary instance and fold it into the headline, which is the exact defect this
    partition exists to fix, arriving silently. The bare `control__…` form is recognised too,
    for a ledger whose ids are instance ids rather than trace stems.
    """
    population = Population.from_labeled(
        [
            LabeledLedger(
                "s3",
                _ledger(
                    _instance("trace-control__flask-read-only", Disposition.VERIFIED_CLEAN),
                    _instance("control__requests-read-then-write", Disposition.VERIFIED_CLEAN),
                    _instance("trace-pallets__flask-4992", Disposition.VERIFIED_CLEAN),
                    # A repo genuinely named with the token elsewhere is NOT a control: the
                    # convention is a PREFIX on the instance id, not a substring anywhere.
                    _instance("trace-org__control__like-repo", Disposition.VERIFIED_CLEAN),
                ),
            )
        ]
    )

    assert population.control_ids() == (
        "control__requests-read-then-write",
        "trace-control__flask-read-only",
    )
    assert population.measured().instance_count() == 2
    assert population.controls().instance_count() == 2


def test_controls_reported_in_their_own_block() -> None:
    """Controls get their own block, with their own counts, and the ids are NAMED.

    The convention is a naming convention, not a guarantee: an instance genuinely called
    `control__*` that is not a control would be mis-partitioned. Naming the ids the report
    TREATED as controls is what makes that mistake visible instead of silent.
    """
    population = Population.from_labeled(
        [
            LabeledLedger(
                "s3",
                _ledger(
                    _instance("trace-a", Disposition.VERIFIED_CLEAN),
                    _instance("trace-control__flask-read-only", Disposition.VERIFIED_CLEAN),
                    _instance("trace-control__flask-write-new-file", Disposition.VERIFIED_CLEAN),
                ),
            )
        ]
    )

    report = render_population_report(population)

    controls_line = next(line for line in report.splitlines() if line.startswith("controls:"))
    assert "2 control" in controls_line
    assert "EXCLUDED" in controls_line
    assert "trace-control__flask-read-only" in report
    assert "trace-control__flask-write-new-file" in report


def test_failing_control_is_reported_as_detector_false_positive() -> None:
    """A FLAGGED control is a detector FALSE POSITIVE here, and explicitly NOT a mint void.

    The meaning of a failing control is context-dependent, and nothing in the data encodes
    the context. In a FRESH MINT a failing control means the instrument was broken while
    capturing, and it voids the mint. In a RE-VERIFICATION of already-banked captures there
    is no mint in flight to void: the control is known-clean by construction, so a flag on
    it is the detector firing on known-good behaviour — a precision signal, which is the very
    thing this measurement is for. Conflating the two would fabricate a void, and a
    fabricated void reads as a PIVOT that the data never supported.
    """
    population = Population.from_labeled(
        [
            LabeledLedger(
                "s3",
                _ledger(
                    _instance("trace-a", Disposition.VERIFIED_CLEAN),
                    _instance(
                        "trace-control__flask-read-only",
                        Disposition.VERIFIED_FLAGGED,
                        flagged_turns=[2],
                    ),
                ),
            )
        ]
    )

    assert [view.trace_id for view in population.failing_controls()] == [
        "trace-control__flask-read-only"
    ]

    report = render_population_report(population)

    failing_line = next(
        line for line in report.splitlines() if "trace-control__flask-read-only" in line
        and "VERIFIED_FLAGGED" in line
    )
    assert "FALSE POSITIVE" in failing_line

    assert "NOT a mint-void condition" in report
    assert "re-verification" in report

    # And it stays out of the headline: 0 violating of 1 measured instance.
    headline = next(line for line in report.splitlines() if "HEADLINE" in line)
    assert "0/1" in headline


def test_population_without_controls_says_so() -> None:
    """No control matched ⇒ the report SAYS so, rather than omitting the block.

    An absent controls block reads as "controls ran and were fine". "No control is in this
    population" is a different and weaker statement, and it is the true one — Stage 3 had
    zero control coverage, and that fact must be legible from the report rather than
    inferred from a silence.
    """
    population = Population.from_labeled(
        [LabeledLedger("s3", _ledger(_instance("trace-a", Disposition.VERIFIED_CLEAN)))]
    )

    report = render_population_report(population)

    assert "controls: none" in report
    assert "NOT the same as" in report
