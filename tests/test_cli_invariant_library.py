"""`--invariant-library <name>` on verify / corpus add / phase0 run — aspect 2 CLI.

The library is the R3 mitigation seam: a stranger applies a named, pre-authored policy
with zero JSON authoring. This file pins the flag semantics on all three `--invariants`
surfaces:

- the flag reaches `verify_turn`: `--invariant-library tests-read-only` FAILs the
  weakening-editor turn at the exact turn (the write under the byte-prefix `tests/`
  fires the `read-only` scope), with and without the defaults;
- a repeated flag appends (both entries apply — the read-only FAIL and the no-create
  PASS both render);
- an UNKNOWN name is exit 2 with a `belay:` message, before any trace is read or any
  replay runs — on all three surfaces, mirroring the malformed-`--invariants`-file
  fail-closed pins;
- `phase0 run` records a library-declared detector in the ledger EXACTLY as
  `--invariants` does (PRD gap 3): the resolved invariants flow into
  `DetectorIdentity.rules`, so a library-declared run is never misrecorded as a
  different detector;
- discovery: `belay invariant-library list` renders all five entries with grounding and
  scope semantics, and `--help` mentions the flag truthfully.

The four replay tests are darwin-gated (real replay re-invokes inside the Seatbelt
sandbox); the fail-closed and ledger tests are cross-platform — they exit or use the
phase0 fake-verifier seam before any replay could run.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION

from belay import cli
from belay.phase0.ledger import from_json
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import default_invariants, resolve_library_entry
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]

_NEEDS_SEATBELT = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)

STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"


# --- the trace rig (mirrors tests/test_verify_cli_invariants.py) -----------------------


def _snapshot(tmp_path: Path, body: str, manifest_dir: Path):
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(body, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _tools_list() -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "edit_file", "annotations": {"readOnlyHint": False}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _reply() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": "edited tests/test_auth.py"}],
                "isError": False,
            },
        }
    ).encode()


def _trace(tmp_path: Path, frames: list[tuple]) -> Path:
    trace_dir = tmp_path / "trace"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return sorted(trace_dir.glob("*.jsonl"))[0]


def _demo_trace(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    handle = _snapshot(tmp_path, STRONG_TEST, manifest_dir)
    trace_path = _trace(
        tmp_path,
        _tools_list() + [("c2s", _call(), handle), ("s2c", _reply(), None)],
    )
    return trace_path, manifest_dir


# --- (1) the flag reaches verify_turn: FAIL at the exact turn, defaults on/off ---------


@_NEEDS_SEATBELT
def test_verify_invariant_library_fails_the_weakening_turn(tmp_path, capsys):
    """`belay verify --invariant-library tests-read-only` FAILs the corrupt success.

    The flag resolves the library entry into the same A1 policy stream `--invariants`
    uses, so the write under the byte-prefix `tests/` fires the `read-only` invariant at
    the exact turn and the exit is non-zero.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--invariant-library", "tests-read-only", "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "A1 invariant" in out, out
    assert "read-only" in out, out
    assert "tests/test_auth.py" in out, out


@_NEEDS_SEATBELT
def test_no_default_invariants_with_library_still_applies(tmp_path, capsys):
    """`--no-default-invariants --invariant-library tests-read-only` still FAILs.

    The library composes on top of NO defaults: the FAIL can only come from the resolved
    entry, proving the flag alone carries the policy.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--invariant-library", "tests-read-only",
         "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "A1 invariant" in out, out
    assert "read-only" in out, out


@_NEEDS_SEATBELT
def test_verify_repeated_invariant_library_flags_append(tmp_path, capsys):
    """A repeated flag APPENDS: both entries are in force on the same turn.

    The weakening turn FAILs on the `tests-read-only` invariant and PASSes the
    `no-create` one (the editor modifies, it does not create); both sub-verdicts render,
    so the output proves both flags reached the turn.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--invariant-library", "tests-read-only",
         "--invariant-library", "no-create",
         "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "read-only invariant" in out, out
    assert "no-create invariant" in out, out


