"""`ClaudeCliModel` — the argv it builds and the environment it hands the child.

Phase 1 of `claude-cli-model` covers exactly two constructed artifacts: the **command
line** and the **child environment**. Both are asserted directly, never by observing a
live run — no `claude` binary is spawned by anything in this file, no network is touched,
and no subscription is consumed. The seam is `runner=`, a callable with `subprocess.run`'s
shape; every test that needs one injects a fake that records what it was handed.

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

import re
import subprocess

import pytest

from eval.minting_driver.clients.claude_cli_client import (
    DEFAULT_CLAUDE_CLI_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_NAME,
    ClaudeCliModel,
)

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
