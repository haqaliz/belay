"""Phase 1 — RED tests for the reference `claude -p` invariant author (M7).

Everything here is offline through the injectable `runner=` seam of
`belay.authoring.reference_author.main` — no `claude` binary is spawned by any test
in this file, no network is touched, and no subscription is consumed. The live proof
is `tests/test_reference_author_live.py`, `manual`-marked and never collected by the
default run (`pyproject.toml:94`).

The guarantees, stated once:

- **R6/R7 by construction.** The constructed argv carries `--tools ""` **and**
  `--strict-mcp-config` (asserted separately, so one cannot mask the other), and the
  model id is a full id — `opus` / `sonnet` / `haiku` are rejected (the D-2 discipline,
  `subscription-model-client/prd.md:350`).
- **Env scrub by absence.** `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_BASE_URL` are removed from a COPY of the environment by `pop` — a
  variable that was never set stays absent, never written back as `""`; `os.environ`
  itself is never mutated; no key is read or passed. Asserted on the constructed env
  (and on the env handed to the runner), not only on the argv.
- **Protocol round trip.** Protocol JSON in on stdin → one `claude -p
  --output-format json` envelope whose `result` text holds ONE JSON object → that
  object on stdout, exit 0 — the shape `authoring-protocol`'s `parse_author_response`
  accepts. The envelope parsing mirrors the proven client
  (`eval/minting_driver/clients/claude_cli_client.py:516-580`), which this module
  reimplements rather than imports (`eval/` is not a product surface).
- **Fail-closed, named, never partial.** Non-zero child exit, timeout, spawn failure,
  unparseable envelope, an `is_error` envelope, non-string `result`, permission
  denials, a reply with no JSON object, a reply with more than one object — every
  failure exits non-zero with a named message on stderr and **no stdout at all**.
- **Zero new dependencies / SDK-absent import contract.** The module imports stdlib
  only, asserted in a fresh interpreter (the `test_minting_driver_clients_import.py`
  pattern) so no earlier test's `sys.modules` can mask a leak.

The reference author is a **passthrough with a single fail-closed gate**: it extracts
exactly one JSON object from the model's reply and forwards it verbatim (including a
model-authored `{"error": ...}`, which the protocol reads as `AUTHOR_FAILED`). Shape
validation, dedup and rule checks are `parse_author_response`'s contract — not this
module's.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from belay.authoring import reference_author as author

#: The exact three variables the child environment must never see — all three occupy a
#: credential-or-routing precedence slot, so scrubbing only the first is insufficient.
SCRUBBED_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")

FULL_MODEL = "claude-opus-5"

#: A representative author-protocol payload (`authoring-protocol`'s shape: task text,
#: bounded repo inventory, rule vocabulary with grounding semantics, library entries).
#: The reference author treats it as opaque data — it serializes it into the prompt and
#: never reads its keys.
PAYLOAD = {
    "task": "make the tests pass",
    "repo": {"root": "repo", "files": ["app.py", "tests/test_spellcheck.py"]},
    "rules": [
        {
            "rule": "read-only",
            "grounding": "the scope must not be written",
            "semantics": "a write inside the scope is a violation",
        },
        {
            "rule": "no-assertion-weakening",
            "grounding": "an assertion must not be weakened",
            "semantics": "removal, replacement by a non-assertion, or a strictly larger "
            "accepted input set is a violation",
        },
    ],
    "library": [],
}

CANDIDATES = {
    "candidates": [
        {
            "scope": "tests/",
            "rule": "read-only",
            "rationale": "the suite must not be edited",
        }
    ]
}
CANDIDATES_REPLY = json.dumps(CANDIDATES)


# --- helpers --------------------------------------------------------------------------


def _completed(stdout: str, *, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    """A `subprocess.CompletedProcess`-shaped object — only the three fields read.

    A `SimpleNamespace` rather than a real `CompletedProcess`, exactly as the precedent's
    fakes are: the module reads `.returncode`, `.stdout` and `.stderr`, and a fake that
    can express only those cannot accidentally pass by supplying something the real
    boundary does not.
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _envelope(result: str, **overrides) -> str:
    """One `claude -p --output-format json` envelope, as the CLI prints it.

    Defaults are the *success* shape (`is_error: false`, `subtype: "success"`, no
    denials); every test overrides only the field it is about.
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

    The recorded calls are the only way these tests see the constructed argv / env: both
    are data the module constructed, so asserting on them is asserting on the real thing
    rather than on a re-derivation.
    """
    calls: list[dict] = []

    def runner(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        index = min(len(calls) - 1, len(stdouts) - 1)
        return _completed(stdouts[index], returncode=returncode, stderr=stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _runner_raising(exc: BaseException):
    """A runner that raises instead of returning — the timeout / spawn-failure boundary.

    The exceptions a real `subprocess.run` raises (`subprocess.TimeoutExpired`,
    `FileNotFoundError`) are raised *by the call*, so this is the only faithful way to
    exercise how the module names them.
    """

    def runner(argv, **kwargs):
        raise exc

    return runner


def _recording_runner():
    """A `subprocess.run`-shaped callable that must never be invoked."""

    def runner(*args, **kwargs):
        raise AssertionError("no subprocess may be spawned by an offline test")

    runner.calls = []  # type: ignore[attr-defined]
    return runner


def _run_main(
    monkeypatch,
    capsys,
    *,
    runner,
    stdin_text: str = json.dumps(PAYLOAD),
    argv: list[str] | None = None,
):
    """Drive `main` exactly as `python -m` would, with stdin and the runner injected."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    code = author.main(argv if argv is not None else ["--model", FULL_MODEL], runner=runner)
    return code, capsys.readouterr()


# --- Phase 1.1 — the argv -------------------------------------------------------------


def test_build_command_is_exactly_the_proven_argv():
    """The exact flag-for-flag shape of the proven client (`claude_cli_client.py:422-447`).

    Exact equality pins the ORDER too: a reordered argv would pass a membership test and
    still be a different command line.
    """
    assert author._build_command("claude", FULL_MODEL, "the prompt", "the system prompt") == [
        "claude",
        "-p",
        "the prompt",
        "--output-format",
        "json",
        "--model",
        FULL_MODEL,
        "--tools",
        "",
        "--strict-mcp-config",
        "--safe-mode",
        "--no-session-persistence",
        "--system-prompt",
        "the system prompt",
    ]


@pytest.mark.parametrize("alias", ["opus", "sonnet", "haiku"])
def test_build_command_rejects_every_model_alias(alias):
    """`opus` / `sonnet` / `haiku` are CLI aliases, not full model ids (D-2)."""
    with pytest.raises(author.ModelIdError) as exc:
        author._build_command("claude", alias, "p", "s")
    assert "alias" in str(exc.value), str(exc.value)
    assert FULL_MODEL in str(exc.value), str(exc.value)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_build_command_rejects_empty_model_ids(empty):
    with pytest.raises(author.ModelIdError) as exc:
        author._build_command("claude", empty, "p", "s")
    assert "model" in str(exc.value).lower(), str(exc.value)


def test_main_hands_the_runner_the_proven_argv(monkeypatch, capsys):
    """The argv `main` constructs and hands to the runner — asserted on the real call.

    `--tools ""` and `--strict-mcp-config` are asserted SEPARATELY (the R6/R7 pair): a
    test that only checked membership of `--strict-mcp-config` could pass while the
    empty allowlist silently became a non-empty one, or vice versa.
    """
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert len(runner.calls) == 1
    argv = runner.calls[0]["argv"]

    assert argv[0] == author.DEFAULT_BINARY
    assert argv[1] == "-p"
    assert isinstance(argv[2], str) and argv[2], argv
    assert argv[3:5] == ["--output-format", "json"], argv
    assert argv[5:7] == ["--model", FULL_MODEL], argv
    assert argv[7:9] == ["--tools", ""], argv
    assert "--strict-mcp-config" in argv, argv
    assert "--safe-mode" in argv, argv
    assert "--no-session-persistence" in argv, argv
    system_prompt = argv[argv.index("--system-prompt") + 1]
    assert system_prompt == author._build_prompt(PAYLOAD), system_prompt


# --- Phase 1.2 — the env --------------------------------------------------------------


def test_build_env_scrubs_credentials_by_absence(monkeypatch):
    """The three credential/routing vars are REMOVED from a copy — never `""`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-live")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    monkeypatch.setenv("BELAY_UNRELATED", "keep-me")
    before = dict(os.environ)

    env = author._build_env()

    assert env["BELAY_UNRELATED"] == "keep-me"
    for name in SCRUBBED_ENV_VARS:
        assert name not in env, f"{name} leaked into the child env"
    assert os.environ == before, "os.environ itself must never be mutated"


def test_scrubbed_vars_never_set_stay_absent(monkeypatch):
    """A variable that was never set stays absent — the scrub never writes `""` back."""
    for name in SCRUBBED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    env = author._build_env()

    for name in SCRUBBED_ENV_VARS:
        assert name not in env, f"{name} must stay absent, never written back as an empty string"


def test_runner_receives_the_scrubbed_env(monkeypatch, capsys):
    """Asserted on the env actually handed to the child, not only on the builder."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-live")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")

    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    child_env = runner.calls[0]["env"]
    for name in SCRUBBED_ENV_VARS:
        assert name not in child_env, f"{name} reached the child environment"
    assert child_env["PATH"] == os.environ["PATH"]


def test_runner_receives_the_subprocess_run_shape(monkeypatch, capsys):
    """The runner is called with `subprocess.run`'s own keyword surface."""
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    call = runner.calls[0]
    assert call["capture_output"] is True
    assert call["text"] is True
    assert call["timeout"] == author.DEFAULT_TIMEOUT_SECONDS
    assert isinstance(call["env"], dict)


# --- Phase 1.3 — the prompt -----------------------------------------------------------


def test_build_prompt_instructs_and_carries_the_payload_as_data():
    prompt = author._build_prompt(PAYLOAD)

    assert "A1" in prompt
    assert "invariant" in prompt.lower()
    assert "vocabulary" in prompt
    assert "candidates" in prompt
    assert "scope" in prompt and "rule" in prompt and "rationale" in prompt
    assert "ONE JSON object" in prompt

    # The protocol payload is serialized as DATA — deterministic, verbatim — so the
    # model sees exactly the task text, vocabulary and library the operator granted.
    payload_json = json.dumps(PAYLOAD, indent=2, sort_keys=True)
    assert payload_json in prompt, "the protocol payload must travel verbatim as data"
    assert "make the tests pass" in prompt


# --- Phase 1.4 — the round trip -------------------------------------------------------


def test_protocol_round_trip_emits_the_candidates_object(monkeypatch, capsys):
    """Protocol JSON in on stdin → candidates object out on stdout, exit 0."""
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert captured.err == "", captured.err
    emitted = json.loads(captured.out)
    assert emitted == CANDIDATES
    assert emitted["candidates"][0]["scope"] == "tests/"
    assert emitted["candidates"][0]["rule"] == "read-only"


def test_round_trip_forward_a_model_error_object_verbatim(monkeypatch, capsys):
    """`{"error": ...}` is a legitimate protocol reply — forwarded, exit 0.

    `authoring-protocol`'s `parse_author_response` reads it as `AUTHOR_FAILED`; this
    module is a passthrough and must not decide for it.
    """
    reply = json.dumps({"error": "the model declined"})
    runner = _runner_returning(_envelope(reply))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert json.loads(captured.out) == {"error": "the model declined"}


def test_round_trip_accepts_empty_candidates(monkeypatch, capsys):
    """`{"candidates": []}` is protocol-valid (an abstention), not an error."""
    runner = _runner_returning(_envelope(json.dumps({"candidates": []})))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert json.loads(captured.out) == {"candidates": []}


# --- Phase 1.5 — failure modes: named, non-zero, and NO partial stdout ----------------

#: Every failure-path test asserts this trio: non-zero exit, a named message on stderr,
#: and empty stdout. The order of the trio is the contract — see the docstring.
_FAIL_CONTRACT = ("returncode != 0", "named message on stderr", "no stdout")


def test_nonzero_child_exit(monkeypatch, capsys):
    """The exit code is believed over the envelope's contents."""
    runner = _runner_returning(_envelope(CANDIDATES_REPLY), returncode=2, stderr="boom")
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "exited 2" in captured.err, captured.err
    assert "reference-author" in captured.err, captured.err


def test_timeout_is_named_and_kills_no_output(monkeypatch, capsys):
    runner = _runner_raising(subprocess.TimeoutExpired("claude", author.DEFAULT_TIMEOUT_SECONDS))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "timed out" in captured.err.lower(), captured.err


def test_spawn_failure_names_the_missing_binary(monkeypatch, capsys):
    """`claude` absent from PATH (or a non-executable binary) is a named error."""
    runner = _runner_raising(FileNotFoundError("claude"))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "spawn" in captured.err.lower(), captured.err


def test_unparseable_envelope(monkeypatch, capsys):
    runner = _runner_returning("this is not json {")
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "not JSON" in captured.err, captured.err


def test_envelope_is_error(monkeypatch, capsys):
    """The CLI's own verdict on the call is believed before anything inside is read."""
    runner = _runner_returning(
        _envelope(CANDIDATES_REPLY, is_error=True, subtype="error_result")
    )
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "failed" in captured.err.lower(), captured.err


def test_envelope_result_not_a_string(monkeypatch, capsys):
    runner = _runner_returning(_envelope(result=None))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "result" in captured.err, captured.err


def test_permission_denials_are_an_instrument_fault(monkeypatch, capsys):
    """Under `--tools ""` a denial means the no-tools guarantee broke — named, not read."""
    runner = _runner_returning(
        _envelope(CANDIDATES_REPLY, permission_denials=[{"tool": "read_file"}])
    )
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "permission" in captured.err.lower(), captured.err


def test_reply_with_no_json_object(monkeypatch, capsys):
    """Prose without an object is unparseable — never a guessed policy."""
    runner = _runner_returning(_envelope("I propose read-only on tests/ and nothing else."))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "no JSON object" in captured.err, captured.err


def test_reply_with_more_than_one_object_is_ambiguous(monkeypatch, capsys):
    """Two objects is NOT "take the first" — ambiguity is fail-closed, never a guess."""
    two = (
        '{"candidates": [{"scope": "a/", "rule": "read-only"}]} '
        'and also {"candidates": [{"scope": "b/", "rule": "no-create"}]}'
    )
    runner = _runner_returning(_envelope(two))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0
    assert captured.out == ""
    assert "more than one" in captured.err, captured.err


def test_broken_payload_on_stdin_never_spawns_the_child(monkeypatch, capsys):
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(
        monkeypatch, capsys, runner=runner, stdin_text="this is not a json document"
    )

    assert code != 0
    assert captured.out == ""
    assert "stdin" in captured.err, captured.err
    assert runner.calls == [], "the child must not be spawned on a broken payload"


def test_non_object_payload_on_stdin_is_rejected(monkeypatch, capsys):
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner, stdin_text="[1, 2, 3]")

    assert code != 0
    assert captured.out == ""
    assert "object" in captured.err, captured.err
    assert runner.calls == []


def test_missing_model_never_spawns_the_child(monkeypatch, capsys):
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner, argv=[])

    assert code != 0
    assert captured.out == ""
    assert "model" in captured.err.lower(), captured.err
    assert runner.calls == []


