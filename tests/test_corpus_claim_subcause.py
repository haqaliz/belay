"""surface-threading: a corpus case keeps the author's sub-cause, and it never decides.

A `NO_CHECK_AUTHOR` claim verdict now carries `sub_cause` / `sub_cause_detail`, and
`claim_case` banks them. The v5 case format absorbs them WITHOUT a schema bump (PRD §5:
an older loader drops a detail, it does not misread a verdict), so this module pins
(`docs/planning/claim-axis-legibility/surface-threading/spec.md` AC 3, AC 4):

1. a v5 case with the two keys round-trips byte-identically, and the keys are
   type-checked when present (`str` or null) — a named error otherwise;
2. `CASE_SCHEMA_VERSION` is still 5;
3. `corpus run` never decides on the sub-cause — a stored `NO_CHECK_AUTHOR /
   AUTHOR_TIMED_OUT` recomputing to `NO_CHECK_AUTHOR / AUTHOR_EXITED_NONZERO` is a
   MATCH (the classifier is status-only);
4. `corpus show` names the stored sub-cause on the claim block;
5. the gate compares the claim on status only: a sub-caused baseline vs one without
   carries no divergence row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay import cli
from belay.corpus import run as run_module
from belay.corpus.case import CASE_SCHEMA_VERSION, Case, load_case, write_case
from belay.corpus.run import MATCH, run_case
from belay.gate.compare import compare
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_NO_CHECK_AUTHOR,
    SUB_CAUSE_AUTHOR_EXITED_NONZERO,
    Abstention,
)
from test_corpus_claim_schema import _full_case
from test_corpus_claim_show import REQUIRES_DARWIN, _build_claim_case, _stub_replay

SUB_CAUSED = {
    "status": "UNVERIFIED",
    "cause": "NO_CHECK_AUTHOR",
    "check": {"source": "", "exit_code": None},
    "sub_cause": "AUTHOR_TIMED_OUT",
    "sub_cause_detail": "no reply within 60s",
}


def _claim_case(claim: dict) -> Case:
    return Case(**{**_full_case().__dict__, "claim": claim})


# --- (1) the case format -------------------------------------------------------------


def test_schema_version_is_still_5() -> None:
    assert CASE_SCHEMA_VERSION == 5


def test_a_sub_caused_claim_round_trips_byte_identically(tmp_path: Path) -> None:
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    write_case(dir_a, _claim_case(dict(SUB_CAUSED)))
    loaded = load_case(dir_a)
    assert loaded.claim == SUB_CAUSED
    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()
    assert json.loads((dir_a / "case.json").read_text())["claim"] == SUB_CAUSED


@pytest.mark.parametrize(
    "key, value",
    [("sub_cause", 3), ("sub_cause", ["AUTHOR_TIMED_OUT"]), ("sub_cause_detail", 7)],
)
def test_a_non_string_sub_cause_key_is_rejected_by_name(tmp_path, key, value) -> None:
    write_case(tmp_path, _claim_case(dict(SUB_CAUSED, **{key: value})))
    with pytest.raises(ValueError, match=f"claim.{key}"):
        load_case(tmp_path)


def test_null_sub_cause_keys_load(tmp_path) -> None:
    claim = dict(SUB_CAUSED, sub_cause=None, sub_cause_detail=None)
    write_case(tmp_path, _claim_case(claim))
    assert load_case(tmp_path).claim == claim


# --- (2) corpus run never decides on the sub-cause ------------------------------------


@REQUIRES_DARWIN
def test_a_different_sub_cause_on_recompute_is_still_a_match(tmp_path, monkeypatch) -> None:
    """The stored case says the author timed out; the recompute's author exited non-zero.
    Both are UNVERIFIED `NO_CHECK_AUTHOR`: the claim contract is the status, so MATCH."""
    _stub_replay(monkeypatch, tmp_path)
    case_dir = _build_claim_case(tmp_path, case_name="drift", declared=SUB_CAUSED)
    recomputed = claims._unverified(
        CAUSE_NO_CHECK_AUTHOR,
        claim_seq=0,
        detail="the check author returned no executable check",
        abstention=Abstention(SUB_CAUSE_AUTHOR_EXITED_NONZERO, "exit 1: boom"),
    )
    monkeypatch.setattr(run_module, "evaluate_claim", lambda **kwargs: recomputed)

    result = run_case(case_dir)

    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []


# --- (3) corpus show names it -----------------------------------------------------------


@REQUIRES_DARWIN
def test_show_names_the_stored_sub_cause(tmp_path, monkeypatch, capsys) -> None:
    _stub_replay(monkeypatch, tmp_path)
    case_dir = _build_claim_case(tmp_path, case_name="shown", declared=SUB_CAUSED)
    monkeypatch.setattr(run_module, "evaluate_claim", lambda **kwargs: claims._unverified(
        CAUSE_NO_CHECK_AUTHOR, claim_seq=0, detail="x",
    ))

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    lines = [line.strip() for line in out.splitlines()]
    at = lines.index("claim expected        UNVERIFIED  (cause: NO_CHECK_AUTHOR)")
    assert lines[at + 1] == "sub-cause: AUTHOR_TIMED_OUT (no reply within 60s)", out


@REQUIRES_DARWIN
def test_show_without_a_sub_cause_prints_no_sub_cause_line(
    tmp_path, monkeypatch, capsys
) -> None:
    """A claim case banked before the sub-cause existed renders no sub-cause line."""
    _stub_replay(monkeypatch, tmp_path)
    old = {k: v for k, v in SUB_CAUSED.items() if not k.startswith("sub_cause")}
    case_dir = _build_claim_case(tmp_path, case_name="pre-field", declared=old)
    monkeypatch.setattr(run_module, "evaluate_claim", lambda **kwargs: claims._unverified(
        CAUSE_NO_CHECK_AUTHOR, claim_seq=0, detail="x",
    ))

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "claim expected" in out, out
    assert "sub-cause" not in out, out


# --- (4) the gate compares the claim on status only ------------------------------------


def test_gate_sees_no_divergence_between_a_sub_caused_claim_and_one_without() -> None:
    old = {k: v for k, v in SUB_CAUSED.items() if not k.startswith("sub_cause")}
    turns = [{"ordinal": 0, "tool": "echo", "status": "PASS", "cause": None,
              "sub_verdicts": []}]
    expected = {"turns": turns, "trajectory": None, "claim": old}
    recomputed = {"turns": turns, "trajectory": None, "claim": dict(SUB_CAUSED)}

    result = compare("run", expected, recomputed)

    assert result.exit_reason == "clean", result
    assert result.divergences == []
