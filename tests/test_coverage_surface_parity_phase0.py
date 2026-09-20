"""Coverage-surface parity for the Phase-0 and interop-export surfaces.

`tests/test_coverage_rendering.py` states the rule this file extends: **no surface may
render a turn's status without also rendering its coverage line** — enforced by a test per
surface, not by review (`verdict-coverage-status/prd.md:203-209`).

Until aspect 1 (`absent-contract-coverage`) a `NOT_COVERED` dimension was RARE: it appeared
only where a tool had actually declared `openWorldHint`. Aspect 1 makes one ROUTINE —
`effect`, emitted on every turn against a server that declared no `readOnlyHint`, which is
every turn against the pinned reference filesystem server. Surfaces that disclosed nothing
were latent; they are now live false-PASS-by-omission paths.

Four things are pinned here, one section each:

- **AC-4** `belay phase0 combine` (`report.render_population_report`) rendered both
  denominators and never called `_coverage_section` at all.
- **AC-5** `_COVERAGE_PROSE` held exactly ONE entry (`effect:network`), so the routine
  `effect` kind read as the anonymous *"outside what Belay observes"* fallback — and no
  test forced an entry, so the NEXT kind would read anonymously too. The guard here is
  STRUCTURAL: it parses `src/belay/` and finds every `kind` a `NOT_COVERED` `Verdict` is
  constructed with, rather than restating a list a new kind can be added beside.
- **AC-6** the boundary is a PERSISTED LEDGER FIELD, not a runtime computation, because
  `belay phase0 report` is a pure re-render. Driven through a FRESH PARSE FROM DISK via the
  real CLI, matching `test_coverage_rendering.py:285`, never an in-memory `RunLedger`.
- **Phase 5** `belay interop export` wrote `belay.verdict.coverage` only when a dimension
  was uncovered. Now ALWAYS written for a verdict-bearing span — present-but-empty rather
  than absent, matching `verify --json`'s `coverage_record`, which is *"ALWAYS present,
  empty when no NOT_COVERED dimension appeared"* (`verify/json.py:196`).

Deterministic and offline: synthetic ledgers, a stub `verify=` seam, no replay, no
Seatbelt, no clock.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.metrics import Metrics
from belay.interop.attach import correlate_and_attach
from belay.interop.export import VERDICT_ATTRIBUTE_PREFIX, build_enriched_document
from belay.interop.otlp import parse_otlp
from belay.phase0.ledger import (
    Disposition,
    InstanceRecord,
    RunLedger,
    from_json,
    to_json,
)
from belay.phase0.population import LabeledLedger, Population
from belay.phase0.report import _COVERAGE_PROSE, render_population_report, render_report
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

from test_interop_export import (  # noqa: E402  — house pattern: reuse the export harness
    SPAN_ID,
    TRACE_CONTEXT_META,
    TRACE_ID,
    UNUSED_MANIFEST_DIR,
    UNUSED_SERVER,
    _doc,
    _otlp_span,
    _span,
    trace_of,
)

#: The kind aspect 1 made routine: the server declared no `readOnlyHint`, so there was
#: never a contract for the observed filesystem effect to be weighed against.
#: `verify/effect.py:103` (`_KIND`).
EFFECT_KIND = "effect"

#: The kind that already had prose — the only one that existed before aspect 1.
#: `verify/effect.py:108` (`_KIND_NETWORK`).
NETWORK_KIND = "effect:network"

#: The anonymous fallback an unlisted kind renders as (`phase0/report.py:198`). A kind
#: reaching a reader through this string is the defect AC-5 exists to close.
ANONYMOUS_FALLBACK = "outside what Belay observes"

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "belay"


# --- helpers ---------------------------------------------------------------------------


def _instance(
    trace_id: str,
    disposition: Disposition = Disposition.VERIFIED_CLEAN,
    *,
    turn_status_counts: dict | None = None,
    not_covered_turns: dict | None = None,
    unverified_causes: dict | None = None,
) -> InstanceRecord:
    """One instance record. Mirrors `test_coverage_rendering.py:220`'s helper."""
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=turn_status_counts or {"PASS": 1},
        flagged_turns=[],
        flagged_addable=[],
        flagged_unaddable=[],
        unverified_causes=unverified_causes or {},
        error=None,
        not_covered_turns=not_covered_turns or {},
    )


