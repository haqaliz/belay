"""Aspect A2 — `cause-and-surfaces`: the boundary abstention gets a NAME of its own.

Phases 4-5 of `verify-tool-not-offered` taught A2 to abstain when the replay boundary
never offered the recorded tool. The abstention was honest and it was ANONYMOUS: the
turn's `TurnVerdict.cause` bucketed under the generic `REPLAYED_RESULT_UNVERIFIED`,
indistinguishable from an unparseable reply, a nondeterministic tool, or any other
result-axis abstention. So the one number the 2026-08-12 gate mint needed and could not
produce — *"how many turns could not be verified because the boundary lacked the tool"*
(`prd.md` G4) — stayed unproducible even after the fix landed.

## The trap this file exists to catch

`_replayed_cause` (`src/belay/verify/turn.py`) builds

    f"{REPLAYED_SUB_VERDICT} {axis}/{kind}: {message}"

and `canonical_cause` buckets by PREFIX on `axis/kind`. `_PREFIX_LABELS` already carries
`("replayed but unverified A2/replay", REPLAYED_RESULT_UNVERIFIED)`, which matches EVERY
result-axis abstention. So declaring a new `REPLAYED_*` constant and registering it in
`interop.attach._REPLAYED_CAUSES` would satisfy the reflection guard while the new bucket
sat **permanently unreached** — G4 silently unmet, checklist ticked, nothing measurable.

**AC-1 is the test that catches that**, and it is written first: it asserts the reached
value, not the declared one. The abstention therefore needs its own sub-verdict `kind`
(`replay:tool-not-offered`, `effect:tool-not-offered`, …), mirroring the `effect:network`
precedent, with `_PREFIX_LABELS` entries ordered AHEAD of the `A2/replay` and `A2/effect`
catch-alls exactly as `effect:network` precedes `effect`. The AXIS stays `A2`.

## Three causes, not two

`tool-not-offered` is a DECIDED fact about the operator's `--server` and it is the one G4
counts. `boundary-ambiguous` (two configured servers both claim the tool, so routing would
be a guess) and `boundary-undecided` (the probe could not be run or read) are IGNORANCE
about the boundary, and they are ignorance of two different shapes with two different
fixes: disambiguate the routing, versus make the probe answerable. Folding either into the
first would inflate exactly the number the gate needs; folding them into each other would
tell an operator to fix the wrong thing.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from belay import cli
from belay.interop.attach import UNRESTORABLE_PRE_STATE, correlate_and_attach
from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger
from belay.corpus.metrics import Metrics
from belay.phase0.report import render_report
from belay.replay.probe import (
    BOUNDARY_AMBIGUOUS,
    BOUNDARY_UNDECIDED,
    TOOL_NOT_OFFERED,
)
from belay.replay.report import (
    REPLAYED_BOUNDARY_AMBIGUOUS,
    REPLAYED_BOUNDARY_UNDECIDED,
    REPLAYED_EFFECT_UNVERIFIED,
    REPLAYED_RESULT_UNVERIFIED,
    REPLAYED_SUB_VERDICT,
    REPLAYED_TOOL_NOT_OFFERED,
    _PREFIX_LABELS,
    canonical_cause,
)
from belay.verify.json import coverage_record, turn_record
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, Verdict

from test_verify_tool_not_offered import (  # noqa: E402  (test-module helper reuse)
    IS_ERROR_RECORDED,
    IS_ERROR_REPLAYED,
    RUN_TOOL,
    _DeterminismSpy,
    _replayed_with_boundary,
    _run_process_records,
    _wire,
    shell_server_cmd,
)


def _not_offered_verdict(tmp_path, monkeypatch, name: str = "cause") -> TurnVerdict:
    """The real `verify_turn`, driven to the not-offered abstention.

    Only `replay_turn`, `classify_determinism` and the probe are stubbed — the DECISION
    and the cause it produces are the engine's own. A hand-built `TurnVerdict` could not
    notice `_replayed_cause` bucketing the abstention into the catch-all, which is the
    entire failure mode this file guards.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    _wire(monkeypatch, reply, {"read_text_file", "write_file"}, _DeterminismSpy())
    return verify_turn(
        _run_process_records(tmp_path, name),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )


# =====================================================================================
# AC-1 — THE BUCKET IS REACHED, NOT MERELY DECLARED
# =====================================================================================


