"""C10 surfaces Phase 1 (RED): the `belay verify` triage surface contract.

The C10 aspect `surfaces` contract, pinned BEFORE the wiring exists (strict TDD):

1. The four flags parse on `verify` ONLY — `--triage-author CMD` (one quoted
   string, shlex-split at use, exit 2 on un-lexable — the `--claim-author`
   shape, `cli.py:946-962`), `--triage-threshold FLOAT`, `--triage-top-n INT`,
   `--no-triage` — and every one is REFUSED (exit 2, naming the flag) on every
   other replay-bearing surface (the parity guard's declared-exact half pins
   the same surface set in `tests/test_cli_flag_parity.py` once the flags
   exist — the registration lands in the same commit as the wiring).
2. A skipped turn renders UNVERIFIED with the exact cause
   `"skipped by the triage budget"` (the verbatim constant the budget module
   documents) on text AND `--json`, is NEVER replayed (the `verify_turn` spy
   never sees its index) and is never PASS, never WARN.
3. `--json` carries an additive `triage` section when triage is configured —
   absent-never-zero when it is not (the `approval` precedent).
4. Shadow mode: configured author, no budget flags ⇒ every turn replayed,
   verdicts identical to a no-triage run, scores recorded in the `triage`
   section.
5. `--no-triage` beats a configured `BELAY_TRIAGE_AUTHOR` (the
   `--no-claim-axis` shape, `cli.py:947`).
6. Threshold and top-N each skip exactly the named turns end-to-end through the
   CLI with a stub author (deterministic scores via `sys.executable -c`).
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.trace import TraceWriter
from belay.verify import turn as turn_module
from belay.verify.triage import WHITELISTED_KEYS
from belay.verify.triage_budget import SKIPPED_BY_BUDGET_CAUSE
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status

#: The exact cause a skipped turn renders — quoted from the budget module's constant.
BUDGET_CAUSE = SKIPPED_BY_BUDGET_CAUSE

TRIAGE_FLAGS = ("--triage-author", "--triage-threshold", "--triage-top-n", "--no-triage")

#: The minimal valid argv for each replay-bearing surface, so the refusal test
#: observes the FLAG being refused rather than a missing-required-argument error.
_MINIMAL_ARGV = {
    "replay": ["replay", "t", "--manifest-dir", "m"],
    "verify": ["verify", "t", "--manifest-dir", "m"],
    "corpus add": ["corpus", "add", "t", "--turn", "0", "--manifest-dir", "m"],
    "corpus run": ["corpus", "run"],
    "corpus show": ["corpus", "show", "c", "--corpus-dir", "d"],
    "phase0 run": ["phase0", "run", "d", "--ledger", "l"],
    "interop correlate": ["interop", "correlate", "s", "t"],
    "interop export": ["interop", "export", "s", "t"],
    "gate baseline": ["gate", "baseline", "t"],
    "gate check": ["gate", "check", "t"],
    "invariant infer": [
        "invariant", "infer", "--task", "t", "--author", "a", "--control", "c", "--out", "o",
    ],
}


def _canned_verifier(status: Status = Status.PASS):
    """A fake `verify_turn` that answers the configured status for any turn.

    `shell_server_command` is accepted because the CLI always passes it; a stub
    that refused it would turn a routing change into unrelated CLI-rendering
    failures (the A3 precedent).
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


def _scoring_author(score_map: dict[int, float]) -> str:
    """One inline triage command: reads the payload, asserts the WHITELISTED key set
    exactly (the egress pin, end-to-end through the real CLI), and scores the turn by
    its `turn_index` — deterministic, no network, no keys."""
    code = (
        "import sys, json; "
        "p = json.load(sys.stdin); "
        f"assert set(p) == set({sorted(WHITELISTED_KEYS)!r}), sorted(p); "
        f's = {score_map!r}[p["turn_index"]]; '
        'sys.stdout.write(json.dumps({"score": s, "confidence": 0.8}))'
    )
    return f"{sys.executable} -c {shlex.quote(code)}"


# --- (1) the flags parse on verify only, refused everywhere else ------------------------


def test_triage_flags_parse_on_verify_only() -> None:
    """The four flags are accepted by `belay verify` together, in any order before
    `--server` (a remainder). Parse-level: the behaviour tests below pin what they do."""
    parser = cli._parser()
    parser.parse_args(
        [
            "verify", "t", "--manifest-dir", "m",
            "--triage-author", "python3 -c 'print(1)'",
            "--triage-threshold", "0.5",
            "--triage-top-n", "2",
            "--no-triage",
            "--server", "x",
        ]
    )