def _ledger(*instances: InstanceRecord) -> RunLedger:
    return RunLedger(instances=list(instances))


def _metrics() -> Metrics:
    return Metrics(
        tp=0, fp=0, fn=0, tn=0,
        precision=None, recall=None, coverage=None,
        unverified=0, pending=0, unverifiable=0, total=0,
    )


def _write_ledger(path: Path, ledger: RunLedger) -> Path:
    path.write_text(json.dumps(to_json(ledger), indent=2), encoding="utf-8")
    return path


def _coverage_block(report: str) -> str:
    """The coverage section of a rendered report, as its own text.

    Scoped rather than searched whole-report, matching
    `test_phase0_population.py:273`'s discipline: a whole-report substring check is a
    proxy for a section and goes green the moment some other section happens to mention
    the word.
    """
    assert "coverage (NOT_COVERED" in report, (
        "no coverage section in the report at all:\n" + report
    )
    return report.split("coverage (NOT_COVERED", 1)[1].split("\n\n", 1)[0]


# --- AC-4: `belay phase0 combine` discloses the coverage boundary ----------------------


def test_ac4_phase0_combine_discloses_the_effect_coverage_boundary() -> None:
    """RED: `render_population_report` rendered both denominators and no coverage line.

    The merge surface is the one where a boundary most easily disappears — it is the
    surface a published number is read off, and `_coverage_section` was never called on
    this path even though `Capture.record.not_covered_turns` carries the data
    (`population.py:109`). A PASS-bearing population report with no stated limits is the
    exact false-PASS-by-omission this status was introduced to prevent.
    """
    population = Population.from_labeled([
        LabeledLedger(
            "s1",
            _ledger(
                _instance(
                    "trace-a",
                    turn_status_counts={"PASS": 3},
                    not_covered_turns={EFFECT_KIND: 3},
                )
            ),
        )
    ])

    report = render_population_report(population)
    block = _coverage_block(report)

    assert "NOT_COVERED" in block, block
    assert EFFECT_KIND in block, "the section must NAME the dimension"
    assert "3/3" in block, "the boundary must be counted against the population's turns"
    assert "never a PASS" in block, (
        "the section must say the boundary is never a PASS — the honesty clause is the "
        "half that makes the disclosure worth rendering"
    )


def test_ac4_phase0_combine_states_an_empty_tally_in_words() -> None:
    """Absent is never zero: a population recording no boundary SAYS so.

    A ledger written before the field existed is byte-indistinguishable from one that
    recorded no boundary, so an omitted section would read as "everything was inside
    coverage" — a claim the data cannot support. Same discipline as
    `_coverage_section`'s empty branch on the single-ledger surface.
    """
    population = Population.from_labeled([
        LabeledLedger("s1", _ledger(_instance("trace-a")))
    ])

    block = _coverage_block(render_population_report(population))

    assert "no NOT_COVERED dimension recorded" in block, block
    assert "NOT a claim that" in block, (
        "the empty tally must carry its disclaimer, or it reads as a clean bill of health"
    )


def test_ac4_phase0_combine_sums_a_kind_across_captures_without_dedup() -> None:
    """Two captures of one instance BOTH contribute — `total_turns()`'s discipline.

    A capture that ran really was verified, and its turns really were outside coverage on
    that dimension. Deduping to the instance here would under-count the boundary against a
    turn denominator that is itself per-capture, printing a fraction of two different
    populations.
    """
    population = Population.from_labeled([
        LabeledLedger(
            "s1",
            _ledger(
                _instance(
                    "trace-a",
                    turn_status_counts={"PASS": 2},
                    not_covered_turns={EFFECT_KIND: 2},
                )
            ),
        ),
        LabeledLedger(
            "s2",
            _ledger(
                _instance(
                    "trace-a",
                    turn_status_counts={"PASS": 2},
                    not_covered_turns={EFFECT_KIND: 2},
                )
            ),
        ),
    ])

    block = _coverage_block(render_population_report(population))

    assert "4/4" in block, block


