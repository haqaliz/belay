"""C6 corpus adjudication + inspection: `corpus label`, `corpus list`, `corpus show`.

`label` completes the human-audit loop that makes the precision/recall metric usable:
`corpus add` stores a case `pending`, a human ADJUDICATES it here, `corpus score` measures
the engine's stored verdicts against those human calls. The one load-bearing invariant this
file pins is the D3 boundary — a human adjudication touches ONLY `human_label` and NEVER
rewrites `expected`, the verdict the engine computed. Label and verdict stay independent, so
scoring the engine against the labels is not scoring it against itself.

`list`/`show` are read-only inspection over the same fail-closed `load_case`; all pure
filesystem, so this whole file runs on every box.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import Case, load_case, write_case
from belay.corpus.curate import set_label


def _case(case_id: str = "cheat-run-0007", human_label: str = "pending") -> Case:
    """A fully-populated case with a FAIL verdict, `pending` by default (un-adjudicated)."""
    return Case(
        id=case_id,
        target_turn_index=3,
        expected={
            "reduced_status": "FAIL",
            "sub_verdicts": [
                {"axis": "A1", "kind": "invariant", "status": "FAIL"},
                {"axis": "A2", "kind": "effect", "status": "PASS"},
            ],
        },
        human_label=human_label,
        invariants=[{"scope": "tests/", "rule": "read-only"}],
        server_command=["python", "editor_server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-07-18T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


def test_set_label_adjudicates_a_pending_case(tmp_path: Path) -> None:
    """(a) `set_label` on a `pending` case reloads with the new label; the rest is unchanged."""
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    returned = set_label(corpus, case.id, "true-positive")
    assert returned == corpus / case.id

    reloaded = load_case(corpus / case.id)
    assert reloaded.human_label == "true-positive"
    # Round-trip integrity: an unrelated field is identical — only the label moved.
    assert reloaded.server_command == case.server_command
    assert reloaded.target_turn_index == case.target_turn_index


def test_relabeling_corrects_an_earlier_call(tmp_path: Path) -> None:
    """(b) A human can correct: true-positive -> false-positive updates in place."""
    corpus = tmp_path / "corpus"
    case = _case(human_label="true-positive")
    write_case(corpus / case.id, case)

    set_label(corpus, case.id, "false-positive")
    assert load_case(corpus / case.id).human_label == "false-positive"


def test_unknown_label_fails_closed(tmp_path: Path) -> None:
    """(c) An unknown label is a fail-closed ValueError — never a silent no-op."""
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    with pytest.raises(ValueError, match="label"):
        set_label(corpus, case.id, "definitely-a-bug")

    # And the case on disk is untouched — the rejected label never landed.
    assert load_case(corpus / case.id).human_label == "pending"


def test_pending_is_not_an_adjudication(tmp_path: Path) -> None:
    """`label` means adjudicate: `pending` is the un-adjudicated default, not a valid target."""
    corpus = tmp_path / "corpus"
    case = _case(human_label="true-positive")
    write_case(corpus / case.id, case)

    with pytest.raises(ValueError, match="label"):
        set_label(corpus, case.id, "pending")


def test_missing_case_fails_closed(tmp_path: Path) -> None:
    """A case-id that does not exist is a fail-closed ValueError, never a silent success."""
    with pytest.raises(ValueError):
        set_label(tmp_path / "corpus", "no-such-case", "true-positive")


def test_label_leaves_expected_byte_identical(tmp_path: Path) -> None:
    """(d) The invariant: `label` touches ONLY `human_label`; `expected` is byte-identical.

    The D3 boundary — a human adjudication never rewrites what the engine computed. Asserted
    at the byte level over the stored `expected`, and by diffing the full payload to prove
    `human_label` is the ONLY key that moved.
    """
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    before = json.loads((corpus / case.id / "case.json").read_text(encoding="utf-8"))
    set_label(corpus, case.id, "true-positive")
    after = json.loads((corpus / case.id / "case.json").read_text(encoding="utf-8"))

    # The engine's verdict is byte-identical, serialized the same deterministic way.
    assert json.dumps(before["expected"], sort_keys=True) == json.dumps(
        after["expected"], sort_keys=True
    )
    # And human_label is the ONLY field that changed.
    assert {k: v for k, v in before.items() if k != "human_label"} == {
        k: v for k, v in after.items() if k != "human_label"
    }
    assert before["human_label"] == "pending"
    assert after["human_label"] == "true-positive"


def test_cli_corpus_label_updates_and_exits_zero(tmp_path: Path, capsys) -> None:
    """`belay corpus label <id> --label ...` adjudicates the case and exits 0."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    rc = cli.main(["corpus", "label", case.id, "--label", "true-positive", "--corpus-dir", str(corpus)])
    assert rc == 0
    assert load_case(corpus / case.id).human_label == "true-positive"


def test_cli_corpus_label_unknown_label_exits_non_zero(tmp_path: Path, capsys) -> None:
    """(c, CLI) An unknown label is rejected by argparse's choices — a non-zero exit."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    with pytest.raises(SystemExit) as exc:
        cli.main(["corpus", "label", case.id, "--label", "not-a-label", "--corpus-dir", str(corpus)])
    assert exc.value.code != 0
    # The case on disk is untouched.
    assert load_case(corpus / case.id).human_label == "pending"


def test_cli_corpus_list_prints_each_case_sorted(tmp_path: Path, capsys) -> None:
    """(e) `corpus list` prints each case-id with its label + reduced_status, sorted by id."""
    from belay import cli

    corpus = tmp_path / "corpus"
    write_case(corpus / "zeta", _case(case_id="zeta", human_label="false-positive"))
    write_case(corpus / "alpha", _case(case_id="alpha", human_label="true-positive"))
    write_case(corpus / "mid", _case(case_id="mid", human_label="pending"))

    rc = cli.main(["corpus", "list", str(corpus)])
    assert rc == 0
    out = capsys.readouterr().out

    assert "alpha" in out and "mid" in out and "zeta" in out
    assert "true-positive" in out and "false-positive" in out and "pending" in out
    assert "FAIL" in out
    # Stable ordering: sorted by case-id.
    assert out.index("alpha") < out.index("mid") < out.index("zeta")


def test_cli_corpus_show_prints_verdict_and_label(tmp_path: Path, capsys) -> None:
    """(f) `corpus show` prints the case's expected sub-verdict set and human_label."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case(human_label="true-positive")
    write_case(corpus / case.id, case)

    rc = cli.main(["corpus", "show", case.id, "--corpus-dir", str(corpus)])
    assert rc == 0
    out = capsys.readouterr().out

    assert "true-positive" in out  # the human label
    assert "FAIL" in out  # the reduced status
    # The sub-verdict set: both axes and their kinds/statuses are shown.
    assert "A1" in out and "invariant" in out
    assert "A2" in out and "effect" in out
    assert "editor_server.py" in out  # server_command


def test_cli_corpus_show_missing_case_exits_non_zero(tmp_path: Path, capsys) -> None:
    """A `show` of a case-id that does not exist is fail-closed, a non-zero exit."""
    from belay import cli

    rc = cli.main(["corpus", "show", "no-such-case", "--corpus-dir", str(tmp_path / "corpus")])
    assert rc != 0