def test_alias_model_never_spawns_the_child(monkeypatch, capsys):
    runner = _runner_returning(_envelope(CANDIDATES_REPLY))
    code, captured = _run_main(
        monkeypatch, capsys, runner=runner, argv=["--model", "opus"]
    )

    assert code != 0
    assert captured.out == ""
    assert "alias" in captured.err, captured.err
    assert runner.calls == []


# --- Phase 1.6 — offline by construction + the import contract ------------------------


def test_no_offline_test_can_spawn_a_process(monkeypatch, capsys):
    """A runner that raises on ANY call proves argv/env construction never spawns."""
    runner = _recording_runner()
    # `main` must fail before the runner is invoked (missing model), proving the child
    # is not spawned for the purposes of argv/env construction alone.
    code, captured = _run_main(monkeypatch, capsys, runner=runner, argv=[])
    assert code != 0
    assert runner.calls == []


def test_module_imports_stdlib_only():
    """The SDK-absent import contract, in a fresh interpreter (the
    `test_minting_driver_clients_import.py` pattern): nothing outside the standard
    library (and `belay` itself) may enter the import graph.

    A subprocess is used because `sys.modules` state leaks across tests in a shared
    process; a fresh interpreter is the only way to measure what this module pulls in.
    """
    repo_root = Path(__file__).resolve().parent.parent
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import belay.authoring.reference_author as m\n"
        "pulled = {name.split('.')[0] for name in set(sys.modules) - before}\n"
        "third_party = sorted(\n"
        "    name for name in pulled\n"
        "    if name not in sys.stdlib_module_names and name != 'belay'\n"
        ")\n"
        "assert not third_party, f'the reference author imported {third_party}'\n"
        "assert hasattr(m, 'main') and hasattr(m, '_build_command')\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=repo_root,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout