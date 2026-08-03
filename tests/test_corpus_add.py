"""C6 Phase 2: `corpus add` composes a SELF-CONTAINED, labeled case from a flagged run.

`add_case` is the seam between a caught failure and the corpus that regresses against it.
It must produce a case that survives deletion of the original run — the trace slice, the
pre-state TREE (copied, not referenced), the A1 policy, the recomputed expected verdict —
and it must take the HUMAN label as a pass-through input it NEVER derives from the verdict.

Two claims carry this file, and each has a control:

1. **The engine never labels (D3).** `add_case` on a FAILing verdict with the label
   defaulted stores `human_label == "pending"`, NOT "true-positive". This is the integrity
   of the whole corpus metric: labeling a case true-positive because the engine FAILed it
   would manufacture 100% precision by construction. `test_engine_never_labels_*` is the
   control — it is written to FAIL against any implementation that derives the label from
   the verdict, and the RED was captured against exactly such a stub before the real
   pass-through code was written.
2. **Self-contained (moat #2 durability).** After `add_case`, DELETING the original
   manifest dir AND the original snapshot tree still leaves a case that restores its
   pre-state — because the tree was COPIED into `<case>/prestate/` and the manifest's
   `tree_path` rewritten to the relative `"prestate"`. `test_self_contained_survives_rm`
   is the durability proof, and it runs the REAL snapshot/restore apparatus (darwin-gated).

The composition tests (artifact set, tree_path, expected shape, label pass-through) are
PLATFORM-INDEPENDENT: they feed `add_case` a synthetic manifest + fake tree + hand-built
records + a hand-built `TurnVerdict`, so the metric-integrity control is not gated behind
macOS. Only the survives-rm restore, which re-executes the real snapshot backend, is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from belay.corpus.add import add_case
from belay.corpus.case import load_case
from belay.trace import TraceWriter
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-07-18T00:00:00+00:00"


# --- shared frame builders (mirroring the launch-demo apparatus) ----------------------


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


def _edit_file_call(call_id: int = 3) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _recorded_reply(call_id: int = 3) -> bytes:
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
    """Record `frames` (dir, raw, state_handle_or_None) via the real writer; read back.

    Verbatim from `test_launch_demo._trace`: going through `TraceWriter` keeps the records
    the exact envelope the engine reads in production, and `set_state_handle` stamps the
    `tools/call` frame with its pre-state handle the way the gate does.
    """
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


# --- a synthetic, platform-independent flagged run ------------------------------------
#
# A fake manifest + fake pre-state tree + hand-built records whose tools/call carries a
# `present` state_handle matching the manifest. This is NOT a real snapshot — add_case's
# job here is COMPOSITION (copy the tree, rewrite the manifest, write the case), which is
# pure filesystem work and needs no Seatbelt. The real restore is proven, darwin-gated,
# by `test_self_contained_survives_rm`.

STRONG_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)


def _synthetic_run(tmp_path: Path, handle: str = "H1"):
    """A (records, manifest_dir, tree_dir) triple: a fake but well-formed flagged run."""
    tree = tmp_path / "snap-tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / f"{handle}.json").write_text(
        json.dumps(
            {
                "handle": handle,
                "tree_path": str(tree),
                "backend": "clonefile",
                "capabilities": ["dir-mtimes", "hardlinks", "setuid"],
                "fidelity_gaps": ["hardlinks", "setuid", "dir-mtimes"],
                "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = _trace(
        tmp_path,
        "synth-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), {"status": "present", "handle": handle}),
            ("s2c", _recorded_reply(), None),
        ],
    )
    return records, manifest_dir, tree


def _fail_verdict() -> TurnVerdict:
    """A FAIL TurnVerdict with three sub-verdicts across A2 and A1 — the launch-demo shape.

    A2 result + A2 effect both PASS the corrupt success; the task-scoped A1 invariant FAILs.
    Reduced FAIL. Two axes and three sub-verdicts so the `expected` shape (test (e)) is
    non-trivial to reproduce.
    """
    return TurnVerdict(
        turn_index=0,
        tool_name="edit_file",
        status=Status.FAIL,
        sub_verdicts=[
            Verdict("A2", "replay", Status.PASS, None, None, "the recorded reply reproduced"),
            Verdict("A2", "effect", Status.PASS, ["tests/test_auth.py"], None, "declared-false"),
            Verdict(
                "A1", "invariant", Status.FAIL,
                ["tests/test_auth.py"], {"rule": "read-only", "scope": "tests/", "turn": 0},
                "read-only invariant on 'tests/' FAILED at turn 0",
            ),
        ],
        cause=None,
    )


def _add_synthetic(tmp_path: Path, *, human_label: str = "pending", verdict=None, run=None) -> Path:
    # `run` lets a caller add the SAME synthetic run twice: `_synthetic_run` builds its tree
    # with a plain `mkdir(parents=True)`, so re-deriving it would collide in the fixture
    # rather than in `add_case` — which is the collision under test.
    records, manifest_dir, _tree = run if run is not None else _synthetic_run(tmp_path)
    return add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=0,
        verdict=verdict if verdict is not None else _fail_verdict(),
        manifest_dir=manifest_dir,
        server_command=[sys.executable, "editor.py"],
        invariants=[Invariant(scope=b"tests/", rule="read-only")],
        human_label=human_label,
        replays=3,
        timeout=20.0,
        source_trace_id="synth-trace",
        captured_at=CAPTURED_AT,
    )


# --- (a) exactly the four artifacts ---------------------------------------------------


def test_add_case_composes_exactly_the_four_artifacts(tmp_path):
    case_dir = _add_synthetic(tmp_path)

    assert case_dir.is_dir()
    names = {p.name for p in case_dir.iterdir()}
    assert names == {"case.json", "trace.jsonl", "manifest.json", "prestate"}, names
    assert (case_dir / "prestate").is_dir()
    # the pre-state TREE is really bundled, not an empty dir.
    assert (case_dir / "prestate" / "tests" / "test_auth.py").read_text(encoding="utf-8") == (
        STRONG_BODY
    )
    # trace.jsonl holds the FULL records (the tools/list handshake too, not just the turn),
    # so a later `corpus run` has the handshake verify_turn needs.
    import base64

    lines = (case_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line]
    frames = [r for r in records if r.get("kind") == "frame"]
    assert len(frames) == 4, frames
    methods = [json.loads(base64.b64decode(f["raw"])).get("method") for f in frames]
    assert "tools/list" in methods and "tools/call" in methods, methods


def test_case_id_is_deterministic_from_trace_and_turn(tmp_path):
    """No uuid, no clock: the case dir name derives from source_trace_id + turn index."""
    case_dir = _add_synthetic(tmp_path)
    assert case_dir.name == "synth-trace-turn0", case_dir.name


# --- (c) the manifest's tree_path is the relative "prestate" --------------------------


def test_manifest_tree_path_is_relative_prestate(tmp_path):
    case_dir = _add_synthetic(tmp_path)
    payload = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["tree_path"] == "prestate", payload["tree_path"]
    # the rest of the manifest is carried through verbatim (sidecar, capabilities, gaps).
    assert payload["handle"] == "H1"
    assert "sidecar" in payload and "fidelity_gaps" in payload


# --- (d) THE ENGINE NEVER LABELS (D3) -------------------------------------------------


def test_engine_never_labels_a_fail_as_true_positive(tmp_path):
    """A FAILing verdict with the label DEFAULTED still stores `human_label == "pending"`.

    This is the security-of-the-metric control. `add_case` has NO code path from the
    verdict to the label; the human label is a pass-through input. A stub that set the
    label from the verdict (e.g. "true-positive" when the verdict is FAIL) FAILs here,
    and that RED was captured before the real pass-through code existed. If this ever
    starts reading "true-positive", the corpus is grading its own homework.
    """
    verdict = _fail_verdict()
    assert verdict.status is Status.FAIL  # precondition: the verdict IS a FAIL

    case_dir = _add_synthetic(tmp_path, verdict=verdict)  # human_label defaulted

    case = load_case(case_dir)
    assert case.human_label == "pending", (
        "the engine must NEVER derive the label from the verdict; a FAIL with no human "
        "label is 'pending', not 'true-positive'"
    )


def test_human_label_is_passed_through_verbatim(tmp_path):
    """When a human label IS supplied it is stored exactly as given."""
    case_dir = _add_synthetic(tmp_path, human_label="true-positive")
    assert load_case(case_dir).human_label == "true-positive"


# --- (e) expected carries the FULL per-sub-verdict set AND the reduced status ----------


def test_expected_carries_full_sub_verdicts_and_reduced_status(tmp_path):
    case_dir = _add_synthetic(tmp_path)
    case = load_case(case_dir)

    assert case.expected["reduced_status"] == "FAIL", case.expected
    subs = case.expected["sub_verdicts"]
    assert len(subs) == 3, subs
    for sub in subs:
        assert set(sub) == {"axis", "kind", "status"}, sub
    axes = {sub["axis"] for sub in subs}
    assert axes == {"A1", "A2"}, axes
    a1 = next(sub for sub in subs if sub["axis"] == "A1")
    assert a1["kind"] == "invariant" and a1["status"] == "FAIL", a1
    # both A2 sub-verdicts are present and PASS — the reduced FAIL is A1's, and `expected`
    # records that, not just the bare reduced status.
    a2 = sorted(sub["kind"] for sub in subs if sub["axis"] == "A2")
    assert a2 == ["effect", "replay"], a2


def test_invariants_and_provenance_are_recorded(tmp_path):
    case_dir = _add_synthetic(tmp_path)
    case = load_case(case_dir)
    assert case.invariants == [{"scope": "tests/", "rule": "read-only"}], case.invariants
    assert case.provenance == {"source_trace_id": "synth-trace", "captured_at": CAPTURED_AT}
    assert case.capture_platform == sys.platform
    assert case.capture_capabilities == ["dir-mtimes", "hardlinks", "setuid"]


# --- error paths ----------------------------------------------------------------------


def test_absent_prestate_is_a_named_valueerror(tmp_path):
    """A turn whose snapshot is absent has no restorable pre-state -> a case cannot be made."""
    records = _trace(
        tmp_path,
        "no-snap",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), {"status": "absent"}),
            ("s2c", _recorded_reply(), None),
        ],
    )
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    with pytest.raises(ValueError, match="pre-state"):
        add_case(
            tmp_path / "corpus",
            records=records, target_turn_index=0, verdict=_fail_verdict(),
            manifest_dir=manifest_dir, server_command=["x"], invariants=[],
            replays=3, timeout=1.0, source_trace_id="no-snap", captured_at=CAPTURED_AT,
        )


def test_missing_manifest_is_a_named_valueerror(tmp_path):
    """A present handle with no persisted manifest cannot be bundled -> named error."""
    records, _manifest_dir, _tree = _synthetic_run(tmp_path)
    empty_dir = tmp_path / "empty-manifests"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="manifest"):
        add_case(
            tmp_path / "corpus",
            records=records, target_turn_index=0, verdict=_fail_verdict(),
            manifest_dir=empty_dir, server_command=["x"], invariants=[],
            replays=3, timeout=1.0, source_trace_id="synth-trace", captured_at=CAPTURED_AT,
        )


# --- re-add: a stored case is never overwritten, and never half-written ---------------
#
# `add_case` used to `mkdir(exist_ok=True)` onto a populated case dir, truncate `trace.jsonl`
# in `"w"` mode, and only then hit `FileExistsError` from `copytree` onto an existing
# `prestate/`. Two consequences, both dangerous: the existing case was damaged on the way to
# failing, and `FileExistsError` is not a `ValueError`, so `phase0/runner.py`'s per-turn
# handler missed it and the WHOLE instance became `ERRORED` — excluded from
# `violation_denominator()`. Re-running a measurement could therefore shrink its own
# denominator and manufacture an `INSTRUMENT SUSPECT`, i.e. a fake PIVOT.


def _case_fingerprint(case_dir: Path) -> dict[str, str]:
    """A `{relpath: sha256}` map over every file under `case_dir`, sorted-path stable.

    Contents only: the failure this guards against (`trace.jsonl` opened `"w"`) changes
    bytes, so a content hash is sufficient and a mode/size comparison would add noise
    without adding a discrimination. Relative paths keep the map comparable across the
    `tmp_path` the case happens to live in.
    """
    import hashlib

    return {
        str(path.relative_to(case_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(case_dir.rglob("*"))
        if path.is_file()
    }


def test_readd_same_case_id_raises_case_exists(tmp_path):
    """A second `add_case` for the same trace + turn refuses, naming the case id.

    `ValueError` specifically, because that is the type `phase0/runner.py` already handles
    per-turn — see `test_case_exists_error_is_a_valueerror`.
    """
    run = _synthetic_run(tmp_path)
    _add_synthetic(tmp_path, run=run)

    with pytest.raises(ValueError) as excinfo:
        _add_synthetic(tmp_path, run=run)

    message = str(excinfo.value)
    assert "synth-trace-turn0" in message, message
    assert "exists" in message, message


def test_readd_leaves_existing_case_byte_identical(tmp_path):
    """A refused re-add mutates NOTHING: every file under the case dir is byte-identical.

    The collision must be detected BEFORE the first write. This is deliberately not a
    statement about which exception is raised — that is
    `test_readd_same_case_id_raises_case_exists`'s job — so the failing call is caught
    broadly here and the assertion is purely about what survives on disk.

    The re-add carries a SECOND capture of the same instance: the same `source_trace_id`
    (hence the same case id) but different records. That is deliberate and it is what makes
    the damage observable — re-adding the *identical* records truncates `trace.jsonl` and
    then rewrites the same bytes, so a content hash cannot see the write at all, and the
    test would pass against the very bug it exists to catch. A re-mint of an instance
    producing a fresh capture under the same trace stem is also the realistic case.
    """
    stored = _synthetic_run(tmp_path)
    case_dir = _add_synthetic(tmp_path, human_label="true-positive", run=stored)
    before = _case_fingerprint(case_dir)
    assert "trace.jsonl" in before and "prestate/tests/test_auth.py" in before, before

    rerun_root = tmp_path / "rerun"
    rerun_root.mkdir()
    rerun = _synthetic_run(rerun_root, handle="H2")

    try:
        _add_synthetic(tmp_path, run=rerun)
    except Exception:  # noqa: BLE001 - WHICH error is the previous test's assertion
        pass
    else:
        pytest.fail("a re-add of an existing case id must not succeed")

    assert _case_fingerprint(case_dir) == before


def test_readd_preserves_human_label_and_root_cause(tmp_path):
    """A human adjudication is not overwritable by the engine, even by a failed re-add.

    The corpus metric measures engine verdicts against HUMAN ground truth, so a label the
    engine could clobber is not ground truth. Today `case.json` survives a collision only
    by accident — `copytree` raises before `write_case` is reached — which is exactly why
    this is pinned.
    """
    from belay.corpus.curate import set_label

    run = _synthetic_run(tmp_path)
    _add_synthetic(tmp_path, run=run)
    root_cause = {"key": "tests-dir-write", "note": "a real weakening of test_auth.py"}
    set_label(tmp_path / "corpus", "synth-trace-turn0", "true-positive", root_cause)

    with pytest.raises(ValueError):
        _add_synthetic(tmp_path, run=run)

    case = load_case(tmp_path / "corpus" / "synth-trace-turn0")
    assert case.human_label == "true-positive", case.human_label
    assert case.root_cause == root_cause, case.root_cause


def test_case_exists_error_is_a_valueerror():
    """The collision type MUST be a `ValueError`, and this is load-bearing, not cosmetic.

    `phase0/runner.py`'s per-turn ingest handler catches `ValueError`, sending the turn to
    `flagged_unaddable` while the instance keeps its real disposition. Any other base class
    escapes to `run_batch`'s catch-all, ERRORs the whole instance, and drops it from
    `violation_denominator()` — the fake-`INSTRUMENT SUSPECT` path.
    """
    from belay.corpus.add import CaseExistsError

    assert issubclass(CaseExistsError, ValueError)


# --- the INTENDED path: a fresh corpus dir, and the determinism boundary --------------
#
# The guard above refuses a re-add. These two guard the GUARD: the supported remedy for a
# collision is a new corpus dir (there is deliberately no `--overwrite`), so if the check were
# ever widened — `corpus_dir.exists()` instead of `case_dir.exists()` is the obvious slip —
# the remedy would refuse too and a whole re-verification would have nowhere to land.

OTHER_CAPTURED_AT = "2026-07-30T12:00:00+00:00"


def _two_turn_synthetic_run(root: Path):
    """A (records, manifest_dir) pair over two turns with two DISTINCT pre-state trees.

    A two-turn run rather than `_synthetic_run`'s single turn because `task_prestate/` only
    exists on a NON-ZERO target turn: at turn 0 the task pre-state IS the target's, so
    `add_case` writes no second tree and declares the existing pair instead (pinned by
    `test_corpus_task_prestate.test_a_turn_zero_case_has_exactly_one_manifest_and_declares_it`).
    Checking the fresh-corpus path on a turn-0 case would therefore check a case shape with
    half the artifacts of the one a real re-verification produces.

    The two trees carry different `marker.txt` bytes, so a mis-bundle is caught by content
    rather than by a filename.
    """
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True)
    for handle, marker in (("H0", "turn-zero"), ("H1", "turn-one")):
        tree = root / f"snap-{handle}"
        (tree / "tests").mkdir(parents=True)
        (tree / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")
        (tree / "marker.txt").write_text(marker, encoding="utf-8")
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

    records = _trace(
        root,
        "two-turn-trace",
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


def _add_two_turn(corpus_dir: Path, run, *, captured_at: str) -> Path:
    records, manifest_dir = run
    return add_case(
        corpus_dir,
        records=records,
        target_turn_index=1,
        verdict=_fail_verdict(),
        manifest_dir=manifest_dir,
        server_command=[sys.executable, "editor.py"],
        invariants=[Invariant(scope=b"tests", rule="no-assertion-weakening")],
        replays=3,
        timeout=20.0,
        source_trace_id="two-turn-trace",
        captured_at=captured_at,
    )


def test_fresh_corpus_dir_ingest_unchanged(tmp_path):
    """The same flagged turn ingested into two fresh corpus dirs composes the same case.

    This is the guard against the guard, and it is the path the next re-verification takes:
    point `--corpus-dir` at a brand-new directory and every flagged turn lands. One of the two
    dirs is **pre-created and empty** — the realistic operator flow (`mkdir`, then measure) and
    the one a collision check widened from `case_dir` to `corpus_dir` would refuse outright.
    The other is absent, so both forms are pinned.

    "Identical modulo `captured_at`" is asserted over the WHOLE case, not just `case.json`:
    every other artifact must be byte-for-byte equal, and `case.json` equal after dropping the
    one injected field the caller varied.
    """
    run = _two_turn_synthetic_run(tmp_path / "run")

    preexisting = tmp_path / "corpus-preexisting"
    preexisting.mkdir()
    absent = tmp_path / "corpus-absent"  # deliberately NOT created; add_case makes it

    first = _add_two_turn(preexisting, run, captured_at=CAPTURED_AT)
    second = _add_two_turn(absent, run, captured_at=OTHER_CAPTURED_AT)

    assert first.name == second.name == "two-turn-trace-turn1", (first.name, second.name)

    # both pre-states are present AND populated, and they hold the RIGHT trees.
    for case_dir in (first, second):
        assert (case_dir / "prestate").is_dir() and (case_dir / "task_prestate").is_dir()
        for tree, marker in ((case_dir / "prestate", "turn-one"),
                             (case_dir / "task_prestate", "turn-zero")):
            assert (tree / "marker.txt").read_text(encoding="utf-8") == marker, tree
            assert (tree / "tests" / "test_auth.py").read_text(encoding="utf-8") == STRONG_BODY

    payloads = []
    for case_dir, expected_at in ((first, CAPTURED_AT), (second, OTHER_CAPTURED_AT)):
        payload = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        assert payload["provenance"]["captured_at"] == expected_at, payload["provenance"]
        payload["provenance"] = {
            k: v for k, v in payload["provenance"].items() if k != "captured_at"
        }
        payloads.append(payload)
    assert payloads[0] == payloads[1]

    fp_first, fp_second = _case_fingerprint(first), _case_fingerprint(second)
    assert fp_first.keys() == fp_second.keys(), (sorted(fp_first), sorted(fp_second))
    assert {k: v for k, v in fp_first.items() if k != "case.json"} == {
        k: v for k, v in fp_second.items() if k != "case.json"
    }


def test_add_case_reads_no_clock_captured_at_is_injected(tmp_path):
    """`captured_at` is caller-injected and stored verbatim — `add_case` reads no clock.

    The determinism boundary, extending `test_case_id_is_deterministic_from_trace_and_turn`
    from the case id to the case CONTENT: `cli.py` reads the clock at the CLI boundary and
    passes the value down, so two composes of the same flagged turn with the same injected
    timestamp are byte-identical. A clock read inside `add_case` would make a re-composed case
    differ from the stored one in a field nothing about the run changed, and the corpus's whole
    claim is that a case is a fixture rather than a recording of when it was written.
    """
    run = _synthetic_run(tmp_path)
    first = _add_synthetic(tmp_path / "a", run=run)
    second = _add_synthetic(tmp_path / "b", run=run)

    payload = json.loads((first / "case.json").read_text(encoding="utf-8"))
    assert payload["provenance"]["captured_at"] == CAPTURED_AT, payload["provenance"]

    assert (first / "case.json").read_bytes() == (second / "case.json").read_bytes()


def test_cli_default_timeout_matches_client(tmp_path):
    """cli.DEFAULT_TIMEOUT is declared locally (to keep --help cheap) but must not drift
    from the replay client's real default."""
    from belay.cli import DEFAULT_TIMEOUT as CLI_DEFAULT
    from belay.replay.client import DEFAULT_TIMEOUT as CLIENT_DEFAULT

    assert CLI_DEFAULT == CLIENT_DEFAULT


