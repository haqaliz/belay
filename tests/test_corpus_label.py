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


#: A well-formed root cause, for the adjudications that now require one.
_ROOT_CAUSE = {"key": "required-test-update", "note": "upstream deletes the same test"}


def test_set_label_adjudicates_a_pending_case(tmp_path: Path) -> None:
    """(a) `set_label` on a `pending` case reloads with the new label; the rest is unchanged."""
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    returned = set_label(corpus, case.id, "true-positive", root_cause=_ROOT_CAUSE)
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
    set_label(corpus, case.id, "true-positive", root_cause=_ROOT_CAUSE)
    after = json.loads((corpus / case.id / "case.json").read_text(encoding="utf-8"))

    # The engine's verdict is byte-identical, serialized the same deterministic way.
    assert json.dumps(before["expected"], sort_keys=True) == json.dumps(
        after["expected"], sort_keys=True
    )
    # And human_label / root_cause are the ONLY fields that changed — the adjudication
    # writes the human's call and its cause, and nothing the engine computed.
    ignored = {"human_label", "root_cause"}
    assert {k: v for k, v in before.items() if k not in ignored} == {
        k: v for k, v in after.items() if k not in ignored
    }
    assert before["human_label"] == "pending"
    assert after["human_label"] == "true-positive"


def test_cli_corpus_label_updates_and_exits_zero(tmp_path: Path, capsys) -> None:
    """`belay corpus label <id> --label ...` adjudicates the case and exits 0."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    rc = cli.main(
        [
            "corpus", "label", case.id,
            "--label", "true-positive",
            "--root-cause-key", "required-test-update",
            "--root-cause-note", "upstream deletes the same test",
            "--corpus-dir", str(corpus),
        ]
    )
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


# ---------------------------------------------------------------------------
# A true-positive REQUIRES a root cause.
#
# The pre-registered criteria demand a root cause beside every TP so a reader
# can judge independence directly (PHASE0_RESULTS.md:38,135; RUNBOOK.md:424).
# A TP without one is therefore a finding the gate cannot evaluate, and letting
# it onto disk would mean scoring a corpus that cannot answer the question it
# exists to answer. Rejected fail-closed, BEFORE any write.
# ---------------------------------------------------------------------------


def test_true_positive_without_a_root_cause_is_rejected(tmp_path: Path) -> None:
    """A TP with no root cause raises, and case.json is left byte-identical.

    Fail-closed BEFORE touching disk, mirroring the existing unknown-label
    rejection: a half-applied adjudication would be worse than none.
    """
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)
    before = (corpus / case.id / "case.json").read_bytes()

    with pytest.raises(ValueError, match="root cause"):
        set_label(corpus, case.id, "true-positive")

    assert (corpus / case.id / "case.json").read_bytes() == before


def test_true_positive_with_a_root_cause_records_both(tmp_path: Path) -> None:
    """A TP with a root cause writes the label AND the cause."""
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    set_label(corpus, case.id, "true-positive", root_cause=_ROOT_CAUSE)

    reloaded = load_case(corpus / case.id)
    assert reloaded.human_label == "true-positive"
    assert reloaded.root_cause == _ROOT_CAUSE


def test_false_positive_needs_no_root_cause(tmp_path: Path) -> None:
    """Only a TP requires a cause; the criteria ask for it beside true positives."""
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    set_label(corpus, case.id, "false-positive")
    assert load_case(corpus / case.id).human_label == "false-positive"


def test_relabeling_preserves_an_existing_root_cause(tmp_path: Path) -> None:
    """Re-labeling does not silently erase a root cause already on the case.

    THE hazard this aspect exists to close: `set_label` round-trips through the
    frozen dataclass and `write_case` serializes a fixed key set, so a cause
    that were not a real Case field would vanish on the next label call — the
    audit's own record destroying itself.
    """
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)
    set_label(corpus, case.id, "true-positive", root_cause=_ROOT_CAUSE)

    # A later correction of the LABEL must not drop the recorded cause.
    set_label(corpus, case.id, "unverifiable")

    reloaded = load_case(corpus / case.id)
    assert reloaded.human_label == "unverifiable"
    assert reloaded.root_cause == _ROOT_CAUSE


def test_malformed_root_cause_is_rejected_before_writing(tmp_path: Path) -> None:
    """A non-kebab key is rejected at adjudication time, not on the next load."""
    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)
    before = (corpus / case.id / "case.json").read_bytes()

    with pytest.raises(ValueError, match="root_cause"):
        set_label(corpus, case.id, "true-positive", root_cause={"key": "Not Kebab", "note": ""})

    assert (corpus / case.id / "case.json").read_bytes() == before


def test_cli_true_positive_without_root_cause_key_exits_non_zero(tmp_path: Path, capsys) -> None:
    """The CLI refuses a TP with no --root-cause-key, and says why."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    rc = cli.main(
        ["corpus", "label", case.id, "--label", "true-positive", "--corpus-dir", str(corpus)]
    )
    assert rc != 0
    assert "root cause" in capsys.readouterr().out.lower()
    # And the case is untouched — still un-adjudicated.
    assert load_case(corpus / case.id).human_label == "pending"


