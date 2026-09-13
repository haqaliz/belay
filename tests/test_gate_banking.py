"""The gate's divergence banking: a regression becomes a corpus case (aspect 4).

`belay gate check` now does moat #2's compounding by default: each divergent
TURN of the new capture whose transition regressed (the decision table's
regression rows) banks as a self-contained corpus case via the existing
`add_case`, labeled `pending` (the engine never labels its own cases), under the
standard `{new-trace-stem}-turnN` namespace. `--no-ingest` disables banking
(parity with `phase0 run`), a clean check banks nothing, and an ingest failure
(a case-id collision on a re-run) is error-contained: reported by name on the
gate surface, the gate's exit code unchanged, the stored case byte-untouched.

The MECHANICS tests run everywhere and are deliberately replay-free: the
verdict-recompute seam (`belay.gate.baseline.verify_turn`) is stubbed to a fixed
status, and the captures carry a SYNTHETIC `present` pre-state handle with a
fake manifest + tree (the `test_corpus_add` rig), so `add_case`'s composition
runs for real without any Seatbelt. That is the honesty split the plan pins:
banking mechanics (case created, expected FAIL stored, pending label,
`--no-ingest`, id collision, stored-policy fidelity) run everywhere; only the
full MATCH recompute — a REAL restore + re-invoke from the bundled pre-state —
is darwin-gated with a named cause, exactly like `tests/test_corpus_roundtrip.py`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.case import load_case
from belay.gate.bank import load_baseline
from belay.identity import RUN_ID_ENV
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

from conftest import CLIENT_LINES, FIXTURE, proxy_cmd, run_over_pipes

SERVER = [sys.executable, str(FIXTURE)]
FIXTURES = Path(__file__).parent / "fixtures"
FAST = FIXTURES / "fast_server.py"
MUTATING = FIXTURES / "mutating_server.py"

#: The scripted client calling `peek` — the fast fixture's tool (a real PASS
#: with a snapshot-bearing capture; the other frames are the shared CLIENT_LINES).
PEEK_LINES = [
    CLIENT_LINES[0],
    CLIENT_LINES[1],
    CLIENT_LINES[2],
    b'{"params":{"name":"peek","arguments":{}},"method":"tools/call","id":3,"jsonrpc":"2.0"}',
]

#: The one tool name both stubs report, matching the synthetic capture's call.
_TOOL = "echo"


def _stub(status: Status):
    """The recompute seam's stub: every `verify_turn` call answers one fixed status.

    The mechanics tests exercise the BANKING mechanics, not replay fidelity, so
    the recompute is pinned to a fixed verdict and never touches a sandbox. The
    stub keeps the real `TurnVerdict` shape (`turn_index`, `tool_name`, status,
    one sub-verdict), so `turn_record`, the comparison and `add_case` all flow.
    """

    def _stub_turn(records, n, **kwargs):
        return TurnVerdict(
            turn_index=n,
            tool_name=_TOOL,
            status=status,
            sub_verdicts=[
                Verdict("A2", "replay", status, None, None, f"stubbed {status.value}")
            ],
            cause=None,
        )

    return _stub_turn


# --- synthetic present-handle captures (the test_corpus_add rig) ----------------------


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": _TOOL, "annotations": {"readOnlyHint": True}}]},
        }
    ).encode()


def _call() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": _TOOL, "arguments": {}},
        }
    ).encode()


def _reply() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"content": [{"type": "text", "text": "echoed"}], "isError": False},
        }
    ).encode()


def _trace_with_identity(tmp_path: Path, name: str, frames: list[tuple]) -> Path:
    """Record `frames` via the REAL writer with a run identity; return the trace path."""
    trace_dir = tmp_path / name
    writer = TraceWriter.in_directory(trace_dir)
    try:
        writer.record("run_identity", run_id="pytest-7432")
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return sorted(trace_dir.glob("*.jsonl"))[0]


def _synthetic_run(tmp_path: Path, name: str, handle: str = "H1"):
    """A fake but well-formed present-handle run: `(trace_path, manifest_dir)`.

    The manifest + tree are synthetic (`add_case`'s composition is pure
    filesystem work); the `tools/call` carries a `present` handle matching it, so
    a banked case bundles a real pre-state tree without any substrate.
    """
    tree = tmp_path / f"{name}-tree"
    tree.mkdir()
    (tree / "note.txt").write_text("hello", encoding="utf-8")
    manifest_dir = tmp_path / f"{name}-manifests"
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
    trace = _trace_with_identity(
        tmp_path,
        name,
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _call(), {"status": "present", "handle": handle}),
            ("s2c", _reply(), None),
        ],
    )
    return trace, manifest_dir


def _capture(tmp_path: Path, name: str, run_id: str | None = None) -> Path:
    """Run the scripted client through the proxy; return the trace file's path.

    Snapshot-less: `BELAY_SNAPSHOT_DIR` is never set, so every recorded
    `state_handle` is `absent` and replay verdicts are honest UNVERIFIED.
    """
    trace_dir = tmp_path / name
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    if run_id is None:
        env.pop(RUN_ID_ENV, None)
    else:
        env[RUN_ID_ENV] = run_id
    run_over_pipes(proxy_cmd(FIXTURE), env=env)
    (path,) = sorted(trace_dir.glob("*.jsonl"))
    return path


def _root(tmp_path: Path, name: str = "root") -> Path:
    root_dir = tmp_path / name
    root_dir.mkdir()
    return root_dir


def _await_recorded(trace_dir: Path, msg_id: int) -> None:
    """Block until the trace holds the recorded s2c reply to `msg_id`.

    Forwarding runs AHEAD of recording, deliberately, so reading a reply on the
    proxy's stdout does NOT establish that the reply is in the trace. Waiting on
    the trace itself (never a sleep) is the sequencing
    `docker_roundtrip_client.py` established: the `tools/list` snapshot must
    precede the call in the trace, or effect-conformance abstains.
    """
    import base64 as b64
    import time

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for path in sorted(trace_dir.glob("*.jsonl")):
            for line in path.read_bytes().split(b"\n"):
                if not line:
                    continue
                record = json.loads(line)
                if record.get("kind") != "frame" or record.get("dir") != "s2c":
                    continue
                raw = record.get("raw", "")
                try:
                    message = json.loads(b64.b64decode(raw))
                except (ValueError, TypeError):
                    continue
                if message.get("id") == msg_id:
                    return
        time.sleep(0.005)
    raise AssertionError(
        f"the trace in {trace_dir!r} never recorded the s2c reply to id {msg_id}"
    )


def _snapshot_capture(
    tmp_path: Path,
    name: str,
    run_id: str,
    server: Path = FAST,
    lines: list[bytes] = PEEK_LINES,
    env_extra: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """A REAL snapshot-bearing capture through the gated proxy; return
    `(trace_path, manifest_dir)`.

    `BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` make the turn gate persist
    `present` handles and manifests, so a later check can restore the pre-state
    and re-invoke the server inside the Seatbelt sandbox. The client is SEQUENCED
    — it waits for the recorded `tools/list` reply before sending the call — so
    the annotation snapshot precedes the call and effect-conformance can decide
    instead of abstaining.
    """
    import subprocess

    base = Path(os.path.realpath(tmp_path))
    workspace = base / f"{name}-ws"
    workspace.mkdir()
    snaps = base / f"{name}-sn"
    snaps.mkdir()
    trace_dir = base / f"{name}-tr"
    trace_dir.mkdir()
    env = os.environ.copy()
    env["BELAY_SANDBOX_SCOPE"] = str(workspace)
    env["BELAY_SNAPSHOT_DIR"] = str(snaps)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    env[RUN_ID_ENV] = run_id
    if env_extra:
        env.update(
            {
                key: value.format(workspace=workspace)
                for key, value in env_extra.items()
            }
        )
    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", sys.executable, str(server)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    def send(raw: bytes, expect_reply: bool) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(raw + b"\n")
        proc.stdin.flush()
        if expect_reply:
            reply = proc.stdout.readline()
            assert reply, "the proxy closed without answering"

    send(lines[0], True)
    send(lines[1], False)
    send(lines[2], True)
    _await_recorded(trace_dir, 2)
    send(lines[3], True)
    assert proc.stdin is not None
    proc.stdin.close()
    if proc.wait(timeout=60) != 0:
        raise RuntimeError(f"the proxy exited non-zero for capture {name!r}")

    (trace_path,) = sorted(trace_dir.glob("*.jsonl"))
    manifest_dir = base / f"{name}-sn.manifests"
    assert manifest_dir.is_dir() and sorted(manifest_dir.glob("*.json"))
    return trace_path, manifest_dir


def _bank_clean(monkeypatch, tmp_path: Path, name: str) -> Path:
    """Bank a PASS-stubbed baseline under the shared root; return the trace path."""
    trace, manifest_dir = _synthetic_run(tmp_path, name)
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr("belay.gate.baseline.verify_turn", _stub(Status.PASS))
    rc = cli.main(
        ["gate", "baseline", str(trace), "--manifest-dir", str(manifest_dir), "--server", *SERVER]
    )
    assert rc == 0, f"banking failed for {name!r}"
    return root


def _stored_baseline(root: Path) -> dict:
    return json.loads(
        (root / "baselines" / "local" / "pytest-7432" / "baseline.json").read_text(encoding="utf-8")
    )


# --- mechanics, everywhere ------------------------------------------------------------


def test_regression_banks_divergent_turns(tmp_path, capsys, monkeypatch):
    """A PASS -> FAIL turn banks as a corpus case: expected FAIL, pending label,
    stored policy round-tripping the baseline (acceptance 1 mechanics).

    The recompute seam is stubbed: banked as PASS, checked as FAIL, so the
    comparison's regression row is deterministic. The banked case carries the
    STORED policy (invariants, server command, replays, timeout) and a `pending`
    label — the engine never labels its own cases.
    """
    root = _bank_clean(monkeypatch, tmp_path, "bank")
    trace2, manifest_dir2 = _synthetic_run(tmp_path, "cap")
    corpus = tmp_path / "corpus"
    monkeypatch.setattr("belay.gate.baseline.verify_turn", _stub(Status.FAIL))

    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifest_dir2),
         "--corpus-dir", str(corpus), "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "regression", doc
    assert doc["outcome"] == "REGRESSION", doc
    (row,) = doc["divergences"]
    assert row["expected"] == "PASS" and row["got"] == "FAIL" and row["regression"], row

    case_id = f"{Path(trace2).stem}-turn0"
    assert doc["ingest"]["banked"] == [case_id], doc
    assert doc["ingest"]["failures"] == [], doc

    case_dir = corpus / case_id
    assert case_dir.is_dir(), case_dir
    stored = load_case(case_dir)
    assert stored.expected["reduced_status"] == "FAIL", stored.expected
    assert stored.human_label == "pending", stored.human_label

    baseline = load_baseline(root / "baselines" / "local" / "pytest-7432")
    assert stored.invariants == baseline.policy["invariants"]
    assert stored.server_command == baseline.provenance["server_command"]
    assert stored.replays == baseline.policy["replays"]
    assert stored.timeout == baseline.policy["timeout"]


def test_no_ingest_banks_nothing(tmp_path, capsys, monkeypatch):
    """`--no-ingest` banks nothing and the gate's verdict/exit are unchanged
    (acceptance 2): same regression, exit 1, empty corpus dir, and the report is
    the ingest run's verdict report verbatim — the `ingest` section alone absent.
    """
    _bank_clean(monkeypatch, tmp_path, "bank")
    trace2, manifest_dir2 = _synthetic_run(tmp_path, "cap")
    monkeypatch.setattr("belay.gate.baseline.verify_turn", _stub(Status.FAIL))

    ingest_corpus = tmp_path / "ingest-corpus"
    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifest_dir2),
         "--corpus-dir", str(ingest_corpus), "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    ingest_doc = json.loads(out)
    assert ingest_doc["ingest"]["banked"], ingest_doc

    bare_corpus = tmp_path / "bare-corpus"
    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifest_dir2),
         "--corpus-dir", str(bare_corpus), "--no-ingest", "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    bare_doc = json.loads(out)
    assert "ingest" not in bare_doc, bare_doc
    assert not bare_corpus.exists() or not any(bare_corpus.iterdir())

    ingest_doc.pop("ingest")
    assert bare_doc == ingest_doc


def test_clean_check_banks_nothing(tmp_path, capsys, monkeypatch):
    """An unchanged re-run is clean and banks nothing (acceptance 4): real
    snapshot-less captures on both sides, every turn an honest UNVERIFIED, the
    comparison clean, and no corpus case written."""
    trace = _capture(tmp_path, "t1", run_id="pytest-7432")
    manifests = tmp_path / "m1"
    manifests.mkdir()
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(
        ["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER]
    )
    capsys.readouterr()
    assert rc == 0

    trace2 = _capture(tmp_path, "t2", run_id="pytest-7432")
    manifests2 = tmp_path / "m2"
    manifests2.mkdir()
    corpus = tmp_path / "corpus"
    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifests2),
         "--corpus-dir", str(corpus), "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "clean", doc
    assert "ingest" not in doc, doc
    assert not corpus.exists() or not any(corpus.iterdir())


def test_ingest_failure_is_error_contained(tmp_path, capsys, monkeypatch):
    """A re-banked regression's `CaseExistsError` is reported by name, the exit
    stays 1, and the stored case is byte-untouched (acceptance 3).

    The second check recomputes the SAME regression, `add_case` refuses the
    existing case id (a stored case may carry a human label), the refusal lands
    in the report's ingest section, and the first case's files are unchanged.
    """
    _bank_clean(monkeypatch, tmp_path, "bank")
    trace2, manifest_dir2 = _synthetic_run(tmp_path, "cap")
    corpus = tmp_path / "corpus"
    monkeypatch.setattr("belay.gate.baseline.verify_turn", _stub(Status.FAIL))

    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifest_dir2),
         "--corpus-dir", str(corpus), "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    case_id = f"{Path(trace2).stem}-turn0"
    case_dir = corpus / case_id
    assert case_dir.is_dir()
    first = {p.name: p.read_bytes() for p in sorted(case_dir.rglob("*")) if p.is_file()}
    assert first, case_dir

    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifest_dir2),
         "--corpus-dir", str(corpus), "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "regression", doc
    assert doc["ingest"]["banked"] == [], doc
    (failure,) = doc["ingest"]["failures"]
    assert failure["turn"] == 0, failure
    assert case_id in failure["cause"], failure
    assert "already exists" in failure["cause"], failure

    second = {p.name: p.read_bytes() for p in sorted(case_dir.rglob("*")) if p.is_file()}
    assert second == first


def test_banking_uses_stored_policy(tmp_path, capsys, monkeypatch):
    """The banked case carries the baseline's STORED policy, never re-resolved
    names: a distinctive operator-declared invariant survives bank -> check ->
    case verbatim, and the case's server command is the stored boundary's."""
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps([{"scope": "vendor/", "rule": "read-only"}]), encoding="utf-8")
    trace, manifest_dir = _synthetic_run(tmp_path, "bank")
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr("belay.gate.baseline.verify_turn", _stub(Status.PASS))
    rc = cli.main(
        ["gate", "baseline", str(trace), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--invariants", str(policy_file), "--server", *SERVER]
    )
    capsys.readouterr()
    assert rc == 0

    trace2, manifest_dir2 = _synthetic_run(tmp_path, "cap")
    corpus = tmp_path / "corpus"
    monkeypatch.setattr("belay.gate.baseline.verify_turn", _stub(Status.FAIL))
    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifest_dir2),
         "--corpus-dir", str(corpus)]
    )
    out = capsys.readouterr().out
    assert rc == 1, out

    baseline = load_baseline(root / "baselines" / "local" / "pytest-7432")
    assert baseline.policy["invariants"] == [{"scope": "vendor/", "rule": "read-only"}]
    stored = load_case(corpus / f"{Path(trace2).stem}-turn0")
    assert stored.invariants == baseline.policy["invariants"], stored.invariants
    assert stored.server_command == baseline.provenance["server_command"]
    assert stored.replays == baseline.policy["replays"]
    assert stored.timeout == baseline.policy["timeout"]


# --- darwin: the real MATCH recompute through `belay corpus run` ----------------------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: the banked case recomputes MATCH by re-invoking the server inside the macOS Seatbelt sandbox",
)


@pytestmark_darwin
def test_banked_case_recomputes_match(tmp_path, capsys, monkeypatch):
    """A REAL snapshot-bearing regression banks, and `belay corpus run` recomputes
    the case MATCH (acceptance 1 at fidelity): restore the bundled pre-state,
    re-invoke the STORED boundary, reproduce the banked FAIL verdict exactly.
    """
    trace, manifests = _snapshot_capture(tmp_path, "c1", "pytest-7432", server=FAST, lines=PEEK_LINES)
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(
        ["gate", "baseline", str(trace), "--manifest-dir", str(manifests),
         "--server", *[sys.executable, str(FAST)]]
    )
    capsys.readouterr()
    assert rc == 0

    trace2, manifests2 = _snapshot_capture(
        tmp_path, "c2", "pytest-7432", server=MUTATING, lines=PEEK_LINES,
        env_extra={"BELAY_TEST_MUTATE_PATH": "{workspace}/mut-target"},
    )
    corpus = tmp_path / "corpus"
    rc = cli.main(
        ["gate", "check", str(trace2), "--manifest-dir", str(manifests2),
         "--corpus-dir", str(corpus)]
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "REGRESSION" in out, out
    case_id = f"{Path(trace2).stem}-turn0"
    case_dir = corpus / case_id
    assert case_dir.is_dir(), out

    rc = cli.main(["corpus", "run", str(corpus)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert f"{case_id} MATCH" in out, out