def test_ac4_phase0_combine_discloses_a_boundary_carried_only_by_a_control() -> None:
    """The coverage section spans the WHOLE population — controls INCLUDED.

    Every other number in this report is computed over `population.measured()`, because a
    control answers "did the instrument work?" rather than "did the agent violate?". A
    coverage boundary is not a rate about agents at all: it is a limit on what the
    INSTRUMENT observed, and the controls ran through the same instrument. Computing it
    over `measured()` would let a boundary that only a control recorded vanish from the
    one surface whose job is to state limits — so the section states its own denominator
    instead of borrowing the headline's.
    """
    population = Population.from_labeled([
        LabeledLedger(
            "s1",
            _ledger(
                _instance("trace-real", turn_status_counts={"PASS": 1}),
                _instance(
                    "trace-control__read-only",
                    turn_status_counts={"PASS": 2},
                    not_covered_turns={EFFECT_KIND: 2},
                ),
            ),
        )
    ])

    block = _coverage_block(render_population_report(population))

    assert EFFECT_KIND in block, block
    assert "2/3" in block, (
        "the denominator must be every turn in the population, controls included — "
        f"got:\n{block}"
    )
    assert "control" in block.lower(), (
        "the section must say controls are counted here, or the denominator silently "
        "disagrees with every other one on the page"
    )


def test_ac4_phase0_combine_coverage_never_reads_as_pass() -> None:
    """The negative form: the coverage section never spells PASS for the boundary.

    `NOT_COVERED` is sub-verdict-only and `reduce` drops it, so a turn carrying one reduces
    to PASS on the strength of everything else. That PASS is honest only while the section
    beside it refuses to claim the dropped dimension passed.
    """
    population = Population.from_labeled([
        LabeledLedger(
            "s1",
            _ledger(
                _instance(
                    "trace-a",
                    turn_status_counts={"PASS": 3},
                    not_covered_turns={EFFECT_KIND: 3},
                )
            ),
        )
    ])

    block = _coverage_block(render_population_report(population))

    effect_line = next(line for line in block.splitlines() if EFFECT_KIND in line)
    assert "PASS" not in effect_line.replace("never a PASS", ""), effect_line


# --- AC-5: the prose is not anonymous -------------------------------------------------


def test_ac5_the_effect_kind_renders_named_prose_not_the_anonymous_fallback() -> None:
    """RED: `_COVERAGE_PROSE` had one entry, so the ROUTINE kind read anonymously.

    *"outside what Belay observes"* is true of both kinds and distinguishes neither. The
    `effect` boundary has a specific, operator-actionable cause — the server declared no
    `readOnlyHint` — and a reader who cannot see that cause cannot act on it (declare an
    invariant, or pick a server that annotates).
    """
    ledger = _ledger(
        _instance(
            "trace-a",
            turn_status_counts={"PASS": 5},
            not_covered_turns={EFFECT_KIND: 5},
        )
    )

    block = _coverage_block(render_report(ledger, _metrics()))

    effect_line = next(line for line in block.splitlines() if EFFECT_KIND in line)
    assert ANONYMOUS_FALLBACK not in effect_line, (
        "the routine kind must not reach a reader through the anonymous fallback: "
        + effect_line
    )
    assert "readOnlyHint" in effect_line, (
        "the prose must name the annotation whose absence created the boundary: "
        + effect_line
    )


def test_ac5_the_network_kind_keeps_its_own_prose() -> None:
    """Additive: the entry that already existed is byte-unchanged.

    Two kinds now share this table, and the older one's sentence is quoted verbatim in
    `test_coverage_rendering.py:313`. A new entry must not generalise the old one into
    something that fits both.
    """
    ledger = _ledger(
        _instance(
            "trace-a",
            turn_status_counts={"PASS": 4},
            not_covered_turns={NETWORK_KIND: 4},
        )
    )

    block = _coverage_block(render_report(ledger, _metrics()))

    assert "network egress is NOT observed" in block, block
    assert ANONYMOUS_FALLBACK not in block, block


