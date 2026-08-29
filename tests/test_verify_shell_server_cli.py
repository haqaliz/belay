"""`belay verify --shell-server` — the routing parity `belay phase0 run` has had since `9138cea`.

The engine has routed per tool since the dual-server aspect: `verify_turn` takes
`shell_server_command` and a recorded `run_process` turn replays against it while every
other turn replays against `--server` (`src/belay/verify/turn.py:210`). Only the
batch/eval surface ever exposed it. `belay verify` — the surface the README, the demo and
the console all document — could not reach it: `belay verify --help` showed `[--server
...]` and nothing else, and `tests/test_phase0_dual_server.py:14` records why ("The CLI
`--shell-server` flag is Phase 3 of the aspect"), planned for the batch runner and never
extended.

**This defect class has now occurred twice.** The L7 launch-demo work found `belay verify`
lacked the `--timeout` that `corpus add` / `phase0 run` / `interop correlate` already had,
and every console verify degraded to `empty-output` because of it. The guard against a
third occurrence is `tests/test_cli_flag_parity.py`; this file pins the flag itself.

**Flag ORDER is load-bearing and is not a style preference.** `--server` is
`nargs=argparse.REMAINDER`, so it swallows every remaining token — `--shell-server`
written after it becomes part of the server's argv rather than a flag. Argparse cannot
host a second remainder (`src/belay/cli.py:1770`), which is why the shell command is ONE
quoted string, `shlex.split` at use, fail-closed on a string that will not lex.
`eval/minting_driver/entrypoint.py` already writes it in that order;
`test_shell_server_written_after_server_is_swallowed_by_the_remainder` pins the
consequence, and the help text says it in words.

Everything here is parser-level and passthrough (`verify_turn` stubbed — nothing is
re-invoked, nothing is sandboxed) EXCEPT the last test, which drives the committed demo
capture through the real CLI on real re-execution and is darwin-gated for the usual named
cause.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "demo"
CAPTURE = DEMO / "capture"
DEMO_SERVER = DEMO / "server.py"


def _capture_trace() -> Path:
    traces = sorted(CAPTURE.glob("trace-*.jsonl"))
    assert len(traces) == 1, f"expected exactly one committed capture trace, got {traces}"
    return traces[0]


def _manifest_dir() -> Path:
    return CAPTURE / f"{_capture_trace().stem}.manifests"


def _parse(*extra: str):
    """Parse a `verify` invocation with `--server` LAST, as the remainder demands."""
    return cli._parser().parse_args(
        ["verify", str(_capture_trace()), "--manifest-dir", "m", *extra, "--server", "srv"]
    )


# --- AC-1: the flag exists, defaults to None, and reaches `verify_turn` ---------------


def test_verify_shell_server_defaults_to_none():
    """Absent flag -> `None` -> today's behavior, byte-for-byte."""
    assert _parse().shell_server is None


def test_verify_accepts_one_quoted_shell_command():
    """ONE string, exactly as `phase0 run --shell-server` takes it."""
    assert _parse("--shell-server", "node /abs/shell.js").shell_server == (
        "node /abs/shell.js"
    )


def _stub_verify_turn(monkeypatch, seen: list) -> None:
    def _stub(records, n, **kwargs):
        seen.append(kwargs.get("shell_server_command", "<absent>"))
        return TurnVerdict(turn_index=n, tool_name="stub", status=Status.PASS)

    monkeypatch.setattr("belay.verify.turn.verify_turn", _stub)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (
            ["--shell-server", "node /abs/eval/servers/shell.js --stdio"],
            ["node", "/abs/eval/servers/shell.js", "--stdio"],
        ),
        ([], None),
    ],
)
def test_verify_passes_the_shell_server_through_to_verify_turn(
    monkeypatch, capsys, extra, expected
):
    """The flag is only worth having if it reaches the replay.

    Asserted on the value `verify_turn` is called with — the shlex-split argv list, or
    `None` — never merely that argparse accepted a string. `None` is passed EXPLICITLY
    rather than omitted so the call site says "no shell axis" out loud.
    """
    seen: list = []
    _stub_verify_turn(monkeypatch, seen)

    cli.main(
        [
            "verify", str(_capture_trace()),
            "--manifest-dir", str(_manifest_dir()),
            "--turn", "0", "--json", *extra,
            "--server", "srv",
        ]
    )
    capsys.readouterr()

    assert seen == [expected]


