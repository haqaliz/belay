"""C6 Phase 3: `belay corpus run` — regression by re-verify, SKIP distinct from regression.

`corpus run` re-verifies every stored case and asserts it still reaches its recorded
verdict; the corpus IS the regression suite. The one property that carries this whole file
is the honest separation the brief names load-bearing:

- a **REGRESSION** is a detector change that flipped a verdict — the corpus caught a real
  drift and the build must break, so the run exits non-zero.
- a **SKIP** is "this box could not evaluate the case" — off the macOS Seatbelt substrate,
  the server was not runnable, a capability mismatch on restore. A SKIP is NEVER a pass and
  NEVER a regression, so it does not fail CI on a non-darwin box.

These tests drive the PURE `classify_case` directly with a stored `expected` dict and a
hand-built `recomputed` TurnVerdict — no server, no replay — so they run everywhere. Two
of them are the mandated teeth:

1. `test_axis_flip_with_unchanged_reduced_status_is_regression` — the D4 point: the reduced
   status stays FAIL but an A1 sub-verdict silently flipped FAIL->PASS. A "compare
   reduced_status only" stub calls it MATCH; this test FAILs that stub. That is why the
   stored `expected` pins the per-sub-verdict SET, not just the reduced status.
2. `test_unverified_with_environment_cause_is_skip_not_regression` — a recomputed UNVERIFIED
   whose cause is an environment gap (server unavailable) is a SKIP, distinct from a
   regression. A naive "any non-match is a regression" stub calls it a regression; this test
   FAILs that stub.

The real replay roundtrip (a flagged run -> add_case -> run_case -> MATCH) lives in
`tests/test_corpus_roundtrip.py`, darwin-gated, because only it re-invokes a server.
"""

from __future__ import annotations

import pytest

from belay.corpus.run import (
    MATCH,
    REGRESSION,
    SKIP,
    CaseResult,
    CorpusRun,
    Divergence,
    classify_case,
    run_corpus,
)
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict


# --- hand-built verdicts (no replay needed) -------------------------------------------


def _sub(axis: str, kind: str, status: Status) -> Verdict:
    return Verdict(axis, kind, status, None, None, f"{axis} {kind} {status.value}")


def _turn(status: Status, subs: list[Verdict], cause: str | None = None) -> TurnVerdict:
    return TurnVerdict(
        turn_index=0, tool_name="edit_file", status=status, sub_verdicts=subs, cause=cause
    )


def _expected(reduced: str, subs: list[tuple[str, str, str]]) -> dict:
    """A stored `expected` dict, exactly the shape `corpus add` writes to case.json."""
    return {
        "reduced_status": reduced,
        "sub_verdicts": [{"axis": a, "kind": k, "status": s} for a, k, s in subs],
    }


# --- (a) recomputed set == expected -> MATCH ------------------------------------------


def test_recomputed_equal_to_expected_is_match():
    expected = _expected(
        "FAIL",
        [("A2", "replay", "PASS"), ("A2", "effect", "PASS"), ("A1", "invariant", "FAIL")],
    )
    recomputed = _turn(
        Status.FAIL,
        [
            _sub("A2", "replay", Status.PASS),
            _sub("A2", "effect", Status.PASS),
            _sub("A1", "invariant", Status.FAIL),
        ],
    )
    result = classify_case(expected, recomputed)
    assert result.outcome == MATCH, result
    assert result.divergences == []


# --- (b) 🔴 AXIS FLIP WITH UNCHANGED REDUCED STATUS -> REGRESSION (the D4 point) --------


def test_axis_flip_with_unchanged_reduced_status_is_regression():
    """Reduced status stays FAIL, but A1 invariant silently flipped FAIL->PASS.

    A "compare reduced_status only" stub returns MATCH here (both reduced are FAIL) and this
    assertion FAILs it. The corpus pins the per-sub-verdict SET precisely so a detector that
    stops catching corrupt success — while some OTHER axis keeps the turn FAIL — is still a
    caught regression, not a silent MATCH.
    """
    expected = _expected("FAIL", [("A1", "invariant", "FAIL"), ("A2", "effect", "FAIL")])
    # A2 effect FAIL still dominates -> reduced FAIL, unchanged. But A1 regressed to PASS.
    recomputed = _turn(
        Status.FAIL,
        [_sub("A1", "invariant", Status.PASS), _sub("A2", "effect", Status.FAIL)],
    )
    result = classify_case(expected, recomputed)

    assert result.outcome == REGRESSION, (
        "the reduced status is an unchanged FAIL, but the A1 invariant flipped FAIL->PASS — "
        "a reduced-status-only comparison would miss this and call it a MATCH"
    )
    flips = [(d.axis, d.kind, d.expected_status, d.got_status) for d in result.divergences]
    assert ("A1", "invariant", "FAIL", "PASS") in flips, flips


