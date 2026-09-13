"""The ci-regression-gate baseline bank: self-contained, identity-keyed, byte-stable.

`belay gate baseline <trace>` verifies a capture by RE-EXECUTION and stores the
expected verdict set — plus the trace, manifests and snapshot trees — under
`baselines/local/<run-id>/`, keyed by the trace's `run_identity` record
(`BELAY_RUN_ID`, aspect 1) or a `--run-id` override. A later `gate check` (aspect 3)
re-verifies against the STORED policy and diffs, so the bank must be deterministic:
re-banking the same trace yields a byte-identical baseline document, and the stored
expected set is exactly what `belay verify --json` of the same trace renders.

These tests pin the aspect's acceptance criteria: the banked baseline is
self-contained and byte-stable, the stored expected set equals the verify surface's
own machine contract, an unidentifiable capture fails closed (`NO_RUN_IDENTITY`,
nothing written), re-banking requires `--force`, provenance round-trips through the
store, and a missing manifest dir fails closed.

The mechanics tests run everywhere with a SNAPSHOT-LESS capture (the proxy records
`absent` pre-state handles, so every turn is an honest UNVERIFIED — no replay
happens, no substrate is needed). The full snapshot-bearing roundtrip re-invokes the
server inside the macOS Seatbelt sandbox, so it is darwin-gated with a named cause,
exactly like `tests/test_corpus_roundtrip.py`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.identity import RUN_ID_ENV

from conftest import FIXTURE, proxy_cmd, run_over_pipes

SERVER = [sys.executable, str(FIXTURE)]


def _capture(tmp_path: Path, name: str, run_id: str | None = None) -> Path:
    """Run the scripted client through the proxy; return the trace file's path.

    Snapshot-less: `BELAY_SNAPSHOT_DIR` is never set, so every recorded
    `state_handle` is `absent` and replay verdicts are honest UNVERIFIED. `run_id`
    None leaves `BELAY_RUN_ID` unset — absent-never-zero; any other value is set
    verbatim on the child env.
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


def _baseline_root(tmp_path: Path, root: str) -> Path:
    root_dir = tmp_path / root
    root_dir.mkdir(exist_ok=True)
    return root_dir


def test_bank_self_contained_and_byte_stable(tmp_path, capsys, monkeypatch):
    """A clean capture banks a full baseline dir; re-banking into a fresh root
    yields a byte-identical baseline.json.

    The layout is the aspect's contract: `baseline.json` + `trace.jsonl` +
    `manifests/` + `snapshots/` under `baselines/local/<run-id>/`. Byte-stability
    is what makes a re-bank comparable at all — a baseline that drifted between
    two banks of the same trace could not anchor a gate diff.
    """
    trace = _capture(tmp_path, "t", run_id="pytest-7432")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    root_a = _baseline_root(tmp_path, "root-a")

    monkeypatch.chdir(root_a)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    out = capsys.readouterr().out
    assert rc == 0, out

    bank_dir = root_a / "baselines" / "local" / "pytest-7432"
    assert (bank_dir / "baseline.json").is_file(), out
    assert (bank_dir / "trace.jsonl").is_file(), out
    assert (bank_dir / "manifests").is_dir(), out
    assert (bank_dir / "snapshots").is_dir(), out
    first = (bank_dir / "baseline.json").read_bytes()

    root_b = _baseline_root(tmp_path, "root-b")
    monkeypatch.chdir(root_b)
    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out

    second = (root_b / "baselines" / "local" / "pytest-7432" / "baseline.json").read_bytes()
    assert second == first


