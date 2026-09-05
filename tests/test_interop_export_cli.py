"""`belay interop export <otlp> <trace>` — the C9 export surface (aspect A2, export-cli).

The export-engine aspect (`export.py`) proved the pure function; this module pins the
CLI surface that runs the pipeline and writes the OTLP/JSON document to `--out` or
stdout, with fail-closed errors and settled exit semantics. It mirrors the correlate
surface's wiring (`tests/test_interop_cli.py`): same lazy-imported `belay.interop.*`,
same `--manifest-dir`/`--server -- CMD...` REMAINDER conventions, `cli.main` + `capsys`
for the rest, subprocess for `--help`, and the Seatbelt-gated real-replay case.

The exit semantics deliberately DIVERGE from correlate: rc 0 on a successful export
REGARDLESS of verdict contents (an all-UNVERIFIED export is still a successful export —
the export is not a gate); rc 2 on the operational fail-closed preflight errors
(mirroring correlate); rc 1 on a write failure (`--out` into an unwritable path). The
divergence is pinned by `test_ac3_success_exit_ignores_verdict_contents`.

Streams are settled and pinned: stdout carries exactly one artifact — the OTLP/JSON
document (to `--out`, or to stdout when `--out` is absent). The summary (human or
`--json`) ALWAYS goes to stderr, and the fail-closed error messages go to stderr too —
so `belay interop export ... > verified.otlp` is always safe and stdout is never
polluted with summary text (AC2/AC4).

Honesty contract pinned here: `--help` states that spans that cannot be replayed export
as UNVERIFIED, never PASS (AC5); the no-`--server` path exports every matched span as
UNVERIFIED (`not-replayed-no-server`) with rc still 0 (AC1/AC3); and a real replay
attaches a real `PASS` verdict whose coverage line is exported per the verdict —
absent here because the fixture's `echo` tool declares no `openWorldHint`, so there is
no `NOT_COVERED` dimension (absent-never-zero, never a bare PASS).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.interop.export import VERDICT_ATTRIBUTE_PREFIX
from belay.interop.otlp import parse_otlp
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING_SERVER = [sys.executable, str(FIXTURES / "conforming_server.py")]

# The exact ids TRACE_CONTEXT_META's traceparent carries — the canonical fixture ids
# shared by test_interop_cli.py / test_interop_export.py.
MATCHED_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
MATCHED_SPAN_ID = "00f067aa0ba902b7"

# A second, distinct traceparent, used TWICE in the trace to build an ambiguous case.
AMBIGUOUS_TRACE_ID = "1" * 32
AMBIGUOUS_SPAN_ID = "2" * 16

UNMATCHED_TRACE_ID = "f" * 32
UNMATCHED_SPAN_ID = "f" * 16


# --- trace-building helpers (mirror test_interop_cli.py) ----------------------------


def _call_with_traceparent(msg_id: int, trace_id: str, span_id: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"s": "hi"},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "traceparent": f"00-{trace_id}-{span_id}-01",
                },
            },
        }
    ).encode()


def _reply(msg_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": "hi"}], "isError": False},
        }
    ).encode()


def _write_trace(tmp_path: Path, frames: list[tuple]) -> Path:
    """`frames` is `(direction, raw_bytes, state_handle_or_None)`; writes via the real writer."""
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


def _mixed_trace(tmp_path: Path) -> Path:
    """One matched turn, two turns sharing ONE traceparent (ambiguous). No unmatched
    turn is needed in the trace itself — "unmatched" is a property of the SPAN."""
    return _write_trace(
        tmp_path,
        [
            ("c2s", _call_with_traceparent(1, MATCHED_TRACE_ID, MATCHED_SPAN_ID), None),
            ("s2c", _reply(1), None),
            ("c2s", _call_with_traceparent(3, AMBIGUOUS_TRACE_ID, AMBIGUOUS_SPAN_ID), None),
            ("s2c", _reply(3), None),
            ("c2s", _call_with_traceparent(5, AMBIGUOUS_TRACE_ID, AMBIGUOUS_SPAN_ID), None),
            ("s2c", _reply(5), None),
        ],
    )


# --- OTLP/JSON document helpers ------------------------------------------------------


def _otlp_span(trace_id: str, span_id: str, name: str = "mcp.tools/call") -> dict:
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": "1700000000000000000",
    }


def _write_otlp(tmp_path: Path, spans: list[dict]) -> Path:
    doc = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
    path = tmp_path / "spans.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _three_span_doc(tmp_path: Path) -> Path:
    return _write_otlp(
        tmp_path,
        [
            _otlp_span(MATCHED_TRACE_ID, MATCHED_SPAN_ID),
            _otlp_span(AMBIGUOUS_TRACE_ID, AMBIGUOUS_SPAN_ID),
            _otlp_span(UNMATCHED_TRACE_ID, UNMATCHED_SPAN_ID),
        ],
    )


# --- AC1: `--out` writes a parseable document; no `--server` -> every span UNVERIFIED --


def test_ac1_export_writes_a_parseable_document(tmp_path, capsys):
    """End-to-end via the stub-free no-`--server` path: correlation still runs (1
    matched, 1 ambiguous, 1 unmatched), `_correlate_without_server` marks every span
    UNVERIFIED, and the file `--out` names parses with `parse_otlp` and every span
    carries `belay.verdict.status`."""
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)
    out_path = tmp_path / "verified.otlp"

    rc = cli.main(["interop", "export", str(otlp_path), str(trace_path), "--out", str(out_path)])
    err = capsys.readouterr().err

    assert rc == 0, err
    assert out_path.exists(), out_path

    spans = parse_otlp(out_path.read_text(encoding="utf-8"))  # must not raise
    assert len(spans) == 3
    for span in spans:
        status = span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"]
        assert status == "UNVERIFIED", status
        assert status != "PASS"

    # The matched span names its honest cause: no --server was even given, so no turn
    # was replayed — never a guessed PASS.
    by_id = {s.span_id: s for s in spans}
    assert by_id[MATCHED_SPAN_ID].attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.cause"] == (
        "not-replayed-no-server"
    )


# --- AC2: without `--out`, stdout is the document ONLY; the summary is on stderr -----


def test_ac2_stdout_is_the_document_only(tmp_path, capsys):
    """No `--out`: the WHOLE of stdout parses as the OTLP document, and no summary
    text appears on stdout — the summary (correlation rate, the no-server honesty
    line) is on stderr, so `> verified.otlp` is always safe."""
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    rc = cli.main(["interop", "export", str(otlp_path), str(trace_path)])
    captured = capsys.readouterr()
    out, err = captured.out, captured.err

    assert rc == 0, err
    doc = json.loads(out)  # the entire stdout is one JSON document
    assert "resourceSpans" in doc

    assert "correlation rate" in err
    assert "no --server given" in err

    assert "correlation rate" not in out
    assert "no --server given" not in out


# --- AC3: fail-closed exit codes; the export is not a gate ----------------------------


@pytest.mark.parametrize(
    ("argv", "expected_rc", "needle"),
    [
        pytest.param(
            "missing-otlp", 2, "OTLP spans file not found",
            id="missing-otlp-file",
        ),
        pytest.param(
            "missing-trace", 2, "trace not found",
            id="missing-trace-file",
        ),
        pytest.param(
            "malformed-otlp", 2, "malformed OTLP/JSON",
            id="malformed-otlp",
        ),
        pytest.param(
            "directory-trace", 2, "directory",
            id="directory-trace-argument",
        ),
        pytest.param(
            "unwritable-out", 1, "cannot write",
            id="unwritable-out-path",
        ),
    ],
)
def test_ac3_fail_closed_exit_codes(tmp_path, capsys, argv: str, expected_rc: int, needle: str):
    """Each operational failure is fail-closed: a clean, named message and a distinct
    exit code — 2 for the preflight errors (mirroring correlate), 1 for the write
    failure — never an empty success, never a traceback."""
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    if argv == "missing-otlp":
        args = [str(tmp_path / "no-such-spans.json"), str(trace_path)]
    elif argv == "missing-trace":
        args = [str(otlp_path), str(tmp_path / "no-such-trace.jsonl")]
    elif argv == "malformed-otlp":
        bad = tmp_path / "bad-spans.json"
        bad.write_text("{ not valid json", encoding="utf-8")
        args = [str(bad), str(trace_path)]
    elif argv == "directory-trace":
        trace_dir = tmp_path / "not-a-file"
        trace_dir.mkdir()
        args = [str(otlp_path), str(trace_dir)]
    else:  # unwritable-out
        args = [str(otlp_path), str(trace_path), "--out", str(tmp_path / "no-such-dir" / "out.otlp")]

    rc = cli.main(["interop", "export", *args])
    err = capsys.readouterr().err
    out = capsys.readouterr().out

    assert rc == expected_rc, f"argv={argv} rc={rc} err={err!r}"
    assert needle in err, f"argv={argv} err={err!r}"
    # stdout stays clean on every failure: it is the document channel and carries
    # nothing here.
    assert out == "", f"argv={argv} stdout={out!r}"


def test_ac3_success_exit_ignores_verdict_contents(tmp_path, capsys):
    """An all-UNVERIFIED export (no `--server`) exits 0 — the export is not a gate,
    verdict contents never decide the exit code. The deliberate divergence from
    correlate (which exits 1 on the same all-UNVERIFIED correlation) is pinned here,
    on identical inputs, so nobody "fixes" the export to match."""
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    rc_export = cli.main(["interop", "export", str(otlp_path), str(trace_path)])
    assert rc_export == 0, capsys.readouterr().err

    rc_correlate = cli.main(["interop", "correlate", str(otlp_path), str(trace_path)])
    assert rc_correlate == 1, "the export and correlate exit codes must not drift together"


# --- AC4: `--json` summary on stderr — export path + correlation shape ----------------


def test_ac4_json_summary_on_stderr(tmp_path, capsys):
    """`--json` with `--out`: stderr carries ONE machine summary that round-trips with
    `json.loads` — `{"export": <path>, "correlation": {matched/total/uncorrelated}}` —
    and stdout is empty (the document went to `--out`)."""
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)
    out_path = tmp_path / "verified.otlp"

    rc = cli.main(
        ["interop", "export", str(otlp_path), str(trace_path), "--out", str(out_path), "--json"]
    )
    captured = capsys.readouterr()
    err, out = captured.err, captured.out

    assert rc == 0, err
    assert out == "", out

    payload = json.loads(err)  # must not raise
    assert payload["export"] == str(out_path)
    assert payload["correlation"]["matched"] == 1
    assert payload["correlation"]["total"] == 3
    assert payload["correlation"]["uncorrelated"]["no-matching-mcp-turn"] == 1
    assert payload["correlation"]["uncorrelated"]["ambiguous-correlation"] == 1


def test_ac4_json_summary_reports_dash_export_path_for_stdout(tmp_path, capsys):
    """`--json` WITHOUT `--out`: the machine summary on stderr reports the export path
    as `-` (the document is on stdout, not in a file), and stdout is still the document
    — the two streams never collide."""
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    rc = cli.main(["interop", "export", str(otlp_path), str(trace_path), "--json"])
    captured = capsys.readouterr()
    err, out = captured.err, captured.out

    assert rc == 0, err
    payload = json.loads(err)
    assert payload["export"] == "-"
    doc = json.loads(out)
    assert "resourceSpans" in doc


# --- AC5: `--help` carries the honesty line — UNVERIFIED, never PASS -----------------


def test_ac5_help_states_unverified_never_pass():
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "interop", "export", "--help"],
        capture_output=True,
        timeout=30,
    )
    out = completed.stdout.decode(errors="replace").lower()

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert "--out" in out
    assert "--server" in out
    assert "--manifest-dir" in out
    assert "--replays" in out
    assert "--timeout" in out
    assert "--json" in out
    assert "unverified" in out
    assert "never" in out and "pass" in out, (
        "help must state the honesty line: spans that cannot be replayed export as "
        "UNVERIFIED, never PASS"
    )


# --- AC6: a real replay exports a real PASS verdict + its coverage per the verdict ----

_REQUIRES_SEATBELT = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)


def _snapshot_handle(tmp_path: Path, manifest_dir: Path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("untouched\n", encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _tools_list_frames() -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "echo", "annotations": {"readOnlyHint": True}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


@_REQUIRES_SEATBELT
def test_ac6_end_to_end_matched_turn_exports_real_pass(tmp_path, capsys):
    """A single matched span, over a REAL trace + REAL snapshot + REAL conforming
    server: `--server` given, the turn actually replays, and the exported document
    carries the real replayed `PASS` verdict — never the no-server UNVERIFIED. The
    coverage line is exported PER THE VERDICT: the fixture's `echo` tool declares no
    `openWorldHint`, so the verdict carries no `NOT_COVERED` dimension and the
    `belay.verdict.coverage` key is ABSENT (absent-never-zero) — never a bare PASS
    without the boundary the verdict actually carries."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    handle = _snapshot_handle(tmp_path, manifest_dir)

    trace_path = _write_trace(
        tmp_path,
        _tools_list_frames()
        + [
            ("c2s", _call_with_traceparent(5, MATCHED_TRACE_ID, MATCHED_SPAN_ID), handle),
            ("s2c", _reply(5), None),
        ],
    )
    otlp_path = _write_otlp(tmp_path, [_otlp_span(MATCHED_TRACE_ID, MATCHED_SPAN_ID)])
    out_path = tmp_path / "verified.otlp"

    rc = cli.main(
        [
            "interop", "export", str(otlp_path), str(trace_path),
            "--out", str(out_path),
            "--manifest-dir", str(manifest_dir),
            "--server", *CONFORMING_SERVER,
        ]
    )
    err = capsys.readouterr().err

    assert rc == 0, err
    assert "correlation rate = 1/1" in err
    assert "PASS" in err

    [span] = parse_otlp(out_path.read_text(encoding="utf-8"))
    attrs = span.attributes
    assert attrs[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "PASS"
    assert attrs[f"{VERDICT_ATTRIBUTE_PREFIX}.axis"] == "A2"
    assert attrs[f"{VERDICT_ATTRIBUTE_PREFIX}.turn_index"] == 0
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.cause" not in attrs, "a clean replay has no cause"
    # coverage per the verdict: no NOT_COVERED dimension on the echo replay -> no
    # coverage key, and the real sub-verdicts are carried verbatim.
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.coverage" not in attrs
    sub_verdicts = json.loads(attrs[f"{VERDICT_ATTRIBUTE_PREFIX}.sub_verdicts"])
    assert [sv["status"] for sv in sub_verdicts] == ["PASS", "PASS"]
    assert all(sv["kind"] in {"replay", "effect"} for sv in sub_verdicts)