def test_a_not_offered_turn_carries_its_own_named_cause(tmp_path, monkeypatch) -> None:
    """AC-1. The turn's cause is the NEW label — never the generic result bucket.

    This is the dead-on-arrival test. A constant declared in `replay/report.py` and
    registered in `interop.attach` passes every other guard in the suite while
    `canonical_cause` still resolves the abstention to `REPLAYED_RESULT_UNVERIFIED`,
    because the `A2/replay` catch-all matches first. Assert the value the engine actually
    produced.
    """
    verdict = _not_offered_verdict(tmp_path, monkeypatch, "ac1")

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.cause == REPLAYED_TOOL_NOT_OFFERED, (
        "the boundary abstention bucketed under the generic result cause -- the new "
        "bucket is declared but unreachable, so G4's number cannot be produced",
        verdict.cause,
    )
    assert verdict.cause != REPLAYED_RESULT_UNVERIFIED, verdict.cause


def test_the_abstention_sub_verdicts_carry_their_own_kind(tmp_path, monkeypatch) -> None:
    """Both A2 sub-verdicts, not just the deciding one (spec in-scope 1).

    Phase 5 gated the effect axis too, so both abstentions must be distinguishable on the
    surfaces that render sub-verdicts individually (`corpus show`, the C7 console, and
    `--json`). The axis stays `A2` on both.
    """
    verdict = _not_offered_verdict(tmp_path, monkeypatch, "kinds")
    kinds = {sub.kind: sub for sub in verdict.sub_verdicts}

    result = kinds[f"replay:{TOOL_NOT_OFFERED}"]
    effect = kinds[f"effect:{TOOL_NOT_OFFERED}"]
    assert result.axis == "A2" and effect.axis == "A2", verdict
    assert result.status is Status.UNVERIFIED and effect.status is Status.UNVERIFIED
    assert "replay" not in kinds, "the generic result kind must not also be emitted"
    assert "effect" not in kinds, "the generic effect kind must not also be emitted"


# =====================================================================================
# AC-2 — the `_PREFIX_LABELS` ordering, pinned by calling `canonical_cause` directly
# =====================================================================================


def _cause(kind: str, message: str = "…") -> str:
    return f"{REPLAYED_SUB_VERDICT} A2/{kind}: {message}"


def test_the_specific_prefix_resolves_ahead_of_the_catch_all() -> None:
    """AC-2. Both shapes, through the real bucketer, in one assertion pair.

    `A2/replay:tool-not-offered` starts with `A2/replay`, so the entry order in
    `_PREFIX_LABELS` is the whole mechanism. Asserted on the FUNCTION, not on the table:
    a reordering that keeps the table's contents intact still breaks the bucket.
    """
    assert canonical_cause(_cause(f"replay:{TOOL_NOT_OFFERED}")) == REPLAYED_TOOL_NOT_OFFERED
    assert canonical_cause(_cause("replay")) == REPLAYED_RESULT_UNVERIFIED
    assert canonical_cause(_cause(f"effect:{TOOL_NOT_OFFERED}")) == REPLAYED_TOOL_NOT_OFFERED
    assert canonical_cause(_cause("effect")) == REPLAYED_EFFECT_UNVERIFIED


def test_the_table_orders_every_boundary_prefix_before_its_catch_all() -> None:
    """The same fact read off the table, so a future edit that reorders it fails loudly."""
    positions = {prefix: i for i, (prefix, _label) in enumerate(_PREFIX_LABELS)}
    for reason in (TOOL_NOT_OFFERED, BOUNDARY_AMBIGUOUS, BOUNDARY_UNDECIDED):
        for kind in ("replay", "effect"):
            specific = f"{REPLAYED_SUB_VERDICT} A2/{kind}:{reason}"
            catch_all = f"{REPLAYED_SUB_VERDICT} A2/{kind}"
            assert specific in positions, ("unregistered boundary prefix", specific)
            assert positions[specific] < positions[catch_all], (
                "a boundary prefix sits behind the catch-all it is a prefix of, so it can "
                "never be reached",
                specific,
            )


# =====================================================================================
# AC-4 — three distinct causes, each round-tripping through `canonical_cause`
# =====================================================================================