def test_cli_root_cause_note_without_key_exits_non_zero(tmp_path: Path, capsys) -> None:
    """A note with no key is an error: the key is what independence groups on."""
    from belay import cli

    corpus = tmp_path / "corpus"
    case = _case()
    write_case(corpus / case.id, case)

    rc = cli.main(
        [
            "corpus", "label", case.id,
            "--label", "false-positive",
            "--root-cause-note", "a note with no key",
            "--corpus-dir", str(corpus),
        ]
    )
    assert rc != 0


# ---------------------------------------------------------------------------
# Rendering: an independence count NEVER travels without the rule that
# produced it.
#
# Same discipline as the coverage line travelling with a PASS. The two readings
# of "independent" disagree, so a bare number invites quoting whichever
# flatters -- exactly what pre-registering the criteria exists to prevent.
# ---------------------------------------------------------------------------


def _tp_case(case_id: str, key: str, tool: str | None, trace: str) -> Case:
    """A true-positive case with a root cause, for the independence counts."""
    case = _case(case_id=case_id, human_label="true-positive")
    return Case(
        **{
            **case.__dict__,
            "root_cause": {"key": key, "note": ""},
            "target_tool": tool,
            "provenance": {"source_trace_id": trace, "captured_at": "2026-07-18T00:00:00Z"},
        }
    )


def test_cli_corpus_score_prints_both_independence_counts_with_their_rules(
    tmp_path: Path, capsys
) -> None:
    """Both counts print, each naming the rule that produced it."""
    from belay import cli

    corpus = tmp_path / "corpus"
    write_case(corpus / "a", _tp_case("a", "cause-one", "edit_file", "trace-x"))
    write_case(corpus / "b", _tp_case("b", "cause-two", "edit_file", "trace-y"))

    assert cli.main(["corpus", "score", str(corpus)]) == 0
    out = capsys.readouterr().out

    assert "independent" in out
    assert "root-cause" in out  # the primary rule, named
    assert "instance" in out and "tool" in out  # the strict rule, named
    # Two distinct causes, but ONE tool across the corpus -> strict collapses to 1.
    assert "2" in out and "1" in out


def test_cli_corpus_score_renders_na_strict_when_a_tp_lacks_a_tool(
    tmp_path: Path, capsys
) -> None:
    """An unevaluable strict count prints n/a with its reason — never 0."""
    from belay import cli

    corpus = tmp_path / "corpus"
    write_case(corpus / "a", _tp_case("a", "cause-one", None, "trace-x"))

    assert cli.main(["corpus", "score", str(corpus)]) == 0
    out = capsys.readouterr().out

    # The STRICT line specifically must read n/a -- not merely "n/a appears
    # somewhere", which recall already satisfies on an all-TP corpus.
    strict = [ln for ln in out.splitlines() if "strict" in ln]
    assert strict, "the strict independence line is missing entirely"
    assert "n/a" in strict[0]
    assert "0" not in strict[0].split("n/a")[0].split("strict")[-1]


def test_cli_corpus_show_renders_root_cause_and_target_tool(tmp_path: Path, capsys) -> None:
    """`corpus show` surfaces both new fields, key and note."""
    from belay import cli

    corpus = tmp_path / "corpus"
    write_case(corpus / "a", _tp_case("a", "required-test-update", "edit_file", "trace-x"))

    assert cli.main(["corpus", "show", "a", "--corpus-dir", str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "required-test-update" in out
    assert "edit_file" in out


def test_cli_corpus_show_marks_an_absent_root_cause_as_absent(tmp_path: Path, capsys) -> None:
    """An unadjudicated case shows the cause as absent, not as an empty string."""
    from belay import cli

    corpus = tmp_path / "corpus"
    write_case(corpus / "a", _case(case_id="a"))

    assert cli.main(["corpus", "show", "a", "--corpus-dir", str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "root_cause" in out
    assert "(absent)" in out


def test_cli_corpus_list_shows_the_root_cause_key(tmp_path: Path, capsys) -> None:
    """`corpus list` carries the grouping key, so the shape distribution is legible."""
    from belay import cli

    corpus = tmp_path / "corpus"
    write_case(corpus / "a", _tp_case("a", "required-test-update", "edit_file", "trace-x"))

    assert cli.main(["corpus", "list", str(corpus)]) == 0
    assert "required-test-update" in capsys.readouterr().out


def test_cli_corpus_list_separates_a_long_case_id_from_its_label(tmp_path: Path, capsys) -> None:
    """A long case id does not run into the next column.

    The real corpus ids ("trace-pallets__flask-4992-turn10") overflowed the id
    column and rendered as "...turn10MATCH"-style run-together text.
    """
    from belay import cli

    corpus = tmp_path / "corpus"
    long_id = "trace-pallets__flask-4992-turn10"
    write_case(corpus / long_id, _case(case_id=long_id))

    assert cli.main(["corpus", "list", str(corpus)]) == 0
    out = capsys.readouterr().out
    assert f"{long_id}pending" not in out
    assert long_id in out and "pending" in out
