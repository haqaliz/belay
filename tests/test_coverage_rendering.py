"""The rendering rule: no surface shows a status without showing what it did not cover.

`NOT_COVERED` is excluded from the reduction, which is the whole point — a dimension Belay
structurally cannot observe must not sink a turn it verified perfectly. But exclusion has a
price, and this file is the payment: a status that moves nothing is a status a reader can
scroll past, and a turn against a server that declared `openWorldHint: false` now prints
**PASS** while the promise it made went unchecked. If that PASS is rendered without its
coverage boundary, this project's central claim — "UNVERIFIED is never rendered as PASS" —
becomes a technicality, and Belay is LESS honest than before the status existed.

So the rule is: **every surface that renders a turn's status also renders its coverage
line**, and the rule is enforced here, one test per surface, not by review:

- `belay verify`'s aggregate block (`cli._emit_aggregate`).
- `belay verify`'s always-on coverage banner (`cli._VERIFY_COVERAGE`, in `--help` too).
- `belay phase0 report` — the hard one. That command is a PURE RE-RENDER of a stored
  ledger: it replays nothing and computes nothing. A coverage statement therefore has to
  be a PERSISTED FIELD or it cannot exist on that surface at all. The load-bearing test
  below writes a ledger, re-reads it through a FRESH parse, renders, and asserts the
  coverage line — proving persistence rather than runtime computation.
- The `INSTRUMENT SUSPECT` branch, which suppresses the report's headline. The coverage
  line must survive it: a rate can be withheld, the limits of what was looked at cannot.

Every test also asserts the negative form of criterion 2: on each surface, the string
`PASS` never stands in for `NOT_COVERED`.

Deterministic, offline, no replay, no Seatbelt: synthetic verdicts and fake verifiers only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.metrics import Metrics
from belay.phase0.ledger import (
    Disposition,
    InstanceRecord,
    RunLedger,
    from_json,
    to_json,
)
from belay.phase0.report import render_report
from belay.phase0.runner import run_batch
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

#: The kind the network dimension emits — the only NOT_COVERED sub-verdict that exists
#: today, and the one the reference `@modelcontextprotocol/server-filesystem` triggers on
#: every single turn.
NETWORK_KIND = "effect:network"

NETWORK_MESSAGE = (
    "openWorldHint conformance NOT_COVERED: tool 'read_text_file' DECLARED "
    "openWorldHint: false (it does not reach the open world) — a promise this run did "
    "not check. Belay observes no outbound bytes — never PASS, never a fabricated FAIL"
)


def _sub(status: Status, *, kind: str = "replay", message: str = "canned") -> Verdict:
    return Verdict("A2", kind, status, None, None, message)


def _turn(
    n: int,
    status: Status,
    *,
    subs: list[Verdict] | None = None,
    cause: str | None = None,
) -> TurnVerdict:
    return TurnVerdict(
        turn_index=n,
        tool_name="read_text_file",
        status=status,
        sub_verdicts=subs if subs is not None else [_sub(status)],
        cause=cause,
    )


def _covered_turn(n: int) -> TurnVerdict:
    """The shape this whole unit is about: everything Belay checks PASSed, and the tool's
    network promise was never inside coverage. Reduces to PASS."""
    return _turn(
        n,
        Status.PASS,
        subs=[
            _sub(Status.PASS, kind="replay"),
            _sub(Status.PASS, kind="effect"),
            _sub(Status.NOT_COVERED, kind=NETWORK_KIND, message=NETWORK_MESSAGE),
        ],
    )


# --------------------------------------------------------- surface 1: verify aggregate


def test_verify_aggregate_renders_coverage_with_status(capsys) -> None:
    """`belay verify`'s aggregate cannot print a PASS tally without the coverage block.

    Three PASSing turns, each carrying a NOT_COVERED network sub-verdict. The block must
    name the dimension, count it against the turns rendered, and carry the message that
    still distinguishes "this tool PROMISED" from "nothing was promised" — the record the
    reduction stopped keeping.
    """
    verdicts = [_covered_turn(n) for n in range(3)]

    cli._emit_aggregate(verdicts, Status)
    out = capsys.readouterr().out

    assert "PASS                  3" in out, out
    assert "coverage" in out.lower(), "the aggregate must render the coverage boundary"
    assert "NOT_COVERED" in out, out
    assert NETWORK_KIND in out, "the coverage block must name the dimension"
    assert "3/3" in out, "the boundary must be counted against the turns rendered"
    assert "DECLARED" in out, "the declared-promise distinction must survive on this surface"


def test_verify_aggregate_is_status_complete(capsys) -> None:
    """Every scored status prints, and no enum member is tallied then silently dropped.

    `counts` is built from `Status` itself, so an unlisted member would be counted and
    never shown. The four scored lines are asserted present; NOT_COVERED is asserted to
    appear as coverage, NOT as a fifth turn-status line reading zero.
    """
    verdicts = [
        _covered_turn(0),
        _turn(1, Status.FAIL, subs=[_sub(Status.FAIL)]),
        _turn(2, Status.WARN, subs=[_sub(Status.WARN)]),
        _turn(3, Status.UNVERIFIED, subs=[_sub(Status.UNVERIFIED)], cause="no-pre-state"),
    ]

    cli._emit_aggregate(verdicts, Status)
    out = capsys.readouterr().out

    for name in ("PASS", "WARN", "FAIL", "UNVERIFIED"):
        assert f"  {name:<22}" in out, f"aggregate dropped the {name} line: {out}"
    assert "NOT a reduced status" not in out, (
        "NOT_COVERED must not be tallied as a turn status — reduce() filters it out"
    )


def test_verify_aggregate_never_renders_not_covered_as_pass(capsys) -> None:
    """Criterion 2 at the rendering level: the aggregate never substitutes PASS.

    A turn whose ONLY sub-verdict is NOT_COVERED reduces (empty-after-filter) to
    UNVERIFIED, and must be listed as UNVERIFIED with an explanation that names coverage
    — never counted as a PASS, and never described by the bare word "unverified".
    """
    verdict = _turn(
        0,
        Status.UNVERIFIED,
        subs=[_sub(Status.NOT_COVERED, kind=NETWORK_KIND, message=NETWORK_MESSAGE)],
    )

    cli._emit_aggregate([verdict], Status)
    out = capsys.readouterr().out

    assert "PASS                  0" in out, out
    assert "UNVERIFIED            1" in out, out
    assert "inside Belay's coverage" in out, out
    assert NETWORK_KIND in out, out


def test_first_unverified_message_names_coverage_not_the_bare_word() -> None:
    """The detail list's fallback: a coverage-only turn is explained, not labelled.

    `_first_unverified_message` used to return the literal string "unverified" for a turn
    whose only sub-verdict was NOT_COVERED — a status word restated as its own explanation.
    """
    verdict = _turn(
        0,
        Status.UNVERIFIED,
        subs=[_sub(Status.NOT_COVERED, kind=NETWORK_KIND, message=NETWORK_MESSAGE)],
    )

    message = cli._first_unverified_message(verdict, Status)

    assert message != "unverified"
    assert "NOT_COVERED" in message
    assert NETWORK_KIND in message
    assert "PASS" not in message.replace("never a PASS", "")


# ------------------------------------------------------------ surface 2: the banner


def test_verify_banner_names_the_coverage_boundary(capsys) -> None:
    """The always-on banner says egress is NOT_COVERED, and says what that costs.

    It must not weaken: it still names `openWorldHint` and `egress`, still refuses a
    network PASS, and now must ALSO warn that because NOT_COVERED is excluded from the
    reduction a turn declaring `openWorldHint: false` can print PASS — which is the exact
    misreading this unit created and must pre-empt.
    """
    with pytest.raises(SystemExit):
        cli.main(["verify", "--help"])
    # Whitespace-collapsed: the banner is hard-wrapped, so a phrase that must survive
    # intact can straddle a newline. The assertions are about the sentence, not the wrap.
    out = " ".join(capsys.readouterr().out.lower().split())

    assert "openworldhint" in out and "egress" in out, "must still name the dimension"
    assert "not_covered" in out, "the banner must use the status's real name"
    assert "never a network pass" in out, "must not weaken the never-a-PASS guarantee"
    assert "can reduce to pass" in out, (
        "the banner must warn that an openWorldHint: false turn can now print PASS"
    )
    assert "nothing about the network" in out, (
        "the banner must say what that PASS does NOT assert"
    )


# ----------------------------------------------------- surface 3: the ledger + report


def _instance(
    trace_id: str,
    disposition: Disposition,
    *,
    turn_status_counts: dict | None = None,
    not_covered_turns: dict | None = None,
    unverified_causes: dict | None = None,
    flagged_turns: list | None = None,
) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=turn_status_counts or {},
        flagged_turns=flagged_turns or [],
        flagged_addable=[],
        flagged_unaddable=[],
        unverified_causes=unverified_causes or {},
        error=None,
        not_covered_turns=not_covered_turns or {},
    )


def _metrics() -> Metrics:
    return Metrics(
        tp=0, fp=0, fn=0, tn=0,
        precision=None, recall=None, coverage=None,
        unverified=0, pending=0, unverifiable=0, total=0,
    )


def test_ledger_round_trips_the_coverage_field() -> None:
    """`not_covered_turns` survives `to_json` -> JSON text -> `from_json` unchanged."""
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a",
                Disposition.VERIFIED_CLEAN,
                turn_status_counts={"PASS": 12},
                not_covered_turns={NETWORK_KIND: 12},
            )
        ]
    )

    reloaded = from_json(json.loads(json.dumps(to_json(ledger))))

    assert reloaded == ledger
    assert reloaded.instances[0].not_covered_turns == {NETWORK_KIND: 12}
    assert reloaded.not_covered_by_kind() == {NETWORK_KIND: 12}


def test_ledger_without_the_coverage_field_still_loads() -> None:
    """A ledger written before coverage was recorded is not a corrupt ledger.

    Every other instance field is fail-closed; this one is optional-with-default on
    purpose. The report distinguishes the two cases in words, so the default is never
    read as "nothing was outside coverage".
    """
    raw = to_json(RunLedger(instances=[_instance("trace-a", Disposition.VERIFIED_CLEAN)]))
    del raw["instances"][0]["not_covered_turns"]

    reloaded = from_json(raw)

    assert reloaded.instances[0].not_covered_turns == {}


def test_phase0_report_shows_coverage_from_a_stored_ledger(tmp_path: Path, capsys) -> None:
    """THE LOAD-BEARING ONE: the coverage line comes off DISK, not off a live verdict.

    `belay phase0 report` replays nothing and recomputes nothing — it parses a ledger file
    and renders it. So this test writes the ledger to disk, invokes the real command (a
    fresh parse, no in-memory `RunLedger` handed across), and asserts the coverage line.
    If the field were a runtime computation rather than a persisted one, this is the test
    that would fail, and the surface where a PASS would print with no stated limits.
    """
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a",
                Disposition.VERIFIED_CLEAN,
                turn_status_counts={"PASS": 12},
                not_covered_turns={NETWORK_KIND: 12},
            )
        ]
    )
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(to_json(ledger), indent=2), encoding="utf-8")

    rc = cli.main([
        "phase0", "report", str(ledger_path), "--corpus-dir", str(tmp_path / "corpus"),
    ])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "coverage" in out.lower(), "phase0 report must render the coverage boundary"
    assert "NOT_COVERED" in out, out
    assert NETWORK_KIND in out, out
    assert "12/12" in out, "the boundary must be counted against the run's turns"
    assert "network egress is NOT observed" in out, out


def test_coverage_line_survives_instrument_suspect() -> None:
    """INSTRUMENT SUSPECT suppresses the headline; it must not suppress the coverage line.

    A rate can honestly be withheld. What Belay did not look at cannot: an all-suspect run
    is exactly where a reader most needs to know which dimensions were never in scope.
    """
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a",
                Disposition.NO_VERIFIABLE_TURNS,
                turn_status_counts={"UNVERIFIED": 4},
                not_covered_turns={NETWORK_KIND: 4},
                unverified_causes={"no-pre-state": 4},
            )
        ]
    )

    out = render_report(ledger, _metrics())

    assert "INSTRUMENT SUSPECT" in out, "precondition: this ledger must be suspect"
    assert "violation rate =" not in out, "precondition: the headline is suppressed"
    assert NETWORK_KIND in out, "the coverage line must survive the suppressed headline"
    assert "NOT_COVERED" in out, out
    assert "4/4" in out, out


def test_report_never_claims_full_coverage_when_nothing_was_recorded() -> None:
    """An empty tally says "not recorded", never "everything was covered".

    A pre-coverage ledger and a run with no boundary are indistinguishable on disk, so the
    report must not turn silence into a coverage claim — that would be the false PASS in
    prose form.
    """
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a", Disposition.VERIFIED_CLEAN, turn_status_counts={"PASS": 2}
            )
        ]
    )

    out = render_report(ledger, _metrics())

    assert "coverage" in out.lower()
    assert "no NOT_COVERED dimension recorded" in out
    assert "NOT a claim that everything was inside coverage" in out


# ------------------------------------------------------ surface 4: the runner's decision


def _call_frame(call_id: int) -> bytes:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": "read_text_file", "arguments": {}},
    }).encode()


def _reply_frame(call_id: int) -> bytes:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": call_id,
        "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
    }).encode()


def _write_trace(trace_dir: Path, n_calls: int) -> Path:
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            writer.observer("c2s")(_call_frame(10 + i), False)
            writer.observer("s2c")(_reply_frame(10 + i), False)
    finally:
        writer.close()
    return writer.path


def _run(trace_dir: Path, corpus_dir: Path, verdict_for) -> RunLedger:
    return run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["echo"],
        invariants=(),
        captured_at="2026-07-23T00:00:00+00:00",
        verifier=lambda records, n, **kwargs: verdict_for(n),
        ingester=lambda *a, **k: Path("unused"),
    )


def test_runner_decides_replayed_any_for_not_covered(tmp_path: Path) -> None:
    """A NOT_COVERED turn status counts as neither replayed nor UNVERIFIED — DECIDED.

    `reduce` makes this unreachable in production, and that is exactly why it must be
    written down: the old `else` branch swept every non-UNVERIFIED status into
    `replayed_any = True`, so a status meaning "outside what Belay checks" would have
    promoted the instance to VERIFIED_CLEAN and put it in the violation-rate denominator.
    A coverage boundary must never manufacture a verified instance.
    """
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    _write_trace(trace_dir, 2)

    ledger = _run(
        trace_dir,
        tmp_path / "corpus",
        lambda n: _turn(n, Status.NOT_COVERED, subs=[_sub(Status.NOT_COVERED, kind=NETWORK_KIND)]),
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.NO_VERIFIABLE_TURNS, (
        "a NOT_COVERED turn must not read as a verified clean instance"
    )
    assert ledger.violation_denominator() == 0


def test_runner_persists_the_coverage_boundary_per_instance(tmp_path: Path) -> None:
    """The runner writes `not_covered_turns` — the field the report later reads back.

    Counted per turn per kind: two PASSing turns each carrying one network sub-verdict is
    2, not 4, so `n/total_turns` reads as a fraction of turns.
    """
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    _write_trace(trace_dir, 2)

    ledger = _run(trace_dir, tmp_path / "corpus", _covered_turn)

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert inst.turn_status_counts == {"PASS": 2}
    assert inst.not_covered_turns == {NETWORK_KIND: 2}
