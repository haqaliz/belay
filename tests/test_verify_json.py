"""`belay verify --json` — the machine contract: ONE document, same objects as the text.

The console seam (live-console L6 / C7, aspect `verify-json`): the console cannot parse
human text and must never compute verdicts itself, so `belay verify --json` emits exactly
what the human report says — per-turn records with every sub-verdict (NOT_COVERED
included, UNVERIFIED with its named cause), the aggregate, the ALWAYS-present coverage
block, the exposure facts, and the trajectory disposition — rendered from the SAME
structured objects the text renderers consume. One computation, two renderers; a
divergence between the two surfaces fails a test here.

The shape is a pinned machine contract: `tests/fixtures/verify_json_snapshot.json` is
committed from the spec's shape (not from an implementation) and the first test compares
the emitted document against it field for field. Deliberate changes are contract changes
and re-pin the snapshot.

The trace under test is a REAL captured run: the docker-roundtrip fixture drives the
gated proxy (`docker_roundtrip_client.py` in front of `docker_roundtrip_server.py`),
which snapshots the workspace and records one `write_note` tools/call that declares
`openWorldHint: false` — so the emitted document carries a genuine NOT_COVERED
`effect:network` sub-verdict and its coverage block, the exact honesty shapes the
contract exists to carry.

Darwin-gated like every verify-surface test: replay re-invokes inside the macOS Seatbelt
sandbox (the Linux-host path is exercised by the docker in-image suite).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION

from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = Path(__file__).parent / "fixtures" / "verify_json_snapshot.json"

#: The placeholder the pinned snapshot carries in `trace`; the test normalizes the live
#: document's (necessarily run-specific) trace path to it before comparing.
TRACE_PLACEHOLDER = "<trace path as given>"

EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)

STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"


def _capture_roundtrip(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Capture one real `write_note` turn through the gated proxy; return
    `(trace, manifest_dir, server_script)`.

    The workspace is REALPATH'd before anything records: the gate stores the realpath as
    the manifest's `source_root` and replay relocation is lexical, so a workspace under a
    symlinked tmp root (macOS `/tmp` -> `/private/tmp`) would not lexically match and the
    replayed write would be denied — the artifact-install precedent,
    `tests/test_artifact_install.py:212-217`.
    """
    base = Path(os.path.realpath(tmp_path))
    ws = base / "ws"
    ws.mkdir()
    snap = base / "sn"
    snap.mkdir()
    trace_dir = base / "tr"
    trace_dir.mkdir()
    shutil.copy(FIXTURES / "docker_roundtrip_server.py", ws / "server.py")
    shutil.copy(FIXTURES / "docker_roundtrip_trace.py", ws / "docker_roundtrip_trace.py")

    env = os.environ.copy()
    env["BELAY_SANDBOX_SCOPE"] = str(ws)
    env["BELAY_SNAPSHOT_DIR"] = str(snap)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    capture = subprocess.run(
        [
            sys.executable,
            str(FIXTURES / "docker_roundtrip_client.py"),
            str(ws / "server.py"),
            str(ws / "note.txt"),
        ],
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    traces = sorted(trace_dir.glob("*.jsonl"))
    assert len(traces) == 1, traces
    return traces[0], base / "sn.manifests", ws / "server.py"


@pytest.fixture(scope="module")
def roundtrip(tmp_path_factory):
    """One real captured roundtrip run, shared by the whole module.

    Verify re-executes against its own scratch restores and never writes back into the
    capture, so every test here can re-run the CLI over the same trace+manifests.
    """
    return _capture_roundtrip(tmp_path_factory.mktemp("verify-json-roundtrip"))


def _verify(trace, manifest_dir, server, *flags: str) -> subprocess.CompletedProcess:
    """Drive the REAL CLI (`python -m belay.cli`) over a trace.

    `flags` are placed BEFORE `--server`: the server argument is
    `argparse.REMAINDER`, so anything after it is consumed into the server command.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "belay.cli",
            "verify",
            str(trace),
            "--manifest-dir",
            str(manifest_dir),
            *flags,
            "--server",
            sys.executable,
            str(server),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )


def _json(run: subprocess.CompletedProcess) -> dict:
    """The emitted document: stdout must be ONE parseable JSON document, nothing else."""
    assert run.stdout.strip().startswith("{"), (
        f"stdout is not a JSON document (rc={run.returncode}):\n{run.stdout[:2000]}"
    )
    return json.loads(run.stdout)


def _editor_trace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A real-replay trace whose turn FAILs via the A1 default and carries NO
    NOT_COVERED sub-verdict (the editor declares no `openWorldHint`).

    Mirror of `test_verify_cli_invariants._demo_trace`: the pre-state holds the STRONG
    test, the editor overwrites it with the gutted body, so the A1
    `no-assertion-weakening` invariant FAILs the corrupt success — a non-zero exit the
    exit-code agreement test needs, and the empty-coverage shape the coverage test needs.
    """
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_TEST, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    handle = present_handle(snap)

    tools_list = [
        (
            "c2s",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode(),
            None,
        ),
        (
            "s2c",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "tools": [
                            {"name": "edit_file", "annotations": {"readOnlyHint": False}}
                        ]
                    },
                }
            ).encode(),
            None,
        ),
    ]
    call = (
        "c2s",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "edit_file", "arguments": {}},
            }
        ).encode(),
        handle,
    )
    reply = (
        "s2c",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {
                    "content": [{"type": "text", "text": "edited tests/test_auth.py"}],
                    "isError": False,
                },
            }
        ).encode(),
        None,
    )

    trace_dir = tmp_path / "trace"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, frame_handle in tools_list + [call, reply]:
            if frame_handle is not None:
                writer.set_state_handle(frame_handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return sorted(trace_dir.glob("*.jsonl"))[0], manifest_dir, FIXTURES / "weakening_editor_server.py"


def test_json_emits_the_pinned_machine_contract(roundtrip) -> None:
    """The emitted document equals the committed snapshot, field for field.

    The snapshot is the pinned contract (`tests/fixtures/verify_json_snapshot.json`),
    written from the spec's shape before any implementation existed. A divergence — a
    renamed key, a dropped sub-verdict, a PASS rendered without its coverage block, a
    status that disagrees with the human report — fails HERE, and a deliberate contract
    change is made by re-pinning the snapshot, never silently.
    """
    trace, manifest_dir, server = roundtrip
    run = _verify(trace, manifest_dir, server, "--json")

    assert run.returncode == 0, run.stdout + run.stderr
    doc = _json(run)
    assert doc["trace"] == str(trace)
    doc["trace"] = TRACE_PLACEHOLDER
    assert doc == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_json_not_covered_sub_verdict_is_never_pass_nor_dropped(roundtrip) -> None:
    """The NOT_COVERED sub-verdict appears as NOT_COVERED with its message.

    The contract's honesty rule: a tool that declared `openWorldHint: false` carries an
    `effect:network` sub-verdict on the machine surface exactly as on the human one —
    never folded into the PASS, never dropped, never renamed into a verdict the console
    could read as a network check.
    """
    trace, manifest_dir, server = roundtrip
    doc = _json(_verify(trace, manifest_dir, server, "--json"))

    network = [
        s
        for s in doc["turns"][0]["sub_verdicts"]
        if s["kind"] == "effect:network"
    ]
    assert len(network) == 1, doc["turns"][0]["sub_verdicts"]
    assert network[0]["status"] == "NOT_COVERED"
    assert network[0]["message"], "the NOT_COVERED sub-verdict must carry its message"


def test_json_agrees_with_the_human_report(roundtrip) -> None:
    """One computation, two renderers: the JSON content is the text content, structured.

    Every turn's (ordinal, tool, status, cause) and every sub-verdict's message are
    rendered from the SAME objects; this test drives the text run and asserts the JSON
    surface carries exactly what the human surface printed. A divergence — the JSON
    recomputing a verdict the text did not print, or the text printing a sub-verdict the
    JSON dropped — fails here.
    """
    trace, manifest_dir, server = roundtrip
    text = _verify(trace, manifest_dir, server)
    doc = _json(_verify(trace, manifest_dir, server, "--json"))

    for turn in doc["turns"]:
        assert f"turn {turn['ordinal']}" in text.stdout, text.stdout
        assert turn["tool"] in text.stdout, text.stdout
        assert turn["status"] in text.stdout, text.stdout
        for sub in turn["sub_verdicts"]:
            assert sub["message"] in text.stdout, (
                f"JSON carries a sub-verdict the human report did not print: {sub}"
            )


def test_json_coverage_block_is_always_present(roundtrip, tmp_path) -> None:
    """The coverage block travels with the status on the machine surface too.

    A PASS without its coverage block is the failure mode `NOT_COVERED` exists to
    prevent, so the block must be present even when there is nothing to report: the
    roundtrip document carries its `effect:network` entry, and a run with NO
    NOT_COVERED sub-verdict at all still carries the (empty) `coverage` key — a document
    missing the key fails this test.
    """
    trace, manifest_dir, server = roundtrip
    doc = _json(_verify(trace, manifest_dir, server, "--json"))

    assert "coverage" in doc
    entry = doc["coverage"]["effect:network"]
    assert entry == {
        "not_observed_turns": 1,
        "of_turns": 1,
        "message": doc["turns"][0]["sub_verdicts"][2]["message"],
    }

    editor_trace, editor_manifests, editor_server = _editor_trace(tmp_path)
    empty = _json(_verify(editor_trace, editor_manifests, editor_server, "--json"))
    assert "coverage" in empty, "the coverage key must be present even when empty"
    assert empty["coverage"] == {}


def test_json_and_text_exit_codes_agree(roundtrip, tmp_path) -> None:
    """`--json` changes the renderer, never the verdict or the exit code.

    The same run exits identically with and without `--json` in all three directions:
    all-PASS (0), an A1 FAIL (1), and an UNVERIFIED turn (1).
    """
    trace, manifest_dir, server = roundtrip
    assert _verify(trace, manifest_dir, server).returncode == 0
    assert _verify(trace, manifest_dir, server, "--json").returncode == 0

    editor_trace, editor_manifests, editor_server = _editor_trace(tmp_path)
    assert _verify(editor_trace, editor_manifests, editor_server).returncode == 1
    assert _verify(editor_trace, editor_manifests, editor_server, "--json").returncode == 1

    missing = tmp_path / "no-manifests"
    missing.mkdir()
    assert _verify(trace, missing, server).returncode == 1
    assert _verify(trace, missing, server, "--json").returncode == 1


def test_json_on_forced_failure_is_valid_and_never_truncated(roundtrip) -> None:
    """An internal failure emits ONE valid error document and a non-zero exit.

    `--turn N` out of range is the fail-fast path: with `--json` the command must not
    print a half-written `turns` document — stdout is a single parseable JSON document
    whose `error` names the cause and whose `turns` is empty, and the exit code matches
    the text run's.
    """
    trace, manifest_dir, server = roundtrip
    text = _verify(trace, manifest_dir, server, "--turn", "99")
    run = _verify(trace, manifest_dir, server, "--json", "--turn", "99")

    assert text.returncode == 2, text.stdout
    assert run.returncode == text.returncode
    doc = _json(run)
    assert doc["error"] is not None
    assert "out of range" in doc["error"]["cause"]
    assert doc["turns"] == [], "a failed run must not emit a truncated turns document"
    assert "coverage" in doc, "the coverage key travels with the error document too"


def test_json_unverified_turn_carries_its_named_cause(roundtrip, tmp_path) -> None:
    """An UNVERIFIED turn appears as UNVERIFIED with its named cause — never as PASS.

    A manifest dir that holds nothing for the turn's handle is the honest fail-soft
    path: the turn is UNVERIFIED with the engine's `manifest not found` bucket, and the
    machine surface carries it exactly as the text report does.
    """
    trace, manifest_dir, server = roundtrip
    missing = tmp_path / "no-manifests"
    missing.mkdir()
    run = _verify(trace, missing, server, "--json")

    assert run.returncode == 1, run.stdout
    doc = _json(run)
    turn = doc["turns"][0]
    assert turn["status"] == "UNVERIFIED"
    assert turn["cause"] == "manifest not found"
    assert any(
        s["status"] == "UNVERIFIED" and s["kind"] == "replay"
        for s in turn["sub_verdicts"]
    )
    assert doc["aggregate"]["UNVERIFIED"] == 1


def test_json_turn_n_keeps_one_record_and_null_trajectory(roundtrip) -> None:
    """`--turn N` narrows the document to ONE record and nulls the trajectory.

    With `--turn N` the facts seam is partial (only one turn was verified), so an
    instance-level trajectory verdict would be fabricated — the text report suppresses
    the line, and the machine surface mirrors that with `"trajectory": null` while the
    whole-trace run carries the real disposition.
    """
    trace, manifest_dir, server = roundtrip
    whole = _json(_verify(trace, manifest_dir, server, "--json"))
    single = _json(_verify(trace, manifest_dir, server, "--json", "--turn", "0"))

    assert len(single["turns"]) == 1
    assert single["turns"][0]["ordinal"] == 0
    assert single["turns"][0]["tool"] == "write_note"
    assert single["trajectory"] is None
    assert whole["trajectory"] is not None
    assert whole["trajectory"]["status"] == "UNVERIFIED"
    assert whole["trajectory"]["cause"] == "NO_CLAIM_RECORDED"