# --- (b) SELF-CONTAINED: survives deletion of the original run (REAL snapshot) ---------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="the survives-rm proof takes a REAL snapshot and restores it in the sandbox",
)


@pytestmark_darwin
def test_self_contained_survives_rm(tmp_path):
    """After add_case, DELETE the original manifest dir AND tree — the case still restores.

    The durability guarantee that makes a case portable and moat #2 real: the pre-state
    tree was COPIED into `<case>/prestate/`, not referenced, and the manifest's tree_path
    rewritten to the relative "prestate". So `load_snapshot(<case>/manifest.json)` +
    `guarded_restore` reconstruct the exact pre-state from the case ALONE.
    """
    from belay.replay.persist import load_snapshot, persist_snapshot
    from belay.snapshot.substrate import guarded_restore, present_handle, take_snapshot

    # A real workspace + real snapshot, persisted the way the gate does.
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    manifest_dir = tmp_path / "run-manifests"
    manifest_path = manifest_dir / f"{snap.manifest.handle}.json"
    persist_snapshot(snap, manifest_path)
    present = present_handle(snap)

    records = _trace(
        tmp_path,
        "real-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), present),
            ("s2c", _recorded_reply(), None),
        ],
    )

    case_dir = add_case(
        tmp_path / "corpus",
        records=records, target_turn_index=0, verdict=_fail_verdict(),
        manifest_dir=manifest_dir, server_command=[sys.executable, "editor.py"],
        invariants=[Invariant(scope=b"tests/", rule="read-only")],
        replays=3, timeout=20.0, source_trace_id="real-trace", captured_at=CAPTURED_AT,
    )

    # NUKE the original run: the manifest dir AND the snapshot tree it referenced.
    original_tree = Path(json.loads(manifest_path.read_text(encoding="utf-8"))["tree_path"])
    shutil.rmtree(manifest_dir)
    shutil.rmtree(original_tree)
    assert not manifest_dir.exists() and not original_tree.exists()

    # The case ALONE still restores the pre-state.
    load_case(case_dir)  # loads clean
    restored = tmp_path / "restored"
    guarded_restore(load_snapshot(case_dir / "manifest.json"), restored)
    assert (restored / "tests" / "test_auth.py").read_text(encoding="utf-8") == STRONG_BODY