#: The package where a `NOT_COVERED` `Verdict` is DECLARED — i.e. where a new coverage
#: dimension can enter the vocabulary. Everywhere else (`cli.py`'s corpus rehydration,
#: `interop/`) a `Verdict` is REBUILT from a recorded sub-verdict dict, so its `kind` is
#: whatever some producer in here already wrote; a pass-through cannot invent a kind.
PRODUCING_PACKAGE = "verify"


def _not_covered_kinds_in_source() -> tuple[dict[str, list[str]], list[str]]:
    """Every `kind` a `NOT_COVERED` `Verdict` is constructed with under `src/belay/`.

    Parses the tree as an AST rather than grepping it, for the reason
    `tests/test_release_workflow.py` parses the workflow as YAML: a regex is satisfied by
    text that happens to co-occur, and the defect worth catching is a kind added in a
    shape a pattern did not anticipate. Module-level string constants are resolved
    (`_KIND = "effect"`), because that is how `effect.py` spells every one of them.

    Returns `({kind: [file:line, ...]}, [unresolved site, ...])`. A `kind` that resolves
    to no string literal is a PASS-THROUGH — `cli.py`'s corpus rehydration reads
    `sub.get("kind")` off disk — and is returned separately rather than failed on: it
    re-creates a kind a producer already declared and cannot introduce a new one. The
    guard below fails on an unresolved site only inside `PRODUCING_PACKAGE`, which is the
    named residual: a producer that computed its `kind` at runtime would escape a static
    check, and no static check can close that.
    """
    found: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        constants: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = node.value.value

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "Verdict":
                continue

            status = _argument(node, index=2, keyword="status")
            if not (
                isinstance(status, ast.Attribute) and status.attr == Status.NOT_COVERED.name
            ):
                continue

            kind = _argument(node, index=1, keyword="kind")
            site = f"{path.relative_to(SRC_ROOT.parents[1])}:{node.lineno}"
            if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
                found.setdefault(kind.value, []).append(site)
            elif isinstance(kind, ast.Name) and kind.id in constants:
                found.setdefault(constants[kind.id], []).append(site)
            else:
                unresolved.append(site)
    return found, unresolved


def _argument(call: ast.Call, *, index: int, keyword: str):
    """One argument of a call, positionally or by keyword — `None` when absent."""
    if len(call.args) > index:
        return call.args[index]
    for kw in call.keywords:
        if kw.arg == keyword:
            return kw.value
    return None


def test_ac5_the_prose_guard_can_see_the_kinds_it_guards() -> None:
    """The guard's own precondition: a scanner that finds nothing is vacuously green.

    Asserted against the two kinds that exist today, so a refactor that moves or renames
    the construction site breaks THIS test — which names the scanner — rather than
    silently disarming the guard below.
    """
    kinds, _ = _not_covered_kinds_in_source()

    assert NETWORK_KIND in kinds, kinds
    assert EFFECT_KIND in kinds, kinds
    assert all(
        f"/{PRODUCING_PACKAGE}/" in site for site in kinds[NETWORK_KIND] + kinds[EFFECT_KIND]
    ), kinds


def test_ac5_every_not_covered_kind_the_engine_emits_has_coverage_prose() -> None:
    """THE DURABLE HALF: the NEXT kind cannot read anonymously either.

    `_COVERAGE_PROSE` deliberately keeps its fallback — a kind with no entry is still
    rendered under its own name, because dropping a boundary for want of a phrase would be
    strictly worse. But a fallback with nothing forcing entries is how the routine kind
    shipped anonymous in the first place. This is the forcing function.
    """
    kinds, unresolved = _not_covered_kinds_in_source()

    declared_unresolved = [site for site in unresolved if f"/{PRODUCING_PACKAGE}/" in site]
    assert not declared_unresolved, (
        "a NOT_COVERED Verdict is DECLARED with a kind this guard cannot resolve to a "
        "string, so nothing can check its prose: "
        f"{declared_unresolved}"
    )
    missing = {kind: sites for kind, sites in kinds.items() if kind not in _COVERAGE_PROSE}
    assert not missing, (
        "every NOT_COVERED kind the engine can emit needs a _COVERAGE_PROSE entry in "
        "src/belay/phase0/report.py, or it reaches a reader as the anonymous "
        f"{ANONYMOUS_FALLBACK!r}: {missing}"
    )


