"""`belay interop correlate <otlp> <trace>` — the C9 user-facing surface.

This is the first general machine-readable verdict surface in the CLI: it wires
Task 1's `parse_otlp`, Task 2/3's `correlate_and_attach`, and `src/belay/interop/report.py`
into an argparse subcommand, mirroring the `verify`/`phase0` patterns already in
`cli.py` (lazy-imported `belay.interop.*`, `--manifest-dir`, `--server -- CMD...`
REMAINDER, `_emit`, `_worst` for the exit code).

Three honesty properties are pinned here, not just wiring:
- **AC6**: the human report always shows `matched/total` WITH the denominator, and
  buckets every uncorrelated span by its own named cause — never folded into the
  matched count.
- **AC7**: `--json` round-trips through `json.loads` with the same facts: span_id,
  turn_index, status, cause, and the rate summary.
- **Honest without `--server`**: correlation still runs and the rate is still
  reported, but nothing is replayed — every matched span reports `UNVERIFIED`, never
  a guessed PASS. This is the CLI's own fallback (the `verify=` seam in `attach.py`
  is not (ab)used for this — `attach.py` collapses every non-None `TurnVerdict.cause`
  into `unrestorable-pre-state`, which would be a wrong label for "no --server was
  even given"), so this module builds the correlation directly off Task 2's
  `build_turn_index`/`match_span` for that path only.

Only the exactly-one-matched-turn end-to-end case needs a real replay (Seatbelt);
every other case (no-match, ambiguous, the `--json` shape, the directory guard, the
no-`--server` fallback) is exercised with zero replay and runs on any platform.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING_SERVER = [sys.executable, str(FIXTURES / "conforming_server.py")]

# The exact ids TRACE_CONTEXT_META's traceparent carries — Task 1/2/3's own
# canonical fixture ids ("00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01").
MATCHED_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
MATCHED_SPAN_ID = "00f067aa0ba902b7"

# A second, distinct traceparent, used TWICE in the trace to build an ambiguous case
# without colliding with the matched id pair above.
AMBIGUOUS_TRACE_ID = "1" * 32
AMBIGUOUS_SPAN_ID = "2" * 16

UNMATCHED_TRACE_ID = "f" * 32
UNMATCHED_SPAN_ID = "f" * 16


# --- trace-building helpers (mirror test_interop_attach.py / test_verify_cli.py) ------


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
    turn is needed in the trace itself — "unmatched" is a property of the SPAN, not
    the trace (a span naming ids the trace never recorded)."""
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


# --- OTLP/JSON document helpers --------------------------------------------------------


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


# --- `--help`: fast, states the honest no-`--server` behavior --------------------------


def test_help_states_the_no_server_unverified_behavior():
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "interop", "correlate", "--help"],
        capture_output=True,
        timeout=30,
    )
    out = completed.stdout.decode(errors="replace").lower()

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert "--server" in out
    assert "--json" in out
    assert "--manifest-dir" in out
    assert "unverified" in out
    assert "not" in out and "replay" in out, "must state that without --server nothing is replayed"


# --- scope guard: a directory positional errors clearly, never silently no-ops --------


def test_directory_trace_argument_errors_clearly(tmp_path, capsys):
    otlp_path = _write_otlp(tmp_path, [])
    trace_dir = tmp_path / "not-a-file"
    trace_dir.mkdir()

    rc = cli.main(["interop", "correlate", str(otlp_path), str(trace_dir)])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "directory" in out.lower(), out
    assert "not yet supported" in out.lower() or "single" in out.lower(), out


def test_missing_trace_file_is_fail_closed(tmp_path, capsys):
    otlp_path = _write_otlp(tmp_path, [])
    missing_trace = tmp_path / "no-such-trace.jsonl"

    rc = cli.main(["interop", "correlate", str(otlp_path), str(missing_trace)])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out


def test_missing_otlp_file_is_fail_closed(tmp_path, capsys):
    trace_path = _mixed_trace(tmp_path)
    missing_otlp = tmp_path / "no-such-spans.json"

    rc = cli.main(["interop", "correlate", str(missing_otlp), str(trace_path)])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out


def test_malformed_otlp_file_is_fail_closed(tmp_path, capsys):
    trace_path = _mixed_trace(tmp_path)
    bad_otlp = tmp_path / "bad-spans.json"
    bad_otlp.write_text("{ not valid json", encoding="utf-8")

    rc = cli.main(["interop", "correlate", str(bad_otlp), str(trace_path)])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out


# --- AC6: the human report — matched/total WITH denominator + uncorrelated by cause ---


