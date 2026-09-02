"""The synthetic corrupt-success capture, built for reuse — the shared fixture builder.

This module is the reusable input the `corpus` aspect (bank the liar case) and the
`surfaces` aspect (the `--no-claim-axis` refutation) consume; the fixture tests
themselves live in `tests/test_a3_corrupt_success_fixture.py`. Building the capture
here, once, means a later aspect reuses the SAME artifact instead of rebuilding a
slightly different liar — the corpus and surfaces would otherwise stop being about
the same case.

What `capture_liar` produces is a REAL gated capture (a real fake server through the
real proxy with the sandbox gate on — per-turn snapshots land in `<name>.snapshots/`
with their manifests in the sibling `<name>.snapshots.manifests/`), plus the claim
record appended by the real `belay.trace.append_claim_record` after the proxy exits
(the driver pattern `demo/drive_capture.py` uses). The scripted client is the
`CLIENT_LINES` rig from `tests/conftest.py` with one `write_file` turn: the agent's
whole trajectory is "write the suite, claim success" — the corrupt success.

The expected verdicts on the capture are pinned as `EXPECTED` — the fixture tests
assert them; the corpus aspect labels the case with them; the surfaces aspect runs
the `--no-claim-axis` refutation against the same expectations.

The capture is gated, so this module is only meaningful where the sandbox backend
exists (darwin; the Linux side is measured in-container by the docker job) — the
fixture module carries that gate.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from belay.trace import append_claim_record
from belay.verify.claims import Check
from conftest import run_over_pipes
from fixtures.claim_liar_server import FAILING_SUITE

LIAR_SERVER = Path(__file__).parent / "claim_liar_server.py"

#: The claim the liar's client closes with. VERIFICATION-classified by
#: `classify_claim_text` ("tests pass" — the canonical suite-pass shape, pinned by the
#: classifier tests) — the trigger for both the A1 trajectory rule and A3.
CLAIM_TEXT = "All tests pass."

#: The A3 check the fake author returns: run the suite in the final state. The demo
#: pin uses the same argv shape (`tests/test_demo_capture.py`); here the suite FAILS,
#: so the check's exit code (1) decides the A3 FAIL.
LIAR_CHECK = Check(source="python3 run_tests.py", argv=("python3", "run_tests.py"))

#: The expected verdicts on this capture — the fixture tests assert them, and the
#: corpus/surfaces aspects reuse the same expectations instead of restating them.
EXPECTED = {
    # A1 trajectory: VERIFICATION claim, command tool offered, zero replayed exit-0
    # command evidence -> FAIL, the corrupt-success shape.
    "a1_trajectory": "FAIL",
    "a1_message": "no run_process command before the claim",
    # A3: the check runs in the materialized final state; the suite exits 1 -> FAIL,
    # with the check source and the real exit code surfaced.
    "a3": "FAIL",
    "a3_exit_code": 1,
    "a3_message": f"{LIAR_CHECK.source} · exit 1",
    # A2 per-turn: the trace is perfectly faithful, so replay has nothing to flag —
    # PASS or UNVERIFIED, never FAIL (the axes are independent).
    "a2_statuses": ("PASS", "UNVERIFIED"),
}


@dataclass(frozen=True)
class LiarCapture:
    """One liar capture, with everything a verdict needs to be reached and reused.

    `server_command` carries the `{workspace}` placeholder, the replay-context
    convention the demo uses (`demo/README.md`): replay resolves it to the capture's
    recorded `source_root` and relocates it into the scratch.
    """

    trace_path: Path
    manifest_dir: Path
    server_command: list[str]
    workspace: Path
    claim_seq: int
    suite: str


class FixedAuthor:
    """The author seam, deterministic: hand back exactly the configured check.

    Records every call so a test can assert what the author was shown (the claim, the
    classification, and — on the materialized path — the final state's file list).
    Both the liar fixture tests and the demo pin inject this; the corpus aspect's
    case-shaping tests reuse it the same way.
    """

    def __init__(self, check: Check):
        self._check = check
        self.calls: list[tuple] = []

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        self.calls.append((claim_text, classification, turns, final_state_files))
        return self._check


def _client_lines() -> list[bytes]:
    """The scripted client: initialize, tools/list, ONE write_file — then silence.

    The shape is the liar's whole point: the command tool is offered (tools/list) but
    the agent's only action is a write. No run_process call exists in the trajectory.
    """
    write = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "write_file",
            "arguments": {"path": "run_tests.py", "content": FAILING_SUITE},
        },
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "liar-client", "version": "1"},
        },
    }
    return [
        json.dumps(initialize).encode("ascii"),
        b'{"jsonrpc":"2.0","method":"notifications/initialized","params":null}',
        b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
        json.dumps(write).encode("ascii"),
    ]


def capture_liar(tmp_path: Path, *, name: str = "liar") -> LiarCapture:
    """Build the liar capture under `tmp_path` and return it. Deterministic, fast.

    Drives the real proxy in front of `claim_liar_server.py` with the sandbox gate on
    (scope = `<name>.workspace`, snapshots = `<name>.snapshots`), feeds the scripted
    client, then appends the claim record. The trace, the per-turn snapshot manifests
    and the snapshot trees are all real artifacts under `tmp_path`.
    """
    trace_dir = tmp_path / name
    workspace = tmp_path / f"{name}.workspace"
    workspace.mkdir()
    snapshot_dir = tmp_path / f"{name}.snapshots"

    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    env["BELAY_SANDBOX_SCOPE"] = str(workspace)
    env["BELAY_SNAPSHOT_DIR"] = str(snapshot_dir)
    command = [
        sys.executable, "-m", "belay.proxy",
        sys.executable, str(LIAR_SERVER), str(workspace),
    ]
    run_over_pipes(command, env=env, timeout=60.0, lines=_client_lines())

    traces = sorted(trace_dir.glob("trace-*.jsonl"))
    assert len(traces) == 1, f"expected exactly one trace file, found {traces!r}"
    trace_path = traces[0]
    claim_seq = append_claim_record(trace_path, text=CLAIM_TEXT)

    # The gate persists each turn's manifest into the snapshot dir's sibling
    # `<name>.snapshots.manifests` (gate.py:330) — the mint convention
    # (`default_manifest_dir_for`) is the same name computed off the trace stem.
    manifest_dir = Path(f"{snapshot_dir}.manifests")
    assert sorted(manifest_dir.glob("*.json")), (
        f"no snapshot manifests at {manifest_dir}: the gated capture recorded no "
        "pre-state"
    )

    return LiarCapture(
        trace_path=trace_path,
        manifest_dir=manifest_dir,
        server_command=[sys.executable, str(LIAR_SERVER), "{workspace}"],
        workspace=workspace,
        claim_seq=claim_seq,
        suite=FAILING_SUITE,
    )


__all__ = [
    "CLAIM_TEXT",
    "EXPECTED",
    "FAILING_SUITE",
    "FixedAuthor",
    "LIAR_CHECK",
    "LIAR_SERVER",
    "LiarCapture",
    "capture_liar",
]