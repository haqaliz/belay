"""`ClaudeCliModel` — the argv, the child env, the envelope it parses, and how it fails.

Phase 1 of `claude-cli-model` covers exactly two constructed artifacts: the **command
line** and the **child environment**. Both are asserted directly, never by observing a
live run — no `claude` binary is spawned by anything in this file, no network is touched,
and no subscription is consumed. The seam is `runner=`, a callable with `subprocess.run`'s
shape; every test that needs one injects a fake that records what it was handed.

Phases 2–4 add the other half: one JSON envelope in, one `ToolCall | Done` out — or a
**named error**, never a fabricated `Done` (criterion 3). The same `runner=` seam carries
all of it: a fake that returns a completed-process-shaped object exercises parsing, a fake
that *raises* exercises classification. Nothing here spawns a process either.

**Error classification is asserted end to end through the real
`resilience.classify_error`**, never by asserting a class name. The class name is not the
contract — the *bucket the shared classifier lands on* is, and it is decided by base
classes whose behaviour is counter-intuitive in both directions (see
`test_the_exception_hierarchy_trap_runs_in_both_directions`). A test that asserted
`isinstance(exc, ClaudeCliTimeoutError)` would have been green against the exact bug the
plan's correction box caught.

**The negative assertions here are the load-bearing ones.** `--bare`, `--max-turns`,
`--dangerously-skip-permissions` and `--add-dir` must each stay *absent*, and the three
credential/routing environment variables must be **missing** from the child env rather
than present-and-empty. Each of those is a plausible future "improvement" that would
silently destroy a property this aspect exists to guarantee, and a test asserting a
non-event is the only thing that notices.

**The environment tests monkeypatch all three variables to be SET first.** A test that
passes only because the developer running it happens to have no `ANTHROPIC_API_KEY`
exported is a bug in the test, not evidence — and this operator's box does have one set,
which is the exact condition criterion 13 was written for.
"""

from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace

import pytest

from eval.minting_driver.clients.claude_cli_client import (
    DEFAULT_CLAUDE_CLI_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_NAME,
    ClaudeCliInvocationError,
    ClaudeCliModel,
    ClaudeCliParseError,
    ClaudeCliToolAttemptError,
    ClaudeCliUnknownToolError,
)
from eval.minting_driver.model import Done, Message, ToolCall

#: The three environment variables the child must never see. All three occupy a
#: credential-or-routing precedence slot in the CLI's own resolution order, so scrubbing
#: only the first is insufficient — see the module under test for the per-variable reason.
SCRUBBED_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")

#: A minimal MCP `tools/list` result. Phase 1 never reads these — they exist so the
#: constructor is called the way the real factory calls it.
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
    }
]


def _model(**overrides) -> ClaudeCliModel:
    """A `ClaudeCliModel` with a fake runner, so no subprocess can be spawned."""
    kwargs = {
        "model": DEFAULT_CLAUDE_CLI_MODEL,
        "tools": TOOLS,
        "runner": _recording_runner(),
    }
    kwargs.update(overrides)
    return ClaudeCliModel(**kwargs)


def _recording_runner():
    """A `subprocess.run`-shaped callable that records and never spawns anything."""

    def runner(*args, **kwargs):  # pragma: no cover - Phase 1 never invokes it
        raise AssertionError("no subprocess may be spawned by a Phase 1 test")

    return runner


def _argv(model: ClaudeCliModel | None = None, prompt: str = "the prompt") -> list[str]:
    target = model if model is not None else _model()
    return target._build_command(prompt=prompt, system_prompt="the system prompt")


def _flag_value(argv: list[str], flag: str) -> str:
    """The single token following `flag`, asserting the flag appears exactly once.

    Exactly-once matters: a second `--model` would be silently accepted by the CLI and the
    argv would then name a model this client did not choose.
    """
    occurrences = [i for i, token in enumerate(argv) if token == flag]
    assert len(occurrences) == 1, f"{flag!r} should appear exactly once in {argv!r}"
    index = occurrences[0]
    assert index + 1 < len(argv), f"{flag!r} has no value in {argv!r}"
    return argv[index + 1]