def test_the_three_boundary_causes_are_distinct() -> None:
    """AC-4a. `not offered` / `ambiguous` / `undecided` are three findings, not one."""
    labels = {
        REPLAYED_TOOL_NOT_OFFERED,
        REPLAYED_BOUNDARY_AMBIGUOUS,
        REPLAYED_BOUNDARY_UNDECIDED,
    }
    assert len(labels) == 3, labels
    assert REPLAYED_RESULT_UNVERIFIED not in labels
    assert REPLAYED_EFFECT_UNVERIFIED not in labels


def test_each_boundary_cause_round_trips_through_canonical_cause() -> None:
    """AC-4b. Idempotence is load-bearing, not cosmetic.

    `phase0.runner` calls `canonical_cause(verdict.cause)` on an ALREADY-canonical label
    before bucketing it, so a label that re-bucketed to something else would publish a
    different name than the verdict carried.
    """
    for label in (
        REPLAYED_TOOL_NOT_OFFERED,
        REPLAYED_BOUNDARY_AMBIGUOUS,
        REPLAYED_BOUNDARY_UNDECIDED,
    ):
        assert canonical_cause(label) == label, label


def test_an_ambiguous_boundary_and_an_unreadable_probe_do_not_share_a_bucket(
    tmp_path, monkeypatch
) -> None:
    """AC-4c, driven through the engine: the two undecided shapes reach DIFFERENT names.

    An unreadable probe is an infrastructure fact; two configured servers both claiming
    the tool is a routing fact the operator can fix by naming one. Same status, different
    name, because the next action differs.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    _wire(monkeypatch, reply, None, _DeterminismSpy())
    unreadable = verify_turn(
        _run_process_records(tmp_path, "undecided"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )
    assert unreadable.cause == REPLAYED_BOUNDARY_UNDECIDED, unreadable

    # Two configured servers, both offering the tool -> the routing is a guess.
    reply2 = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    _wire(monkeypatch, reply2, {RUN_TOOL, "read_text_file"}, _DeterminismSpy())
    ambiguous = verify_turn(
        _run_process_records(tmp_path, "ambiguous"),
        0,
        server_command=["other-server"],
        shell_server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )
    assert ambiguous.cause == REPLAYED_BOUNDARY_AMBIGUOUS, ambiguous
    assert ambiguous.cause != unreadable.cause


# =====================================================================================
# AC-3 — the reflection guard stays green, and C9 reports the NEW cause
# =====================================================================================


def test_interop_reports_the_new_cause_and_never_an_unrestorable_pre_state(
    tmp_path, monkeypatch
) -> None:
    """AC-3. The `interop-merge-repair` bug class, re-armed for the new bucket.

    A cause outside `_REPLAYED_CAUSES` is reported by C9 as `unrestorable-pre-state` — an
    assertion that the snapshot could not be restored. Here it restored fine and the tool
    was re-invoked against a boundary that does not offer it. The span must carry the new
    name, not a fabricated restore failure and not a bare, causeless UNVERIFIED.
    """
    from conftest import trace_of
    from fixtures.connection_frames import TRACE_CONTEXT_META
    from test_interop_attach import SPAN_ID, TRACE_ID, _span

    # The cause is produced by the REAL `verify_turn` on the real abstention path — a
    # hand-built TurnVerdict could not notice the engine bucketing it into the catch-all.
    # Only the correlation is exercised here, so that verdict is handed to `attach` through
    # the `verify=` seam rather than replayed a second time.
    verdict = _not_offered_verdict(tmp_path, monkeypatch, "interop")
    assert verdict.cause == REPLAYED_TOOL_NOT_OFFERED, verdict

    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])

    [result] = correlate_and_attach(
        records,
        [_span(TRACE_ID, SPAN_ID)],
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
        verify=lambda *a, **k: verdict,
    )
    assert result.cause != UNRESTORABLE_PRE_STATE, (
        "interop reported an unrestorable pre-state for a turn that replayed fine -- the "
        "new bucket is not in the closed replayed-cause vocabulary",
        result,
    )
    assert result.cause == REPLAYED_TOOL_NOT_OFFERED, result
    assert result.status is Status.UNVERIFIED


# =====================================================================================
# AC-5 — one rendering assertion per surface, each with its coverage line
# =====================================================================================

#: A hand-built stand-in for the surfaces that render a stored/serialised verdict rather
#: than computing one. The engine-produced value is pinned by AC-1 above; these assert the
#: RENDERING, so building the verdict here keeps each surface's test to one moving part.
NETWORK_KIND = "effect:network"
NETWORK_MESSAGE = (
    "openWorldHint conformance NOT_COVERED: tool 'run_process' DECLARED openWorldHint: "
    "false — a promise this run did not check"
)
RESULT_MESSAGE = (
    "result-equivalence UNVERIFIED on tool 'run_process': the replay boundary does not "
    "offer this tool"
)
EFFECT_MESSAGE = (
    "effect-conformance UNVERIFIED on tool 'run_process': the replay boundary does not "
    "offer this tool"
)


def _rendered_turn() -> TurnVerdict:
    return TurnVerdict(
        turn_index=0,
        tool_name="run_process",
        status=Status.UNVERIFIED,
        sub_verdicts=[
            Verdict("A2", f"replay:{TOOL_NOT_OFFERED}", Status.UNVERIFIED, None, None,
                    RESULT_MESSAGE),
            Verdict("A2", f"effect:{TOOL_NOT_OFFERED}", Status.UNVERIFIED, None, None,
                    EFFECT_MESSAGE),
            Verdict("A2", NETWORK_KIND, Status.NOT_COVERED, None, None, NETWORK_MESSAGE),
        ],
        cause=REPLAYED_TOOL_NOT_OFFERED,
    )


def test_surface_verify_text_prints_the_cause_and_the_coverage_boundary(capsys) -> None:
    """Surface 1: `belay verify`, per turn and in the aggregate."""
    cli._emit_verdict(_rendered_turn())
    cli._emit_aggregate([_rendered_turn()], Status)
    out = capsys.readouterr().out

    assert REPLAYED_TOOL_NOT_OFFERED in out, out
    assert f"replay:{TOOL_NOT_OFFERED}" in out, out
    assert f"effect:{TOOL_NOT_OFFERED}" in out, out
    assert "UNVERIFIED" in out and "coverage" in out.lower(), out
    assert NETWORK_KIND in out, "the coverage line must travel with the status"
    # The spec's risk 3: the text renderer groups by AXIS, not by kind. Narrowing the kind
    # must not split one turn's A2 block into three. Pinned, not trusted.
    assert out.count("A2 ") == 3, ("the A2 block fragmented by kind", out)
    # …and the status is never rendered flush against the kind (the pre-existing
    # `effect:networkNOT_COVERED` collision, which the narrowed kinds would have joined).
    for kind in (f"replay:{TOOL_NOT_OFFERED}", f"effect:{TOOL_NOT_OFFERED}", NETWORK_KIND):
        assert f"{kind}UNVERIFIED" not in out and f"{kind}NOT_COVERED" not in out, (kind, out)


def test_surface_verify_json_carries_the_cause_and_the_kinds() -> None:
    """Surface 2: `verify --json`. The coverage block still counts only NOT_COVERED."""
    record = turn_record(_rendered_turn())

    assert record["cause"] == REPLAYED_TOOL_NOT_OFFERED, record
    kinds = [s["kind"] for s in record["sub_verdicts"]]
    assert f"replay:{TOOL_NOT_OFFERED}" in kinds and f"effect:{TOOL_NOT_OFFERED}" in kinds

    coverage = coverage_record([_rendered_turn()])
    assert set(coverage) == {NETWORK_KIND}, (
        "the new kinds are UNVERIFIED, not NOT_COVERED -- they must never enter the "
        "coverage block",
        coverage,
    )


def test_surface_corpus_show_renders_the_boundary_kind_and_message(
    tmp_path: Path, capsys
) -> None:
    """Surface 3: `belay corpus show` — the corpus is the regression suite."""
    case_dir = tmp_path / "case-001"
    case_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "id": "case-001",
                "target_turn_index": 0,
                "human_label": "pending",
                "expected": {
                    "reduced_status": "UNVERIFIED",
                    "sub_verdicts": [
                        {
                            "axis": "A2",
                            "kind": f"replay:{TOOL_NOT_OFFERED}",
                            "status": "UNVERIFIED",
                            "message": RESULT_MESSAGE,
                        },
                        {
                            "axis": "A2",
                            "kind": NETWORK_KIND,
                            "status": "NOT_COVERED",
                            "message": NETWORK_MESSAGE,
                        },
                    ],
                },
                "server_command": ["some-server"],
                "invariants": [],
                "replays": 3,
                "timeout": 30.0,
                "provenance": "test",
                "capture_platform": "darwin",
                "capture_capabilities": ["seatbelt"],
            }
        ),
        encoding="utf-8",
    )

    rc = cli._cmd_corpus_show(SimpleNamespace(case_id="case-001", corpus_dir=str(tmp_path)))
    out = capsys.readouterr().out

    assert rc == 0, out
    assert f"replay:{TOOL_NOT_OFFERED}" in out, out
    assert "does not offer this tool" in out, out
    assert NETWORK_KIND in out, "the coverage line must travel with the status"


def test_surface_interop_correlate_renders_the_cause_in_text_and_json() -> None:
    """Surface 4: `belay interop correlate`, both renderings."""
    from belay.interop.attach import CorrelatedSpan
    from belay.interop import report as interop_report

    span = CorrelatedSpan(
        span_id="a" * 16, turn_index=0, verdict=_rendered_turn(),
        cause=REPLAYED_TOOL_NOT_OFFERED,
    )

    text = interop_report.render([span])
    assert REPLAYED_TOOL_NOT_OFFERED in text, text
    assert "UNVERIFIED" in text, text
    assert "coverage" in text.lower() and NETWORK_KIND in text, text

    doc = interop_report.to_json([span])
    assert doc["spans"][0]["cause"] == REPLAYED_TOOL_NOT_OFFERED, doc
    kinds = [s["kind"] for s in doc["spans"][0]["sub_verdicts"]]
    assert f"replay:{TOOL_NOT_OFFERED}" in kinds, doc


# =====================================================================================
# AC-6 — `phase0 report` counts the new bucket as its OWN line
# =====================================================================================


def _metrics() -> Metrics:
    return Metrics(
        tp=0, fp=0, fn=0, tn=0,
        precision=None, recall=None, coverage=None,
        unverified=0, pending=0, unverifiable=0, total=0,
    )


def test_phase0_report_counts_the_new_bucket_on_its_own_line() -> None:
    """AC-6. G4's number, readable off the report: a line of its own, not folded in.

    A fixture batch carrying BOTH the new bucket and the generic one: if the two shared a
    bucket the mint could never answer *"how many turns could not be verified because the
    boundary lacked the tool"*, which is the whole reason this aspect exists.
    """
    ledger = RunLedger(
        instances=[
            InstanceRecord(
                trace_id="trace-a",
                disposition=Disposition.VERIFIED_CLEAN,
                turn_status_counts={"UNVERIFIED": 5},
                flagged_turns=[], flagged_addable=[], flagged_unaddable=[],
                unverified_causes={
                    REPLAYED_TOOL_NOT_OFFERED: 3,
                    REPLAYED_RESULT_UNVERIFIED: 2,
                },
                error=None,
                not_covered_turns={},
            )
        ]
    )

    out = render_report(ledger, _metrics())

    assert "UNVERIFIED by cause:" in out, out
    assert f"{REPLAYED_TOOL_NOT_OFFERED}" in out, out
    assert REPLAYED_RESULT_UNVERIFIED in out, out
    lines = [ln for ln in out.splitlines() if REPLAYED_TOOL_NOT_OFFERED in ln]
    assert len(lines) == 1 and "3" in lines[0], (
        "the boundary bucket must be its own counted line", lines,
    )


# =====================================================================================
# AC-8 — the pinned contracts that must NOT move
# =====================================================================================


def test_the_manifest_not_found_path_keeps_the_generic_replay_kind(tmp_path) -> None:
    """AC-8. A turn that never replayed keeps `kind == "replay"` and its own cause.

    The new kinds belong to the REPLAYED path only. The non-replayed branch
    (`_unverifiable_verdict`) is a different fact and its `--json` shape is pinned by
    `tests/test_verify_json.py` and `tests/fixtures/verify_json_snapshot.json`.
    """
    from belay.replay.engine import NOT_VERIFIABLE, TurnReplay
    from belay.verify import turn as turn_module

    records = _run_process_records(tmp_path, "manifestless")
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            turn_module,
            "replay_turn",
            lambda *a, **k: TurnReplay(
                turn_index=0, status=NOT_VERIFIABLE, reinvoked=False,
                result_equivalence=None, recorded_reply=None, replayed_reply=None,
                delta=[], cause="no persisted snapshot manifest for handle abc",
            ),
        )
        verdict = verify_turn(
            records, 0, server_command=shell_server_cmd(), manifest_dir="/nonexistent",
        )
    finally:
        monkey.undo()

    assert [s.kind for s in verdict.sub_verdicts] == ["replay"], verdict
    assert verdict.cause == "manifest not found", verdict