def test_triage_flags_are_refused_on_every_other_replay_bearing_surface(capsys) -> None:
    """Each flag is REFUSED (exit 2, naming the flag) on every other replay-bearing
    surface — triage is the verify surface's budget, like `--claim-author` before it."""
    for surface, argv in _MINIMAL_ARGV.items():
        if surface == "verify":
            continue
        for flag in TRIAGE_FLAGS:
            with pytest.raises(SystemExit) as exc:
                cli._parser().parse_args(argv + ([flag] if flag == "--no-triage" else [flag, "x"]))
            assert exc.value.code == 2, (surface, flag)
            err = capsys.readouterr().err
            assert flag in err, (surface, flag, err)


def test_unlexable_triage_author_is_fail_closed_exit_2(tmp_path, capsys) -> None:
    """An un-lexable `--triage-author` (an unterminated quote) is a HARD error: exit 2
    naming the flag — Belay must never half-execute a command it could not parse, and
    must never quietly degrade the run to "no triage" (`--claim-author`'s rule)."""
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--triage-author", "'unterminated",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "--triage-author" in out, out
    assert "could not be parsed" in out, out


def test_unlexable_triage_author_is_fail_closed_exit_2_json(tmp_path, capsys) -> None:
    """The `--json` surface of the same failure: an error document, never a truncated
    run, same non-zero exit."""
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--triage-author", "'unterminated",
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert doc["error"] is not None, doc
    assert "--triage-author" in doc["error"]["cause"], doc


# --- (2) a skipped turn: UNVERIFIED-by-budget, never replayed, never PASS --------------


def test_skipped_turn_renders_unverified_with_budget_cause_and_is_never_replayed(
    tmp_path, monkeypatch, capsys
):
    """`--triage-threshold 0.5` with scores [0.9, 0.2, 0.6]: turn 1 is skipped. It
    renders UNVERIFIED with the exact cause `"skipped by the triage budget"` on text,
    the `verify_turn` spy never sees turn 1 (a skipped turn is NOT replayed), and the
    turn is never PASS, never WARN. The run exits non-zero: an UNVERIFIED turn is not
    a success a shell can trust."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv("BELAY_TRIAGE_AUTHOR", raising=False)
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--triage-author", _scoring_author({0: 0.9, 1: 0.2, 2: 0.6}),
            "--triage-threshold", "0.5",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert calls == [0, 2], calls  # turn 1 was never replayed
    assert "edit_file         UNVERIFIED" in out, out
    assert f"cause: {BUDGET_CAUSE}" in out, out
    assert BUDGET_CAUSE in out, out  # the UNVERIFIED list names it verbatim too
    assert "triage: budgeted, threshold 0.5, 1 skipped, 2 scored" in out, out


def test_skipped_turn_json_record_is_unverified_with_budget_cause(
    tmp_path, monkeypatch, capsys
):
    """The `--json` surface of the same skip: the skipped turn's record carries
    status UNVERIFIED and the verbatim cause; the replayed turns stay PASS."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv("BELAY_TRIAGE_AUTHOR", raising=False)
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--triage-author", _scoring_author({0: 0.9, 1: 0.2, 2: 0.6}),
            "--triage-threshold", "0.5",
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert calls == [0, 2], calls
    assert [t["status"] for t in doc["turns"]] == ["PASS", "UNVERIFIED", "PASS"], doc
    assert doc["turns"][1]["cause"] == BUDGET_CAUSE, doc
    assert doc["turns"][1]["status"] not in ("PASS", "WARN"), doc
    assert doc["triage"] == {
        "mode": "budgeted",
        "threshold": 0.5,
        "skipped": 1,
        "scores": [
            {"ordinal": 0, "score": 0.9, "confidence": 0.8},
            {"ordinal": 2, "score": 0.6, "confidence": 0.8},
        ],
    }, doc["triage"]


# --- (3) the additive triage section: absent-never-zero (the approval precedent) -------


