"""THE REFUTATION: triage on vs off leaves every verdict on the replayed turns byte-identical.

This test is the C10 answer to the question every reviewer asks of a cheap model near
the verdict: *"doesn't the triage model change what gets verified?"* The refutation is
the one-command proof that it does not — triage is a **queue-orderer, never a judge**
(PRD guardrail: *a model may triage, only execution may decide*). A triage command
configured with NO budget knobs is SHADOW mode — every turn still replays — and the
two runs of the same committed capture must render the same PASS and the same FAIL,
byte for byte, exit code and all.

What this test actually catches: triage LEAKING into the verdict — a skipped turn that
renders as a PASS, a verdict that changes because a triage command was configured, a
budget that silently shrinks in shadow mode, an off-whitelist payload leaving the box
(asserted by the author's own refusal AND by the test reading what the CLI built).

Three pins:

1. **Identity (the refutation, must never be weakened):** the committed demo capture
   verified twice through the REAL CLI — once with a stub triage author (fixed scores,
   `{"score": 0.5, "confidence": 0.9}`, no budget flags -> shadow mode) and once with
   triage absent. The `--json` documents' every shared key is BYTE-IDENTICAL (the
   on-side differs only in the additive `triage` section — absent-never-zero), the
   exit codes agree, and an anti-vacuity spy proves the on-side really consulted
   triage (one invocation per turn, observed on disk) and the off-side never did (the
   marker did not grow).
2. **Absent => no-op:** no flag and no `BELAY_TRIAGE_AUTHOR` => triage is a complete
   no-op — every turn replayed, no `triage` section, and NOTHING is spawned: the
   resolver returns None and the seam's only I/O channel (subprocess) is proven never
   to run, so no network can be attempted either. The env var is scrubbed by ABSENCE,
   never set to `""`.
3. **Whitelist at the surface (the honest-line pair):** the payload the real CLI
   constructs for the author carries EXACTLY `WHITELISTED_KEYS` and nothing else —
   no raw state, no trace bytes (structurally unrepresentable in JSON, asserted
   anyway). The author itself refuses an off-whitelist payload and the marker records
   the refusal; the test reads every payload the CLI built and asserts the key set
   directly. (The seam-level assertion lives in `tests/test_verify_triage.py:152`;
   this pins it at the CLI boundary on real data.)

The refutation runs with a STUB author — deterministic, no model, no network in CI
(acceptance 4). The demo half is a real re-execution of the ~44s `run_process` turns
and is darwin-gated like every capture test (`tests/test_refutation_no_claim_axis.py:89-95`).

**Do not weaken this module.** The tests here are the C10 capstone
(`docs/planning/jev-triage/refutation/plan_20260921.md`). If a surface change breaks
the byte-identity, the surface change is wrong — not this test.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.verify import triage
from belay.verify import turn as turn_module
from belay.verify.triage import WHITELISTED_KEYS
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status

REQUIRES_CAPTURE = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the demo capture's re-execution runs inside the "
        "macOS Seatbelt sandbox; the Linux side is measured in tests/test_docker_inimage.py"
    ),
)


def _recording_scoring_author(marker: Path, dump: Path) -> str:
    """One inline triage command — the anti-vacuity and whitelist spies in one.

    Reads the payload, appends `1` to the marker file when it carries EXACTLY the
    whitelisted keys and `0` when it does not (the author's own half of the honest-line
    pair: an off-whitelist payload is REFUSED — `{"error"}` + exit 1, fail-closed —
    and the refusal is recorded on disk, because fail-open means the refusal alone
    would change no verdict and stay silent), dumps every payload it accepted to the
    dump file (the test's half: the construction-level assertion on what the real CLI
    built), and answers a FIXED score — deterministic, no model, no network.
    """
    code = (
        "import sys, json; "
        "p = json.load(sys.stdin); "
        f"ok = set(p) == set({sorted(WHITELISTED_KEYS)!r}); "
        f"open({str(marker)!r}, 'a').write('1' if ok else '0'); "
        f"open({str(dump)!r}, 'a').write(json.dumps(p, sort_keys=True) + chr(10)) "
        "if ok else None; "
        'sys.stdout.write(json.dumps({"score": 0.5, "confidence": 0.9} '
        'if ok else {"error": "off-whitelist payload"})); '
        "sys.exit(0 if ok else 1)"
    )
    return f"{sys.executable} -c {shlex.quote(code)}"


def _demo_verify(extra_flags: list[str]) -> tuple[int, dict, str]:
    """`belay verify --json` on the committed demo capture through the REAL CLI.

    `extra_flags` are placed BEFORE `--server` (the server argument is
    `argparse.REMAINDER`). Returns (exit code, parsed document, stdout text).
    """
    from test_demo_capture import (
        SERVER,
        _capture_trace,
        _manifest_dir,
        _recorded_source_root,
    )

    argv = [
        "verify",
        str(_capture_trace()),
        "--manifest-dir",
        str(_manifest_dir()),
        "--timeout",
        "300",
        "--json",
        *extra_flags,
        "--server",
        sys.executable,
        str(SERVER),
        _recorded_source_root(),
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    text = buf.getvalue()
    return rc, json.loads(text), text


@pytest.fixture(scope="module")
def triage_demo_runs(tmp_path_factory) -> tuple[dict, dict]:
    """The SAME committed demo capture verified twice through the REAL CLI.

    Once with triage configured in SHADOW mode (the stub author above — a real
    subprocess per turn, its invocations and payloads recorded on disk) and once
    with triage absent (env scrubbed by absence). Both runs are real re-executions
    of the ~44s `run_process` turns, so this fixture is the slow half of the
    refutation (budget ~10 min for the module); it is darwin-gated at use. Each
    side carries (rc, doc, text, marker text, payload dumps); the marker is the
    anti-vacuity spy — every triage invocation appends one char.
    """
    workdir = tmp_path_factory.mktemp("triage-refutation")
    marker = workdir / "triage-invoked"
    dump = workdir / "triage-payloads.jsonl"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv(triage.TRIAGE_ENV, raising=False)
    try:
        rc_on, doc_on, text_on = _demo_verify(
            ["--triage-author", _recording_scoring_author(marker, dump)]
        )
        on_marker = marker.read_text(encoding="utf-8") if marker.exists() else ""
        on_dumps = dump.read_text(encoding="utf-8") if dump.exists() else ""

        rc_off, doc_off, text_off = _demo_verify([])
        off_marker = marker.read_text(encoding="utf-8") if marker.exists() else ""
    finally:
        monkeypatch.undo()

    return (
        {"rc": rc_on, "doc": doc_on, "text": text_on, "marker": on_marker, "dumps": on_dumps},
        {"rc": rc_off, "doc": doc_off, "text": text_off, "marker": off_marker, "dumps": ""},
    )


# --- (1) THE IDENTITY PIN: triage on vs off, byte-identical verdicts ---------------------


@REQUIRES_CAPTURE
def test_triage_on_vs_off_leaves_every_verdict_byte_identical(triage_demo_runs) -> None:
    """THE REFUTATION, verify surface: the demo capture's every PASS is identical with
    a triage command configured (shadow mode — every turn still replayed) and with
    triage absent.

    The comparison shape is exact: the on-side `--json` document differs from the
    off-side ONLY in the additive `triage` section — every shared key (`turns`,
    `aggregate`, `trajectory`, `coverage`, `exposure`, `trace`, `error`) is
    byte-identical — and the exit codes agree. Shadow mode reports mode `shadow`
    with zero skipped and one recorded score per replayed turn.

    Anti-vacuity, observed on disk, never inferred: the on-side consulted triage
    exactly once per turn (the stub command ran — one marker char per invocation)
    and the off-side never did (the marker did not grow between the two runs).
    This is not two identical runs that both skipped triage.
    """
    on, off = triage_demo_runs

    assert on["rc"] == off["rc"] == 0, (on["rc"], off["rc"])
    assert all(turn["status"] == "PASS" for turn in on["doc"]["turns"]), on["doc"]["turns"]
    assert on["doc"]["trajectory"]["status"] == "PASS", on["doc"]["trajectory"]

    # Every shared key byte-identical: the on-side differs ONLY by the additive
    # `triage` section (absent-never-zero), never by a verdict.
    shared_on = {key: value for key, value in on["doc"].items() if key != "triage"}
    assert shared_on == off["doc"], (
        "triage must leave every PASS and every FAIL identical — a surface that lets "
        "the triage configuration leak into the verdict breaks this test"
    )
    assert on["doc"]["turns"] == off["doc"]["turns"], on["doc"]["turns"]
    assert on["doc"]["aggregate"] == off["doc"]["aggregate"], on["doc"]["aggregate"]
    assert on["doc"]["trajectory"] == off["doc"]["trajectory"], on["doc"]["trajectory"]

    # The additive section, exactly: shadow mode, zero skipped, one fixed score per turn.
    assert on["doc"]["triage"] == {
        "mode": "shadow",
        "skipped": 0,
        "scores": [
            {"ordinal": n, "score": 0.5, "confidence": 0.9}
            for n in range(len(on["doc"]["turns"]))
        ],
    }, on["doc"]["triage"]
    assert "triage" not in off["doc"], off["doc"]

    # Anti-vacuity: the on-side really consulted triage (once per turn, on disk); the
    # off-side never did (the marker did not grow). The JSON cannot show this itself —
    # shadow mode skips nothing — so the marker is the proof.
    assert len(on["marker"]) == len(on["doc"]["turns"]), on["marker"]
    assert off["marker"] == on["marker"], (
        "the off-side triage never ran, but the marker grew: "
        f"on={len(on['marker'])} off={len(off['marker'])}"
    )


# --- (2) ABSENT => NO-OP: no flag, no env, no subprocess, no network ---------------------


def _spawn_spy(name: str):
    def spy(*args, **kwargs):
        raise AssertionError(
            f"triage {name} was reached with no --triage-author and no "
            f"{triage.TRIAGE_ENV} — absent triage must be a complete no-op"
        )

    return spy


def _canned_verifier(status: Status = Status.PASS):
    """A fake `verify_turn` that answers the configured status for any turn.

    `shell_server_command` is accepted because the CLI always passes it; a stub
    that refused it would turn a routing change into unrelated CLI-rendering
    failures (the surfaces-aspect precedent).
    """

    def verifier(
        records, n, *, server_command, manifest_dir, replays, invariants, timeout,
        shell_server_command=None,
    ):
        return TurnVerdict(
            turn_index=n,
            tool_name="edit_file",
            status=status,
            replayed_is_error=False,
        )

    return verifier


def _spy_verifier(calls: list[int]):
    """Wrap the canned verifier in a call log — the "was it replayed?" spy."""

    def spy(records, n, **kwargs):
        calls.append(n)
        return _canned_verifier()(records, n, **kwargs)

    return spy


def _tool_list_frames(tool: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": name, "annotations": {"readOnlyHint": False}}
                    for name in (tool, "run_process")
                ]
            },
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call_frame(msg_id: int, tool: str, arguments: dict) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()


def _reply_frame(msg_id: int, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _multi_turn_trace(tmp_path: Path, n_calls: int = 3) -> Path:
    """A real trace with `n_calls` `tools/call` turns (one tool, per-turn handles)."""
    from belay.trace import TraceWriter

    writer = TraceWriter.in_directory(tmp_path / "traces")
    try:
        for direction, raw, handle in _tool_list_frames("edit_file"):
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
        for i in range(n_calls):
            call_id = 10 + i
            call = _call_frame(call_id, "edit_file", {"path": "/repo/src/a.py"})
            writer.set_state_handle({"status": "present", "handle": f"H{i}"}, frame=call)
            writer.observer("c2s")(call, False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    return writer.path


def test_absent_triage_is_a_noop_no_subprocess_no_network(
    tmp_path, monkeypatch, capsys
) -> None:
    """No flag and no `BELAY_TRIAGE_AUTHOR` => triage is a NO-OP: every turn replayed,
    no `triage` section (absent-never-zero), and NOTHING is spawned or constructed —
    the resolver returns None, and the seam's only I/O channel (subprocess) is proven
    never to run, so no network can be attempted either.

    The env var is scrubbed by ABSENCE, never set to `""` — an empty value would still
    occupy the precedence slot, so the pin asserts the key is genuinely absent and the
    resolver still answers None.
    """
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv(triage.TRIAGE_ENV, raising=False)
    assert triage.TRIAGE_ENV not in os.environ, (
        f"{triage.TRIAGE_ENV} must be scrubbed by ABSENCE, never set to \"\""
    )

    # The spawn spies: triage may construct nothing and spawn nothing. The only I/O
    # the seam can perform is the subprocess it would launch, so "no spawn" IS "no
    # network" — nothing leaves the process.
    monkeypatch.setattr(triage.subprocess, "run", _spawn_spy("subprocess.run"))
    monkeypatch.setattr(triage.subprocess, "Popen", _spawn_spy("subprocess.Popen"))
    monkeypatch.setattr(triage, "SubprocessTriage", _spawn_spy("SubprocessTriage"))

    trace_path = _multi_turn_trace(tmp_path)
    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)

    assert triage.triage_from_env() is None  # the resolver: absent, never a crash
    assert rc == 0, doc
    assert calls == [0, 1, 2], calls  # every turn replayed — triage changed nothing
    assert "triage" not in doc, doc  # absent-never-zero, the approval precedent


# --- (3) THE WHITELIST AT THE SURFACE: the honest-line pair ------------------------------


@REQUIRES_CAPTURE
def test_the_payload_constructed_at_the_cli_boundary_carries_only_whitelisted_keys(
    triage_demo_runs,
) -> None:
    """The honest-line pair, pinned at the CLI boundary on real data: the payload the
    real `belay verify` run constructs for the triage author carries EXACTLY
    `WHITELISTED_KEYS` and no raw state or trace bytes.

    (a) The author's own half: every payload it received passed its `set(payload) ==
    WHITELISTED_KEYS` assertion — the marker is all `1`s (a `0` records a refused
    off-whitelist payload, which fail-open would otherwise keep silent).
    (b) The test's half: every payload the CLI built is read back from disk and
    asserted directly — the key set is exact, and every value is a JSON scalar
    (bytes are structurally unrepresentable in JSON, asserted anyway).
    """
    on, _off = triage_demo_runs

    assert on["rc"] == 0, on["text"]
    assert on["marker"] and set(on["marker"]) == {"1"}, (
        f"the triage author refused {on['marker'].count('0')} of "
        f"{len(on['marker'])} payload(s): an off-whitelist payload left the CLI. "
        f"marker={on['marker']!r}"
    )

    lines = [line for line in on["dumps"].splitlines() if line]
    assert len(lines) == len(on["doc"]["turns"]), (
        f"one payload per turn expected, got {len(lines)}"
    )
    for line in lines:
        payload = json.loads(line)
        assert set(payload) == WHITELISTED_KEYS, (
            "the CLI constructed an off-whitelist payload: "
            f"{sorted(set(payload) ^ WHITELISTED_KEYS)}"
        )
        for key, value in payload.items():
            assert not isinstance(value, bytes), key  # raw bytes never egress
            assert isinstance(value, (str, int, bool, float, list, type(None))), (
                key, type(value)
            )