@pytestmark_darwin
def test_cli_corpus_add_composes_a_case_with_pending_label(tmp_path, capsys):
    """`belay corpus add` end-to-end: recompute the verdict, compose the case, label pending.

    The CLI recomputes the turn's verdict by REAL re-execution (verify_turn), so this is
    darwin-gated. It must NOT label — no --label means the stored label is "pending".
    """
    from belay.cli import main
    from belay.replay.persist import persist_snapshot
    from belay.snapshot.substrate import present_handle, take_snapshot

    fixtures = Path(__file__).parent / "fixtures"
    editor = fixtures / "weakening_editor_server.py"

    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    manifest_dir = tmp_path / "run-manifests"
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    present = present_handle(snap)

    records = _trace(
        tmp_path,
        "cli-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), present),
            ("s2c", _recorded_reply(), None),
        ],
    )
    trace_path = tmp_path / "cli-trace.jsonl"
    trace_path.write_bytes(b"\n".join(json.dumps(r).encode() for r in records) + b"\n")

    corpus_dir = tmp_path / "corpus"
    rc = main(
        [
            "corpus", "add", str(trace_path),
            "--turn", "0",
            "--manifest-dir", str(manifest_dir),
            "--corpus-dir", str(corpus_dir),
            "--server", sys.executable, str(editor),
        ]
    )
    assert rc == 0, capsys.readouterr()

    case_dir = corpus_dir / "cli-trace-turn0"
    assert case_dir.is_dir()
    names = {p.name for p in case_dir.iterdir()}
    assert names == {"case.json", "trace.jsonl", "manifest.json", "prestate"}, names
    case = load_case(case_dir)
    assert case.human_label == "pending", "the CLI must not label; default is pending"
    assert case.expected["reduced_status"] == "FAIL", case.expected


