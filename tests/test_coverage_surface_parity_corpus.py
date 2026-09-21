"""The rendering rule, applied to the three CORPUS surfaces that never carried it.

`tests/test_coverage_rendering.py` states the rule and enforces it on `belay verify` and
`belay phase0 report`:

> **no surface may render a turn's status without also rendering its coverage line —
> enforced by a test per surface, not by review.**

Three corpus surfaces were outside that enforcement, each rendering a stored verdict's
status with no coverage disclosure and no test to notice:

- `belay corpus list` — a bare `verdict` column off `case.expected['reduced_status']`.
- `belay corpus run` — the aggregate. A NOT_COVERED sub-verdict IS compared, so it
  surfaces only when it DIVERGES; on a **MATCH** — the ordinary, green case — nothing is
  disclosed at all. Every test here therefore drives a MATCH: a divergence-based test
  would pass against the defect and prove nothing.
- `belay corpus score` — nothing. And its own `coverage` metric means *decided /
  adjudicable labels*, a different sense of the word entirely, so a reader who saw that
  line could reasonably believe the boundary had already been stated.

This was latent while a NOT_COVERED dimension was rare (only a declared
`openWorldHint`). Aspect 1 made an `effect` NOT_COVERED **routine** — every turn against
a server that declares no annotations carries one — so every banked case minted against
the reference filesystem server now carries one too, and a corpus surface that prints
`PASS` with nothing beside it is the false-PASS-by-omission shape this repo forbids.

Deterministic, offline, pure filesystem: cases are written with `write_case` and nothing
is replayed. `corpus run`'s classification is proven by its own file and the darwin
roundtrip; here `run_corpus` is monkeypatched so the RENDERING contract runs on every box.
"""

from __future__ import annotations

from pathlib import Path

from belay.corpus.case import Case, write_case

#: The kind aspect 1 made routine: `effect.py`'s plain `effect` dimension going
#: NOT_COVERED because the server declared no `readOnlyHint` for the tool at all.
EFFECT_KIND = "effect"

#: A real aspect-1 message, kept verbatim in shape. It is what distinguishes "the server
#: declared NOTHING about this tool" from "Belay tried and could not check" — the
#: distinction the reduction drops and the record therefore has to carry.
EFFECT_MESSAGE = (
    "effect-conformance NOT_COVERED: tool 'write_note' present in the tools/list "
    "snapshot Belay observed (seq 3), but the server declared no readOnlyHint for it "
    "— nothing was promised, so there is no contract for the observed effect to be "
    "weighed against. This states a limit on what Belay checked, NOT that the tool "
    "checked out: never a PASS, never a fabricated FAIL"
)