# --- AC-2: an un-lexable string is a hard error, named, never half-executed -----------


UNLEXABLE = 'node "/abs/shell.js'  # an unterminated quote


def test_unlexable_shell_server_is_a_named_hard_error(monkeypatch, capsys):
    """`shlex` cannot tokenize it, so Belay refuses — exit 2, nothing replayed.

    Fail-closed is the whole point: a command Belay cannot parse must never be
    half-executed, and must never be silently dropped into "no shell axis", which would
    verify the run against a boundary the operator did not ask for.
    """
    seen: list = []
    _stub_verify_turn(monkeypatch, seen)

    rc = cli.main(
        [
            "verify", str(_capture_trace()),
            "--manifest-dir", str(_manifest_dir()),
            "--turn", "0",
            "--shell-server", UNLEXABLE,
            "--server", "srv",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "--shell-server" in out, out
    assert seen == [], "nothing may be replayed after an un-lexable server command"


def test_unlexable_shell_server_under_json_emits_an_error_document(monkeypatch, capsys):
    """`--json` must never answer a hard error with a truncated document."""
    seen: list = []
    _stub_verify_turn(monkeypatch, seen)

    rc = cli.main(
        [
            "verify", str(_capture_trace()),
            "--manifest-dir", str(_manifest_dir()),
            "--turn", "0", "--json",
            "--shell-server", UNLEXABLE,
            "--server", "srv",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    document = json.loads(out)
    assert "--shell-server" in document["error"]["cause"], document
    assert seen == []


# --- the ORDER pin: `--server` is a remainder and swallows what follows ---------------


def test_shell_server_written_after_server_is_swallowed_by_the_remainder():
    """`--shell-server` AFTER `--server` is not a flag at all — it is server argv.

    This is not a bug to fix; it is what `nargs=REMAINDER` means, and argparse cannot
    host a second remainder. It is pinned because the failure is silent: the run does not
    error, it replays against a server command with two stray tokens appended, and the
    shell axis is simply absent.
    """
    args = cli._parser().parse_args(
        [
            "verify", str(_capture_trace()), "--manifest-dir", "m",
            "--server", "srv", "--shell-server", "node /abs/shell.js",
        ]
    )
    assert args.shell_server is None
    assert args.server == ["srv", "--shell-server", "node /abs/shell.js"]


def test_verify_help_states_that_shell_server_must_precede_server():
    """The ordering requirement is documented where the operator meets it."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        with pytest.raises(SystemExit):
            cli.main(["verify", "--help"])
    text = buffer.getvalue()

    assert "--shell-server" in text, text
    assert "--shell-server BEFORE --server" in text, text


# --- AC-4: absent the flag, the output is byte-identical to today ---------------------


#: `belay verify` text output, through the aggregate block, for one stubbed PASS turn of
#: the committed capture. The standing coverage prose below the aggregate is deliberately
#: NOT pinned here: it is `cli._VERIFY_COVERAGE`, shared by every surface and pinned by
#: `tests/test_coverage_rendering.py`, and duplicating it would make this fixture break
#: on unrelated wording work. What this fixture guards is the region a new flag could
#: plausibly leak into — the header, the per-turn lines and the aggregate.
TODAYS_OUTPUT_THROUGH_THE_AGGREGATE = """\
belay verify {trace}

  7 tool-call turn(s); verifying 1 by re-execution.
  manifests             {manifests}

turns
  turn 1   list_files        PASS
      A2 replay    PASS        stub

aggregate
  turns verified        1
  PASS                  1
  WARN                  0
  FAIL                  0
  UNVERIFIED            0
"""


def _stub_pass_turn(monkeypatch) -> None:
    def _stub(records, n, **kwargs):
        return TurnVerdict(
            turn_index=n, tool_name="list_files", status=Status.PASS,
            sub_verdicts=[
                Verdict(
                    axis="A2", kind="replay", status=Status.PASS,
                    observed="stub", expected="stub", message="stub",
                )
            ],
        )

    monkeypatch.setattr("belay.verify.turn.verify_turn", _stub)


def _run_text_verify(*extra: str) -> int:
    return cli.main(
        [
            "verify", str(_capture_trace()),
            "--manifest-dir", str(_manifest_dir()),
            "--turn", "1", *extra,
            "--server", "srv",
        ]
    )


def test_absent_the_flag_the_rendered_output_is_unchanged(monkeypatch, capsys):
    """The regression fixture: today's output, byte-for-byte, with no flag given."""
    _stub_pass_turn(monkeypatch)
    rc = _run_text_verify()
    out = capsys.readouterr().out

    assert rc == 0, out
    expected = TODAYS_OUTPUT_THROUGH_THE_AGGREGATE.format(
        trace=_capture_trace(), manifests=_manifest_dir()
    )
    assert out.startswith(expected), repr(out[: len(expected) + 200])


def test_the_flag_changes_nothing_on_the_rendering_surface(monkeypatch, capsys):
    """Adding `--shell-server` changes ROUTING, never rendering.

    Same stubbed turn, same document: the flag must not add a line, a header, or a
    coverage claim of its own. (The routing itself is asserted above, on the value
    `verify_turn` receives.)
    """
    _stub_pass_turn(monkeypatch)
    _run_text_verify()
    without = capsys.readouterr().out

    _stub_pass_turn(monkeypatch)
    _run_text_verify("--shell-server", "node /abs/shell.js")
    with_flag = capsys.readouterr().out

    assert with_flag == without


# --- AC-5: the README states the limit, and the prose cannot drift from the flag ------


def _readme() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _limits_section() -> str:
    text = _readme()
    assert "## Coverage & limits, stated exactly" in text
    return text.split("## Coverage & limits, stated exactly", 1)[1].split("\n---", 1)[0]


REPLAY_BOUNDARY_HEADING = (
    "### Replay re-invokes against the server(s) you name, and nothing else"
)


def test_readme_states_the_replay_boundary_limit():
    """The limits section gained the subsection it never had.

    Twelve subsections stated what a verdict covers; none stated that the replay
    BOUNDARY is whatever the operator named on the command line.
    """
    assert REPLAY_BOUNDARY_HEADING in _limits_section()


def test_the_readme_subsection_names_the_flag_and_its_ordering():
    """Machine-checked so the prose cannot drift from the flag it documents."""
    section = _limits_section().split(REPLAY_BOUNDARY_HEADING, 1)[1].split("\n### ", 1)[0]
    assert "--shell-server" in section, section
    assert "--server" in section, section
    assert "run_process" in section, section
    assert "before `--server`" in section, section


def test_the_readme_subsection_describes_the_abstention_that_shipped_and_nothing_more():
    """The honesty guard on this documentation, and the reason it is a test.

    **This test and the subsection it guards were rewritten together**, as the version it
    replaces required: the A2 abstention landed (`verify-tool-not-offered` aspect
    `boundary-probe`). On a DIVERGED reply the engine now asks the boundary what it offers
    and reports `UNVERIFIED` rather than a fabricated result-equivalence FAIL when the
    recorded tool is absent, so the README saying so is no longer docs running ahead of the
    engine — and the first half below **proves** it by scoring that exact shape through the
    real renderer rather than trusting the prose.

    The guard therefore flips direction rather than disappearing. What the README could then
    over-claim was not the STATUS but the **cause bucket**, so while no such constant
    existed the subsection had to SAY so, and this block asserted the admission verbatim.

    **Rewritten a THIRD time, for the cause bucket** (aspect `cause-and-surfaces`). That
    later slice landed: the abstention now carries its own sub-verdict `kind`, its own
    `REPLAYED_*` constant and its own `_PREFIX_LABELS` entry ahead of the `A2/replay`
    catch-all. So the admission must now be GONE, a fragment of it must remain QUOTED (a
    paragraph that is merely shorter tells a reader nothing about what changed), and — the
    part that matters most — the bucket must be **reached**, not merely declared: a constant
    registered behind the catch-all satisfies every reflection guard in the suite and stays
    permanently empty. The engine proves that here too, off the same rendered verdict.

    **Rewritten a second time, for the EFFECT axis** (aspect `boundary-probe`, phase 5).
    The subsection used to admit a second gap in as many words — *"Nor is the effect
    sub-verdict gated yet — on such a turn it can still read 'the observed effect conforms'
    although nothing was observed"*. That half has now shipped: `render_effect_verdict`
    takes the same single `tool_offered` answer and abstains rather than reading the
    capture's declared `readOnlyHint` as though it were an observation of this replay. So
    the admission must be GONE (a stale admission is its own dishonesty — it under-claims a
    fix users depend on), the subsection must describe what replaced it, and — as with the
    status half — the engine is made to prove it here rather than the prose being trusted.
    """
    section = _limits_section().split(REPLAY_BOUNDARY_HEADING, 1)[1].split("\n### ", 1)[0]

    # 1. The README describes the abstention — and the engine really abstains.
    assert "UNVERIFIED" in section, section
    from belay.replay.engine import DIVERGED, REPLAYED, TurnReplay
    from belay.verify.result import render_result_verdict

    reply = TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=DIVERGED,
        recorded_reply=b'{"jsonrpc":"2.0","id":3,"result":{"isError":false}}',
        replayed_reply=b'{"jsonrpc":"2.0","id":3,"result":{"isError":true}}',
        delta=[],
    )
    verdict = render_result_verdict(
        reply, None, tool_offered=False, tool_name="run_process"
    )
    assert verdict.status is Status.UNVERIFIED, (
        "the README describes an abstention the engine does not make", verdict,
    )

    # 2. The cause BUCKET has LANDED (aspect `cause-and-surfaces`), so the admission that
    #    it had not must be gone — and the engine must really produce the bucket, not merely
    #    declare it. This block used to read the other way round:
    #
    #        has_bucket = any("tool-not-offered" in getattr(report, name, "") ...)
    #        if not has_bucket:
    #            assert "does not yet carry a distinct named cause" in section
    #
    #    i.e. it permitted the admission for exactly as long as no bucket existed. That
    #    condition is now false, so the assertion is inverted rather than deleted: the README
    #    may not imply a bucket the engine has not got, and it may not keep admitting a gap
    #    the engine has closed. A stale admission under-claims a shipped fix, which is the
    #    same drift as over-claiming one.
    from belay.replay.probe import TOOL_NOT_OFFERED
    from belay.replay.report import (
        REPLAYED_RESULT_UNVERIFIED,
        REPLAYED_SUB_VERDICT,
        REPLAYED_TOOL_NOT_OFFERED,
        canonical_cause,
    )

    assert "does not yet carry a distinct named cause" not in section, (
        "the abstention DOES carry a distinct named cause now; leaving the admission "
        "standing under-claims a shipped fix"
    )
    assert "cannot yet separate it by name" in section, (
        "the subsection must QUOTE the admission it removed, so a reader can see what "
        "changed rather than find the paragraph silently shorter"
    )

    # …and the bucket is REACHED, not merely declared: the sub-verdict this section
    # describes carries its own kind, and `canonical_cause` resolves that kind ahead of the
    # `A2/replay` catch-all. Without the ordering the bucket would exist and stay empty.
    assert verdict.kind == f"replay:{TOOL_NOT_OFFERED}", (
        "the abstention kept the generic replay kind, so its cause buckets with every "
        "other result-axis abstention and the README's claim is false",
        verdict,
    )
    reached = canonical_cause(
        f"{REPLAYED_SUB_VERDICT} {verdict.axis}/{verdict.kind}: {verdict.message}"
    )
    assert reached == REPLAYED_TOOL_NOT_OFFERED, (reached, verdict.kind)
    assert reached != REPLAYED_RESULT_UNVERIFIED

    # 3. The EFFECT axis is gated now, so the admission that it was not must be gone…
    assert "Nor is the *effect* sub-verdict gated yet" not in section, (
        "the effect sub-verdict IS gated now; leaving the admission standing under-claims "
        "a shipped fix, which is as much a drift as over-claiming one"
    )
    assert "the observed effect conforms" in section, (
        "the subsection must still QUOTE the sentence it removed, so a reader can see what "
        "changed rather than find the paragraph silently shorter"
    )
    assert "effect-conformance" in section or "effect sub-verdict" in section, section

    # …and the engine really does abstain on that axis, on the same evidence.
    from belay.verify.effect import render_effect_verdict

    records = _run_process_trace_records()
    effect = render_effect_verdict(records, 0, [], tool_offered=False)
    assert effect.status is Status.UNVERIFIED, (
        "the README describes an effect abstention the engine does not make", effect,
    )
    assert "the observed effect conforms" not in effect.message, effect.message
    assert render_effect_verdict(records, 0, []).status is Status.PASS, (
        "and gating it must not have cost the axis the verdict it always made on an "
        "offered tool"
    )


def _run_process_trace_records() -> list[dict]:
    """A one-turn `run_process` trace whose tool declares `readOnlyHint: false`.

    The demo capture's shape, built in-memory: a `tools/list` response declaring the hint,
    then the `tools/call`. It is the declaration that routes the turn down the
    declared-false -> PASS branch, so it is what the abstention has to override.
    """
    frames = [
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0", "id": 2,
            "result": {"tools": [{
                "name": "run_process",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": False, "openWorldHint": False},
            }]},
        },
        {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "run_process", "arguments": {"command_line": "printf hi"}},
        },
        {"jsonrpc": "2.0", "id": 3, "result": {"content": [], "isError": False}},
    ]
    directions = ["c2s", "s2c", "c2s", "s2c"]
    return [
        {
            "kind": "frame", "seq": i, "dir": d, "t_in": float(i),
            "raw": base64.b64encode(json.dumps(f).encode()).decode(),
        }
        for i, (d, f) in enumerate(zip(directions, frames))
    ]


# --- AC-3: the payoff, end to end on the COMMITTED demo capture ----------------------


#: The capture's `run_process` turns re-run a real suite (~44s each); the CLI's 10s
#: default would abstain on the clock.
CAPTURE_TIMEOUT = "300"

#: Turn 6 is the post-edit `run_process` — the agent's own verification evidence.
SHELL_TURN = "6"

#: A filesystem-only replay boundary: it speaks MCP, it offers the capture's read/write
#: tools, and it offers NO command tool. Standing in for the ordinary multi-server
#: configuration, where the server the operator names for file turns is simply not the
#: one that served `run_process`.
FILESYSTEM_ONLY_SERVER = '''\
"""A filesystem-only MCP boundary: no command tool, and it says so."""
import json, sys

TOOLS = [
    {"name": "list_files", "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "read_text_file", "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]

def reply(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

for raw in sys.stdin.buffer:
    line = raw.strip()
    if not line:
        continue
    message = json.loads(line)
    method, msg_id = message.get("method"), message.get("id")
    if method == "initialize":
        reply({"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
            "serverInfo": {"name": "filesystem-only", "version": "1"}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = message.get("params", {}).get("name")
        reply({"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text", "text": "no such tool: %r" % name}],
            "isError": True}})
    elif msg_id is not None:
        reply({"jsonrpc": "2.0", "id": msg_id,
               "error": {"code": -32601, "message": "method not found"}})
'''


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox; "
        "the Linux side of this capture is measured in tests/test_docker_inimage.py"
    ),
)
def test_the_demo_captures_shell_turn_is_verifiable_only_when_it_is_routed(
    tmp_path, capsys
):
    """The payoff, on the committed artifact, through the documented CLI.

    Two runs of the SAME command over the SAME real capture, differing by one flag:

      1. `--server` names a filesystem-only boundary — the ordinary shape of a run
         captured from an agent with more than one MCP server. The recorded
         `run_process` turn is re-invoked against a server that does not implement it,
         the reply is readable and reproduces every time, and the turn does NOT reach a
         verdict Belay can stand behind. **Before this flag existed, `belay verify` had
         no way out of that**: the routing the engine already supported was reachable
         only from `belay phase0 run`.
      2. The same command with `--shell-server` naming the server that really served the
         turn (written BEFORE `--server`, which is a remainder): the turn is re-invoked
         against the right boundary, really re-runs the suite in the restored pre-state,
         and reaches a real **PASS**.

    Nothing is mocked: this is `cli.main` driving `verify_turn` driving `replay_turn`
    inside the sandbox, against the capture `tests/test_demo_capture.py` pins.
    """
    filesystem_only = tmp_path / "filesystem_only_server.py"
    filesystem_only.write_text(FILESYSTEM_ONLY_SERVER, encoding="utf-8")

    common = [
        "verify", str(_capture_trace()),
        "--manifest-dir", str(_manifest_dir()),
        "--turn", SHELL_TURN, "--json", "--timeout", CAPTURE_TIMEOUT,
    ]

    unrouted_rc = cli.main(
        [*common, "--server", sys.executable, str(filesystem_only), "{workspace}"]
    )
    unrouted = json.loads(capsys.readouterr().out)

    routed_rc = cli.main(
        [
            *common,
            "--shell-server", f"{sys.executable} {DEMO_SERVER} {{workspace}}",
            "--server", sys.executable, str(filesystem_only), "{workspace}",
        ]
    )
    routed = json.loads(capsys.readouterr().out)

    assert unrouted_rc != 0, unrouted
    assert unrouted["turns"][0]["status"] != "PASS", unrouted
    assert routed_rc == 0, routed
    assert routed["turns"][0]["status"] == "PASS", routed
    assert routed["turns"][0]["tool"] == "run_process", routed
