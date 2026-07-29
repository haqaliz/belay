"""A corpus case bundles the TASK pre-state (turn 0), not only the target turn's.

`no-assertion-weakening` is judged against **turn 0's** tree — that is what stops an agent
editing a scratch test it wrote earlier in the same run from reading as cheating. But a case
bundled exactly one pre-state, the TARGET turn's, so on every non-zero-turn case the rule
resolved nothing and answered UNVERIFIED. Fail-closed and honest, and useless as a fixture:
the unit's binding criterion is that the 7 audited cases reach **PASS**, and an abstention
proves nothing.

So a case gains two artifacts, `task_manifest.json` + `task_prestate/`, composed exactly the
way the target pair already is (copy the tree, rewrite `tree_path` to the relative name).

## Resolution needs no change in `corpus/run.py` — and this file drives the real resolver

`replay.engine._manifest_for` globs `manifest_dir/*.json` and matches on the recorded
**handle, not the filename**, and `run_case` already passes `manifest_dir=case_dir`. So a
second manifest in the case dir resolves automatically. That is the whole design, so
`test_both_manifests_resolve_by_handle` drives the REAL `_manifest_for` rather than asserting
filenames — a design resting on a glob's behaviour must be tested against that glob.

## The turn-0 case bundles NOTHING extra, and that is a property, not an optimisation

When the target turn IS turn 0 the two handles are identical, so `add_case` skips the
duplicate and declares the task pre-state as the existing `manifest.json` / `prestate/`.
Writing both would put two same-handle manifests in one directory and leave which one
`sorted(glob)` returns as an *"it should be harmless"* no fixture exercises. Eliminating the
situation beats reasoning about it.

## Backward compatibility is a REQUIREMENT here, not an observation

A case written before this format has no turn-0 manifest, so the rule must reach UNVERIFIED
with a named cause — never PASS, never FAIL — and the case must classify **REGRESSION, not
SKIP**: a missing task pre-state is a case-FORMAT gap, identical on every box, and filing it
as SKIP (an environment gap) would let a real detector regression hide behind it. The upgrade
path is to re-add. Both are pinned here against the real `run_case` / `classify_case`.

The composition tests are PLATFORM-INDEPENDENT (synthetic manifests + fake trees + hand-built
records), matching `test_corpus_add.py`. Only the re-verification tests, which re-invoke a
server inside the macOS Seatbelt sandbox, are darwin-gated.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from belay.corpus.add import add_case
from belay.corpus.case import CASE_SCHEMA_VERSION, load_case
from belay.corpus.run import MATCH, REGRESSION, SKIP, run_case
from belay.replay.engine import _manifest_for
from belay.trace import TraceWriter
from belay.verify.invariants import (
    NO_TASK_PRESTATE_HANDLE,
    NO_TASK_PRESTATE_MANIFEST,
    Invariant,
)
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-07-29T00:00:00+00:00"

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_SERVER = FIXTURES / "weakening_editor_server.py"

STRONG_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)


# --- frame builders (mirroring the add / roundtrip apparatus) -------------------------


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "edit_file", "annotations": {"readOnlyHint": False}}]},
        }
    ).encode()


def _edit_file_call(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _recorded_reply(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "result": {
                "content": [{"type": "text", "text": "edited tests/test_auth.py"}],
                "isError": False,
            },
        }
    ).encode()


def _trace(tmp_path: Path, name: str, frames: list[tuple]):
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


# --- a synthetic TWO-turn run (platform-independent) ----------------------------------
#
# Two fake snapshot trees whose contents DIFFER, two manifests naming them, and records
# whose two `tools/call` frames carry the two handles. `add_case` on turn 1 must bundle
# turn 1's tree as `prestate/` and turn 0's as `task_prestate/`, so a mis-wire that copied
# the target tree twice is caught by the differing marker rather than by a filename.


def _fake_tree(root: Path, marker: str) -> Path:
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")
    (root / "marker.txt").write_text(marker, encoding="utf-8")
    return root


def _fake_manifest(manifest_dir: Path, handle: str, tree: Path) -> None:
    (manifest_dir / f"{handle}.json").write_text(
        json.dumps(
            {
                "handle": handle,
                "tree_path": str(tree),
                "backend": "clonefile",
                "capabilities": ["dir-mtimes", "hardlinks", "setuid"],
                "fidelity_gaps": [],
                "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _two_turn_run(tmp_path: Path):
    """A (records, manifest_dir) pair holding two turns with two DISTINCT pre-states."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    _fake_manifest(manifest_dir, "H0", _fake_tree(tmp_path / "snap-0", "turn-zero"))
    _fake_manifest(manifest_dir, "H1", _fake_tree(tmp_path / "snap-1", "turn-one"))

    records = _trace(
        tmp_path,
        "synth-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(3), {"status": "present", "handle": "H0"}),
            ("s2c", _recorded_reply(3), None),
            ("c2s", _edit_file_call(4), {"status": "present", "handle": "H1"}),
            ("s2c", _recorded_reply(4), None),
        ],
    )
    return records, manifest_dir