def test_json_triage_section_absent_when_triage_not_configured(
    tmp_path, monkeypatch, capsys
):
    """No `--triage-author` and no `BELAY_TRIAGE_AUTHOR`: triage is ABSENT — every
    turn replayed, no `triage` key in the JSON document (absent, never a zero), exit 0."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv("BELAY_TRIAGE_AUTHOR", raising=False)
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

    assert rc == 0
    assert calls == [0, 1, 2], calls
    assert "triage" not in doc, doc


# --- (4) shadow mode: every turn replayed, scores recorded alongside -------------------


def test_shadow_mode_replays_every_turn_with_identical_verdicts_and_records_scores(
    tmp_path, monkeypatch, capsys
):
    """Configured author, no budget flags: the safe default — every turn replayed,
    the verdicts identical to a no-triage run of the same trace, and the scores
    recorded in the `triage` section (mode `shadow`, zero skipped)."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv("BELAY_TRIAGE_AUTHOR", raising=False)
    trace_path = _multi_turn_trace(tmp_path)
    author = _scoring_author({0: 0.9, 1: 0.2, 2: 0.6})

    rc_shadow = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--triage-author", author,
            "--server", "unused",
        ]
    )
    doc_shadow = json.loads(capsys.readouterr().out)

    calls.clear()
    rc_plain = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--server", "unused",
        ]
    )
    doc_plain = json.loads(capsys.readouterr().out)

    assert rc_shadow == rc_plain == 0
    assert calls == [0, 1, 2], calls  # shadow mode replays every turn
    assert doc_shadow["turns"] == doc_plain["turns"], "shadow mode must not change verdicts"
    assert doc_shadow["aggregate"] == doc_plain["aggregate"]
    assert "triage" not in doc_plain
    assert doc_shadow["triage"] == {
        "mode": "shadow",
        "skipped": 0,
        "scores": [
            {"ordinal": 0, "score": 0.9, "confidence": 0.8},
            {"ordinal": 1, "score": 0.2, "confidence": 0.8},
            {"ordinal": 2, "score": 0.6, "confidence": 0.8},
        ],
    }, doc_shadow["triage"]

    rc_text = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--triage-author", author,
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out
    assert rc_text == 0, out
    assert "triage: shadow, 0 skipped, 3 scored" in out, out


# --- (5) --no-triage beats a configured env (the --no-claim-axis shape) ----------------


def test_no_triage_beats_a_configured_env(tmp_path, monkeypatch, capsys):
    """`--no-triage` with `BELAY_TRIAGE_AUTHOR` set (and budget knobs given): triage
    is disabled ENTIRELY — every turn replayed, no `triage` section, exit 0. An
    operator can turn triage off without unsetting their configuration."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.setenv("BELAY_TRIAGE_AUTHOR", _scoring_author({0: 0.9, 1: 0.2, 2: 0.6}))
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--no-triage",
            "--triage-threshold", "0.5",
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert calls == [0, 1, 2], calls
    assert "triage" not in doc, doc


# --- (6) threshold and top-N each skip exactly the named turns -------------------------


def test_threshold_skips_exactly_the_named_turns(tmp_path, monkeypatch, capsys):
    """Acceptance 5's threshold half, end-to-end through the CLI: scores [0.9, 0.2,
    0.6] under threshold 0.5 replay turns {0, 2} and skip exactly turn 1 — with a
    REAL stub author (a subprocess, no network)."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv("BELAY_TRIAGE_AUTHOR", raising=False)
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--triage-author", _scoring_author({0: 0.9, 1: 0.2, 2: 0.6}),
            "--triage-threshold", "0.5",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert calls == [0, 2], calls


def test_top_n_skips_exactly_the_named_turns(tmp_path, monkeypatch, capsys):
    """Acceptance 5's top-N half: top 1 of scores [0.9, 0.2, 0.6] replays exactly
    turn 0 (the highest score, ties broken by lowest index) and skips turns 1 and 2."""
    calls: list[int] = []
    monkeypatch.setattr(turn_module, "verify_turn", _spy_verifier(calls))
    monkeypatch.delenv("BELAY_TRIAGE_AUTHOR", raising=False)
    trace_path = _multi_turn_trace(tmp_path)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--triage-author", _scoring_author({0: 0.9, 1: 0.2, 2: 0.6}),
            "--triage-top-n", "1",
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert calls == [0], calls
    assert [t["status"] for t in doc["turns"]] == ["PASS", "UNVERIFIED", "UNVERIFIED"], doc
    assert doc["triage"] == {
        "mode": "budgeted",
        "top_n": 1,
        "skipped": 2,
        "scores": [
            {"ordinal": 0, "score": 0.9, "confidence": 0.8},
        ],
    }, doc["triage"]