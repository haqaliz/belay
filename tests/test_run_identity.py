"""Run identity: `BELAY_RUN_ID` captured once into the trace as a `run_identity` record.

A trace carries no identity: the filename stem is the only key and `trace_id`
is explicitly not unique across stages. The ci-regression-gate's baseline bank
needs an in-band key so it can know two captures are "the same run" — this is
that key. The operator sets `BELAY_RUN_ID=<task>/<agent-version>` at capture
time; the proxy validates it fail-closed (exit 2 on an unusable value), records
it once at start (absent-never-zero when unset), and any reader can recover it
via `derive_run_identity` without guessing.

These tests pin the aspect's acceptance criteria: capture with the env set
records and derives the id (and never more than once), capture without it stays
absent, the reader keeps the record as an understood kind (new kind in `KINDS`,
no schema bump), derive ignores other records and malformed values, unusable
ids are rejected at capture with a named error, and valid ids — slashes
included — are recorded verbatim.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from belay.identity import RUN_ID_ENV, derive_run_identity
from belay.replay.reader import read_trace
from belay.trace import KINDS

from conftest import CLIENT_LINES, FIXTURE, proxy_cmd, run_over_pipes


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def _capture(tmp_path: Path, name: str, run_id: str | None = None) -> Path:
    """Run the scripted client through the proxy; return the trace file's path.

    `run_id` None leaves `BELAY_RUN_ID` unset — absent-never-zero; any other
    value is set verbatim on the child env.
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


def _run_rejected(run_id: str, trace_dir: Path) -> tuple[int, str]:
    """Run the proxy with an unusable id; return (returncode, stderr text)."""
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    env[RUN_ID_ENV] = run_id
    proc = subprocess.Popen(
        proxy_cmd(FIXTURE),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    _stdout, stderr = proc.communicate(b"\n".join(CLIENT_LINES) + b"\n", timeout=5)
    return proc.returncode, stderr.decode(errors="replace")


def test_capture_with_run_id_records_and_derives_it(tmp_path) -> None:
    """Env set -> exactly one `run_identity` record, proxy-observed, derived back.

    The record is written once, at proxy start: it must precede every frame, so
    a future move that records it elsewhere (or twice) fails here.
    """
    path = _capture(tmp_path, "t", run_id="pytest-7432")

    identity = [r for r in _records(path) if r["kind"] == "run_identity"]
    assert len(identity) == 1
    assert identity[0]["run_id"] == "pytest-7432"
    assert identity[0]["observation_point"] == "proxy"
    first_frame = min(r["seq"] for r in _records(path) if r["kind"] == "frame")
    assert identity[0]["seq"] < first_frame

    assert derive_run_identity(read_trace(path).records) == "pytest-7432"


def test_capture_without_run_id_has_no_record(tmp_path) -> None:
    """No env -> derives None, and no `run_identity` kind exists in the trace."""
    path = _capture(tmp_path, "t")

    records = _records(path)
    assert derive_run_identity(records) is None
    assert all(r["kind"] != "run_identity" for r in records)


def test_reader_keeps_run_identity_as_understood_record(tmp_path) -> None:
    """The reader returns the record in `records`, never in `skips`.

    `run_identity` is a first-class kind in `KINDS` (no schema bump), so the
    reader must treat it as understood — a skip here would silently discard
    live data the gate aspects key on.
    """
    assert "run_identity" in KINDS
    path = _capture(tmp_path, "t", run_id="pytest-7432")

    result = read_trace(path)

    identity = [r for r in result.records if r["kind"] == "run_identity"]
    assert len(identity) == 1
    assert identity[0]["run_id"] == "pytest-7432"
    assert all(s.kind != "run_identity" for s in result.skips)


def test_derive_ignores_other_records(tmp_path) -> None:
    """Records without the kind derive None; a malformed `run_id` derives None too."""
    records = _records(_capture(tmp_path, "t"))
    assert derive_run_identity(records) is None

    records.append({"kind": "run_identity", "run_id": 42})
    assert derive_run_identity(records) is None


@pytest.mark.parametrize(
    "run_id",
    [
        "",  # empty: set-but-empty is still unusable, never an anonymous capture
        "   ",
        "a b",
        "a\tb",
        "..",
        "a/../b",
        "/x",
        "x/",
        "x\u0001y",
    ],
)
def test_unusable_run_ids_are_rejected_at_capture(tmp_path, run_id) -> None:
    """An unusable id -> proxy exits 2, stderr names the env var, no trace written."""
    trace_dir = tmp_path / "t"

    code, stderr = _run_rejected(run_id, trace_dir)

    assert code == 2
    assert RUN_ID_ENV in stderr
    assert not list(trace_dir.rglob("*.jsonl"))


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        "   ",
        "a b",
        "a\tb",
        "..",
        "a/../b",
        "/x",
        "x/",
        "x\u0000y",
        "x\x7fy",
    ],
)
def test_validate_run_id_rejects_every_unusable_shape(run_id) -> None:
    """The validation contract, at the unit level.

    `\x00` cannot travel through a process env (`execve` refuses a NUL), so the
    control-char rule is pinned here too — the capture-level rejection above can
    only carry a control char the OS will actually deliver.
    """
    from belay.identity import validate_run_id

    with pytest.raises(ValueError):
        validate_run_id(run_id)


@pytest.mark.parametrize("run_id", ["pytest-7432", "task/agent-vN", "a/b/c"])
def test_validate_run_id_accepts_the_documented_shapes(run_id) -> None:
    from belay.identity import validate_run_id

    assert validate_run_id(run_id) is None


@pytest.mark.parametrize(
    "run_id",
    [
        "pytest-7432",
        "task/agent-vN",
        "a/b/c",
    ],
)
def test_valid_run_ids_recorded_verbatim(tmp_path, run_id) -> None:
    """A valid id — slashes included — is recorded and derived back exactly."""
    path = _capture(tmp_path, "t", run_id=run_id)

    identity = [r for r in _records(path) if r["kind"] == "run_identity"]
    assert len(identity) == 1
    assert identity[0]["run_id"] == run_id
    assert derive_run_identity(read_trace(path).records) == run_id