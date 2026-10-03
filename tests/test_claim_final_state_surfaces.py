"""surface-threading: a `FINAL_STATE_UNOBSERVABLE` sub-cause rides every surface.

CHARACTERIZATION pins, green on arrival. `sub-cause-producer` made the evaluator emit one
of four `FINAL_STATE_*` sub-causes; every surface was already cause-agnostic (it copies and
renders on the PRESENCE of `sub_cause`, never on the cause), so these pins hold behaviour
that already exists. Each was proven able to fail by breaking the surface and reverting
(`docs/planning/final-state-reasons/surface-threading/plan_20261003.md`).

Pinned, per `FINAL_STATE_*` sub-cause (helpers reused from the `NO_CHECK_AUTHOR` modules):

1. verify text: `[FINAL_STATE_UNOBSERVABLE/<SUB>] — never PASS`, the detail line only
   when non-empty;
2. `phase0 report`: the same line from a stored ledger dict; a ledger dict with the cause
   and NO sub-cause renders exactly as before (never back-filled);
3. `corpus show`: a `sub-cause:` line for a stored case, none when absent;
4. corpus recompute: a different (or absent) sub-cause is still a MATCH (status-only);
5. corpus case: a final-state-sub-caused claim round-trips byte-identically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from belay import cli
from belay.corpus import run as run_module
from belay.corpus.case import load_case, write_case
from belay.corpus.run import MATCH, run_case
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_FINAL_STATE_UNOBSERVABLE,
    SUB_CAUSE_FINAL_STATE_NO_TURN,
    SUB_CAUSE_FINAL_STATE_NO_WORKSPACE,
    SUB_CAUSE_FINAL_STATE_NOT_REPLAYED,
    SUB_CAUSE_FINAL_STATE_REPLAY_RAISED,
    Abstention,
)
from test_claim_subcause_surfaces import _emitted, _inst, _shapers
from test_corpus_claim_show import REQUIRES_DARWIN, _build_claim_case, _stub_replay
from test_corpus_claim_subcause import _claim_case

# (sub-cause, detail): NO_TURN and NO_WORKSPACE carry no detail, the other two do (PRD M3).
REASONS = [
    (SUB_CAUSE_FINAL_STATE_NO_TURN, ""),
    (SUB_CAUSE_FINAL_STATE_REPLAY_RAISED, "OSError"),
    (SUB_CAUSE_FINAL_STATE_NOT_REPLAYED, "unverified: no snapshot"),
    (SUB_CAUSE_FINAL_STATE_NO_WORKSPACE, ""),
]
_IDS = [sub for sub, _ in REASONS]

_FS_BASE = {
    "status": "UNVERIFIED",
    "cause": "FINAL_STATE_UNOBSERVABLE",
    "check": {"source": "", "exit_code": None},
}


def _final_state(sub: str, detail: str):
    return claims._unverified(
        CAUSE_FINAL_STATE_UNOBSERVABLE,
        claim_seq=3,
        detail="the final state could not be observed",
        abstention=Abstention(sub, detail),
    )


def _stored(sub: str, detail: str) -> dict:
    return dict(_FS_BASE, sub_cause=sub, sub_cause_detail=detail)


# --- (1) verify text ---------------------------------------------------------------


@pytest.mark.parametrize("sub, detail", REASONS, ids=_IDS)
def test_verify_text_names_the_final_state_sub_cause(sub, detail, capsys) -> None:
    lines = _emitted(_final_state(sub, detail), capsys)
    head = f"    UNVERIFIED [FINAL_STATE_UNOBSERVABLE/{sub}] — never PASS"
    if detail:
        assert lines[-2:] == [head, f"      ({detail})"]
    else:
        assert lines[-1] == head
    assert "PASS" not in lines[-1].replace("never PASS", "")


def test_verify_text_without_a_sub_cause_is_byte_identical_for_final_state(capsys) -> None:
    verdict = claims._unverified(CAUSE_FINAL_STATE_UNOBSERVABLE, claim_seq=3, detail="x")
    assert _emitted(verdict, capsys)[-1] == (
        "    UNVERIFIED [FINAL_STATE_UNOBSERVABLE] — never PASS"
    )


# --- (2) phase0 report -------------------------------------------------------------


@pytest.mark.parametrize("sub, detail", REASONS, ids=_IDS)
def test_report_line_names_the_final_state_sub_cause(sub, detail) -> None:
    from belay.phase0.report import _claim_line

    expected = f"  trace-a: claim UNVERIFIED [FINAL_STATE_UNOBSERVABLE/{sub}] — never PASS"
    if detail:
        expected += f" ({detail})"
    assert _claim_line(_inst(_stored(sub, detail))) == expected


def test_report_line_for_a_final_state_ledger_without_a_sub_cause_is_unchanged() -> None:
    """A ledger written before the sub-cause existed (as in `cm-stage1.json`): never
    back-filled, rendered exactly as before."""
    from belay.phase0.report import _claim_line

    assert _claim_line(_inst(dict(_FS_BASE))) == (
        "  trace-a: claim UNVERIFIED [FINAL_STATE_UNOBSERVABLE] — never PASS"
    )


# --- (3) corpus show ---------------------------------------------------------------


@REQUIRES_DARWIN
@pytest.mark.parametrize("sub, detail", REASONS, ids=_IDS)
def test_show_names_the_stored_final_state_sub_cause(
    sub, detail, tmp_path, monkeypatch, capsys
) -> None:
    _stub_replay(monkeypatch, tmp_path)
    case_dir = _build_claim_case(tmp_path, case_name="shown", declared=_stored(sub, detail))
    monkeypatch.setattr(run_module, "evaluate_claim", lambda **kwargs: _final_state(sub, detail))

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    lines = [line.strip() for line in out.splitlines()]
    at = lines.index("claim expected        UNVERIFIED  (cause: FINAL_STATE_UNOBSERVABLE)")
    want = f"sub-cause: {sub}" + (f" ({detail})" if detail else "")
    assert lines[at + 1] == want, out


@REQUIRES_DARWIN
def test_show_without_a_final_state_sub_cause_prints_no_sub_cause_line(
    tmp_path, monkeypatch, capsys
) -> None:
    _stub_replay(monkeypatch, tmp_path)
    case_dir = _build_claim_case(tmp_path, case_name="pre-field", declared=dict(_FS_BASE))
    monkeypatch.setattr(
        run_module,
        "evaluate_claim",
        lambda **kwargs: claims._unverified(CAUSE_FINAL_STATE_UNOBSERVABLE, claim_seq=0, detail="x"),
    )

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "claim expected" in out, out
    assert "sub-cause" not in out, out


# --- (4) corpus recompute never decides on the sub-cause ----------------------------


@REQUIRES_DARWIN
@pytest.mark.parametrize("recomputed_sub", [None, SUB_CAUSE_FINAL_STATE_NO_WORKSPACE])
def test_a_different_final_state_sub_cause_on_recompute_is_still_a_match(
    recomputed_sub, tmp_path, monkeypatch
) -> None:
    """Stored says the last turn did not replay; the recompute names another reason (or
    none). Both are UNVERIFIED `FINAL_STATE_UNOBSERVABLE`: the contract is status only."""
    _stub_replay(monkeypatch, tmp_path)
    case_dir = _build_claim_case(
        tmp_path,
        case_name="drift",
        declared=_stored(SUB_CAUSE_FINAL_STATE_NOT_REPLAYED, "unverified: no snapshot"),
    )
    recomputed = claims._unverified(
        CAUSE_FINAL_STATE_UNOBSERVABLE,
        claim_seq=0,
        detail="x",
        abstention=Abstention(recomputed_sub, "") if recomputed_sub else None,
    )
    monkeypatch.setattr(run_module, "evaluate_claim", lambda **kwargs: recomputed)

    result = run_case(case_dir)

    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []


# --- (5) the case format -----------------------------------------------------------


@pytest.mark.parametrize("sub, detail", REASONS, ids=_IDS)
def test_a_final_state_sub_caused_claim_round_trips_byte_identically(
    sub, detail, tmp_path: Path
) -> None:
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    write_case(dir_a, _claim_case(_stored(sub, detail)))
    loaded = load_case(dir_a)
    assert loaded.claim == _stored(sub, detail)
    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()


@pytest.mark.parametrize("sub, detail", REASONS, ids=_IDS)
def test_the_shapers_carry_each_final_state_sub_cause_last(sub, detail) -> None:
    for name, record in _shapers(_final_state(sub, detail)).items():
        assert record["sub_cause"] == sub, (name, record)
        assert record["sub_cause_detail"] == detail, (name, record)
        assert list(record)[-2:] == ["sub_cause", "sub_cause_detail"], (name, record)
