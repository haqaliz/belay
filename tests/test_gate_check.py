"""The gate check command: compare a new capture against its banked baseline.

`belay gate check <trace>` answers "did the new agent version break a
previously-passing trajectory?" in CI, grounded in re-execution: it re-verifies
the banked baseline's OWN trace against the stored policy (proving replayability
and surfacing engine drift), verifies the new capture against the SAME stored
policy, and diffs the two verdict sets by the pure decision table
(`tests/test_gate_compare.py`). Exit 0 = comparison ran, no regression; 1 = a
grounded regression; 2 = preflight (missing baseline / no identity / unusable
baseline), outcome rendered UNVERIFIED + named cause — never a false clean, never
a false regression.

The mechanics tests run everywhere with SNAPSHOT-LESS captures (every turn is an
honest UNVERIFIED, so an unchanged re-run is byte-stable clean and a toolset
change is a named shape row). The regression tests need a REAL re-invocation —
replay requires `present` pre-state handles, which require the gated proxy's
snapshot, which re-invokes the server inside the macOS Seatbelt sandbox — so they
are darwin-gated with a named cause, exactly like `tests/test_gate_baseline.py`'s
snapshot roundtrip.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.identity import RUN_ID_ENV

from conftest import CLIENT_LINES, FIXTURE, proxy_cmd, run_over_pipes

SERVER = [sys.executable, str(FIXTURE)]
FIXTURES = Path(__file__).parent / "fixtures"
FAST = FIXTURES / "fast_server.py"
MUTATING = FIXTURES / "mutating_server.py"
NONDET = FIXTURES / "nondeterministic_server.py"

#: The scripted client calling `peek` — the fast fixture's tool, which declares
#: `readOnlyHint: true` and answers deterministically, so a snapshot-bearing turn
#: against it is a REAL PASS (the other frames are the shared CLIENT_LINES).
PEEK_LINES = [
    CLIENT_LINES[0],
    CLIENT_LINES[1],
    CLIENT_LINES[2],
    b'{"params":{"name":"peek","arguments":{}},"method":"tools/call","id":3,"jsonrpc":"2.0"}',
]

#: The scripted client calling `clobber` instead of `peek` — the toolset-change
#: capture (the other frames are the shared CLIENT_LINES, byte for byte).
CLOBBER_LINES = [
    CLIENT_LINES[0],
    CLIENT_LINES[1],
    CLIENT_LINES[2],
    b'{"params":{"name":"clobber","arguments":{}},"method":"tools/call","id":3,"jsonrpc":"2.0"}',
]


def _capture(
    tmp_path: Path,
    name: str,
    run_id: str | None = None,
    server: Path = FIXTURE,
    lines: list[bytes] = CLIENT_LINES,
    env_extra: dict[str, str] | None = None,
) -> Path:
    """Run the scripted client through the proxy; return the trace file's path.

    Snapshot-less: `BELAY_SNAPSHOT_DIR` is never set, so every recorded
    `state_handle` is `absent` and replay verdicts are honest UNVERIFIED. `run_id`
    None leaves `BELAY_RUN_ID` unset — absent-never-zero.
    """
    trace_dir = tmp_path / name
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    if run_id is None:
        env.pop(RUN_ID_ENV, None)
    else:
        env[RUN_ID_ENV] = run_id
    if env_extra:
        env.update(env_extra)
    run_over_pipes(proxy_cmd(server), env=env, lines=lines)
    (path,) = sorted(trace_dir.glob("*.jsonl"))
    return path


def _snapshot_capture(
    tmp_path: Path,
    name: str,
    run_id: str,
    server: Path = FIXTURE,
    lines: list[bytes] = CLIENT_LINES,
    env_extra: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """A REAL snapshot-bearing capture through the gated proxy; return
    `(trace_path, manifest_dir)`.

    `BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` make the turn gate persist
    `present` handles and manifests, so a later check can restore the pre-state
    and re-invoke the server inside the Seatbelt sandbox.
    """
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
        env.update(env_extra)
    run_over_pipes(proxy_cmd(server), env=env, lines=lines)
    (trace_path,) = sorted(trace_dir.glob("*.jsonl"))
    manifest_dir = base / f"{name}-sn.manifests"
    assert manifest_dir.is_dir() and sorted(manifest_dir.glob("*.json"))
    return trace_path, manifest_dir


def _root(tmp_path: Path, name: str = "root") -> Path:
    root_dir = tmp_path / name
    root_dir.mkdir()
    return root_dir


# --- everywhere: snapshot-less mechanics --------------------------------------------


def test_unchanged_capture_is_clean(tmp_path, capsys, monkeypatch):
    """Capture -> bank -> capture the same clean run again -> check -> exit 0, and
    the report is byte-stable against the baseline's expected set (acceptance 2).

    Snapshot-less, every turn is an honest UNVERIFIED on BOTH sides, so the
    comparison is equality: no divergences, no shape, no drift, clean exit. The
    capture verdicts in the report equal the stored expected set exactly — the
    gate's report is the bank's own machine contract, re-rendered.
    """
    trace = _capture(tmp_path, "t1", run_id="pytest-7432")
    manifests = tmp_path / "m1"
    manifests.mkdir()
    root = _root(tmp_path)
    monkeypatch.chdir(root)

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out

    trace2 = _capture(tmp_path, "t2", run_id="pytest-7432")
    manifests2 = tmp_path / "m2"
    manifests2.mkdir()
    rc = cli.main(["gate", "check", str(trace2), "--manifest-dir", str(manifests2), "--json"])
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "clean", doc
    assert doc["outcome"] == "PASS", doc
    assert doc["divergences"] == [] and doc["shape"] == [] and doc["drift"] == []
    assert doc["skip_reason"] is None, doc

    stored = json.loads(
        (root / "baselines" / "local" / "pytest-7432" / "baseline.json").read_text(encoding="utf-8")
    )
    assert doc["capture"]["turns"] == stored["expected"]["turns"]
    assert doc["capture"]["trajectory"] == stored["expected"]["trajectory"]


def test_missing_baseline_preflight(tmp_path, capsys, monkeypatch):
    """Check with no bank -> exit 2, `BASELINE_NOT_FOUND`, outcome UNVERIFIED +
    named cause (acceptance 3). Never a false clean, never a false regression.
    """
    trace = _capture(tmp_path, "t", run_id="pytest-7432")
    manifests = tmp_path / "m"
    manifests.mkdir()
    monkeypatch.chdir(_root(tmp_path))

    rc = cli.main(["gate", "check", str(trace), "--manifest-dir", str(manifests), "--json"])
    out = capsys.readouterr().out
    assert rc == 2, out
    doc = json.loads(out)
    assert doc["outcome"] == "UNVERIFIED", doc
    assert doc["exit_reason"] == "preflight", doc
    assert doc["skip_reason"] == "BASELINE_NOT_FOUND", doc
    assert "BASELINE_NOT_FOUND" in out, out


def test_no_identity_preflight(tmp_path, capsys, monkeypatch):
    """A trace without identity and no `--run-id` -> exit 2, `NO_RUN_IDENTITY`,
    outcome UNVERIFIED + named cause (acceptance 3)."""
    trace = _capture(tmp_path, "t")
    manifests = tmp_path / "m"
    manifests.mkdir()
    monkeypatch.chdir(_root(tmp_path))

    rc = cli.main(["gate", "check", str(trace), "--manifest-dir", str(manifests)])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "NO_RUN_IDENTITY" in out, out
    assert "UNVERIFIED" in out, out


def test_toolset_change_is_shape_not_failure(tmp_path, capsys, monkeypatch):
    """A capture against a DIFFERENT server (tool set differs) -> exit 0 with a
    named shape row, never a regression (acceptance 4 spirit).

    The tool name recorded on the turn is the toolset's: the new capture calls
    `clobber` where the baseline called `echo`, so the same ordinal carries a
    renamed tool and the gate reports the shape change — and, snapshot-less, both
    turns abstain identically, so no status transition exists to misread.
    """
    trace = _capture(tmp_path, "t1", run_id="pytest-7432")
    manifests = tmp_path / "m1"
    manifests.mkdir()
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out

    trace2 = _capture(
        tmp_path, "t2", run_id="pytest-7432", server=MUTATING, lines=CLOBBER_LINES,
        env_extra={"BELAY_TEST_MUTATE_PATH": str(tmp_path / "mut")},
    )
    manifests2 = tmp_path / "m2"
    manifests2.mkdir()
    rc = cli.main(["gate", "check", str(trace2), "--manifest-dir", str(manifests2), "--json"])
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "clean", doc
    assert doc["divergences"] == [], doc
    kinds = [row["kind"] for row in doc["shape"]]
    assert "tool-rename" in kinds, doc
    rename = next(row for row in doc["shape"] if row["kind"] == "tool-rename")
    assert rename["dimension"] == "turn 0", rename
    assert rename["expected"] == "echo" and rename["got"] == "clobber", rename


def test_json_report_contract(tmp_path, capsys, monkeypatch):
    """The `--json` document is a pinned machine contract; UNVERIFIED never
    renders as PASS anywhere in it (M7).

    The clean snapshot-less run renders every turn UNVERIFIED — so the document
    must NOT contain a single turn whose status is PASS — while the gate's own
    outcome is PASS ("the comparison found no regression"), with the abstentions
    named in the capture records that travel beside it. The key set is pinned:
    schema, run id, trace, outcome, exit reason, skip reason, the three row
    families, the capture verdicts and the coverage block.
    """
    trace = _capture(tmp_path, "t1", run_id="pytest-7432")
    manifests = tmp_path / "m1"
    manifests.mkdir()
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out

    trace2 = _capture(tmp_path, "t2", run_id="pytest-7432")
    manifests2 = tmp_path / "m2"
    manifests2.mkdir()
    rc = cli.main(["gate", "check", str(trace2), "--manifest-dir", str(manifests2), "--json"])
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert set(doc) == {
        "schema", "run_id", "trace", "outcome", "exit_reason", "skip_reason",
        "divergences", "shape", "drift", "capture", "coverage",
    }, doc
    assert doc["schema"] == 1
    assert doc["run_id"] == "pytest-7432"
    assert doc["outcome"] == "PASS"
    assert doc["exit_reason"] == "clean"
    assert doc["skip_reason"] is None
    assert doc["capture"]["turns"], doc
    for turn in doc["capture"]["turns"]:
        assert turn["status"] == "UNVERIFIED", turn
    assert '"status": "PASS"' not in out, out


# --- darwin: the real re-invocation (Seatbelt) --------------------------------------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: gate check re-invokes the server inside the macOS Seatbelt sandbox",
)


@pytestmark_darwin
def test_injected_failing_turn_regresses(tmp_path, capsys, monkeypatch):
    """A baseline re-verified against an injected trajectory change -> exit 1 with
    a named regression row (acceptance 1).

    The banked baseline's turn is a real PASS (snapshot restored, reply
    reproduces, declared readOnlyHint honoured). The second capture is made
    against a server that answers DIFFERENTLY (the mutating fixture's canned
    `clobbered`), so at check time the recorded call does not reproduce on the
    stored boundary: the replay diverges, the boundary offers the tool, the
    classifier finds the divergence deterministic, and the turn FAILs —
    PASS -> FAIL, named, exit 1. Never a silent pass.
    """
    trace, manifests = _snapshot_capture(tmp_path, "c1", "pytest-7432", server=FAST, lines=PEEK_LINES)
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *[sys.executable, str(FAST)]])
    out = capsys.readouterr().out
    assert rc == 0, out
    stored = json.loads(
        (root / "baselines" / "local" / "pytest-7432" / "baseline.json").read_text(encoding="utf-8")
    )
    assert stored["expected"]["turns"][0]["status"] == "PASS", stored

    trace2, manifests2 = _snapshot_capture(
        tmp_path, "c2", "pytest-7432", server=MUTATING, lines=PEEK_LINES,
        env_extra={"BELAY_TEST_MUTATE_PATH": str(tmp_path / "mut")},
    )
    rc = cli.main(["gate", "check", str(trace2), "--manifest-dir", str(manifests2), "--json"])
    out = capsys.readouterr().out
    assert rc == 1, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "regression", doc
    assert doc["outcome"] == "REGRESSION", doc
    (row,) = doc["divergences"]
    assert row["dimension"] == "turn 0 (peek)", row
    assert row["expected"] == "PASS" and row["got"] == "FAIL", row
    assert row["regression"], row
    assert doc["drift"] == [], doc


@pytestmark_darwin
def test_nondeterministic_turn_does_not_fail(tmp_path, capsys, monkeypatch):
    """A turn that replays divergently against a boundary that cannot settle ->
    UNVERIFIED with a named cause, exit 0 — never a regression (acceptance 4).

    The check replays the clean capture against an override boundary (the
    nondeterministic fixture): the reply diverges from the recorded one, the
    boundary probe cannot read a toolset (that server answers no `tools/list`),
    so the engine abstains with the named `boundary-undecided` cause instead of
    crying FAIL — the honest-conservative default, and the gate exits 0.
    """
    trace, manifests = _snapshot_capture(tmp_path, "c1", "pytest-7432", server=FAST, lines=PEEK_LINES)
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *[sys.executable, str(FAST)], "--timeout", "2"])
    assert rc == 0, capsys.readouterr().out

    trace2, manifests2 = _snapshot_capture(tmp_path, "c2", "pytest-7432", server=FAST, lines=PEEK_LINES)
    monkeypatch.setenv("BELAY_TEST_NONDET_SOURCE", "clock")
    rc = cli.main(["gate", "check", str(trace2), "--manifest-dir", str(manifests2), "--json", "--server", *[sys.executable, str(NONDET)]])
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["exit_reason"] == "clean", doc
    assert doc["divergences"] == [], doc
    (turn,) = doc["capture"]["turns"]
    assert turn["status"] == "UNVERIFIED", turn
    assert turn["cause"], turn


@pytestmark_darwin
def test_snapshot_roundtrip_regression(tmp_path, capsys, monkeypatch):
    """Full snapshot-bearing roundtrip: bank -> check -> exit 0 at fidelity; then
    an injected failing capture -> exit 1 with the named regression row (acceptance
    1+3 at fidelity).

    Unlike the snapshot-less mechanics tests, both turns here are REAL replayed
    verdicts (restore + re-invoke inside the Seatbelt sandbox), so the clean check
    is a grounded clean and the failing check a grounded regression.
    """
    trace, manifests = _snapshot_capture(tmp_path, "c1", "pytest-7432", server=FAST, lines=PEEK_LINES)
    root = _root(tmp_path)
    monkeypatch.chdir(root)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *[sys.executable, str(FAST)]])
    assert rc == 0, capsys.readouterr().out

    trace2, manifests2 = _snapshot_capture(tmp_path, "c2", "pytest-7432", server=FAST, lines=PEEK_LINES)
    rc = cli.main(["gate", "check", str(trace2), "--manifest-dir", str(manifests2)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REGRESSION" not in out, out

    trace3, manifests3 = _snapshot_capture(
        tmp_path, "c3", "pytest-7432", server=MUTATING, lines=PEEK_LINES,
        env_extra={"BELAY_TEST_MUTATE_PATH": str(tmp_path / "mut")},
    )
    rc = cli.main(["gate", "check", str(trace3), "--manifest-dir", str(manifests3)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "PASS -> FAIL" in out, out
    assert "REGRESSION" in out, out