def _fail_verdict(turn: int) -> TurnVerdict:
    return TurnVerdict(
        turn_index=turn,
        tool_name="edit_file",
        status=Status.FAIL,
        sub_verdicts=[
            Verdict("A2", "replay", Status.PASS, None, None, "the recorded reply reproduced"),
            Verdict("A1", "invariant", Status.FAIL, ["tests/test_auth.py"], None, "weakened"),
        ],
        cause=None,
    )


def _add(tmp_path: Path, records, manifest_dir, turn: int) -> Path:
    return add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=turn,
        verdict=_fail_verdict(turn),
        manifest_dir=manifest_dir,
        server_command=[sys.executable, "editor.py"],
        invariants=[Invariant(scope=b"tests", rule="no-assertion-weakening")],
        replays=3,
        timeout=20.0,
        source_trace_id="synth-trace",
        captured_at=CAPTURED_AT,
    )


# --- 1. the artifact set: exactly SIX on a non-zero target turn -----------------------


def test_a_non_zero_turn_case_composes_exactly_six_artifacts(tmp_path):
    """Set equality, not containment: a subset check would let a stray file in unnoticed."""
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    names = {p.name for p in case_dir.iterdir()}
    assert names == {
        "case.json",
        "trace.jsonl",
        "manifest.json",
        "prestate",
        "task_manifest.json",
        "task_prestate",
    }, names
    assert (case_dir / "task_prestate").is_dir()


# --- 2. the two manifests carry DIFFERENT handles and different relative trees --------


def test_the_two_manifests_are_distinct_and_neither_overwrites_the_other(tmp_path):
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    target = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    task = json.loads((case_dir / "task_manifest.json").read_text(encoding="utf-8"))

    assert target["handle"] == "H1", target
    assert target["tree_path"] == "prestate", target
    assert task["handle"] == "H0", task
    assert task["tree_path"] == "task_prestate", task


# --- 3. `task_prestate/` holds turn 0's REAL tree, not a second copy of the target's ---


def test_task_prestate_holds_turn_zeros_tree_not_the_targets(tmp_path):
    """Asserted on a file whose content DIFFERS between the two turns.

    A mis-wire that copied the target tree twice would satisfy every filename and handle
    assertion above and still bundle the wrong bytes — which is the failure that produces a
    fixture that looks green and judges the wrong baseline.
    """
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    assert (case_dir / "task_prestate" / "marker.txt").read_text(encoding="utf-8") == "turn-zero"
    assert (case_dir / "prestate" / "marker.txt").read_text(encoding="utf-8") == "turn-one"


# --- 4. resolution is BY HANDLE, through the real `_manifest_for` ---------------------


def test_both_manifests_resolve_by_handle_through_the_real_resolver(tmp_path):
    """The whole design rests on `_manifest_for`'s by-handle glob, so drive it, not a stub."""
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    assert _manifest_for("H0", case_dir) == case_dir / "task_manifest.json"
    assert _manifest_for("H1", case_dir) == case_dir / "manifest.json"


# --- 5. the bundle is DECLARED in case.json, and the declaration is fail-closed -------


def test_the_declaration_names_the_handle_and_both_bundled_filenames(tmp_path):
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    case = load_case(case_dir)
    assert case.task_prestate == {
        "handle": "H0",
        "tree": "task_prestate",
        "manifest": "task_manifest.json",
    }, case.task_prestate
    assert case.schema_version == CASE_SCHEMA_VERSION == 2


def test_a_case_without_a_task_prestate_key_loads_and_declares_nothing(tmp_path):
    """Optional-and-defaulted, like `root_cause`: `_REQUIRED_FIELDS` is closed and fail-closed,
    so a required new field would make every case already on disk unloadable."""
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    raw = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    del raw["task_prestate"]
    (case_dir / "case.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")

    assert load_case(case_dir).task_prestate is None