@pytestmark_darwin
def test_cli_corpus_add_passes_label_through(tmp_path, capsys):
    """`--label true-positive` is stored verbatim — the human's call, passed through."""
    from belay.cli import main
    from belay.replay.persist import persist_snapshot
    from belay.snapshot.substrate import present_handle, take_snapshot

    fixtures = Path(__file__).parent / "fixtures"
    editor = fixtures / "weakening_editor_server.py"

    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    manifest_dir = tmp_path / "run-manifests"
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    present = present_handle(snap)

    records = _trace(
        tmp_path,
        "cli-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), present),
            ("s2c", _recorded_reply(), None),
        ],
    )
    trace_path = tmp_path / "cli-trace.jsonl"
    trace_path.write_bytes(b"\n".join(json.dumps(r).encode() for r in records) + b"\n")

    corpus_dir = tmp_path / "corpus"
    rc = main(
        [
            "corpus", "add", str(trace_path),
            "--turn", "0",
            "--manifest-dir", str(manifest_dir),
            "--corpus-dir", str(corpus_dir),
            "--label", "true-positive",
            "--server", sys.executable, str(editor),
        ]
    )
    assert rc == 0, capsys.readouterr()
    assert load_case(corpus_dir / "cli-trace-turn0").human_label == "true-positive"


