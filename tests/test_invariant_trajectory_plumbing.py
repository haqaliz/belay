"""A1 / trajectory-rule Phase 2: the rule is DECLARED, and structurally never per-turn.

`suite-before-success-claim` is the instance-level rule that the funded mint's exposure
gate demanded: "the suite must be executed before a success claim", judged against
observed replay effects, not test-file content. Phase 1 shipped its trigger, the claim
classifier; this phase wires the RULE into the invariant machinery. Two properties are
load-bearing, and both are pinned here:

- **Declared.** `load_invariants` accepts it from an operator file (any scope string —
  scope is meaningless for an instance-level rule), and `default_invariants()` ships it
  on, alongside the two test-path weakening rules.
- **Structurally per-turn-excluded — the poisoning hazard.** A1 today is per-turn and
  REPLAYED-only. If this rule were per-turn-evaluated it would emit an A1 sub-verdict on
  every turn, and since UNVERIFIED outranks PASS, every turn would reduce to UNVERIFIED
  -> `NO_VERIFIABLE_TURNS` -> `INSTRUMENT SUSPECT`. The rule is evaluated ONCE per
  instance (Phase 3); `verify_turn` must never see it. `test_declaring_the_rule_changes
  _no_per_turn_verdict` drives the REAL `verify_turn` twice — same trace, same invariants
  list, once with the rule declared and once without — and asserts the per-turn
  sub-verdicts are identical in length, axis, status and message: declaring the rule
  adds no sub-verdict and changes no status.

The rig mirrors `test_invariant_weakening_rule.py`: real `TraceWriter` records, a real
persisted turn-0 snapshot, a real BTH-1 delta between two real trees, `replay_turn`
stubbed to a REPLAYED reply. No network, deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.replay.persist import persist_snapshot
from belay.snapshot.bth1 import diff_records, scan_tree
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify import turn as turn_module
from belay.verify.invariants import (
    CONTENT_GROUNDED_RULES,
    RULE_NO_ASSERTION_WEAKENING,
    RULE_SUITE_BEFORE_SUCCESS_CLAIM,
    Invariant,
    default_invariants,
    load_invariants,
)
from belay.verify.turn import verify_turn

STRONG = b"def test_rejects_wrong_password():\n    assert not authenticate('a', 'wrong')\n"
GUTTED = b"def test_rejects_wrong_password():\n    assert True\n"

TESTS = Invariant(scope=b"tests", rule=RULE_NO_ASSERTION_WEAKENING)
TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)


# --- (a) the loader: the rule is declared, and fail-closed is preserved -----------------


def test_load_invariants_accepts_the_trajectory_rule_with_any_scope(tmp_path: Path) -> None:
    """An operator file declaring the rule loads — and scope is NOT validated for it.

    The rule judges the whole trajectory, so no path subtree scopes it; any scope string
    is accepted (here the empty string, the shape `default_invariants()` itself emits).
    """
    path = tmp_path / "inv.json"
    path.write_text(json.dumps([{"scope": "", "rule": RULE_SUITE_BEFORE_SUCCESS_CLAIM}]))

    assert load_invariants(path) == [TRAJECTORY]


def test_load_invariants_still_rejects_an_unknown_rule(tmp_path: Path) -> None:
    """C15, re-pinned on this phase: a rule Belay does not understand is still a ValueError.

    Extending `_KNOWN_RULES` must never soften the loader — silently dropping a declared
    rule would verify the run against less than the operator asked for.
    """
    path = tmp_path / "inv.json"
    path.write_text(json.dumps([{"scope": "", "rule": "make-coffee"}]))

    with pytest.raises(ValueError) as excinfo:
        load_invariants(path)

    assert "make-coffee" in str(excinfo.value)


# --- (b) THE POISONING GUARD: declaring the rule changes no per-turn verdict -------------


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    """Write `files` (relative path -> bytes) under `root` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


def _tools_list() -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "edit_file", "annotations": {"readOnlyHint": False}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call(msg_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _reply(msg_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": "edited"}], "isError": False},
        }
    ).encode()


def _record(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    """Record `(direction, raw, state_handle_or_None)` through the REAL trace writer."""
    trace_dir = tmp_path / name
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    path = sorted(trace_dir.glob("*.jsonl"))[0]
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def _snapshotted(tmp_path: Path, name: str, files: dict[str, bytes]):
    """A real workspace, snapshotted and persisted: `(present_handle, manifest_dir)`."""
    work = _tree(tmp_path / f"{name}-work", files)
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap), manifest_dir


