"""A1 / C5, invariant-library aspect 1: the `no-create` and `no-delete` delta rules.

Two new delta-grounded rules join `read-only`: `no-create` (nothing may APPEAR under the
scope) and `no-delete` (nothing under the scope may DISAPPEAR). Both are decided from the
BTH-1 `FieldDiff` structure alone — created is `field is None and left is None`, deleted
is `field is None and right is None` — with the SAME raw byte-prefix scope semantics as
`read-only`, preserving the prefix-vs-segment asymmetry against
`no-assertion-weakening` exactly. No content trees are needed for either rule, so the
call-site tree resolution in `verify/turn.py` must not pay for them.

The honesty lines, mirrored from the `read-only` branch:

- `delta is None` -> UNVERIFIED, never PASS: an unobserved effect cannot satisfy an
  invariant.
- FAIL names the rule and the violating path(s); the message is rule-generic — the rule
  name comes from the invariant, never hard-coded "read-only".
- near-miss prefixes (`testsuite/` vs scope `tests/`) do not fire: byte-prefix, not
  substring.
- an empty scope `b""` is whole-tree semantics, exactly like `read-only`.

The trees here are real directories written by the test, and the deltas are real BTH-1
diffs (`diff_records(scan_tree(pre), scan_tree(post))`) — the house pattern from
`tests/test_inferred_invariants.py` — rather than hand-built `FieldDiff`s, so the
created/deleted side markers are exercised the way replay produces them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.snapshot.bth1 import FieldDiff, diff_records, scan_tree
from belay.verify.invariants import (
    CONTENT_GROUNDED_RULES,
    INSTANCE_LEVEL_RULES,
    RULE_NO_CREATE,
    RULE_NO_DELETE,
    _DELTA_GROUNDED_RULES,
    _KNOWN_RULES,
    Invariant,
    evaluate_invariant,
    load_invariants,
)
from belay.verify.verdict import Status


# --- the rig: two real trees and the real BTH-1 delta between them ---------------------


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    """Write `files` (relative path -> bytes) under `root` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


def _delta(tmp_path: Path, pre: dict[str, bytes], post: dict[str, bytes], *, name: str = "pair"):
    """The REAL BTH-1 delta between two real trees — the shape replay hands A1."""
    pre_root = _tree(tmp_path / f"{name}-pre", pre)
    post_root = _tree(tmp_path / f"{name}-post", post)
    return diff_records(scan_tree(pre_root), scan_tree(post_root))


# --- Phase 1.1: the loader accepts the two new rules; the partition stays whole --------


def test_loader_accepts_no_create_rule(tmp_path: Path) -> None:
    """An operator file declaring `no-create` loads as a known, byte-scoped invariant.

    The rule was a reserved name the loader rejected by design; it now loads exactly like
    `read-only` does, with the scope encoded to raw bytes.
    """
    path = tmp_path / "invariants.json"
    path.write_text(json.dumps([{"scope": "scratch/", "rule": "no-create"}]))

    assert load_invariants(path) == [Invariant(scope=b"scratch/", rule=RULE_NO_CREATE)]


def test_loader_accepts_no_delete_rule(tmp_path: Path) -> None:
    """An operator file declaring `no-delete` loads as a known, byte-scoped invariant."""
    path = tmp_path / "invariants.json"
    path.write_text(json.dumps([{"scope": "scratch/", "rule": "no-delete"}]))

    assert load_invariants(path) == [Invariant(scope=b"scratch/", rule=RULE_NO_DELETE)]


def test_no_create_and_no_delete_are_known_and_delta_grounded() -> None:
    """Both names join `_KNOWN_RULES` AND `_DELTA_GROUNDED_RULES`, and the three grounding
    sets still partition the known rules — no rule is left ungrounded.

    A rule that joined `_KNOWN_RULES` without joining a grounding set would be accepted
    from an operator file and then evaluated with no grounding on every turn — the
    abstention loophole wearing a wiring bug's coat (mirrors the pin at
    `tests/test_invariant_trajectory_plumbing.py:249`, asserted here in full).
    """
    assert RULE_NO_CREATE in _KNOWN_RULES
    assert RULE_NO_DELETE in _KNOWN_RULES
    assert RULE_NO_CREATE in _DELTA_GROUNDED_RULES
    assert RULE_NO_DELETE in _DELTA_GROUNDED_RULES
    assert _KNOWN_RULES == CONTENT_GROUNDED_RULES | _DELTA_GROUNDED_RULES | INSTANCE_LEVEL_RULES
    assert not (CONTENT_GROUNDED_RULES & _DELTA_GROUNDED_RULES)
    assert not (CONTENT_GROUNDED_RULES & INSTANCE_LEVEL_RULES)
    assert not (_DELTA_GROUNDED_RULES & INSTANCE_LEVEL_RULES)


def test_unknown_rule_is_still_rejected_by_name(tmp_path: Path) -> None:
    """An unknown rule stays a named `ValueError` from the loader (regression pin,
    mirrors `tests/test_invariants.py:141-153`).

    The two new names did not open the loader to arbitrary rules — `no-rename` is not
    implemented and must be rejected, not silently dropped.
    """
    path = tmp_path / "invariants.json"
    path.write_text(json.dumps([{"scope": "x", "rule": "no-rename"}]))

    with pytest.raises(ValueError) as excinfo:
        load_invariants(path)

    assert "no-rename" in str(excinfo.value)


# --- Phase 1.2: evaluation from the BTH-1 delta (byte-prefix, rule-generic) ------------