# --- AC-6: round-trip persistence, through a FRESH PARSE FROM DISK --------------------


def test_ac6_effect_coverage_survives_a_ledger_round_trip(tmp_path: Path, capsys) -> None:
    """THE LOAD-BEARING ONE for the new kind: the line comes off DISK.

    `belay phase0 report` replays nothing and recomputes nothing, so a coverage statement
    that existed only at verification time could never reach this surface. The ledger is
    written to a file and the REAL command parses it — no in-memory `RunLedger` is handed
    across — exactly as `test_coverage_rendering.py:285` does for the network kind.
    """
    ledger_path = _write_ledger(
        tmp_path / "ledger.json",
        _ledger(
            _instance(
                "trace-a",
                turn_status_counts={"PASS": 7},
                not_covered_turns={EFFECT_KIND: 7},
            )
        ),
    )

    rc = cli.main([
        "phase0", "report", str(ledger_path), "--corpus-dir", str(tmp_path / "corpus"),
    ])
    out = capsys.readouterr().out

    assert rc == 0, out
    block = _coverage_block(out)
    assert EFFECT_KIND in block, block
    assert "7/7" in block, block
    assert "readOnlyHint" in block, block


def test_ac6_two_coverage_kinds_survive_one_ledger_unchanged() -> None:
    """`not_covered_turns` already admits a SECOND kind — NO schema change.

    It is a `dict[str, int]` keyed by sub-verdict `kind` (`ledger.py:161`), and aspect 1
    observed a live ledger reading `{"effect": 1}`. This pins that: both kinds survive
    `to_json` -> JSON text -> `from_json` with their counts intact and no key coalesced.
    """
    ledger = _ledger(
        _instance(
            "trace-a",
            turn_status_counts={"PASS": 6},
            not_covered_turns={EFFECT_KIND: 6, NETWORK_KIND: 2},
        )
    )

    reloaded = from_json(json.loads(json.dumps(to_json(ledger))))

    assert reloaded.instances[0].not_covered_turns == {EFFECT_KIND: 6, NETWORK_KIND: 2}
    assert reloaded.not_covered_by_kind() == {EFFECT_KIND: 6, NETWORK_KIND: 2}

    block = _coverage_block(render_report(reloaded, _metrics()))
    assert f"{EFFECT_KIND}: NOT observed for 6/6" in block, block
    assert f"{NETWORK_KIND}: NOT observed for 2/6" in block, block


def test_ac6_effect_coverage_survives_a_fresh_parse_into_combine(
    tmp_path: Path, capsys
) -> None:
    """The merge surface, off disk too — `phase0 combine` is a re-render as well.

    AC-4 proves the renderer discloses; this proves the disclosure is PERSISTED, on the
    surface a published merged number is read off.
    """
    first = _write_ledger(
        tmp_path / "s1.json",
        _ledger(
            _instance(
                "trace-a",
                turn_status_counts={"PASS": 2},
                not_covered_turns={EFFECT_KIND: 2},
            )
        ),
    )
    second = _write_ledger(
        tmp_path / "s2.json",
        _ledger(
            _instance(
                "trace-b",
                turn_status_counts={"PASS": 2},
                not_covered_turns={EFFECT_KIND: 1},
            )
        ),
    )

    rc = cli.main(["phase0", "combine", f"s1={first}", f"s2={second}"])
    out = capsys.readouterr().out

    assert rc == 0, out
    block = _coverage_block(out)
    assert EFFECT_KIND in block, block
    assert "3/4" in block, block