def _sub_verdict_shape(verdict) -> tuple:
    """The full per-turn shape: reduced status + every sub-verdict, verbatim."""
    return (
        verdict.status,
        verdict.cause,
        tuple((v.axis, v.kind, v.status, v.message) for v in verdict.sub_verdicts),
    )


def test_declaring_the_rule_changes_no_per_turn_verdict(tmp_path: Path, monkeypatch) -> None:
    """The poisoning guard, on the REAL `verify_turn`: zero verdict change from the rule.

    Same trace, same invariants list, twice — once with `suite-before-success-claim`
    declared, once without. The per-turn sub-verdicts must be identical in length, axis,
    status and message: an instance-level rule adds no per-turn sub-verdict and changes
    no status. If this rule ever leaked into the per-turn loop, it would emit an A1
    sub-verdict on every turn and (UNVERIFIED outranking PASS) poison every run into
    `NO_VERIFIABLE_TURNS` -> `INSTRUMENT SUSPECT`.
    """
    zero, manifest_dir = _snapshotted(tmp_path, "t0", {"tests/test_x.py": STRONG})
    records = _record(
        tmp_path, "trace",
        _tools_list() + [("c2s", _call(2), zero), ("s2c", _reply(2), None)],
    )
    workspace = _tree(tmp_path / "ws", {"tests/test_x.py": GUTTED})
    delta = diff_records(scan_tree(tmp_path / "t0-work"), scan_tree(workspace))
    monkeypatch.setattr(
        turn_module,
        "replay_turn",
        lambda *a, **k: TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=_reply(2),
            replayed_reply=_reply(2),
            delta=delta,
            workspace=str(workspace),
        ),
    )

    without = verify_turn(
        records, 0,
        server_command=["unused"], manifest_dir=manifest_dir,
        invariants=[TESTS],
    )
    declared = verify_turn(
        records, 0,
        server_command=["unused"], manifest_dir=manifest_dir,
        invariants=[TESTS, TRAJECTORY],
    )

    assert _sub_verdict_shape(declared) == _sub_verdict_shape(without)
    a1 = [v for v in declared.sub_verdicts if v.axis == "A1"]
    assert len(a1) == 1, a1  # exactly the per-turn rule; the trajectory rule added nothing


# --- (c) the default set: the rule ships on, alongside the two test-path rules -----------


def test_default_invariants_declares_the_trajectory_rule() -> None:
    """`default_invariants()` ships the rule ON (R3), with an empty scope.

    Scope is not meaningful for an instance-level rule — there is no path subtree to
    scope — so it is declared `b""`, and the two test-path weakening rules are still
    present.
    """
    defaults = default_invariants()

    weakening = [inv for inv in defaults if inv.rule == RULE_NO_ASSERTION_WEAKENING]
    assert sorted(inv.scope for inv in weakening) == [b"testing", b"tests"], defaults

    trajectory = [inv for inv in defaults if inv.rule == RULE_SUITE_BEFORE_SUCCESS_CLAIM]
    assert trajectory == [TRAJECTORY], defaults


# --- (d) the category guard: every known rule is grounded in exactly one of three sets ----


def test_every_known_rule_belongs_to_exactly_one_grounding_category() -> None:
    """The three grounding sets partition `_KNOWN_RULES` — no rule is left ungrounded.

    A rule that joined `_KNOWN_RULES` without joining the delta-grounded, the
    content-grounded OR the instance-level set would be accepted from an operator file
    and then evaluated with no grounding on every turn — an abstention loophole wearing a
    wiring bug's coat. The instance-level set closes that door for trajectory rules
    differently from the other two: they are excluded from per-turn evaluation BY
    CONSTRUCTION, so no trees are needed and no loophole exists.
    """
    from belay.verify.invariants import _DELTA_GROUNDED_RULES, _KNOWN_RULES, INSTANCE_LEVEL_RULES

    assert RULE_SUITE_BEFORE_SUCCESS_CLAIM in INSTANCE_LEVEL_RULES
    assert _KNOWN_RULES == CONTENT_GROUNDED_RULES | _DELTA_GROUNDED_RULES | INSTANCE_LEVEL_RULES
    assert not (CONTENT_GROUNDED_RULES & INSTANCE_LEVEL_RULES)
    assert not (_DELTA_GROUNDED_RULES & INSTANCE_LEVEL_RULES)