@pytest.mark.parametrize(
    "malformed",
    [
        "task_prestate",  # not an object
        {},  # neither shape
        {"handle": "H0", "tree": "task_prestate"},  # bundled shape missing `manifest`
        {"handle": "H0", "tree": 7, "manifest": "task_manifest.json"},  # wrong type
        {"status": "absent"},  # absent shape with no cause
        {"status": "bundled", "cause": "x"},  # a status this loader does not know
    ],
)
def test_a_malformed_task_prestate_is_a_named_valueerror(tmp_path, malformed):
    """The fail-closed shape every other field in `case.py` has: never a silent default."""
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    raw = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    raw["task_prestate"] = malformed
    (case_dir / "case.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="task_prestate"):
        load_case(case_dir)


# --- 5b. the turn-0 ruling: ONE manifest on disk, and the declaration resolves to it ---


def test_a_turn_zero_case_has_exactly_one_manifest_and_declares_it(tmp_path):
    """Two same-handle manifests must never coexist in one case dir.

    At turn 0 the task pre-state IS the target's, so the duplicate is skipped and the
    declaration points at the existing pair. Asserted two ways — the artifact set, and the
    declaration resolving through the REAL `_manifest_for` to that same file — so no future
    reader has to reason about which of two equivalent manifests a `sorted(glob)` returns.
    """
    records, manifest_dir = _two_turn_run(tmp_path)
    case_dir = _add(tmp_path, records, manifest_dir, turn=0)

    names = {p.name for p in case_dir.iterdir()}
    assert names == {"case.json", "trace.jsonl", "manifest.json", "prestate"}, names
    assert not (case_dir / "task_manifest.json").exists()
    assert not (case_dir / "task_prestate").exists()

    declared = load_case(case_dir).task_prestate
    assert declared == {"handle": "H0", "tree": "prestate", "manifest": "manifest.json"}
    assert _manifest_for(declared["handle"], case_dir) == case_dir / declared["manifest"]


# --- 9. add-time fail-closed: RECORD the absence, never refuse the case ---------------


def test_an_unresolvable_turn_zero_handle_still_composes_a_case(tmp_path):
    """A case with a target pre-state but no TASK pre-state is still fully replayable — A2 is
    unaffected and only A1 abstains. Raising would send the turn to `flagged_unaddable` and
    lose the case entirely, trading an honest partial verdict for no evidence at all."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    _fake_manifest(manifest_dir, "H1", _fake_tree(tmp_path / "snap-1", "turn-one"))
    records = _trace(
        tmp_path,
        "synth-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(3), {"status": "absent"}),
            ("s2c", _recorded_reply(3), None),
            ("c2s", _edit_file_call(4), {"status": "present", "handle": "H1"}),
            ("s2c", _recorded_reply(4), None),
        ],
    )

    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    names = {p.name for p in case_dir.iterdir()}
    assert names == {"case.json", "trace.jsonl", "manifest.json", "prestate"}, names
    assert load_case(case_dir).task_prestate == {
        "status": "absent",
        "cause": NO_TASK_PRESTATE_HANDLE,
    }


def test_an_unresolvable_turn_zero_manifest_still_composes_a_case(tmp_path):
    """The second variant: turn 0's handle is `present` but no manifest names it."""
    records, manifest_dir = _two_turn_run(tmp_path)
    (manifest_dir / "H0.json").unlink()

    case_dir = _add(tmp_path, records, manifest_dir, turn=1)

    names = {p.name for p in case_dir.iterdir()}
    assert names == {"case.json", "trace.jsonl", "manifest.json", "prestate"}, names
    assert load_case(case_dir).task_prestate == {
        "status": "absent",
        "cause": NO_TASK_PRESTATE_MANIFEST,
    }


# --- 6/7/8. backward compatibility, against the REAL re-verification ------------------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="run_case re-invokes the server inside the macOS Seatbelt sandbox",
)


def _real_two_turn_run(tmp_path: Path):
    """A real two-snapshot run: turn 0 over the STRONG test, turn 1 over it unchanged.

    The weakening editor overwrites `tests/test_auth.py` with a gutted body under replay, so
    judged against turn 0's tree the resulting content has lost an assertion — an A1 FAIL
    that the task pre-state is REQUIRED to reach.
    """
    from belay.replay.persist import persist_snapshot
    from belay.snapshot.substrate import present_handle, take_snapshot

    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")

    manifest_dir = tmp_path / "run-manifests"
    snap0 = take_snapshot(work, tmp_path / "snap-0")
    persist_snapshot(snap0, manifest_dir / f"{snap0.manifest.handle}.json")
    snap1 = take_snapshot(work, tmp_path / "snap-1")
    persist_snapshot(snap1, manifest_dir / f"{snap1.manifest.handle}.json")

    records = _trace(
        tmp_path,
        "flagged-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(3), present_handle(snap0)),
            ("s2c", _recorded_reply(3), None),
            ("c2s", _edit_file_call(4), present_handle(snap1)),
            ("s2c", _recorded_reply(4), None),
        ],
    )
    return records, manifest_dir