# --- (c) 🔴 SKIP vs REGRESSION --------------------------------------------------------


def test_unverified_with_environment_cause_is_skip_not_regression():
    """A recomputed UNVERIFIED whose cause is "server unavailable" is a SKIP, not a regression.

    A naive "any non-match is a regression" stub calls this a regression (the recomputed set
    differs from the expected FAIL) and this assertion FAILs it. The server being un-runnable
    on THIS box is an environment gap — the case was not evaluated here — never a detector
    change, so it must not exit CI non-zero.
    """
    from belay.replay.engine import UNANSWERED_TARGET

    expected = _expected("FAIL", [("A1", "invariant", "FAIL"), ("A2", "effect", "FAIL")])
    recomputed = _turn(
        Status.UNVERIFIED,
        [_sub("A2", "replay", Status.UNVERIFIED)],
        cause=UNANSWERED_TARGET,
    )
    result = classify_case(expected, recomputed)

    assert result.outcome == SKIP, (
        "the server did not answer — an environment gap, not a detector regression"
    )
    assert result.outcome != REGRESSION
    assert result.skip_reason is not None


def test_unverified_with_canonical_replay_bucket_is_skip():
    """The cause a REAL verify_turn emits (the canonical bucket) is recognised as a SKIP.

    `verify_turn` stores the CANONICAL cause bucket on the TurnVerdict, not the raw engine
    string, so the SKIP detection must match the bucket the engine actually produces — this
    guards against a set that only knows the raw constant and misses the real roundtrip.
    """
    from belay.replay.report import REPLAY_DID_NOT_ANSWER

    expected = _expected("FAIL", [("A1", "invariant", "FAIL")])
    recomputed = _turn(
        Status.UNVERIFIED,
        [_sub("A2", "replay", Status.UNVERIFIED)],
        cause=REPLAY_DID_NOT_ANSWER,
    )
    assert classify_case(expected, recomputed).outcome == SKIP


def test_unverified_with_capability_mismatch_is_skip():
    """A backend capability mismatch on restore is an environment gap -> SKIP."""
    from belay.snapshot.substrate import UnrestorableCause

    expected = _expected("FAIL", [("A1", "invariant", "FAIL")])
    recomputed = _turn(
        Status.UNVERIFIED,
        [_sub("A2", "replay", Status.UNVERIFIED)],
        cause=UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH.value,
    )
    assert classify_case(expected, recomputed).outcome == SKIP


def test_unverified_with_non_environment_cause_is_not_skipped():
    """A NON-environment UNVERIFIED is a regression, not a free pass under the SKIP banner.

    A self-contained case bundles its own manifest, so "manifest not found" on recompute is
    corruption of the engine's read of the case — a real divergence from the stored FAIL,
    never an environment gap. If the SKIP set were too broad it would hide this; it must not.
    """
    expected = _expected("FAIL", [("A1", "invariant", "FAIL"), ("A2", "effect", "FAIL")])
    recomputed = _turn(
        Status.UNVERIFIED,
        [_sub("A2", "replay", Status.UNVERIFIED)],
        cause="manifest not found",
    )
    result = classify_case(expected, recomputed)
    assert result.outcome == REGRESSION, result
    assert result.outcome != SKIP


# --- (d) a genuine decisive divergence -> REGRESSION ----------------------------------


def test_expected_fail_recomputed_all_pass_is_regression():
    """expected FAIL, recomputed PASS with the SAME sub-verdict kinds all PASS -> REGRESSION."""
    expected = _expected(
        "FAIL",
        [("A2", "replay", "PASS"), ("A2", "effect", "PASS"), ("A1", "invariant", "FAIL")],
    )
    recomputed = _turn(
        Status.PASS,
        [
            _sub("A2", "replay", Status.PASS),
            _sub("A2", "effect", Status.PASS),
            _sub("A1", "invariant", Status.PASS),
        ],
    )
    result = classify_case(expected, recomputed)
    assert result.outcome == REGRESSION
    flips = [(d.axis, d.kind, d.expected_status, d.got_status) for d in result.divergences]
    assert ("A1", "invariant", "FAIL", "PASS") in flips, flips
    # the reduced status also moved, and that is named too.
    reduced = [d for d in result.divergences if d.kind == "reduced_status"]
    assert reduced and reduced[0].expected_status == "FAIL" and reduced[0].got_status == "PASS"