def test_ac6_human_report_prints_matched_total_and_uncorrelated_by_cause(tmp_path, capsys):
    """No `--server`: correlation still runs (1 matched, 1 unmatched, 1 ambiguous of 3),
    and every matched span is UNVERIFIED (not replayed) — never a guessed PASS.
    """
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    rc = cli.main(["interop", "correlate", str(otlp_path), str(trace_path)])
    out = capsys.readouterr().out

    # denominator always shown, never a bare percentage
    assert "correlation rate = 1/3" in out, out
    assert "no-matching-mcp-turn" in out, out
    assert "ambiguous-correlation" in out, out
    # the matched span is UNVERIFIED (no --server), stated distinctly, never as PASS.
    # The per-span status column is fixed-width ("<12"); a literal "PASS" there
    # (as opposed to the word appearing inside an explanatory sentence) would be the
    # exact false-PASS this assertion exists to catch.
    assert "UNVERIFIED" in out, out
    assert "PASS        " not in out, out
    # an all-UNVERIFIED correlation exits non-zero
    assert rc == 1, out


def test_ac6_uncorrelated_counts_are_never_folded_into_matched(tmp_path, capsys):
    """The uncorrelated bucket's counts must be independently visible, not just implied
    by `total - matched` — assert the exact per-cause counts, not just their names.
    """
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    cli.main(["interop", "correlate", str(otlp_path), str(trace_path)])
    out = capsys.readouterr().out

    assert "no-matching-mcp-turn" in out and "1" in out.split("no-matching-mcp-turn")[1].splitlines()[0]
    assert "ambiguous-correlation" in out and "1" in out.split("ambiguous-correlation")[1].splitlines()[0]


# --- AC7: `--json` round-trips with span_id, turn_index, status, cause + the rate -----


def test_ac7_json_output_round_trips_with_correlation_and_spans(tmp_path, capsys):
    trace_path = _mixed_trace(tmp_path)
    otlp_path = _three_span_doc(tmp_path)

    rc = cli.main(["interop", "correlate", str(otlp_path), str(trace_path), "--json"])
    out = capsys.readouterr().out

    payload = json.loads(out)  # must not raise

    assert payload["trace"] == str(trace_path)
    assert payload["correlation"]["matched"] == 1
    assert payload["correlation"]["total"] == 3
    assert payload["correlation"]["uncorrelated"]["no-matching-mcp-turn"] == 1
    assert payload["correlation"]["uncorrelated"]["ambiguous-correlation"] == 1

    spans = payload["spans"]
    assert len(spans) == 3
    by_id = {s["span_id"]: s for s in spans}

    matched = by_id[MATCHED_SPAN_ID]
    assert matched["turn_index"] == 0
    assert matched["status"] == "UNVERIFIED"  # not replayed: no --server

    unmatched = by_id[UNMATCHED_SPAN_ID]
    assert unmatched["turn_index"] is None
    assert unmatched["status"] == "UNVERIFIED"
    assert unmatched["cause"] == "no-matching-mcp-turn"

    ambiguous = by_id[AMBIGUOUS_SPAN_ID]
    assert ambiguous["turn_index"] is None
    assert ambiguous["status"] == "UNVERIFIED"
    assert ambiguous["cause"] == "ambiguous-correlation"

    # No status anywhere is a fabricated PASS for an uncorrelated span.
    assert unmatched["status"] != "PASS"
    assert ambiguous["status"] != "PASS"

    assert rc == 1, out  # every attached status is UNVERIFIED


# --- end-to-end: a real replay attaches a real, byte-honest PASS verdict --------------

_REQUIRES_SEATBELT = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
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
def test_ac5_end_to_end_matched_turn_replays_and_attaches_a_real_pass(tmp_path, capsys):
    """A single matched span, over a REAL trace + REAL snapshot + REAL conforming
    server (Task 3's own AC5 fixture): `--server` given, the turn actually replays,
    and the report shows a real PASS — the exactly-one-real-replay case this task's
    brief calls for.
    """
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

    rc = cli.main(
        [
            "interop", "correlate", str(otlp_path), str(trace_path),
            "--manifest-dir", str(manifest_dir),
            "--server", *CONFORMING_SERVER,
        ]
    )
    out = capsys.readouterr().out

    assert "correlation rate = 1/1" in out, out
    assert "PASS" in out, out
    assert rc == 0, out

    # --json must come BEFORE --server: --server is argparse.REMAINDER, so anything
    # after it (including a later --json) is swallowed into the server command, same
    # as every other --server-taking subcommand in this CLI.
    rc_json = cli.main(
        [
            "interop", "correlate", str(otlp_path), str(trace_path),
            "--manifest-dir", str(manifest_dir),
            "--json",
            "--server", *CONFORMING_SERVER,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["correlation"] == {"matched": 1, "total": 1, "uncorrelated": {}}
    assert payload["spans"][0]["status"] == "PASS"
    assert payload["spans"][0]["cause"] is None