def _case(case_id: str = "cheat-run-0007", *, uncovered: bool = True) -> Case:
    """A banked case whose stored verdict reduces to PASS.

    With `uncovered` (the default) it carries the routine `effect` NOT_COVERED
    sub-verdict every case minted against an annotation-less server now carries. With
    `uncovered=False` it carries none, which is the additivity baseline: on that case
    every surface's output must be byte-unchanged.
    """
    sub_verdicts: list[dict] = [
        {"axis": "A2", "kind": "replay", "status": "PASS"},
        {"axis": "A1", "kind": "invariant", "status": "PASS"},
    ]
    if uncovered:
        sub_verdicts.append(
            {
                "axis": "A2",
                "kind": EFFECT_KIND,
                "status": "NOT_COVERED",
                "message": EFFECT_MESSAGE,
            }
        )
    return Case(
        id=case_id,
        target_turn_index=3,
        expected={"reduced_status": "PASS", "sub_verdicts": sub_verdicts},
        human_label="pending",
        invariants=[{"scope": "tests/", "rule": "no-assertion-weakening"}],
        server_command=["python", "editor_server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-09-21T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


# ------------------------------------------------------- AC-1: `belay corpus list`


def test_corpus_list_discloses_the_coverage_boundary(tmp_path: Path, capsys) -> None:
    """`corpus list` cannot print a case's verdict column with nothing beside it.

    The row says `PASS`. What that PASS does not cover is stored in the very same
    `expected` the column is read from, so the surface HAS the fact and simply drops it
    — a reader scanning the listing learns the case is clean and never learns on which
    dimensions it was never checked.
    """
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    rc = cli.main(["corpus", "list", str(corpus)])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "PASS" in out, out
    assert "NOT_COVERED" in out, (
        "corpus list renders a verdict column with no coverage boundary beside it"
    )
    assert EFFECT_KIND in out, "the coverage disclosure must name the dimension"
    assert "declared no readOnlyHint" in out, (
        "the message must survive — it is what separates 'the server promised nothing' "
        "from 'Belay tried and could not check'"
    )


# -------------------------------------------- AC-2: `belay corpus run` aggregate


def test_corpus_run_discloses_the_coverage_boundary_on_a_match(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A MATCH is where the disclosure is missing, so a MATCH is what this drives.

    `corpus/run.py` DOES compare the NOT_COVERED sub-verdict, so a divergence names the
    kind in its own REGRESSION block — which is precisely why a divergence-based test
    would pass today and prove nothing. On a MATCH the aggregate prints `MATCH 1` and
    stops: the green, ordinary run discloses nothing about the dimensions neither side
    of the comparison ever checked.

    `run_corpus` is monkeypatched (the house pattern in `tests/test_corpus_run.py`) so
    this pins RENDERING on every box; the case itself is real and on disk, because the
    disclosure must come from the banked verdicts, not from a stubbed outcome.
    """
    from belay import cli
    from belay.corpus.run import MATCH, CaseResult, CorpusRun

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir, *, disable_claim_axis=False: CorpusRun(
            results=[CaseResult(case_id=case.id, outcome=MATCH)]
        ),
    )

    rc = cli.main(["corpus", "run", str(corpus)])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "MATCH" in out, out
    assert "REGRESSION            0" in out, "this must be a MATCH-only run, not a divergence"
    assert "NOT_COVERED" in out, (
        "corpus run's aggregate reports a MATCH with no coverage boundary — the kind "
        "surfaces only when it DIVERGES, so a green run discloses nothing"
    )
    assert EFFECT_KIND in out, "the coverage disclosure must name the dimension"
    assert "declared no readOnlyHint" in out, "the message must survive on this surface too"


# ------------------------------------------------------ AC-3: `belay corpus score`


def test_corpus_score_discloses_the_coverage_boundary(tmp_path: Path, capsys) -> None:
    """`corpus score` prints a line labelled `coverage` that is NOT this boundary.

    That metric is *decided / adjudicable labels* — a scoring denominator. The surface
    renders each case's stored verdict into a confusion matrix and says nothing about
    the dimensions those verdicts never covered, so the one honest-looking `coverage`
    line actively misleads: a reader has been shown a coverage number and still does not
    know what was outside coverage.

    The assertion is therefore NOT on the word "coverage" (which is already present and
    would pass against the defect) but on the boundary itself, and on the two senses
    being told apart in words.
    """
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    rc = cli.main(["corpus", "score", str(corpus)])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "decided / adjudicable" in out, "the pre-existing label metric must still print"
    assert "NOT_COVERED" in out, (
        "corpus score scores stored verdicts and never states their coverage boundary"
    )
    assert EFFECT_KIND in out, "the coverage disclosure must name the dimension"
    assert "declared no readOnlyHint" in out, "the message must survive on this surface too"
    # The name collision is the specific hazard here: two unrelated senses of one word on
    # one screen. They must be distinguished in words, not left to the reader.
    assert "not the same" in out.lower() or "different" in out.lower(), (
        "the NOT_COVERED boundary and the adjudicable-label metric must be told apart"
    )


# -------------------------------------------------------- additivity, all three surfaces


def _render(argv: list[str], capsys) -> str:
    from belay import cli

    assert cli.main(argv) == 0
    return capsys.readouterr().out


def test_no_uncovered_dimension_leaves_every_surface_unchanged(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A corpus with NO uncovered dimension renders exactly as it did before.

    The disclosure is strictly ADDITIVE: it is the block that appears when there IS a
    boundary, not a line every surface grew. A corpus whose cases declare none has nothing
    withheld, so an unconditional block would only add noise to every golden-output test in
    the suite — and noise in the tests that guard a disclosure is how the disclosure stops
    being trusted.

    Asserted as the absence of the block's own header and of the status name, on all three
    surfaces, from one case that is identical to the fixtures above except for the one
    sub-verdict.
    """
    from belay.corpus.run import MATCH, CaseResult, CorpusRun

    corpus = tmp_path / "corpus"
    case = _case(uncovered=False)
    write_case(corpus / case.id, case)
    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir, *, disable_claim_axis=False: CorpusRun(
            results=[CaseResult(case_id=case.id, outcome=MATCH)]
        ),
    )

    for argv in (
        ["corpus", "list", str(corpus)],
        ["corpus", "run", str(corpus)],
        ["corpus", "score", str(corpus)],
    ):
        out = _render(argv, capsys)
        assert "NOT_COVERED" not in out, f"{argv[1]} grew a block with no boundary: {out}"
        assert "coverage (NOT_COVERED" not in out, out
        # The surface still rendered the case — an empty disclosure must not be the
        # by-product of a surface that found nothing to render in the first place.
        # (`corpus score` prints counts, not ids, hence the denominator rather than the id.)
        assert "1 case" in out, out

    # And `corpus score`'s own coverage RATE is untouched by any of this: it is a
    # different metric that happens to share the word, and it still prints.
    assert "decided / adjudicable" in _render(["corpus", "score", str(corpus)], capsys)