def test_no_create_created_path_under_scope_fails(tmp_path: Path) -> None:
    """`no-create` scope `b"scratch/"` + a file CREATED under it -> FAIL naming rule+path.

    Created is the BTH-1 side marker `field is None and left is None` — the path exists
    only on the post side. The verdict keeps the A1 invariant sub-verdict shape, and the
    message names the rule and the violating path.
    """
    inv = Invariant(scope=b"scratch/", rule=RULE_NO_CREATE)
    delta = _delta(tmp_path, {}, {"scratch/x.txt": b"created"})

    verdict = evaluate_invariant(inv, delta, turn_index=3)

    assert verdict.axis == "A1"
    assert verdict.kind == "invariant"
    assert verdict.status is Status.FAIL
    assert "no-create" in verdict.message
    assert "scratch/x.txt" in verdict.message


def test_no_delete_deleted_path_under_scope_fails(tmp_path: Path) -> None:
    """`no-delete` scope `b"scratch/"` + a file DELETED under it -> FAIL naming rule+path.

    Deleted is the BTH-1 side marker `field is None and right is None` — the path exists
    only on the pre side.
    """
    inv = Invariant(scope=b"scratch/", rule=RULE_NO_DELETE)
    delta = _delta(tmp_path, {"scratch/x.txt": b"gone"}, {})

    verdict = evaluate_invariant(inv, delta, turn_index=3)

    assert verdict.axis == "A1"
    assert verdict.kind == "invariant"
    assert verdict.status is Status.FAIL
    assert "no-delete" in verdict.message
    assert "scratch/x.txt" in verdict.message


def test_clean_delta_content_change_passes_both_rules(tmp_path: Path) -> None:
    """The two rules judge PRESENCE, not content: a content-only change under scope -> PASS.

    A modified file is neither created nor deleted, so both rules hold even though the
    file lives under the scope.
    """
    delta = _delta(tmp_path, {"scratch/x.txt": b"old"}, {"scratch/x.txt": b"new"})

    for rule in (RULE_NO_CREATE, RULE_NO_DELETE):
        inv = Invariant(scope=b"scratch/", rule=rule)
        verdict = evaluate_invariant(inv, delta, turn_index=0)
        assert verdict.status is Status.PASS, verdict.message


def test_creation_and_deletion_outside_scope_pass(tmp_path: Path) -> None:
    """Byte-prefix scope: a created/deleted path OUTSIDE `scratch/` -> PASS."""
    no_create = Invariant(scope=b"scratch/", rule=RULE_NO_CREATE)
    created_outside = _delta(tmp_path, {}, {"other/x.txt": b"created"}, name="created-outside")
    assert evaluate_invariant(no_create, created_outside, 0).status is Status.PASS

    no_delete = Invariant(scope=b"scratch/", rule=RULE_NO_DELETE)
    deleted_outside = _delta(tmp_path, {"other/x.txt": b"gone"}, {}, name="deleted-outside")
    assert evaluate_invariant(no_delete, deleted_outside, 0).status is Status.PASS


def test_near_miss_prefix_does_not_fire(tmp_path: Path) -> None:
    """`b"tests/"` must NOT match `b"testsuite/x"` — a directory prefix, not a substring.

    The read-only near-miss pin (`tests/test_invariant_weakening_rule.py:222-251`)
    reproduced for the new rules: a created/deleted file under `testsuite/` passes both.
    """
    no_create = Invariant(scope=b"tests/", rule=RULE_NO_CREATE)
    created = _delta(tmp_path, {}, {"testsuite/x.txt": b"created"}, name="near-miss-create")
    assert evaluate_invariant(no_create, created, 0).status is Status.PASS

    no_delete = Invariant(scope=b"tests/", rule=RULE_NO_DELETE)
    deleted = _delta(tmp_path, {"testsuite/x.txt": b"gone"}, {}, name="near-miss-delete")
    assert evaluate_invariant(no_delete, deleted, 0).status is Status.PASS


def test_empty_scope_is_whole_tree(tmp_path: Path) -> None:
    """Empty scope `b""` -> whole-tree semantics: ANY created/deleted path fires.

    Mirrors `read-only`'s empty-prefix behaviour — every path starts with the empty
    prefix, so a creation deep in the tree FAILs `no-create` and a deletion there FAILs
    `no-delete`.
    """
    no_create = Invariant(scope=b"", rule=RULE_NO_CREATE)
    created = _delta(tmp_path, {}, {"a/b/x.txt": b"created"}, name="whole-tree-create")
    assert evaluate_invariant(no_create, created, 0).status is Status.FAIL

    no_delete = Invariant(scope=b"", rule=RULE_NO_DELETE)
    deleted = _delta(tmp_path, {"a/b/x.txt": b"gone"}, {}, name="whole-tree-delete")
    assert evaluate_invariant(no_delete, deleted, 0).status is Status.FAIL


def test_delta_none_is_unverified_never_pass(tmp_path: Path) -> None:
    """`delta is None` -> UNVERIFIED with the rule named, never PASS.

    Mirrors the delta-None pin (`tests/test_invariant_eval.py:95-107`) for the new rules:
    an unobserved effect cannot satisfy an invariant.
    """
    for rule in (RULE_NO_CREATE, RULE_NO_DELETE):
        inv = Invariant(scope=b"scratch/", rule=rule)
        verdict = evaluate_invariant(inv, None, turn_index=2)
        assert verdict.status is Status.UNVERIFIED
        assert verdict.status is not Status.PASS
        assert rule in verdict.message