def test_bank_stores_expected_verdict_set(tmp_path, capsys, monkeypatch):
    """The stored expected set is the verify surface's own machine contract.

    `expected.turns`/`trajectory` equal `belay verify --json`'s turns/trajectory
    of the same trace — same builders, same composition, one computation. With no
    claim author configured the claim key is ABSENT (absent-never-zero), exactly as
    the verify document omits it. `--json` prints the stored baseline document.
    """
    trace = _capture(tmp_path, "t", run_id="pytest-7432")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    monkeypatch.chdir(_baseline_root(tmp_path, "root"))

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--json", "--server", *SERVER])
    out = capsys.readouterr().out
    assert rc == 0, out
    stored = json.loads(out)

    rc = cli.main(["verify", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER, "--json"])
    out = capsys.readouterr().out
    assert rc == 1, out  # the snapshot-less trace's UNVERIFIED turns exit non-zero
    doc = json.loads(out)

    assert stored["expected"]["turns"] == doc["turns"]
    assert stored["expected"]["trajectory"] == doc["trajectory"]
    assert "claim" not in stored["expected"]
    assert "claim" not in doc


def test_bank_without_identity_fails_closed(tmp_path, capsys, monkeypatch):
    """A trace with no identity (and no `--run-id`) exits 2 with `NO_RUN_IDENTITY`
    and writes nothing; `--run-id X` banks under X.

    An unusable override is refused too: a run id that cannot safely become a
    directory key must never create a weird path (the fail-closed contract
    `identity.validate_run_id` pins at capture).
    """
    trace = _capture(tmp_path, "t")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    root = _baseline_root(tmp_path, "root")
    monkeypatch.chdir(root)

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "NO_RUN_IDENTITY" in out, out
    assert not (root / "baselines").exists()

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--run-id", "task/agent-vN", "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out
    assert (root / "baselines" / "local" / "task" / "agent-vN" / "baseline.json").is_file()

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--run-id", "a b", "--server", *SERVER])
    assert rc == 2, capsys.readouterr().out