# ---------------------------------------------------------------------------
# Phase 2+ helpers: a runner that returns envelopes, and a runner that raises
# ---------------------------------------------------------------------------

#: The conversation `loop.py` hands a model on its first turn: one system message, then
#: the task. Built the same way here so the prompt tests exercise the real shape.
SYSTEM_MESSAGE = "You are minting a Phase-0 capture."
TASK_MESSAGE = "Fix the failing test in util.py."
FIRST_TURN = [
    Message(role="system", content=SYSTEM_MESSAGE),
    Message(role="user", content=TASK_MESSAGE),
]


def _completed(stdout: str, *, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    """A `subprocess.CompletedProcess`-shaped object — only the three fields read.

    A `SimpleNamespace` rather than a real `CompletedProcess` for the same reason the
    sibling clients' fakes are namespaces: the client reads exactly `.returncode`,
    `.stdout` and `.stderr`, and a fake that can express *only* those cannot accidentally
    pass by supplying something the real boundary does not.
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _envelope(result: str = '{"kind": "done", "reason": "finished"}', **overrides) -> str:
    """One `claude -p --output-format json` envelope, as the CLI prints it.

    Defaults are the *success* shape (`is_error: false`, `subtype: "success"`, no
    denials); every test overrides only the field it is about, so a test named for
    `permission_denials` cannot accidentally be passing because of `is_error`.
    """
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "result": result,
        "session_id": "0000-test",
        "permission_denials": [],
    }
    envelope.update(overrides)
    return json.dumps(envelope)


def _runner_returning(*stdouts: str, returncode: int = 0, stderr: str = ""):
    """A runner handing back one recorded envelope per call, and recording every call.

    The recorded calls are the *only* way these tests see the prompt: the argv is data the
    client constructed, so asserting on it is asserting on the real thing rather than on a
    re-derivation of it.
    """
    calls: list[dict] = []

    def runner(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        index = min(len(calls) - 1, len(stdouts) - 1)
        return _completed(stdouts[index], returncode=returncode, stderr=stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _runner_raising(exc: BaseException):
    """A runner that raises instead of returning — the Phase 4 boundary.

    The exceptions a real `subprocess.run` raises (`FileNotFoundError`,
    `subprocess.TimeoutExpired`) are raised *by the call*, so this is the only faithful
    way to exercise how the client re-raises them.
    """

    def runner(argv, **kwargs):
        raise exc

    return runner


def _client(*, runner, tools: list[dict] | None = None, **overrides) -> ClaudeCliModel:
    """A `ClaudeCliModel` over a given runner — the Phase 2+ counterpart of `_model`."""
    kwargs = {
        "model": DEFAULT_CLAUDE_CLI_MODEL,
        "tools": TOOLS if tools is None else tools,
        "runner": runner,
    }
    kwargs.update(overrides)
    return ClaudeCliModel(**kwargs)


def _propose(result_or_stdout: str, *, raw: bool = False, tools: list[dict] | None = None):
    """One `propose_next` over one envelope. `raw=True` passes stdout through untouched."""
    stdout = result_or_stdout if raw else _envelope(result_or_stdout)
    client = _client(runner=_runner_returning(stdout), tools=tools)
    return client.propose_next(list(FIRST_TURN))


def _prompt_of(runner, index: int = 0) -> str:
    """The `-p` value of the recorded call at `index`."""
    return _flag_value(runner.calls[index]["argv"], "-p")


# ---------------------------------------------------------------------------
# The argv — what it grants (criteria 8, 9, 14)
# ---------------------------------------------------------------------------


def test_argv_empties_the_tool_allowlist():
    """Criterion 8: no tools are granted to the subprocess — `--tools ""` in the argv.

    This is the R6/R7 guarantee in code. The oracle may propose a tool call as *text*; it
    may not execute one itself, because every edit has to cross the MCP boundary the proxy
    is recording. If this assertion ever weakens, the mint's verifiability claim weakens
    with it.
    """
    argv = _argv()

    assert _flag_value(argv, "--tools") == ""


def test_the_emptied_allowlist_is_an_empty_string_not_an_omitted_value():
    """Criterion 8: `--tools` is followed by an empty *token*, not by the next flag.

    `["--tools", "--strict-mcp-config"]` would parse as an allowlist naming a flag, or as
    a missing value — either way the allowlist is no longer provably empty. The empty
    string has to survive into the argv as its own element.
    """
    argv = _argv()

    index = argv.index("--tools")
    assert argv[index + 1] == ""
    assert argv[index + 1] is not None


def test_argv_carries_strict_mcp_config():
    """Criterion 14: `--strict-mcp-config`, asserted separately from `--tools ""`.

    Without it the operator's own MCP servers are inherited into the oracle — a filesystem
    path that never crosses the recorded proxy, i.e. an R6 hole. Emptying the built-in
    tool allowlist does not close it; these are two different grants and they need two
    different assertions.
    """
    assert "--strict-mcp-config" in _argv()


def test_argv_disables_session_persistence():
    """`--no-session-persistence`: a full mint would otherwise leave ~800 session files.

    Nothing downstream reads them, and a resumed run that silently picked one up would not
    be the fresh-context oracle every other part of this design assumes.
    """
    assert "--no-session-persistence" in _argv()


def test_argv_requests_a_json_envelope():
    """`--output-format json` — the envelope Phase 2 parses.

    Asserted here because the flag is part of the constructed command, not of the parsing.
    """
    assert _flag_value(_argv(), "--output-format") == "json"


def test_argv_passes_the_prompt_under_dash_p():
    """The prompt is the value of `-p`: one string, non-interactive."""
    argv = _argv(prompt="do the thing")

    assert _flag_value(argv, "-p") == "do the thing"


def test_argv_passes_our_own_system_prompt():
    """`--system-prompt` carries our text — see the module docstring's measured table.

    The default Claude Code system prompt costs ~5.6x more prefix tokens per call and ties
    the oracle's behaviour to Claude Code's own prompt version, which is not reproducible
    across boxes.
    """
    argv = _argv()

    assert _flag_value(argv, "--system-prompt") == "the system prompt"


def test_the_binary_is_the_first_token():
    """The command names the binary explicitly, and it is overridable for a probe."""
    assert _argv()[0] == "claude"
    assert _argv(model=_model(binary="/opt/claude/bin/claude"))[0] == "/opt/claude/bin/claude"


# ---------------------------------------------------------------------------
# The model id (criteria 9, 20)
# ---------------------------------------------------------------------------


def test_argv_names_the_exact_model_id_it_was_given():
    """Criterion 9: the model id is explicit in the argv, verbatim.

    Not normalised, not aliased, not defaulted at argv-build time — the string the caller
    passed is the string the CLI receives, so the recorded provenance and the actual
    request cannot disagree.
    """
    argv = _argv(model=_model(model="claude-sonnet-4-5-20250929"))

    assert _flag_value(argv, "--model") == "claude-sonnet-4-5-20250929"


def test_the_model_property_reports_the_id_the_argv_names():
    """Criterion 9: the id is *recorded*, read off the object that made the calls."""
    client = _model(model="claude-sonnet-4-5-20250929")

    assert client.model == "claude-sonnet-4-5-20250929"
    assert _flag_value(_argv(model=client), "--model") == client.model


def test_constructing_without_a_model_raises():
    """Criterion 9: the client cannot run on an implicit default — omitting it is an error."""
    with pytest.raises(TypeError):
        ClaudeCliModel(tools=TOOLS, runner=_recording_runner())  # type: ignore[call-arg]


@pytest.mark.parametrize("empty", ["", "   "])
def test_constructing_with_an_empty_model_raises(empty: str):
    """Criterion 9: an empty id is the implicit default wearing a disguise.

    `--model ""` would let the CLI fall back to whatever it considers current, which is
    precisely the drift criterion 9 forbids — so it is refused at construction, where the
    cause is still visible, rather than at argv-build time inside a live mint.
    """
    with pytest.raises(ValueError):
        ClaudeCliModel(model=empty, tools=TOOLS, runner=_recording_runner())


def test_the_default_model_constant_is_a_full_id_not_an_alias():
    """Criterion 20: `claude-opus-5`, never `opus`.

    An alias silently drifts to whatever is newest between two mints, so two runs that
    report the same model string would not have used the same model — exactly what
    criterion 9 forbids, arriving through the constant instead of the argv.
    """
    assert DEFAULT_CLAUDE_CLI_MODEL == "claude-opus-5"
    assert DEFAULT_CLAUDE_CLI_MODEL not in ("opus", "sonnet", "haiku", "opusplan", "default")
    assert re.fullmatch(r"claude-[a-z0-9]+-[a-z0-9-]+", DEFAULT_CLAUDE_CLI_MODEL)


# ---------------------------------------------------------------------------
# The argv — what it must NEVER contain (criteria 15, 16)
# ---------------------------------------------------------------------------


def test_argv_never_contains_bare():
    """Criterion 15: `--bare` is absent, deliberately asserted as a non-event.

    Its help reads *"OAuth and keychain are never read"*. It looks like the isolation flag
    a future reader would reach for and it would break the subscription path outright —
    the one thing this whole aspect exists to make work.
    """
    assert "--bare" not in _argv()


def test_argv_never_contains_max_turns():
    """Criterion 16: `--max-turns` is absent — it is a no-op and would fake a bound.

    Probed 2026-08-05: absent from `--help`, accepted silently, and `--max-turns 1`
    still produced `num_turns: 2`. The real bound is the harness's `DEFAULT_MAX_STEPS`
    plus this client's own subprocess timeout; a flag that looks like a bound and is not
    one is worse than no flag.
    """
    assert "--max-turns" not in _argv()


@pytest.mark.parametrize("flag", ["--dangerously-skip-permissions", "--add-dir"])
def test_argv_never_widens_the_grant(flag: str):
    """The oracle is granted nothing beyond a prompt — no permission bypass, no extra dir.

    Neither flag is needed under `--tools ""`, and either would re-open a path around the
    recorded MCP boundary.
    """
    assert flag not in _argv()


# ---------------------------------------------------------------------------
# The child environment (criteria 7, 13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("var", SCRUBBED_ENV_VARS)
def test_child_env_omits_each_credential_variable(var: str, monkeypatch):
    """Criteria 7 and 13: no API key reaches the subprocess — asserted on the child env.

    All three are monkeypatched to be SET before the assertion. A leaked key produces a run
    that succeeds and looks *identical* while silently billing a metered key, so a test
    that only passed on a box without one set would certify nothing.
    """
    for name in SCRUBBED_ENV_VARS:
        monkeypatch.setenv(name, f"value-for-{name}")

    child_env = _model()._build_env()

    assert var not in child_env


def test_child_env_scrubs_by_absence_never_by_empty_string(monkeypatch):
    """Criterion 13: absent, not `""` — an empty string still occupies its precedence slot.

    `ANTHROPIC_API_KEY=""` is not "no key"; it is a key whose value is empty, and it can
    both authenticate as an empty credential and shadow the OAuth profile that is supposed
    to be used. The variable has to be gone.
    """
    for name in SCRUBBED_ENV_VARS:
        monkeypatch.setenv(name, "a-real-looking-value")

    child_env = _model()._build_env()

    assert [name for name in SCRUBBED_ENV_VARS if name in child_env] == []
    assert "" not in {child_env.get(name) for name in SCRUBBED_ENV_VARS if name in child_env}


def test_child_env_is_scrubbed_surgically_and_inherits_everything_else(monkeypatch):
    """The child still gets the rest of the environment — PATH included, or nothing spawns.

    The scrub is three named removals, not a whitelist: `claude` needs `PATH`, `HOME` and
    its own configuration to find the OAuth profile at all.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-travel")
    monkeypatch.setenv("BELAY_CLAUDE_CLI_ENV_PROBE", "kept")

    child_env = _model()._build_env()

    assert child_env["BELAY_CLAUDE_CLI_ENV_PROBE"] == "kept"
    assert "PATH" in child_env
    assert "ANTHROPIC_API_KEY" not in child_env


def test_child_env_does_not_mutate_the_parent_environment(monkeypatch):
    """Scrubbing builds a copy — the mint process keeps its own env intact.

    `os.environ.pop` here would remove the operator's key from the *parent* for the rest of
    the batch, breaking every later instance on a different provider.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-travel")

    _model()._build_env()

    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-should-not-travel"


def test_a_variable_that_is_not_set_is_simply_not_there(monkeypatch):
    """Deleting an already-absent variable is not an error, and adds nothing.

    A box with no key set must not end up with `ANTHROPIC_API_KEY` present-and-empty in
    the child, which a naive `env[name] = ""` scrub would produce.
    """
    for name in SCRUBBED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    child_env = _model()._build_env()

    assert [name for name in SCRUBBED_ENV_VARS if name in child_env] == []


# ---------------------------------------------------------------------------
# Construction surface
# ---------------------------------------------------------------------------


def test_provider_is_the_registered_name():
    """The provider recorded with this instance's accounting is `claude-cli`."""
    assert _model().provider == PROVIDER_NAME
    assert PROVIDER_NAME == "claude-cli"


def test_the_runner_seam_defaults_to_subprocess_run():
    """The default boundary is `subprocess.run`; every test overrides it.

    Asserted rather than assumed: if the default were something else, every offline test
    here would still pass while the live path spawned nothing.
    """
    client = ClaudeCliModel(model=DEFAULT_CLAUDE_CLI_MODEL, tools=TOOLS)

    assert client._runner is subprocess.run


def test_the_timeout_is_owned_by_the_client():
    """Criterion 16's other half: the bound is this timeout, not a CLI flag.

    `--max-turns` does not bound a run, so the only thing that stops a wedged child is a
    timeout this client passes to the runner itself.
    """
    assert DEFAULT_TIMEOUT_SECONDS == 600.0
    assert _model().timeout == DEFAULT_TIMEOUT_SECONDS
    assert _model(timeout=30.0).timeout == 30.0


# ---------------------------------------------------------------------------
# The envelope -> ToolCall | Done (criteria 1, 2)
# ---------------------------------------------------------------------------


def test_a_well_formed_reply_maps_to_a_tool_call():
    """Criterion 1: a well-formed response maps to a `ToolCall` with name and arguments.

    The oracle cannot *make* a tool call — `--tools ""` guarantees that — so the only thing
    a turn can produce is a proposal in text. If that text does not become a `ToolCall`,
    nothing crosses the recorded MCP boundary and the mint captures nothing.
    """
    step = _propose('{"kind": "tool_call", "name": "read_file", "arguments": {"path": "/repo/util.py"}}')

    assert step == ToolCall(name="read_file", arguments={"path": "/repo/util.py"})


def test_tool_call_arguments_arrive_as_a_dict_not_a_json_string():
    """Criterion 1: `arguments` is a dict by the time `loop.py` sees it.

    `loop.py:117` hands `step.arguments` straight to `tools_call`, which puts it in the
    JSON-RPC `params`. A JSON *string* there would reach the MCP server as a string and be
    rejected — a whole instance lost to a type nobody converted.
    """
    step = _propose('{"kind": "tool_call", "name": "read_file", "arguments": {"path": "a"}}')

    assert isinstance(step, ToolCall)
    assert isinstance(step.arguments, dict)


def test_a_tool_call_with_no_arguments_key_yields_an_empty_dict():
    """A zero-argument tool call is legitimate; an absent `arguments` is not an error.

    The MCP server is the authority on whether a call is missing a required argument, and
    its rejection is recorded in the capture. Guessing arguments here would be worse.
    """
    step = _propose('{"kind": "tool_call", "name": "read_file"}')

    assert step == ToolCall(name="read_file", arguments={})


def test_a_completion_reply_maps_to_done():
    """Criterion 2: a completion response maps to `Done`, carrying the stated reason."""
    step = _propose('{"kind": "done", "reason": "the test passes now"}')

    assert step == Done(reason="the test passes now")


def test_prose_around_the_json_object_is_tolerated():
    """Criterion 1: the object is extracted from surrounding prose, not required to be alone.

    Models narrate. Rejecting a correct decision because it arrived with a sentence in
    front of it would throw away real turns — tolerance here is not laxity, because the
    *kind* is still read from the object and never inferred from the prose.
    """
    step = _propose(
        'I should read the file first.\n'
        '{"kind": "tool_call", "name": "read_file", "arguments": {"path": "a"}}\n'
        'Then I will decide.'
    )

    assert step == ToolCall(name="read_file", arguments={"path": "a"})


def test_a_code_fenced_json_object_is_tolerated():
    """Criterion 1: a fenced block is prose too — the fence is not part of the JSON."""
    step = _propose('```json\n{"kind": "done", "reason": "all set"}\n```')

    assert step == Done(reason="all set")


def test_a_brace_that_is_not_json_does_not_stop_the_search():
    """Criterion 1: a `{` in the prose is skipped, not treated as the payload's start.

    A naive "find the first `{`" extractor fails on any reply that mentions a set or a
    dict in passing, and the failure mode is a `ClaudeCliParseError` on a turn the model
    got right.
    """
    step = _propose('the set {a, b} matters. {"kind": "done", "reason": "ok"}')

    assert step == Done(reason="ok")


def test_an_object_without_a_kind_is_skipped_in_favour_of_one_with_it():
    """Criterion 1: the payload is the object that declares a `kind`, not merely the first.

    Models sometimes emit a scratch object before the decision. Taking the first object
    unconditionally would read that scratch as the reply and raise on a good turn.
    """
    step = _propose('{"thinking": "which file?"} {"kind": "done", "reason": "ok"}')

    assert step == Done(reason="ok")


# ---------------------------------------------------------------------------
# Unparseable is an error, never a Done (criteria 3, 4)
# ---------------------------------------------------------------------------


def test_stdout_that_is_not_json_raises_rather_than_returning_a_done():
    """Criterion 3: an unparseable envelope is a named error, never a fabricated `Done`.

    This is the single most important assertion in the file. A fabricated `Done` ends the
    trajectory *silently and successfully*: the instance is recorded as captured, its turn
    count is short, and every downstream verdict is computed over a run that stopped for a
    reason nobody can see. A `0%` violation rate assembled from such runs would be a
    measurement of the parser, not of the agent.
    """
    with pytest.raises(ClaudeCliParseError):
        _propose("claude: command failed\n", raw=True)


def test_a_result_with_no_json_object_raises_rather_than_returning_a_done():
    """Criterion 3: prose with no object at all is an error — the same silent-stop hazard."""
    with pytest.raises(ClaudeCliParseError):
        _propose("I am not sure what to do next.")


def test_an_unrecognised_kind_raises_rather_than_returning_a_done():
    """Criterion 3: only `tool_call` and `done` are decisions; anything else is unparsed.

    `{"kind": "thinking"}` is not a completion, and treating an unknown kind as one would
    turn every future protocol drift into a quietly truncated trajectory.
    """
    with pytest.raises(ClaudeCliParseError):
        _propose('{"kind": "thinking", "reason": "hmm"}')


def test_a_tool_call_with_no_name_raises():
    """Criterion 3/4: a nameless tool call is not a call — there is nothing to invoke."""
    with pytest.raises(ClaudeCliParseError):
        _propose('{"kind": "tool_call", "arguments": {"path": "a"}}')


def test_tool_call_arguments_that_are_not_an_object_raise():
    """Criterion 3: `arguments` must be a JSON object; a string is not one silently coerced.

    `loop.py` puts this straight into the JSON-RPC `params`, so a non-object here becomes a
    malformed MCP request rather than a turn.
    """
    with pytest.raises(ClaudeCliParseError):
        _propose('{"kind": "tool_call", "name": "read_file", "arguments": "path=a"}')


def test_a_tool_name_not_in_the_schemas_is_an_error_not_passed_through():
    """Criterion 4: a tool the schemas do not name never reaches `loop.py`.

    The alternative is a `tools/call` for a tool the server does not have, which produces
    a JSON-RPC error the capture records as a real turn — noise that looks like agent
    behaviour but is a client-side validation failure.
    """
    with pytest.raises(ClaudeCliUnknownToolError, match="write_file"):
        _propose('{"kind": "tool_call", "name": "write_file", "arguments": {"path": "a"}}')


def test_the_unknown_tool_error_names_the_tools_that_were_offered():
    """Criterion 4: the error says what *was* available, so a mis-wire is diagnosable.

    A bare "unknown tool" cannot distinguish a hallucinating model from a `tools/list`
    that came back empty because the proxy was mis-wired — and those want opposite fixes.
    """
    with pytest.raises(ClaudeCliUnknownToolError, match="read_file"):
        _propose('{"kind": "tool_call", "name": "write_file", "arguments": {}}')


def test_more_than_one_tool_call_warns_and_takes_the_first():
    """One call per turn, never a queue — mirroring `anthropic_client.py:270-277`.

    R7 (one `tools/call` in flight) is a property of the control flow, and it stays that
    way only because no client ever hands the loop a batch. Dropping the extras is the
    safe direction; doing it silently is not, hence the warning.
    """
    with pytest.warns(UserWarning, match="2 tool call"):
        step = _propose(
            '{"kind": "tool_call", "name": "read_file", "arguments": {"path": "first"}}\n'
            '{"kind": "tool_call", "name": "read_file", "arguments": {"path": "second"}}'
        )

    assert step == ToolCall(name="read_file", arguments={"path": "first"})


# ---------------------------------------------------------------------------
# The envelope's own status fields (criteria 1, 19)
# ---------------------------------------------------------------------------


def test_is_error_true_raises_an_invocation_error():
    """Criterion 1: `is_error: true` is the CLI telling us the call failed. Believe it.

    Reading `result` out of a failed envelope would parse the CLI's *error text* as a model
    decision — the most direct route there is to a fabricated turn.
    """
    with pytest.raises(ClaudeCliInvocationError):
        _propose(_envelope(is_error=True, result="usage limit reached"), raw=True)


def test_a_subtype_other_than_success_raises():
    """Criterion 1: only `subtype: "success"` is a usable envelope.

    The CLI signals a truncated or aborted run through the subtype while `is_error` may
    still be false, so checking only `is_error` would accept a partial run as a decision.
    """
    with pytest.raises(ClaudeCliInvocationError, match="error_max_turns"):
        _propose(_envelope(subtype="error_max_turns"), raw=True)


def test_an_absent_subtype_raises_rather_than_being_assumed_successful():
    """Criterion 1: absent is not success — the fail-safe direction.

    An envelope shape we do not recognise is a shape we cannot read a decision out of. The
    alternative default silently promotes every future CLI change to a passing turn.
    """
    stdout = json.dumps({"type": "result", "is_error": False, "result": "{}"})

    with pytest.raises(ClaudeCliInvocationError):
        _propose(stdout, raw=True)


def test_non_empty_permission_denials_raises_a_tool_attempt_error():
    """Criterion 19: a denial means the oracle *attempted a tool* — an instrument fault.

    Under `--tools ""` this is supposed to be impossible. If it happens, the emptied
    allowlist is not doing what the argv tests claim, and the whole R6 story is in doubt —
    so the signal is raised, never discarded.
    """
    with pytest.raises(ClaudeCliToolAttemptError, match="Bash"):
        _propose(
            _envelope(permission_denials=[{"tool_name": "Bash", "tool_input": {}}]),
            raw=True,
        )


def test_a_denial_is_raised_even_when_the_reply_parses_perfectly():
    """Criterion 19: the denial is not discarded just because the turn looks usable.

    This is the whole content of "never discard it". The envelope below carries a valid
    tool-call decision *and* evidence that the tool allowlist leaked; returning the
    decision would bury the fault under a turn that looks completely normal.
    """
    stdout = _envelope(
        result='{"kind": "tool_call", "name": "read_file", "arguments": {"path": "a"}}',
        permission_denials=[{"tool_name": "Edit", "tool_input": {}}],
    )

    with pytest.raises(ClaudeCliToolAttemptError):
        _propose(stdout, raw=True)


def test_an_error_envelope_is_reported_as_an_invocation_error_before_denials_are_read():
    """The check order is fixed: `is_error` first, then denials (plan §1, envelope contract).

    Both are errors, so only the *named type* differs — and it differs in what an operator
    does next. A failed invocation is the provider's problem; a denial is ours.
    """
    stdout = _envelope(
        is_error=True,
        permission_denials=[{"tool_name": "Bash", "tool_input": {}}],
    )

    with pytest.raises(ClaudeCliInvocationError):
        _propose(stdout, raw=True)


# ---------------------------------------------------------------------------
# Accounting: usage is absent-never-zero, cost is never read (criteria 17, 18)
# ---------------------------------------------------------------------------


def test_usage_is_none_until_a_reply_reports_it():
    """Criterion 18: absent is not zero — `usage` stays `None`, never `{}` and never `0`.

    A fabricated `0` in the ledger is the accounting twin of rendering `UNVERIFIED` as
    `PASS`: it reports a measurement that was never taken.
    """
    client = _client(runner=_runner_returning(_envelope()))

    assert client.usage is None

    client.propose_next(list(FIRST_TURN))

    assert client.usage is None


def test_usage_records_the_reported_fields():
    """Criterion 18: a reported usage is folded under the recorded vocabulary.

    `batch.py:229` reads exactly `input_tokens` / `output_tokens`, so those are the names
    a claude-cli instance has to produce for its accounting to appear in the ledger at all.
    """
    client = _client(
        runner=_runner_returning(_envelope(usage={"input_tokens": 7026, "output_tokens": 42}))
    )

    client.propose_next(list(FIRST_TURN))

    assert client.usage == {"input_tokens": 7026, "output_tokens": 42}


def test_a_partial_usage_records_the_present_field_and_omits_the_missing_one():
    """Criterion 18: half a usage is recorded as half, not completed with a zero."""
    client = _client(runner=_runner_returning(_envelope(usage={"output_tokens": 11})))

    client.propose_next(list(FIRST_TURN))

    assert client.usage == {"output_tokens": 11}


def test_usage_accumulates_across_calls():
    """Criterion 18: the totals are per instance, summed over every turn it drove."""
    client = _client(
        runner=_runner_returning(
            _envelope(usage={"input_tokens": 100, "output_tokens": 10}),
            _envelope(usage={"input_tokens": 200, "output_tokens": 20}),
        )
    )

    client.propose_next(list(FIRST_TURN))
    client.propose_next(list(FIRST_TURN))

    assert client.usage == {"input_tokens": 300, "output_tokens": 30}


@pytest.mark.parametrize("value", [True, -5, 1.5, "700", None, {"nested": 1}])
def test_a_usage_value_that_is_not_a_token_count_is_ignored_rather_than_raising(value):
    """Criterion 18: a strange shape reads as absent, and never ends the instance.

    Same rules as `local_client._token_count`: `bool` excluded (a flag is not a token),
    negatives refused (a total that can go down is worse than one honestly missing a
    term), non-integral floats refused rather than truncated. A client that raised here
    would trade a whole instance for a cosmetic accounting field.
    """
    client = _client(runner=_runner_returning(_envelope(usage={"input_tokens": value})))

    client.propose_next(list(FIRST_TURN))

    assert client.usage is None


def test_a_usage_that_is_not_an_object_is_ignored():
    """Criterion 18: `usage: null` (or any non-object) leaves the total untouched."""
    client = _client(runner=_runner_returning(_envelope(usage="lots")))

    client.propose_next(list(FIRST_TURN))

    assert client.usage is None


def test_total_cost_usd_is_never_read_stored_or_surfaced():
    """Criterion 17: the dollar figure in the envelope is not recorded anywhere.

    Under a subscription there is no per-token price, so a dollar amount carried forward
    from a metered envelope is invented precision — and it would appear in the ledger next
    to real measurements with nothing marking the difference (`prd.md` D-1).
    """
    client = _client(
        runner=_runner_returning(_envelope(total_cost_usd=0.2491, usage={"input_tokens": 5}))
    )

    client.propose_next(list(FIRST_TURN))

    assert client.usage == {"input_tokens": 5}
    assert not hasattr(client, "cost")
    assert not hasattr(client, "total_cost_usd")
    state = repr(vars(client))
    assert "0.2491" not in state
    assert "cost" not in state.lower()