def _real_case(tmp_path: Path, turn: int) -> Path:
    """`verify_turn` -> `add_case` on a real run, at `turn`."""
    from belay.verify.turn import verify_turn

    records, manifest_dir = _real_two_turn_run(tmp_path)
    invariants = [Invariant(scope=b"tests", rule="no-assertion-weakening")]
    verdict = verify_turn(
        records,
        turn,
        server_command=[sys.executable, str(EDITOR_SERVER)],
        manifest_dir=manifest_dir,
        invariants=invariants,
        replays=3,
    )
    assert verdict.status is Status.FAIL, verdict  # precondition: a caught A1 FAIL
    return add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=turn,
        verdict=verdict,
        manifest_dir=manifest_dir,
        server_command=[sys.executable, str(EDITOR_SERVER)],
        invariants=invariants,
        replays=3,
        timeout=20.0,
        source_trace_id="flagged-trace",
        captured_at=CAPTURED_AT,
    )


def _strip_to_legacy(case_dir: Path) -> None:
    """Make an added case LEGACY-shaped: the four old artifacts, no declaration."""
    shutil.rmtree(case_dir / "task_prestate", ignore_errors=True)
    (case_dir / "task_manifest.json").unlink(missing_ok=True)
    raw = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    raw.pop("task_prestate", None)
    (case_dir / "case.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")


@pytestmark_darwin
def test_a_new_non_zero_turn_case_replays_to_its_recorded_verdict(tmp_path):
    """The point of the whole aspect: a non-zero-turn case now re-verifies from itself alone."""
    case_dir = _real_case(tmp_path, turn=1)
    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)


@pytestmark_darwin
def test_a_legacy_non_zero_turn_case_is_unverified_never_pass_and_never_fail(tmp_path):
    """R3: absent task pre-state -> A1 UNVERIFIED with a NAMED cause.

    Pinned on a real legacy-shaped case rather than left to fall out of `_manifest_for`
    returning `None` — incidental correctness is what `interop-merge-repair` was written to
    clean up, and a property nothing asserts is a property that silently stops holding.
    """
    from belay.verify.turn import verify_turn

    case_dir = _real_case(tmp_path, turn=1)
    _strip_to_legacy(case_dir)

    case = load_case(case_dir)
    from belay.replay.reader import read_trace

    recomputed = verify_turn(
        read_trace(case_dir / "trace.jsonl").records,
        case.target_turn_index,
        server_command=case.server_command,
        manifest_dir=case_dir,
        invariants=[Invariant(scope=b"tests", rule="no-assertion-weakening")],
        replays=case.replays,
        timeout=case.timeout,
    )
    a1 = [v for v in recomputed.sub_verdicts if v.axis == "A1"]
    assert len(a1) == 1, recomputed.sub_verdicts
    assert a1[0].status is Status.UNVERIFIED, a1[0]
    assert NO_TASK_PRESTATE_MANIFEST in a1[0].message, a1[0].message
    assert recomputed.cause is not None


@pytestmark_darwin
def test_a_legacy_non_zero_turn_case_classifies_regression_not_skip(tmp_path):
    """R4: a missing task pre-state is a case-FORMAT gap, identical on every box.

    Filing it as SKIP ("this box could not evaluate the case") would let a real detector
    regression hide behind an environment excuse. The REGRESSION is the signal telling the
    operator to re-add, and `_SKIP_CAUSES` must not be widened to quiet it.
    """
    case_dir = _real_case(tmp_path, turn=1)
    _strip_to_legacy(case_dir)

    result = run_case(case_dir)
    assert result.outcome == REGRESSION, (result.outcome, result.skip_reason)
    assert result.outcome != SKIP


@pytestmark_darwin
def test_a_legacy_case_whose_target_turn_is_zero_still_evaluates(tmp_path):
    """R3's turn-0 exception: such a case genuinely HAS the baseline — its one manifest IS
    turn 0's — so it must reach a real verdict, not abstain. `test_corpus_roundtrip.py`'s
    roundtrip silently depends on this."""
    case_dir = _real_case(tmp_path, turn=0)
    _strip_to_legacy(case_dir)

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)