# --- Phase 5: `belay interop export` always writes the coverage attribute -------------


def _export_one(tmp_path: Path, verdict: TurnVerdict, *, matched: bool = True):
    """One span exported through the `verify=` stub seam.

    `matched=False` gives the span ids a trace never recorded, so correlation finds no
    turn and `verify` is never reached — the only honest way to reach the no-verdict
    branch (handing `verify` a `None` is not a state `correlate_and_attach` produces).
    """
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    trace_id, span_id = (TRACE_ID, SPAN_ID) if matched else ("f" * 32, "f" * 16)
    spans = [_span(trace_id, span_id)]
    doc = _doc([_otlp_span(trace_id, span_id)])
    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=lambda *a, **k: verdict,
    )
    exported = build_enriched_document(doc, spans, results)
    [span] = parse_otlp(json.dumps(exported))
    return span


def _clean_verdict() -> TurnVerdict:
    return TurnVerdict(
        turn_index=0, tool_name="echo", status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "result", Status.PASS, observed="ok", expected="ok",
                    message="the reply reproduced"),
        ],
        cause=None,
    )


def test_phase5_export_always_writes_the_coverage_attribute(tmp_path: Path) -> None:
    """RED: a verdict with no uncovered dimension exported NO `coverage` key at all.

    The shipped rule elsewhere is that the coverage key is PRESENT-BUT-EMPTY, never absent
    — `verify/json.coverage_record` is *"ALWAYS present, empty when no NOT_COVERED
    dimension appeared on these turns"*. On this surface the conditional made two very
    different facts arrive identically at a collector: *"Belay checked every dimension"*
    and *"this exporter predates the coverage attribute"*. A dashboard cannot tell them
    apart, and one of them is a clean bill of health nobody issued.
    """
    span = _export_one(tmp_path, _clean_verdict())

    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "PASS"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.coverage"] == "[]", (
        "an empty coverage array is a statement; an absent key is indistinguishable from "
        "an older exporter"
    )


def test_phase5_export_coverage_attribute_still_carries_its_kinds(tmp_path: Path) -> None:
    """Additive: a span WITH an uncovered dimension is byte-unchanged.

    The routine `effect` kind, on this surface, alongside the status.
    """
    verdict = TurnVerdict(
        turn_index=0, tool_name="write_file", status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "result", Status.PASS, observed="ok", expected="ok",
                    message="the reply reproduced"),
            Verdict("A2", EFFECT_KIND, Status.NOT_COVERED, observed=None, expected=None,
                    message="the server declared no readOnlyHint for it"),
        ],
        cause=None,
    )

    span = _export_one(tmp_path, verdict)

    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.coverage"] == '["effect"]'
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "PASS"


def test_phase5_export_an_uncovered_span_makes_no_coverage_claim(tmp_path: Path) -> None:
    """A span with NO verdict makes no coverage statement — and that is deliberate.

    "Always present" is scoped to a verdict-bearing span. An unmatched or unreplayed span
    exports `UNVERIFIED` with its named cause and no `axis`, `turn_index` or
    `sub_verdicts` either: nothing was verified, so there are no dimensions to report on.
    Writing `[]` there would assert "every dimension was inside coverage" about a turn
    Belay never looked at — the false-PASS shape, one status over.
    """
    span = _export_one(tmp_path, _clean_verdict(), matched=False)

    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "UNVERIFIED"
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.coverage" not in span.attributes


@pytest.mark.parametrize("kind", sorted(_COVERAGE_PROSE))
def test_every_prose_entry_names_its_own_dimension(kind: str) -> None:
    """No entry is the anonymous fallback in disguise, and none is empty.

    A table whose entries restate the fallback satisfies the guard above and informs
    nobody — the failure mode of forcing an entry rather than a useful one.
    """
    prose = _COVERAGE_PROSE[kind]

    assert prose.strip(), kind
    assert ANONYMOUS_FALLBACK not in prose, (kind, prose)
    assert "NOT_COVERED" in prose or "NOT observed" in prose or "not observed" in prose, (
        kind,
        prose,
    )
