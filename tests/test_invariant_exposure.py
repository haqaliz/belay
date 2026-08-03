"""A1 exposure accounting: the count the rule already makes, as a structured fact.

`_evaluate_content_rule` already counts `compared` (files it judged) and `in_scope` (files
the delta touched under scope) to build its PASS/FAIL prose. Nothing downstream can read
those counts, so a PASS that judged zero files (the rule reached no comparison) is
indistinguishable from a PASS that judged and found nothing wrong — a "false zero" that
this unit closes by putting the count Belay already has into `Verdict.expected["exposure"]`.

**Absence is the absence of the key** — not `None`, not `{}`, never a fabricated `0`. Three
shapes:

- the five early abstains and every `read-only` return: no `exposure` key at all (the rule
  never got as far as counting anything);
- the file-budget abstain: `{"in_scope": M}` only — `compared` is never initialised at that
  point, and inventing a zero there would be a fabricated finding;
- FAIL, the post-judging abstain, and PASS: `{"compared": N, "in_scope": M}`, both real.

`test_every_content_return_path_reports_exposure_or_declares_none` is the enumeration: one
case per one of the nine `_evaluate_content_rule` return paths, so no path is left
unasserted. The four `read-only` paths are asserted separately, since they are a different
rule with no exposure concept at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from belay.snapshot.bth1 import diff_records, scan_tree
from belay.verify.invariants import (
    IN_SCOPE_FILE_BUDGET,
    NO_POST_STATE_TREE,
    NO_TASK_PRESTATE_HANDLE,
    NO_TASK_PRESTATE_TREE,
    RULE_NO_ASSERTION_WEAKENING,
    RULE_READ_ONLY,
    ContentRoots,
    Invariant,
    evaluate_invariant,
)
from belay.verify.verdict import Status

STRONG = b"def test_rejects_wrong_password():\n    assert not authenticate('a', 'wrong')\n"
GUTTED = b"def test_rejects_wrong_password():\n    assert True\n"

TESTS = Invariant(scope=b"tests", rule=RULE_NO_ASSERTION_WEAKENING)


# --- the rig: two real trees and the real BTH-1 delta between them, mirroring the sibling
# `test_invariant_weakening_rule.py` suite rather than hand-building `FieldDiff`s -----------


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


def _pair(tmp_path: Path, pre: dict[str, bytes], post: dict[str, bytes]):
    pre_root = _tree(tmp_path / "pre", pre)
    post_root = _tree(tmp_path / "post", post)
    delta = diff_records(scan_tree(pre_root), scan_tree(post_root))
    return ContentRoots(pre=pre_root, post=post_root), delta


# --- the nine-path enumeration ----------------------------------------------------------


def _delta_none(tmp_path, monkeypatch):
    verdict = evaluate_invariant(TESTS, None, 0, roots=ContentRoots(cause=None))
    return verdict, None


def _roots_none(tmp_path, monkeypatch):
    _roots, delta = _pair(tmp_path, {"tests/test_x.py": STRONG}, {"tests/test_x.py": GUTTED})
    verdict = evaluate_invariant(TESTS, delta, 0, roots=None)
    return verdict, None


def _roots_pre_or_post_none(tmp_path, monkeypatch):
    _roots, delta = _pair(tmp_path, {"tests/test_x.py": STRONG}, {"tests/test_x.py": GUTTED})
    verdict = evaluate_invariant(
        TESTS, delta, 0, roots=ContentRoots(cause=NO_TASK_PRESTATE_HANDLE)
    )
    return verdict, None


def _task_prestate_tree_missing(tmp_path, monkeypatch):
    roots, delta = _pair(tmp_path, {"tests/test_x.py": STRONG}, {"tests/test_x.py": GUTTED})
    gone = ContentRoots(pre=tmp_path / "vanished-pre", post=roots.post, cause=NO_TASK_PRESTATE_TREE)
    verdict = evaluate_invariant(TESTS, delta, 0, roots=gone)
    return verdict, None


def _post_state_tree_missing(tmp_path, monkeypatch):
    roots, delta = _pair(tmp_path, {"tests/test_x.py": STRONG}, {"tests/test_x.py": GUTTED})
    gone = ContentRoots(pre=roots.pre, post=tmp_path / "vanished-post", cause=NO_POST_STATE_TREE)
    verdict = evaluate_invariant(TESTS, delta, 0, roots=gone)
    return verdict, None


def _budget_exceeded(tmp_path, monkeypatch):
    from belay.verify import invariants as invariants_module

    monkeypatch.setattr(invariants_module, "MAX_IN_SCOPE_FILES", 1)
    roots, delta = _pair(
        tmp_path,
        {"tests/test_a.py": STRONG, "tests/test_b.py": STRONG},
        {"tests/test_a.py": GUTTED, "tests/test_b.py": GUTTED},
    )
    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)
    return verdict, {"in_scope": 2}


def _fail(tmp_path, monkeypatch):
    roots, delta = _pair(tmp_path, {"tests/test_x.py": STRONG}, {"tests/test_x.py": GUTTED})
    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)
    return verdict, {"compared": 1, "in_scope": 1}


def _abstain_after_judging(tmp_path, monkeypatch):
    roots, delta = _pair(
        tmp_path,
        {"tests/test_x.py": b"def test_x():\n    with pytest.raises(ValueError):\n        go()\n"},
        {"tests/test_x.py": b"def test_x():\n    assert go() is None\n"},
    )
    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)
    return verdict, {"compared": 1, "in_scope": 1}


def _pass(tmp_path, monkeypatch):
    roots, delta = _pair(
        tmp_path,
        {"tests/test_x.py": STRONG},
        {"tests/test_x.py": STRONG + b"\n\ndef test_new():\n    assert 1 + 1 == 2\n"},
    )
    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)
    return verdict, {"compared": 1, "in_scope": 1}


CASES = {
    "delta_none": (_delta_none, Status.UNVERIFIED),
    "roots_none": (_roots_none, Status.UNVERIFIED),
    "roots_pre_or_post_none": (_roots_pre_or_post_none, Status.UNVERIFIED),
    "task_prestate_tree_missing": (_task_prestate_tree_missing, Status.UNVERIFIED),
    "post_state_tree_missing": (_post_state_tree_missing, Status.UNVERIFIED),
    "budget_exceeded": (_budget_exceeded, Status.UNVERIFIED),
    "fail": (_fail, Status.FAIL),
    "abstain_after_judging": (_abstain_after_judging, Status.UNVERIFIED),
    "pass": (_pass, Status.PASS),
}


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_every_content_return_path_reports_exposure_or_declares_none(
    case_name: str, tmp_path: Path, monkeypatch
) -> None:
    """One case per one of the NINE `_evaluate_content_rule` return paths.

    Each asserts either the exact `{"compared", "in_scope"}` (or partial `{"in_scope"}`)
    pair, or that `"exposure"` is absent from `expected` entirely. This is the enumeration:
    if a path is added to the rule without a case here, this test's own docstring — and the
    aspect's spine — is broken.
    """
    builder, expected_status = CASES[case_name]

    verdict, expected_exposure = builder(tmp_path, monkeypatch)

    assert verdict.status is expected_status, verdict.message
    assert isinstance(verdict.expected, dict), verdict.expected
    if expected_exposure is None:
        assert "exposure" not in verdict.expected, verdict.expected
    else:
        assert verdict.expected.get("exposure") == expected_exposure, verdict.expected


# --- named criteria from the brief, each its own test ------------------------------------


def test_fail_path_reports_what_it_judged(tmp_path: Path) -> None:
    """A turn flagging 1 of N in-scope files reports BOTH counts — today it reports neither.

    One file is a same-turn addition (absent from the task pre-state, skipped rather than
    compared); the other is weakened. `in_scope` counts both; `compared` counts only the one
    the rule actually judged.
    """
    roots, delta = _pair(
        tmp_path,
        {"tests/test_x.py": STRONG},
        {
            "tests/test_x.py": GUTTED,
            "tests/test_new.py": b"def test_new():\n    assert 1 + 1 == 2\n",
        },
    )

    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)

    assert verdict.status is Status.FAIL, verdict.message
    assert verdict.expected["exposure"] == {"compared": 1, "in_scope": 2}, verdict.expected


def test_read_only_rule_declares_no_exposure(tmp_path: Path) -> None:
    """A `read-only` verdict never carries an `exposure` key, on any of its FOUR return
    paths — UNVERIFIED (delta unobserved), FAIL, PASS, and the not-delta-grounded abstain
    for an unimplemented rule. `read-only` has no exposure concept; a fabricated `0` there
    would make it indistinguishable from a content verdict that compared nothing.
    """
    read_only = Invariant(scope=b"tests/", rule=RULE_READ_ONLY)
    roots, delta = _pair(
        tmp_path, {"tests/test_x.py": STRONG}, {"tests/test_x.py": STRONG + b"\n"}
    )

    delta_unobserved = evaluate_invariant(read_only, None, 0)
    fail = evaluate_invariant(read_only, delta, 0, roots=roots)
    passed = evaluate_invariant(
        Invariant(scope=b"other/", rule=RULE_READ_ONLY), delta, 0, roots=roots
    )
    not_delta_grounded = evaluate_invariant(
        Invariant(scope=b"tests/", rule="not-a-real-rule"), delta, 0, roots=roots
    )

    assert [v.status for v in (delta_unobserved, fail, passed, not_delta_grounded)] == [
        Status.UNVERIFIED,
        Status.FAIL,
        Status.PASS,
        Status.UNVERIFIED,
    ]
    for verdict in (delta_unobserved, fail, passed, not_delta_grounded):
        assert isinstance(verdict.expected, dict), verdict.expected
        assert "exposure" not in verdict.expected, verdict.expected


def test_budget_abstain_reports_in_scope_without_fabricating_compared(
    tmp_path: Path, monkeypatch
) -> None:
    """The file-budget abstain carries `in_scope` but NEVER a fabricated `compared`.

    `compared` is not initialised at this point in the rule; inventing a zero here would be
    a fabricated finding, not an honestly reported absence.
    """
    from belay.verify import invariants as invariants_module

    monkeypatch.setattr(invariants_module, "MAX_IN_SCOPE_FILES", 1)
    roots, delta = _pair(
        tmp_path,
        {"tests/test_a.py": STRONG, "tests/test_b.py": STRONG},
        {"tests/test_a.py": GUTTED, "tests/test_b.py": GUTTED},
    )

    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)

    assert verdict.status is Status.UNVERIFIED, verdict.message
    assert verdict.expected["cause"] == IN_SCOPE_FILE_BUDGET, verdict.expected
    exposure = verdict.expected["exposure"]
    assert exposure == {"in_scope": 2}, exposure
    assert "compared" not in exposure, exposure


def test_compared_counts_judgement_attempts_including_deletions(tmp_path: Path) -> None:
    """`compared` means JUDGEMENT ATTEMPTS, not decisions — it includes a deletion.

    Pinned so a later refactor cannot silently redefine `compared` to mean "decided": the
    counter increments before `_judge_file` runs, and a deletion IS a judgement attempt even
    though there is no resulting content to diff.
    """
    roots, delta = _pair(tmp_path, {"tests/test_x.py": STRONG}, {})

    verdict = evaluate_invariant(TESTS, delta, 0, roots=roots)

    assert verdict.status is Status.FAIL, verdict.message
    assert verdict.expected["exposure"] == {"compared": 1, "in_scope": 1}, verdict.expected