def test_a_dropped_sub_verdict_is_a_regression():
    """An expected sub-verdict that recompute no longer emits at all is a regression.

    Matched by (axis, kind): a key present in expected but absent from recomputed diverges
    against `None`, so a whole axis silently disappearing cannot read as a MATCH.
    """
    expected = _expected("FAIL", [("A2", "effect", "PASS"), ("A1", "invariant", "FAIL")])
    recomputed = _turn(Status.PASS, [_sub("A2", "effect", Status.PASS)])
    result = classify_case(expected, recomputed)
    assert result.outcome == REGRESSION
    keys = {(d.axis, d.kind) for d in result.divergences}
    assert ("A1", "invariant") in keys, result.divergences


# --- (e) run_corpus aggregation + exit-code logic -------------------------------------


def _match(case_id: str) -> CaseResult:
    return CaseResult(case_id=case_id, outcome=MATCH)


def _regression(case_id: str) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        outcome=REGRESSION,
        divergences=[Divergence("A1", "invariant", "FAIL", "PASS")],
    )


def _skip(case_id: str) -> CaseResult:
    return CaseResult(case_id=case_id, outcome=SKIP, skip_reason="server unavailable")


def test_corpus_run_aggregates_mixed_outcomes_into_counts():
    run = CorpusRun(results=[_match("m"), _regression("r"), _skip("s")])
    assert run.matches == 1
    assert run.regressions == 1
    assert run.skips == 1
    assert len(run.results) == 3


def test_a_regression_present_means_non_zero_exit():
    run = CorpusRun(results=[_match("m"), _regression("r"), _skip("s")])
    assert run.has_regression is True


def test_match_and_skip_only_is_a_clean_exit():
    """A pure MATCH+SKIP run is NOT a CI failure — else the corpus fails on every non-darwin box."""
    run = CorpusRun(results=[_match("m"), _skip("s")])
    assert run.has_regression is False
    # an all-SKIP run (a non-darwin box) is also clean, and its partial coverage is visible.
    all_skipped = CorpusRun(results=[_skip("a"), _skip("b")])
    assert all_skipped.has_regression is False
    assert all_skipped.skips == 2


# --- run_corpus is fail-closed on a corrupt case dir (runs on every platform) ----------


def test_run_corpus_fails_closed_on_a_corrupt_case_dir(tmp_path):
    """A subdirectory with no case.json is a named error, never a silent skip.

    load_case reads and validates case.json BEFORE any platform gate, so a corrupt case dir
    raises on every box — a corpus that quietly dropped an unreadable case would regress
    against fewer cases than it holds, the exact false-completeness the corpus exists to
    refuse.
    """
    corpus = tmp_path / "corpus"
    (corpus / "not-a-case").mkdir(parents=True)
    with pytest.raises(ValueError):
        run_corpus(corpus)


# --- the CLI: exit non-zero IFF at least one REGRESSION (runs everywhere) --------------


def test_cli_corpus_run_exits_non_zero_on_regression(tmp_path, monkeypatch, capsys):
    """`belay corpus run` exits non-zero when any case REGRESSED — the CI signal.

    The classification is proven by the pure tests and the darwin roundtrip; here the CLI
    WIRING is checked in isolation by monkeypatching `run_corpus`, so the exit contract runs
    on every box regardless of substrate.
    """
    from belay import cli

    (tmp_path / "corpus").mkdir()
    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir: CorpusRun(results=[_match("kept"), _regression("drifted"), _skip("off")]),
    )
    rc = cli.main(["corpus", "run", str(tmp_path / "corpus")])
    assert rc != 0
    out = capsys.readouterr().out
    assert "drifted" in out and "REGRESSION" in out


def test_cli_corpus_run_exits_zero_on_match_and_skip_only(tmp_path, monkeypatch, capsys):
    """A run that is all MATCH/SKIP exits 0 — a pure SKIP is partial coverage, not a failure."""
    from belay import cli

    (tmp_path / "corpus").mkdir()
    monkeypatch.setattr(
        "belay.corpus.run.run_corpus",
        lambda _dir: CorpusRun(results=[_match("kept"), _skip("off")]),
    )
    rc = cli.main(["corpus", "run", str(tmp_path / "corpus")])
    assert rc == 0
    out = capsys.readouterr().out
    # the SKIP count is stated plainly, so a reader knows coverage was partial.
    assert "SKIP" in out and "1" in out