# --- (2) unknown name is exit 2 on all three surfaces, before any trace is read --------


def test_verify_unknown_invariant_library_name_is_fail_closed(tmp_path, capsys, monkeypatch):
    """`--invariant-library bogus` is exit 2 with a `belay:` message naming the name.

    Resolution happens BEFORE the trace is read and before any replay: the verifier is
    pinned unreachable, mirroring `test_malformed_invariants_file_is_fail_closed`'s
    fail-closed contract for the file path — a typo must never verify against nothing.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)

    def unreachable_verifier(*args, **kwargs):
        raise AssertionError("verify_turn must never be reached with an unknown library name")

    import belay.verify.turn as verify_turn_module
    monkeypatch.setattr(verify_turn_module, "verify_turn", unreachable_verifier)

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--invariant-library", "bogus", "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert "bogus" in out, out


def test_corpus_add_unknown_invariant_library_name_is_fail_closed(tmp_path, capsys, monkeypatch):
    """`corpus add --invariant-library bogus` is exit 2, before any replay."""
    trace_path, manifest_dir = _demo_trace(tmp_path)

    def unreachable_verifier(*args, **kwargs):
        raise AssertionError("verify_turn must never be reached with an unknown library name")

    import belay.verify.turn as verify_turn_module
    monkeypatch.setattr(verify_turn_module, "verify_turn", unreachable_verifier)

    rc = cli.main(
        ["corpus", "add", str(trace_path), "--turn", "0",
         "--manifest-dir", str(manifest_dir),
         "--invariant-library", "bogus", "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert "bogus" in out, out


def test_phase0_run_unknown_invariant_library_name_is_fail_closed(
    tmp_path, capsys, monkeypatch
) -> None:
    """`phase0 run --invariant-library bogus` is exit 2 and `run_batch` is never reached.

    Mirrors `test_phase0_cli.py::test_phase0_run_malformed_invariants_file_is_fail_closed`:
    the verifier seam is pinned unreachable and the ledger is never written.
    """
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    ledger_path = tmp_path / "ledger.json"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        call = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "t", "arguments": {}}}
        ).encode()
        reply = json.dumps(
            {"jsonrpc": "2.0", "id": 1,
             "result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}
        ).encode()
        writer.observer("c2s")(call, False)
        writer.observer("s2c")(reply, False)
    finally:
        writer.close()

    def unreachable_verifier(*args, **kwargs):
        raise AssertionError("run_batch must never be reached with an unknown library name")

    import belay.phase0.runner as phase0_runner
    monkeypatch.setattr(phase0_runner, "verify_turn", unreachable_verifier)
    monkeypatch.setattr(phase0_runner, "add_case", unreachable_verifier)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--ledger", str(ledger_path),
            "--invariant-library", "bogus",
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert "bogus" in out, out
    assert not ledger_path.exists()


# --- (3) the ledger records library-declared detectors exactly as --invariants does -----


def _write_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """Write one `trace-*.jsonl` of `n_calls` `tools/call` turns, via the real writer."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            call = json.dumps(
                {"jsonrpc": "2.0", "id": call_id, "method": "tools/call",
                 "params": {"name": tool, "arguments": {}}}
            ).encode()
            reply = json.dumps(
                {"jsonrpc": "2.0", "id": call_id,
                 "result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}
            ).encode()
            writer.observer("c2s")(call, False)
            writer.observer("s2c")(reply, False)
    finally:
        writer.close()
    return writer.path


def _verdict(n: int, status: Status) -> TurnVerdict:
    return TurnVerdict(
        turn_index=n,
        tool_name="t",
        status=status,
        sub_verdicts=[Verdict("A2", "replay", status, None, None, "canned")],
        cause=None,
    )


def _patch_seam(monkeypatch, canned) -> None:
    """Point `belay.phase0.runner`'s verifier/ingester seam at fakes, no Seatbelt involved."""
    import belay.phase0.runner as phase0_runner

    def stem_verifier(records, n, *, server_command, manifest_dir, invariants, replays, timeout):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    monkeypatch.setattr(phase0_runner, "verify_turn", stem_verifier)
    monkeypatch.setattr(
        phase0_runner, "add_case",
        lambda corpus_dir, **kwargs: Path(corpus_dir) / "unused-case",
    )


def test_phase0_run_records_library_invariant_on_top_of_defaults(
    tmp_path, capsys, monkeypatch
) -> None:
    """`phase0 run --invariant-library no-create` records the entry IN the detector.

    The ledger's `DetectorIdentity.rules` is built from the resolved invariants list —
    the very list passed to `run_batch` — so a library-declared run is recorded as the
    library-declared detector, never as the defaults alone (PRD gap 3).
    """
    trace_dir = tmp_path / "traces"
    ledger_path = tmp_path / "ledger.json"
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    _patch_seam(monkeypatch, {clean_path.stem: [_verdict(0, Status.PASS)]})

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(tmp_path / "corpus"),
            "--ledger", str(ledger_path),
            "--invariant-library", "no-create",
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out

    ledger = from_json(json.loads(ledger_path.read_text(encoding="utf-8")))
    expected = tuple(
        (os.fsdecode(inv.scope), inv.rule) for inv in default_invariants()
    ) + tuple((os.fsdecode(inv.scope), inv.rule) for inv in resolve_library_entry("no-create"))
    assert ledger.detector is not None
    assert ledger.detector.rules == expected
    assert "no-create" in out, out


def test_phase0_run_no_defaults_with_library_records_only_the_library(
    tmp_path, capsys, monkeypatch
) -> None:
    """`--no-default-invariants --invariant-library no-create` records the entry alone.

    Mirrors the "empty detector" pin: the record holds exactly what was in force — the
    library entry, and nothing else — so the run can be dated by its true detector.
    """
    trace_dir = tmp_path / "traces"
    ledger_path = tmp_path / "ledger.json"
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    _patch_seam(monkeypatch, {clean_path.stem: [_verdict(0, Status.PASS)]})

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(tmp_path / "corpus"),
            "--ledger", str(ledger_path),
            "--no-default-invariants",
            "--invariant-library", "no-create",
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out

    ledger = from_json(json.loads(ledger_path.read_text(encoding="utf-8")))
    expected = tuple(
        (os.fsdecode(inv.scope), inv.rule) for inv in resolve_library_entry("no-create")
    )
    assert ledger.detector is not None
    assert ledger.detector.rules == expected
    assert "detector: unrecorded" not in out, out


# --- (4) discovery: `belay invariant-library list` + truthful help ---------------------


def test_invariant_library_list_renders_all_five_entries(capsys) -> None:
    """`belay invariant-library list` prints every entry: rules, scope semantics, grounding.

    The scope-semantics column must not overclaim: every library entry uses the raw
    byte-PREFIX semantics (the segment semantics belong to `no-assertion-weakening`),
    and the egress row carries the honesty note — unobservable, no egress instrument.
    """
    rc = cli.main(["invariant-library", "list"])
    out = capsys.readouterr().out

    assert rc == 0, out
    for name in (
        "no-create", "no-delete", "tests-read-only", "source-read-only", "network-egress",
    ):
        assert name in out, out
    assert "read-only" in out, out
    assert "byte-prefix" in out, out
    assert "segment" not in out, "the list must not claim segment semantics for delta rules"
    assert "delta" in out, out
    assert "ungrounded" in out, out
    assert "unobservable" in out, out
    assert "no egress instrument" in out, out


def test_verify_help_mentions_invariant_library(capsys) -> None:
    """`belay verify --help` carries `--invariant-library` with a truthful description.

    The help text is hard-wrapped, so a phrase can straddle a line break ("invariant-"
    then "library"); the assertions are wrap-insensitive.
    """
    with pytest.raises(SystemExit):
        cli.main(["verify", "--help"])
    out = capsys.readouterr().out
    flat = re.sub(r"-\s+", "-", re.sub(r"\s+", " ", out))
    flat_lower = flat.lower()

    assert "--invariant-library" in out, out
    assert "belay invariant-library list" in flat, out
    assert "an unknown name is a fail-closed error" in flat_lower, out