def test_rebank_requires_force(tmp_path, capsys, monkeypatch):
    """Re-banking an existing run id without `--force` exits 2 and leaves the
    stored baseline byte-untouched; `--force` replaces it.

    The refusal is decided BEFORE any write — a failed re-bank must never
    truncate or half-rewrite the stored baseline.
    """
    trace = _capture(tmp_path, "t", run_id="pytest-7432")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    root = _baseline_root(tmp_path, "root")
    monkeypatch.chdir(root)

    argv = ["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER]
    assert cli.main(argv) == 0
    stored = root / "baselines" / "local" / "pytest-7432" / "baseline.json"
    first = stored.read_bytes()

    rc = cli.main(argv)
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "already exists" in out, out
    assert stored.read_bytes() == first

    rc = cli.main(argv + ["--force"])
    assert rc == 0, capsys.readouterr().out
    assert stored.is_file()


def test_provenance_round_trips(tmp_path, capsys, monkeypatch):
    """Provenance and the stored policy round-trip through the store.

    `engine_version` (from the installed distribution), `platform` and the
    resolved `server_command` are recorded; the A1 policy is stored as the
    RESOLVED invariant list — never re-resolved at load. Snapshot-less, the
    `capabilities` key is OMITTED (absent-never-zero).
    """
    from belay.gate.bank import load_baseline

    trace = _capture(tmp_path, "t", run_id="task/agent-vN")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    root = _baseline_root(tmp_path, "root")
    monkeypatch.chdir(root)

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(manifests), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out

    baseline = load_baseline(root / "baselines" / "local" / "task" / "agent-vN")
    assert baseline.run_id == "task/agent-vN"
    assert isinstance(baseline.provenance["engine_version"], str)
    assert baseline.provenance["engine_version"]
    assert baseline.provenance["platform"] == sys.platform
    assert baseline.provenance["server_command"] == SERVER
    assert "capabilities" not in baseline.provenance
    assert baseline.policy["replays"] == 3
    assert baseline.policy["timeout"] == 10.0
    assert [inv["rule"] for inv in baseline.policy["invariants"]] == [
        "no-assertion-weakening",
        "no-assertion-weakening",
        "suite-before-success-claim",
    ]
    assert baseline.policy["manifest_dir"] == "manifests"


def test_missing_manifest_dir_fails_closed(tmp_path, capsys, monkeypatch):
    """A `--manifest-dir` pointing nowhere exits 2 and writes nothing."""
    trace = _capture(tmp_path, "t", run_id="pytest-7432")
    root = _baseline_root(tmp_path, "root")
    monkeypatch.chdir(root)

    rc = cli.main(["gate", "baseline", str(trace), "--manifest-dir", str(tmp_path / "nowhere"), "--server", *SERVER])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "--manifest-dir" in out, out
    assert not (root / "baselines").exists()


def test_manifest_dir_defaults_to_stem_sibling_only_when_it_exists(tmp_path, capsys, monkeypatch):
    """Without `--manifest-dir`, the trace's `<stem>.manifests` sibling is the
    default ONLY when it exists (the mint convention); absent it, the flag is
    required and the bank fails closed."""
    trace = _capture(tmp_path, "t", run_id="pytest-7432")
    root = _baseline_root(tmp_path, "root")
    monkeypatch.chdir(root)

    rc = cli.main(["gate", "baseline", str(trace), "--server", *SERVER])
    assert rc == 2, capsys.readouterr().out

    sibling = trace.parent / (trace.stem + ".manifests")
    sibling.mkdir()
    rc = cli.main(["gate", "baseline", str(trace), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out
    assert (root / "baselines" / "local" / "pytest-7432" / "baseline.json").is_file()


# --- darwin: the real snapshot-bearing roundtrip --------------------------------------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: gate baseline re-invokes the server inside the macOS Seatbelt sandbox",
)


@pytestmark_darwin
def test_bank_roundtrip_with_snapshots(tmp_path, capsys, monkeypatch):
    """A real snapshot-bearing capture banks self-contained: every bundled
    manifest's tree_path is rewritten to a RELATIVE path inside the baseline's
    own `snapshots/` — no path outside the baseline dir remains — and the stored
    expected set equals a fresh verify of the same trace.

    Captured through the real gated proxy with `BELAY_SNAPSHOT_DIR` (the trace
    carries `present` handles and the gate persists the manifests), so the bank
    must copy each snapshot tree in and re-point the manifests at the copies —
    the exact property that makes the baseline survive deletion of the original
    run.
    """
    base = Path(os.path.realpath(tmp_path))
    workspace = base / "ws"
    workspace.mkdir()
    snaps = base / "sn"
    snaps.mkdir()
    trace_dir = base / "tr"
    trace_dir.mkdir()

    env = os.environ.copy()
    env["BELAY_SANDBOX_SCOPE"] = str(workspace)
    env["BELAY_SNAPSHOT_DIR"] = str(snaps)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    env[RUN_ID_ENV] = "pytest-7432"
    run_over_pipes(proxy_cmd(FIXTURE), env=env)
    (trace_path,) = sorted(trace_dir.glob("*.jsonl"))
    manifest_dir = base / "sn.manifests"
    assert manifest_dir.is_dir() and sorted(manifest_dir.glob("*.json"))

    root = base / "root"
    root.mkdir()
    monkeypatch.chdir(root)
    rc = cli.main(["gate", "baseline", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *SERVER])
    assert rc == 0, capsys.readouterr().out

    bank_dir = root / "baselines" / "local" / "pytest-7432"
    stored = json.loads((bank_dir / "baseline.json").read_text(encoding="utf-8"))
    snapshots = (bank_dir / "snapshots").resolve()
    for manifest in sorted((bank_dir / "manifests").glob("*.json")):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        tree = Path(payload["tree_path"])
        assert not tree.is_absolute(), payload["tree_path"]
        resolved = (bank_dir / "manifests" / tree).resolve()
        assert resolved.parent == snapshots, payload["tree_path"]
        assert resolved.is_dir(), payload["tree_path"]

    rc = cli.main(["verify", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *SERVER, "--json"])
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert stored["expected"]["turns"] == doc["turns"]