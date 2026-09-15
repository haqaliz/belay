"""Phase 3 — `belay invariant infer`: orchestration, calibration, artifact emission.

Tests for `src/belay/authoring/infer.py` and the `belay invariant infer` CLI wiring
(the `authoring-protocol` aspect, phases 3-5). The author is an out-of-process BYOK
command: JSON in on stdin, JSON out on stdout — every test here drives it through the
injectable `runner=` seam or a local fake-author SCRIPT, so no model, no network and no
`claude` binary is ever involved.

The contract, stated once:

- **Calibration is execution, through the SHIPPED composition.** `infer` replays the
  control by calling `belay.verify.turn.verify_turn` — the same function `belay verify`
  calls — once per control turn, with the candidate invariants ONLY (never the
  defaults). There is no second evaluator, and the spy test proves it.
- **A candidate that FAILs any control turn is rejected** (`CALIBRATION_FAILED`), a
  candidate that PASSes or abstains is kept, and a control that never reaches a decided
  A2 result sub-verdict makes calibration vacuous (`CONTROL_UNREPLAYABLE`) — never a
  `"calibrated"` record for a control that was never re-executed.
- **Fail-closed at every step.** A bad author, a bad candidate, a bad control or a bad
  task spec exits 2 with a named cause and leaves the `--out` path untouched: no
  partial file, no empty artifact.
- **The artifact is deterministic** for fixed inputs (sorted keys, no timestamps) and
  its digest is the loader's own `canonical_policy_digest`, so `load_invariants`
  trusts it and `belay verify --invariants <artifact>` enforces it.

Darwin-gated tests replay inside the macOS Seatbelt sandbox (house pattern,
`tests/test_verify_cli_invariants.py:34-37`); everything else is offline.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION
from fixtures.create_server import REPLY_TEXT as CREATE_REPLY
from fixtures.weakening_editor_server import REPLY_TEXT as EDITOR_REPLY

from belay import cli
from belay.authoring.infer import (
    ARTIFACT_WRITE_FAILED,
    CALIBRATION_FAILED,
    CONTROL_UNREADABLE,
    CONTROL_UNREPLAYABLE,
    MANIFESTS_UNRESOLVABLE,
    NO_SURVIVING_CANDIDATES,
    TASK_UNREADABLE,
    run_infer,
)
from belay.authoring.protocol import (
    AUTHOR_FAILED,
    AUTHOR_OUTPUT_UNPARSEABLE,
    NO_AUTHOR_CONFIGURED,
    UNKNOWN_RULE,
)
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import (
    AUTHORED_SCHEMA,
    Invariant,
    canonical_policy_digest,
    load_invariants,
)
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

FIXTURES = Path(__file__).parent / "fixtures"
CREATE_CMD = [sys.executable, str(FIXTURES / "create_server.py")]
EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]

TASK_TEXT = "Fix the failing test in tests/test_auth.py without weakening its assertions.\n"
STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"

requires_replay = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)


# ---------------------------------------------------------------------------
# Fixtures: traces, snapshots, fake authors (house patterns)
# ---------------------------------------------------------------------------


def _seeded_handle(tmp_path: Path, seed, manifest_dir: Path, name: str):
    """Snapshot a seeded workspace and persist its manifest; return the handle."""
    work = tmp_path / f"work-{name}"
    work.mkdir()
    seed(work)
    snap = take_snapshot(work, tmp_path / f"snap-{name}")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _tools_list(tool: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [{"name": tool, "annotations": {"readOnlyHint": False}}]
            },
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call(tool: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    ).encode()


def _reply(reply_text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": reply_text}],
                "isError": False,
            },
        }
    ).encode()


def _record_frames(writer: TraceWriter, frames: list[tuple]) -> None:
    for direction, raw, handle in frames:
        if handle is not None:
            writer.set_state_handle(handle, frame=raw)
        writer.observer(direction)(raw, False)


def _control(
    tmp_path: Path,
    *,
    name: str,
    tool: str = "create_file",
    reply_text: str = CREATE_REPLY,
    seed=lambda work: None,
    sibling: bool = False,
    calls: int = 1,
) -> tuple[Path, Path]:
    """One control trace + its manifest dir.

    `sibling=True` writes the manifests to the trace's own `<stem>.manifests` sibling
    (the CLI's default resolution); otherwise they land in a separate dir the caller
    passes explicitly. `calls=0` records the tools/list handshake with no tools/call.
    """
    trace_dir = tmp_path / ("captures" if sibling else f"trace-{name}")
    writer = TraceWriter.in_directory(trace_dir)
    trace_path = writer.path
    manifest_dir = (
        trace_path.parent / f"{trace_path.stem}.manifests"
        if sibling
        else tmp_path / f"manifests-{name}"
    )
    manifest_dir.mkdir(parents=True, exist_ok=True)
    handle = _seeded_handle(tmp_path, seed, manifest_dir, name)
    frames = _tools_list(tool)
    for _ in range(calls):
        frames = frames + [("c2s", _call(tool), handle), ("s2c", _reply(reply_text), None)]
    try:
        _record_frames(writer, frames)
    finally:
        writer.close()
    return trace_path, manifest_dir


def _strong_seed(work: Path) -> None:
    (work / "tests").mkdir()
    (work / "tests" / "test_auth.py").write_text(STRONG_TEST, encoding="utf-8")


def _task(tmp_path: Path, *, name: str = "task.md", text: str = TASK_TEXT) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: bytes = b""):
        self.returncode = returncode
        self.stdout = stdout


class _FakeRunner:
    """The injectable author seam: records calls, returns a canned process."""

    def __init__(self, stdout: bytes = b"", returncode: int = 0, exc: Exception | None = None):
        self._stdout = stdout
        self._returncode = returncode
        self._exc = exc
        self.calls: list[tuple] = []

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs))
        if self._exc is not None:
            raise self._exc
        return _FakeProc(self._returncode, self._stdout)


def _author_stdout(*candidates: dict, model: str | None = None) -> bytes:
    payload: dict = {"candidates": [dict(c) for c in candidates]}
    if model is not None:
        payload["model"] = model
    return json.dumps(payload).encode("utf-8")


def _write_fake_author(
    tmp_path: Path, *, stdout_text: str, returncode: int = 0, name: str = "fake_author.py"
) -> str:
    """A real local author command (no model, no network): prints and exits."""
    script = tmp_path / name
    script.write_text(
        "import sys\n"
        f"sys.stdout.write({stdout_text!r})\n"
        f"sys.exit({returncode})\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"


def _canned_turn(n: int, *, a1: Verdict | None = None, decided: bool = True) -> TurnVerdict:
    """A hand-built TurnVerdict for the spy tests: decided A2 result + optional A1."""
    if decided:
        subs = [
            Verdict(
                "A2", "replay", Status.PASS,
                observed=None, expected=None,
                message="replayed reply reproduced the recorded reply",
            )
        ]
    else:
        subs = [
            Verdict(
                "A2", "replay", Status.UNVERIFIED,
                observed=None, expected=None,
                message="turn UNVERIFIED: the pre-state could not be restored",
            )
        ]
    if a1 is not None:
        subs.append(a1)
    status = Status.PASS
    if any(v.status is Status.FAIL for v in subs):
        status = Status.FAIL
    elif any(v.status is Status.UNVERIFIED for v in subs):
        status = Status.UNVERIFIED
    return TurnVerdict(turn_index=n, tool_name="create_file", status=status, sub_verdicts=subs)


def _fail_verdict(n: int, *, rule: str, scope: str) -> Verdict:
    return Verdict(
        "A1", "invariant", Status.FAIL,
        observed=["generated/new_file.txt"],
        expected={"rule": rule, "scope": scope, "turn": n},
        message=f"{rule} invariant on {scope!r} FAILED at turn {n}",
    )


def _spy(monkeypatch, *, decided: bool = True, a1=None):
    """Install a verify_turn spy; returns the recorded calls. `a1` is a factory(n)->Verdict."""
    import belay.verify.turn as turn_module

    calls: list[tuple] = []

    def spy(records, n, **kwargs):
        calls.append((records, n, kwargs))
        return _canned_turn(n, a1=a1(n) if a1 is not None else None, decided=decided)

    monkeypatch.setattr(turn_module, "verify_turn", spy)
    return calls


def _run(tmp_path, *, task=None, control, manifest_dir, out=None, runner=None,
         server=CREATE_CMD, timeout=10.0, replays=3, repo=None):
    return run_infer(
        task_path=task or _task(tmp_path),
        control_path=control,
        author_command=("fake-author",),
        out_path=out or (tmp_path / "policy.json"),
        manifest_dir=manifest_dir,
        server_command=server,
        timeout=timeout,
        replays=replays,
        repo_dir=repo,
        runner=runner if runner is not None else _FakeRunner(_author_stdout(
            {"scope": "tests/", "rule": "read-only", "rationale": "tests are read-only"}
        )),
    )


# ---------------------------------------------------------------------------
# Criterion 1 — the RED/GREEN pair: emit, then verify both fixtures
# ---------------------------------------------------------------------------


@requires_replay
def test_infer_emits_an_artifact_that_fails_the_corrupt_fixture_and_passes_the_control(
    tmp_path, capsys
):
    """The emitted artifact enforces A1: corrupt FAILs at turn 0, clean control PASSes."""
    control, manifests = _control(tmp_path, name="clean")
    task = _task(tmp_path)
    out = tmp_path / "policy.json"
    rationale = "the task forbids touching the tests"

    result = _run(
        tmp_path, task=task, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout(
            {"scope": "tests/", "rule": "read-only", "rationale": rationale},
            model="fake-model-1",
        )),
    )

    assert result.ok is True, result
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["schema"] == AUTHORED_SCHEMA
    assert payload["author"] == {"program": "fake-author", "model": "fake-model-1"}
    assert payload["task"] == {
        "path": str(task),
        "sha256": hashlib.sha256(task.read_bytes()).hexdigest(),
    }
    assert payload["control"] == {
        "trace": str(control),
        "sha256": hashlib.sha256(control.read_bytes()).hexdigest(),
        "turns": 1,
        "calibrated": True,
    }
    expected_digest = canonical_policy_digest(
        invariants=[Invariant(scope=b"tests/", rule="read-only")],
        task_sha256=payload["task"]["sha256"],
        control_sha256=payload["control"]["sha256"],
    )
    assert payload["calibration"] == {"digest": expected_digest}
    assert payload["invariants"] == [
        {"scope": "tests/", "rule": "read-only", "rationale": rationale}
    ]

    # The loader's recompute matches, so the artifact ENFORCES rather than abstains.
    assert load_invariants(out) == [Invariant(scope=b"tests/", rule="read-only")]

    # The corrupt fixture: the artifact's A1 invariant FAILs the exact turn, A2 PASSes.
    corrupt, corrupt_manifests = _control(
        tmp_path, name="corrupt", tool="edit_file", reply_text=EDITOR_REPLY,
        seed=_strong_seed,
    )
    rc = cli.main(
        ["verify", str(corrupt), "--manifest-dir", str(corrupt_manifests),
         "--invariants", str(out), "--json", "--server", *EDITOR_CMD]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1, doc
    turn = doc["turns"][0]
    assert turn["status"] == "FAIL", turn
    a1 = [
        s for s in turn["sub_verdicts"]
        if (s["axis"], s["kind"]) == ("A1", "invariant") and s.get("rule") == "read-only"
    ]
    assert len(a1) == 1, turn["sub_verdicts"]
    assert a1[0]["status"] == "FAIL", a1[0]
    assert "tests/test_auth.py" in a1[0]["message"], a1[0]
    by_axis = {(s["axis"], s["kind"]): s["status"] for s in turn["sub_verdicts"]}
    assert by_axis[("A2", "replay")] == "PASS", turn["sub_verdicts"]
    assert by_axis[("A2", "effect")] == "PASS", turn["sub_verdicts"]

    # The clean control PASSes under the same artifact.
    rc = cli.main(
        ["verify", str(control), "--manifest-dir", str(manifests),
         "--invariants", str(out), "--json", "--server", *CREATE_CMD]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0, doc
    assert doc["aggregate"]["PASS"] == 1, doc["aggregate"]


# ---------------------------------------------------------------------------
# Criterion 2 — author failure modes are fail-closed, no artifact
# ---------------------------------------------------------------------------


def test_author_nonzero_exit_is_author_failed(tmp_path):
    control, manifests = _control(tmp_path, name="af1")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(returncode=3, stdout=b"boom"),
    )
    assert result.ok is False
    assert result.cause == AUTHOR_FAILED
    assert not out.exists()


def test_author_timeout_is_author_failed(tmp_path):
    control, manifests = _control(tmp_path, name="af2")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(exc=subprocess.TimeoutExpired("fake-author", 60.0)),
    )
    assert result.ok is False
    assert result.cause == AUTHOR_FAILED
    assert not out.exists()


def test_author_unparseable_stdout_is_author_output_unparseable(tmp_path):
    control, manifests = _control(tmp_path, name="af3")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(stdout=b"this is not json {"),
    )
    assert result.ok is False
    assert result.cause == AUTHOR_OUTPUT_UNPARSEABLE
    assert not out.exists()


def test_author_missing_candidates_key_is_author_output_unparseable(tmp_path):
    control, manifests = _control(tmp_path, name="af4")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(stdout=json.dumps({"scope": "tests/"}).encode()),
    )
    assert result.ok is False
    assert result.cause == AUTHOR_OUTPUT_UNPARSEABLE
    assert not out.exists()


def test_author_error_payload_is_author_failed(tmp_path):
    control, manifests = _control(tmp_path, name="af5")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(stdout=json.dumps({"error": "the model said no"}).encode()),
    )
    assert result.ok is False
    assert result.cause == AUTHOR_FAILED
    assert not out.exists()


# ---------------------------------------------------------------------------
# Criterion 3 — unknown rules are rejected, never emitted
# ---------------------------------------------------------------------------


def test_unknown_rule_is_dropped_with_unknown_rule_and_others_kept(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="ur1")
    out = tmp_path / "policy.json"
    _spy(monkeypatch)
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout(
            {"scope": "", "rule": "network-egress"},
            {"scope": "tests/", "rule": "read-only", "rationale": "keep me"},
        )),
    )
    assert result.ok is True, result
    assert [r["cause"] for r in result.rejections] == [UNKNOWN_RULE]
    assert result.rejections[0]["rule"] == "network-egress"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["invariants"] == [
        {"scope": "tests/", "rule": "read-only", "rationale": "keep me"}
    ]


def test_only_unknown_rules_is_no_surviving_candidates(tmp_path):
    control, manifests = _control(tmp_path, name="ur2")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout({"scope": "", "rule": "network-egress"})),
    )
    assert result.ok is False
    assert result.cause == NO_SURVIVING_CANDIDATES
    assert result.rejections[0]["cause"] == UNKNOWN_RULE
    assert not out.exists()


def test_empty_candidate_list_is_no_surviving_candidates(tmp_path):
    control, manifests = _control(tmp_path, name="ur3")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout()),
    )
    assert result.ok is False
    assert result.cause == NO_SURVIVING_CANDIDATES
    assert not out.exists()


# ---------------------------------------------------------------------------
# Criterion 4 — calibration is execution and rejects over-fire
# ---------------------------------------------------------------------------


def test_calibration_rejects_a_candidate_that_fails_the_control(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="cal1")
    out = tmp_path / "policy.json"
    _spy(monkeypatch, a1=lambda n: _fail_verdict(n, rule="read-only", scope="generated/"))
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout(
            {"scope": "generated/", "rule": "read-only", "rationale": "nothing may be written"},
        )),
    )
    assert result.ok is False
    assert result.cause == CALIBRATION_FAILED
    assert result.calibration_rejects == (
        {
            "scope": "generated/",
            "rule": "read-only",
            "rationale": "nothing may be written",
            "cause": CALIBRATION_FAILED,
        },
    )
    assert not out.exists()


def test_calibration_keeps_the_candidates_that_pass(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="cal2")
    out = tmp_path / "policy.json"
    _spy(
        monkeypatch,
        a1=lambda n: (
            _fail_verdict(n, rule="read-only", scope="generated/")
            if n == 0 else None
        ),
    )
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout(
            {"scope": "generated/", "rule": "read-only"},
            {"scope": "tests/", "rule": "read-only"},
        )),
    )
    assert result.ok is True, result
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["invariants"] == [
        {"scope": "tests/", "rule": "read-only", "rationale": None}
    ]


# ---------------------------------------------------------------------------
# Criterion 5 — the structural pin: the shipped composition, candidates only
# ---------------------------------------------------------------------------


def test_calibration_calls_verify_turn_once_per_turn_with_candidates_only(
    tmp_path, monkeypatch
):
    """No second evaluator: one verify_turn per control turn, candidates-only invariants."""
    import belay.replay.engine as engine

    control, manifests = _control(tmp_path, name="pin1", calls=2)
    out = tmp_path / "policy.json"
    calls = _spy(monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "infer must not re-invoke the replay engine directly; calibration goes "
            "through belay.verify.turn.verify_turn"
        )

    monkeypatch.setattr(engine, "replay_turn", forbidden)

    runner = _FakeRunner(_author_stdout(
        {"scope": "tests/", "rule": "read-only", "rationale": "r1"},
        {"scope": "generated/", "rule": "no-create", "rationale": "r2"},
    ))
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out, runner=runner
    )

    assert result.ok is True, result
    assert [n for _records, n, _kwargs in calls] == [0, 1]
    expected = [
        Invariant(scope=b"generated/", rule="no-create"),
        Invariant(scope=b"tests/", rule="read-only"),
    ]
    for _records, _n, kwargs in calls:
        assert kwargs["invariants"] == expected, kwargs["invariants"]
        assert kwargs["server_command"] == CREATE_CMD
        assert Path(kwargs["manifest_dir"]) == manifests
        assert kwargs["timeout"] == 10.0
        assert kwargs["replays"] == 3

    # The author was handed the task text and nothing from the control (D-7 wiring).
    payload = json.loads(runner.calls[0][1]["input"].decode("utf-8"))
    assert payload["task"] == TASK_TEXT
    assert "control" not in payload and "trace" not in payload


# ---------------------------------------------------------------------------
# Criterion 6 — a vacuous calibration emits nothing
# ---------------------------------------------------------------------------


def test_control_with_zero_tool_calls_is_unreplayable(tmp_path):
    control, manifests = _control(tmp_path, name="vac1", calls=0)
    out = tmp_path / "policy.json"
    result = _run(tmp_path, control=control, manifest_dir=manifests, out=out)
    assert result.ok is False
    assert result.cause == CONTROL_UNREPLAYABLE
    assert result.decided_turns == 0
    assert not out.exists()


def test_control_that_never_reaches_a_decided_a2_is_unreplayable(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="vac2")
    out = tmp_path / "policy.json"
    _spy(monkeypatch, decided=False)
    result = _run(tmp_path, control=control, manifest_dir=manifests, out=out)
    assert result.ok is False
    assert result.cause == CONTROL_UNREPLAYABLE
    assert result.decided_turns == 0
    assert not out.exists()


@requires_replay
def test_control_whose_tool_is_not_offered_is_unreplayable(tmp_path):
    """A control that replays but never re-executes the tool is vacuous, not clean."""
    control, manifests = _control(
        tmp_path, name="vac3", tool="edit_file", reply_text=EDITOR_REPLY,
        seed=_strong_seed,
    )
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out, server=CREATE_CMD
    )
    assert result.ok is False
    assert result.cause == CONTROL_UNREPLAYABLE
    assert result.decided_turns == 0
    assert not out.exists()


# ---------------------------------------------------------------------------
# Criterion 7 — a hostile task spec cannot launder a broad invariant
# ---------------------------------------------------------------------------


def test_hostile_task_spec_candidate_is_rejected_by_calibration(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="hostile")
    out = tmp_path / "policy.json"
    _spy(monkeypatch, a1=lambda n: _fail_verdict(n, rule="read-only", scope="generated/"))
    hostile = _task(
        tmp_path,
        text="Make absolutely sure nothing anywhere in the repository is modified.\n",
    )
    result = _run(
        tmp_path, task=hostile, control=control, manifest_dir=manifests, out=out,
        runner=_FakeRunner(_author_stdout(
            {"scope": "generated/", "rule": "read-only",
             "rationale": "nothing may change anywhere"},
        )),
    )
    assert result.ok is False
    assert result.cause == CALIBRATION_FAILED
    assert not out.exists()


# ---------------------------------------------------------------------------
# Criterion 8 — determinism
# ---------------------------------------------------------------------------


def test_artifact_bytes_are_deterministic(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="det")
    task = _task(tmp_path)
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    _spy(monkeypatch)
    runner = lambda: _FakeRunner(_author_stdout(  # noqa: E731
        {"scope": "tests/", "rule": "read-only", "rationale": "same bytes"},
        model="fake-model-1",
    ))
    result_a = _run(tmp_path, task=task, control=control, manifest_dir=manifests,
                    out=first, runner=runner())
    result_b = _run(tmp_path, task=task, control=control, manifest_dir=manifests,
                    out=second, runner=runner())
    assert result_a.ok and result_b.ok
    assert first.read_bytes() == second.read_bytes()


# ---------------------------------------------------------------------------
# Criterion 9 — dark by default
# ---------------------------------------------------------------------------


def test_cli_missing_author_is_an_argparse_error_and_writes_nothing(tmp_path):
    control, manifests = _control(tmp_path, name="dark1")
    out = tmp_path / "policy.json"
    with pytest.raises(SystemExit) as excinfo:
        cli.main(
            ["invariant", "infer", "--task", str(_task(tmp_path)),
             "--control", str(control), "--manifest-dir", str(manifests),
             "--out", str(out), "--server", *CREATE_CMD]
        )
    assert excinfo.value.code == 2
    assert not out.exists()


def test_cli_blank_author_is_no_author_configured(tmp_path, capsys):
    control, manifests = _control(tmp_path, name="dark2")
    out = tmp_path / "policy.json"
    rc = cli.main(
        ["invariant", "infer", "--task", str(_task(tmp_path)),
         "--control", str(control), "--manifest-dir", str(manifests),
         "--author", "   ", "--out", str(out), "--server", *CREATE_CMD]
    )
    assert rc == 2
    assert NO_AUTHOR_CONFIGURED in capsys.readouterr().out
    assert not out.exists()


def test_empty_author_command_is_no_author_configured(tmp_path):
    control, manifests = _control(tmp_path, name="dark3")
    out = tmp_path / "policy.json"
    result = run_infer(
        task_path=_task(tmp_path),
        control_path=control,
        author_command=(),
        out_path=out,
        manifest_dir=manifests,
        server_command=CREATE_CMD,
        timeout=10.0,
        replays=3,
    )
    assert result.ok is False
    assert result.cause == NO_AUTHOR_CONFIGURED
    assert not out.exists()


# ---------------------------------------------------------------------------
# Criterion 10 — the `--json` surface
# ---------------------------------------------------------------------------


@requires_replay
def test_cli_json_surface_reports_everything_and_resolves_the_manifest_sibling(
    tmp_path, capsys
):
    control, manifests = _control(tmp_path, name="json", sibling=True)
    out = tmp_path / "policy.json"
    author = _write_fake_author(
        tmp_path,
        stdout_text=json.dumps(
            {
                "model": "fake-model-1",
                "candidates": [
                    {"scope": "tests/", "rule": "read-only", "rationale": "r"}
                ],
            }
        ),
    )
    rc = cli.main(
        ["invariant", "infer", "--task", str(_task(tmp_path)), "--author", author,
         "--control", str(control), "--out", str(out), "--json",
         "--server", *CREATE_CMD]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 0, doc
    assert doc["ok"] is True
    assert doc["artifact"] == str(out)
    assert doc["model"] == "fake-model-1"
    assert doc["candidates"] == [
        {"scope": "tests/", "rule": "read-only", "rationale": "r"}
    ]
    assert doc["rejections"] == []
    assert doc["calibration_rejects"] == []
    assert doc["turns"] == 1
    assert doc["decided_turns"] == 1
    assert doc["error"] is None
    assert out.is_file()
    assert manifests.is_dir()


def test_cli_text_surface_reports_the_drops_and_writes_nothing(tmp_path, capsys):
    control, manifests = _control(tmp_path, name="text1")
    out = tmp_path / "policy.json"
    author = _write_fake_author(
        tmp_path,
        stdout_text=json.dumps(
            {"candidates": [{"scope": "", "rule": "network-egress"}]}
        ),
    )
    rc = cli.main(
        ["invariant", "infer", "--task", str(_task(tmp_path)), "--author", author,
         "--control", str(control), "--manifest-dir", str(manifests),
         "--out", str(out), "--server", *CREATE_CMD]
    )
    text = capsys.readouterr().out
    assert rc == 2, text
    assert UNKNOWN_RULE in text, text
    assert NO_SURVIVING_CANDIDATES in text, text
    assert not out.exists()


def test_cli_json_failure_document_names_the_cause(tmp_path, capsys):
    control, manifests = _control(tmp_path, name="text2")
    out = tmp_path / "policy.json"
    author = _write_fake_author(tmp_path, stdout_text="", returncode=1)
    rc = cli.main(
        ["invariant", "infer", "--task", str(_task(tmp_path)), "--author", author,
         "--control", str(control), "--manifest-dir", str(manifests),
         "--out", str(out), "--json", "--server", *CREATE_CMD]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 2, doc
    assert doc["ok"] is False
    assert doc["error"] == {"cause": AUTHOR_FAILED}
    assert doc["artifact"] is None
    assert not out.exists()


# ---------------------------------------------------------------------------
# The remaining named failure paths
# ---------------------------------------------------------------------------


def test_missing_task_is_named_and_writes_nothing(tmp_path):
    control, manifests = _control(tmp_path, name="miss1")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, task=tmp_path / "nope.md", control=control,
        manifest_dir=manifests, out=out,
    )
    assert result.ok is False
    assert result.cause == TASK_UNREADABLE
    assert not out.exists()


def test_missing_control_is_named_and_writes_nothing(tmp_path):
    _control_marker, manifests = _control(tmp_path, name="miss2")
    out = tmp_path / "policy.json"
    result = _run(
        tmp_path, control=tmp_path / "nope.jsonl", manifest_dir=manifests, out=out
    )
    assert result.ok is False
    assert result.cause == CONTROL_UNREADABLE
    assert not out.exists()


def test_corrupt_control_is_named_and_writes_nothing(tmp_path):
    _control_marker, manifests = _control(tmp_path, name="miss3")
    broken = tmp_path / "broken.jsonl"
    broken.write_text("this is not json\n", encoding="utf-8")
    out = tmp_path / "policy.json"
    result = _run(tmp_path, control=broken, manifest_dir=manifests, out=out)
    assert result.ok is False
    assert result.cause == CONTROL_UNREADABLE
    assert not out.exists()


def test_missing_manifests_is_named_and_writes_nothing(tmp_path):
    control, _manifests = _control(tmp_path, name="miss4")
    out = tmp_path / "policy.json"
    result = _run(tmp_path, control=control, manifest_dir=None, out=out)
    assert result.ok is False
    assert result.cause == MANIFESTS_UNRESOLVABLE
    assert not out.exists()


def test_cli_without_manifest_dir_and_no_sibling_is_fail_closed(tmp_path, capsys):
    control, _manifests = _control(tmp_path, name="miss5", sibling=False)
    out = tmp_path / "policy.json"
    author = _write_fake_author(
        tmp_path,
        stdout_text=json.dumps(
            {"candidates": [{"scope": "tests/", "rule": "read-only"}]}
        ),
    )
    rc = cli.main(
        ["invariant", "infer", "--task", str(_task(tmp_path)), "--author", author,
         "--control", str(control), "--out", str(out), "--json",
         "--server", *CREATE_CMD]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 2, doc
    assert doc["error"] == {"cause": MANIFESTS_UNRESOLVABLE}
    assert not out.exists()


def test_cli_without_server_is_fail_closed(tmp_path, capsys):
    control, manifests = _control(tmp_path, name="miss6")
    out = tmp_path / "policy.json"
    author = _write_fake_author(
        tmp_path,
        stdout_text=json.dumps(
            {"candidates": [{"scope": "tests/", "rule": "read-only"}]}
        ),
    )
    rc = cli.main(
        ["invariant", "infer", "--task", str(_task(tmp_path)), "--author", author,
         "--control", str(control), "--manifest-dir", str(manifests), "--out", str(out)]
    )
    assert rc == 2
    assert not out.exists()


def test_artifact_write_failure_is_named(tmp_path, monkeypatch):
    control, manifests = _control(tmp_path, name="write")
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    out = blocked / "policy.json"
    _spy(monkeypatch)
    result = _run(tmp_path, control=control, manifest_dir=manifests, out=out)
    assert result.ok is False
    assert result.cause == ARTIFACT_WRITE_FAILED
    assert not out.exists()


# ---------------------------------------------------------------------------
# Repo inventory: bounded, sorted, and never the VCS metadata
# ---------------------------------------------------------------------------


def test_repo_inventory_is_sorted_bounded_and_skips_git(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("y = 2\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    control, manifests = _control(tmp_path, name="repo")
    out = tmp_path / "policy.json"
    _spy(monkeypatch)
    runner = _FakeRunner(_author_stdout({"scope": "tests/", "rule": "read-only"}))
    result = _run(
        tmp_path, control=control, manifest_dir=manifests, out=out,
        runner=runner, repo=repo,
    )
    assert result.ok is True, result
    payload = json.loads(runner.calls[0][1]["input"].decode("utf-8"))
    assert payload["repo"]["files"] == ["src/app.py", "tests/test_app.py"]