# --- target_tool: recorded so independence stays computable ---------------------------
#
# The gate's STRICT independence clause is "distinct instances AND distinct
# tools", but the tool appears nowhere in case.json -- it lives in the trace.
# `corpus add` already holds both the trace and the turn index, so it records
# the tool here and the strict count stays computable without re-reading traces
# at score time (which would make `score()` do I/O).


def test_add_case_records_the_target_tool(tmp_path):
    """The composed case carries the target turn's tool name."""
    case_dir = _add_synthetic(tmp_path)
    assert load_case(case_dir).target_tool == "edit_file"


# --- help text must not assert a precondition the code never enforces -----------------
#
# `add_case` reads `verdict` at exactly one place (to build `expected`) and the CLI
# handler applies no FAIL filter. Composing a case for a turn the detector did NOT flag
# is a supported path -- it is how a recorded miss (`corpus label --recorded-miss-note`)
# enters the corpus at all. The old help text claimed the opposite ("one flagged turn",
# "the trace file the flagged turn is in"), which sends a reader looking for a filter
# that was never there and, worse, concludes the corpus cannot hold a miss.


def test_corpus_add_help_does_not_assert_a_flagged_turn_precondition() -> None:
    """`belay corpus add --help` must not claim a flagged/FAIL precondition on the turn.

    Asserted on the PARSER's help strings, because the wrong claim in --help is exactly
    what would send a reader looking for a filter that does not exist.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "corpus", "add", "--help"],
        capture_output=True,
        timeout=30,
    )
    out = completed.stdout.decode(errors="replace").lower()

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert "flagged turn" not in out
    assert "flagged run" not in out
    # the manual unflagged-turn path must be documented where a user reading --help finds
    # it, not merely absent of the false claim.
    assert "need not" in out or "not be flagged" in out or "any turn" in out
