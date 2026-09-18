"""Phase 1 — RED tests for the reference `claude -p` author of the A3 claim axis.

The module under test does not exist yet: `src/belay/verify/reference_claim_author.py`,
runnable as `python -m belay.verify.reference_claim_author --model <full-id>` and wired
by `BELAY_CLAIM_AUTHOR`. Every test here fails with `ModuleNotFoundError` until it does.

Everything is offline through the injectable `runner=` seam of `main` — no `claude`
binary is spawned by any test in this file, no network is touched, and no subscription
is consumed. The live proof is a separate `manual`-marked, owner-run file
(`pyproject.toml:94` addopts keeps it out of CI). The precedent for both the module and
this suite is the shipped invariant author, `src/belay/authoring/reference_author.py` and
`tests/test_reference_author.py`: same idiom, same guarantees, different payload.

The guarantees under test, stated once:

- **The protocol reply is real, not re-derived.** `test_emits_a_valid_check_payload`
  feeds the module's own stdout to the REAL `belay.verify.author._parse_check` — the
  fail-closed parser `SubprocessAuthor` uses — so what is asserted is that Belay itself
  gets a `Check`, not that a copy of the parser in this file would.
- **R6/R7 by construction.** The constructed argv carries `--tools` with an **empty
  value** and `--strict-mcp-config`, asserted in two SEPARATE tests so one cannot mask
  the other (the precedent does this deliberately: a membership test on
  `--strict-mcp-config` would stay green while the empty allowlist quietly became a
  non-empty one). The model id is a full id — `opus` / `sonnet` / `haiku` are rejected
  (the D-2 discipline).
- **Env scrub by absence, never `""`.** `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_BASE_URL` never reach the child. The test SETS all three to non-empty
  values itself rather than relying on the box's ambient state (`ANTHROPIC_BASE_URL`
  happens to be set on the owner's machine, and a test that passes only because of that
  is not a test). Absence is asserted as absence AND explicitly as *not* `""` — an empty
  value still occupies its precedence slot. `os.environ` itself is never mutated.
- **Every malformed reply is an abstention, never an exception and never a usable
  check.** Bad JSON, a non-object payload, `{"error": ...}`, a non-`str` source, a
  non-`list` argv, an argv holding a non-`str` token, a non-zero child exit — each must
  yield NO `Check`, either because the module refused (non-zero exit, named stderr, no
  stdout) or because its stdout fails `_parse_check`. Belay reads either as
  `NO_CHECK_AUTHOR` → UNVERIFIED, never a crash and never a guessed check.
- **Diagnostics on stderr, never stdout.** `SubprocessAuthor` parses stdout as exactly
  one JSON object; a stray `print()` to stdout breaks the parse and silently disables
  A3, which is strictly worse than a named refusal.
- **Zero-dep.** The module imports stdlib or first-party `belay` only — AST-scanned, and
  never imported for the scan, mirroring `tests/test_verify_zero_llm.py`.

**Deliberately asserted through `main`, not through private helpers.** The argv, the
child env and the exit discipline are all observed on the real call the module makes to
the injected runner. A test that asserted on `_build_command` / `_build_env` directly
would pin a private signature this suite has no business fixing, and would assert on a
re-derivation rather than on what the child actually receives.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from belay.verify.author import _MAX_OUTPUT, _parse_check

#: The module this suite drives. Absent in RED — `_module()` raises `ModuleNotFoundError`
#: naming it, which is the failure every test here must show before any implementation.
MODULE_NAME = "belay.verify.reference_claim_author"

#: The exact three variables the child environment must never see. All three occupy a
#: credential-or-routing precedence slot, so scrubbing only the first is insufficient
#: (`reference_author.py:60-64`).
SCRUBBED_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")

#: A full model id. The CLI's `opus` / `sonnet` / `haiku` aliases are rejected: an alias
#: pins the reply to whatever the CLI's alias table says on the operator's box, which is
#: not reproducible policy (`reference_author.py:66-69`).
FULL_MODEL = "claude-opus-5"

MODEL_ALIASES = ("opus", "sonnet", "haiku")

#: A representative A3 author-protocol payload — the object `SubprocessAuthor.author_check`
#: writes to the author's stdin (`src/belay/verify/author.py:97-105`, `sort_keys=True`).
#: The author treats it as opaque data: it serializes it into the prompt as DATA.
PAYLOAD = {
    "claim": "I fixed the failing test and verified the suite passes.",
    "classification": "VERIFICATION",
    "final_state_files": ["app.py", "tests/test_spellcheck.py"],
    "turns": [
        {"seq": 4, "tool": "edit_file"},
        {"seq": 6, "tool": "run_process"},
    ],
}

#: The check the model is expected to author: source verbatim, argv runnable relative to
#: the materialized final workspace (`claims.py:92-102`).
CHECK_SOURCE = "python -m pytest tests/test_spellcheck.py re-derives the claim"
CHECK_ARGV = ["python", "-m", "pytest", "-q", "tests/test_spellcheck.py"]
CHECK_REPLY = json.dumps({"source": CHECK_SOURCE, "argv": CHECK_ARGV})


# --- the module under test ------------------------------------------------------------


def _module():
    """The module under test, imported by name.

    In RED this raises `ModuleNotFoundError` naming `MODULE_NAME` — which is exactly the
    failure this phase is asserting. Imported per-test rather than at module scope so
    every test is COLLECTED and fails individually, instead of the whole file erroring
    out at collection and reporting nothing about the contract.
    """
    return importlib.import_module(MODULE_NAME)


def _module_path() -> Path:
    """The module's source file, located WITHOUT importing it.

    `test_verify_zero_llm.py:11-19` states the reason and this mirrors it: importing runs
    side effects and reports on the venv rather than on the source that ships. `find_spec`
    resolves the origin without executing the module; absent, it raises the same named
    `ModuleNotFoundError` every other test here shows.
    """
    spec = importlib.util.find_spec(MODULE_NAME)
    if spec is None or spec.origin is None:
        raise ModuleNotFoundError(
            f"No module named {MODULE_NAME!r} — the reference claim author has not been "
            "written yet (Phase 2).",
            name=MODULE_NAME,
        )
    return Path(spec.origin)


# --- helpers --------------------------------------------------------------------------


def _completed(stdout: str, *, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    """A `subprocess.CompletedProcess`-shaped object — only the three fields read.

    A `SimpleNamespace` rather than a real `CompletedProcess`, exactly as the precedent's
    fakes are: a fake that can express only `.returncode`, `.stdout` and `.stderr` cannot
    accidentally pass by supplying something the real boundary does not.
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _envelope(result: str, **overrides) -> str:
    """One `claude -p --output-format json` envelope, as the CLI prints it.

    Defaults are the *success* shape (`is_error: false`, `subtype: "success"`, no
    denials); a test overrides only the field it is about. This is the precedent's own
    fixture (`tests/test_reference_author.py:110-126`) and the shape the real binary
    emits, so it is the contract the module must read, not a convenience of this suite.
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


def _runner_returning(stdout: str, *, returncode: int = 0, stderr: str = ""):
    """A runner handing back one recorded envelope, and recording every call.

    The recorded calls are the only way these tests see the constructed argv and env:
    both are data the module built and handed to the child, so asserting on them is
    asserting on the real thing rather than on a re-derivation.
    """
    calls: list[dict] = []

    def runner(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        return _completed(stdout, returncode=returncode, stderr=stderr)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _runner_raising(exc: BaseException):
    """A runner that raises instead of returning — the spawn-failure / timeout boundary.

    The exceptions a real `subprocess.run` raises (`FileNotFoundError`,
    `subprocess.TimeoutExpired`) are raised *by the call*, so this is the only faithful
    way to exercise how the module names them.
    """

    def runner(argv, **kwargs):
        raise exc

    runner.calls = []  # type: ignore[attr-defined]
    return runner


def _run_main(
    monkeypatch,
    capsys,
    *,
    runner,
    stdin_text: str = json.dumps(PAYLOAD, sort_keys=True),
    argv: list[str] | None = None,
):
    """Drive `main` exactly as `python -m` would, with stdin and the runner injected."""
    module = _module()
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    code = module.main(
        argv if argv is not None else ["--model", FULL_MODEL],
        runner=runner,
    )
    return code, capsys.readouterr()


def _argv_of(runner) -> list[str]:
    """The single argv the module handed the child, with a named failure if it did not."""
    assert len(runner.calls) == 1, f"expected exactly one child call, got {runner.calls}"
    return runner.calls[0]["argv"]


# --- A1 — the protocol reply ----------------------------------------------------------


def test_emits_a_valid_check_payload(monkeypatch, capsys):
    """A stubbed model reply becomes a `Check` through the REAL fail-closed parser.

    The assertion deliberately runs `belay.verify.author._parse_check` — the very
    function `SubprocessAuthor.author_check` calls on the author's stdout — rather than a
    copy. A copy could drift from the shipped parser and certify a payload Belay would
    reject, which is the one thing this test exists to rule out.
    """
    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert captured.err == "", captured.err

    check = _parse_check(captured.out)
    assert check is not None, captured.out
    assert check.source == CHECK_SOURCE
    assert check.argv == tuple(CHECK_ARGV)


# --- A2 / A3 — the child environment --------------------------------------------------


def test_env_scrub_removes_all_three_anthropic_vars_by_absence(monkeypatch, capsys):
    """None of the three `ANTHROPIC_*` names reaches the child — by absence, never `""`.

    The test SETS all three to non-empty values itself; relying on the box's ambient
    state would make this pass for the wrong reason on a machine that happens to have
    them unset. Both assertions are made per name: `not in` (absence) and, separately and
    explicitly, that the value is not the empty string — an empty value still occupies
    its credential/routing precedence slot, so writing `""` back would not be a scrub.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-live")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    monkeypatch.setenv("BELAY_UNRELATED", "keep-me")

    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    child_env = runner.calls[0]["env"]

    for name in SCRUBBED_ENV_VARS:
        assert name not in child_env, f"{name} reached the child environment"
        assert child_env.get(name) != "", (
            f"{name} must be ABSENT from the child env, never present-but-empty — an "
            "empty value still occupies its precedence slot"
        )

    # The scrub is surgical: everything else the operator set still travels.
    assert child_env["BELAY_UNRELATED"] == "keep-me"
    assert child_env["PATH"] == os.environ["PATH"]


def test_os_environ_is_not_mutated_by_building_child_env(monkeypatch, capsys):
    """Building the child env copies; it never mutates this process's environment.

    A scrub that popped from `os.environ` itself would strip the operator's key for the
    rest of the session and break every later provider-driven run in the same process.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-live")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    before = dict(os.environ)

    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert dict(os.environ) == before, "os.environ itself must never be mutated"


# --- A4 — R6/R7, asserted as two independent properties -------------------------------


def test_argv_grants_no_tools(monkeypatch, capsys):
    """`--tools` is followed by an EMPTY string element: the model is granted no tools.

    The value is asserted, not just the flag. Dropping the empty element would leave
    `--tools` consuming the next flag as its allowlist, and the emptiness this argv is
    supposed to guarantee would quietly stop being true.
    """
    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    argv = _argv_of(runner)
    assert "--tools" in argv, argv
    assert argv[argv.index("--tools") + 1] == "", argv


def test_argv_carries_strict_mcp_config(monkeypatch, capsys):
    """`--strict-mcp-config`: the model inherits no MCP configuration from the box.

    A SEPARATE test from the `--tools ""` one, deliberately (the precedent's reasoning):
    folded into one assertion block, a regression in either half could be masked by the
    other still holding.
    """
    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    assert "--strict-mcp-config" in _argv_of(runner), _argv_of(runner)


# --- A5 — the model id ----------------------------------------------------------------


@pytest.mark.parametrize("alias", MODEL_ALIASES)
def test_model_alias_is_rejected(alias, monkeypatch, capsys):
    """`opus` / `sonnet` / `haiku` are CLI aliases, not full model ids (D-2).

    Rejected before the child is spawned, with a named message on stderr and no stdout —
    an alias resolves to whatever the operator's CLI alias table says, which is not
    reproducible policy.
    """
    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner, argv=["--model", alias])

    assert code != 0, captured
    assert captured.out == "", captured.out
    assert "alias" in captured.err.lower(), captured.err
    assert runner.calls == [], "an alias must be refused before the child is spawned"


def test_full_model_id_is_accepted(monkeypatch, capsys):
    """A full model id is accepted and travels verbatim onto the argv."""
    runner = _runner_returning(_envelope(CHECK_REPLY))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code == 0, captured
    argv = _argv_of(runner)
    assert "--model" in argv, argv
    assert argv[argv.index("--model") + 1] == FULL_MODEL, argv


# --- A6 — every malformed shape is an abstention --------------------------------------

#: `(reply_text, child_returncode)` — the shapes a model or a child can produce that must
#: never become a usable `Check`. Each is named by its `id` so a failure says which.
_MALFORMED = [
    pytest.param("this is not json at all {", 0, id="invalid-json"),
    pytest.param("[1, 2, 3]", 0, id="json-array-not-object"),
    pytest.param(json.dumps({"error": "I cannot re-derive this claim"}), 0, id="error-object"),
    pytest.param(json.dumps({"source": 42, "argv": CHECK_ARGV}), 0, id="source-not-a-str"),
    pytest.param(json.dumps({"source": CHECK_SOURCE, "argv": "pytest -q"}), 0, id="argv-not-a-list"),
    pytest.param(
        json.dumps({"source": CHECK_SOURCE, "argv": ["python", 7]}),
        0,
        id="argv-token-not-a-str",
    ),
    pytest.param(CHECK_REPLY, 2, id="child-exit-non-zero"),
]


@pytest.mark.parametrize(("reply", "returncode"), _MALFORMED)
def test_malformed_model_output_is_an_abstention(reply, returncode, monkeypatch, capsys):
    """No malformed shape yields a usable check — and none raises.

    Two honest outcomes, and the test accepts either because both land on
    `NO_CHECK_AUTHOR` (UNVERIFIED) at Belay's end:

    1. the module REFUSES — non-zero exit, a named message on stderr, and **no stdout**
       (a partial stdout would be parsed as a reply);
    2. the module forwards a reply the REAL `_parse_check` rejects — `{"error": ...}` is
       a legitimate protocol reply and is forwarded verbatim by design.

    What is NOT acceptable is an exception escaping `main` (the test would error rather
    than fail), or a `Check` being produced from a shape the contract does not name.
    """
    runner = _runner_returning(_envelope(reply), returncode=returncode)
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    if code == 0:
        assert _parse_check(captured.out) is None, (
            "a malformed author reply must never parse into a Check; "
            f"stdout was {captured.out[:400]!r}"
        )
    else:
        assert captured.out == "", (
            "a refusal must write NOTHING to stdout — partial output is parsed as a "
            f"reply; got {captured.out[:400]!r}"
        )
        assert captured.err.strip() != "", "a refusal must name its cause on stderr"


# --- A7 — the 1 MiB cap ---------------------------------------------------------------


def test_oversized_output_does_not_hang(monkeypatch, capsys):
    """A reply past `author._MAX_OUTPUT` (1 MiB) is handled, and never half-parsed.

    `SubprocessAuthor` truncates the author's stdout at 1 MiB *before* parsing
    (`author.py:53, 118`), so an oversized reply arrives at `_parse_check` cut mid-token.
    The module must either refuse it outright or emit it — and in both cases Belay must
    end up with NO check rather than a check reconstructed from a truncated payload.

    The test completing at all is the "does not hang" assertion: there is no real child,
    no clock and no network in this path, so a module that blocked would never return.
    """
    oversized = "x" * (_MAX_OUTPUT + 4096)
    runner = _runner_returning(_envelope(json.dumps({"source": oversized, "argv": CHECK_ARGV})))
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert isinstance(code, int), "main must return an exit code, not hang"

    if code == 0:
        truncated = captured.out.encode("utf-8")[:_MAX_OUTPUT].decode("utf-8", errors="replace")
        assert _parse_check(truncated) is None, (
            "an over-cap reply must not survive Belay's 1 MiB truncation as a Check"
        )
    else:
        assert captured.out == "", captured.out
        assert captured.err.strip() != "", "a refusal must name its cause on stderr"


# --- A8 — zero third-party dependencies -----------------------------------------------


def test_module_imports_no_third_party_package():
    """Every import in the module is stdlib or first-party `belay`.

    The technique is `tests/test_verify_zero_llm.py:103-129`: `ast.walk` over the source,
    never an import of it, so an import nested inside a function counts too and the guard
    reports on the source that ships rather than on this venv. The module lives under
    `src/belay/verify/`, which that guard already scans for inference clients — this one
    is the stricter, module-scoped statement of the zero-runtime-dependency contract.
    """
    path = _module_path()
    tree = ast.parse(path.read_bytes(), filename=str(path))

    roots: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend((alias.name.split(".")[0], node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                roots.append((node.module.split(".")[0], node.lineno))

    assert roots, f"{path} imports nothing — this guard would pass vacuously"

    offenders = [
        f"{path.name}:{lineno} imports {root!r}"
        for root, lineno in roots
        if root not in sys.stdlib_module_names and root != "belay"
    ]
    assert not offenders, (
        "the reference claim author must import stdlib or first-party belay only — the "
        "zero-runtime-dependency contract is non-negotiable:\n  " + "\n  ".join(offenders)
    )


# --- §2 — diagnostics never touch stdout ----------------------------------------------


@pytest.mark.parametrize(
    ("runner_factory", "case"),
    [
        pytest.param(
            lambda: _runner_raising(FileNotFoundError("claude")),
            "spawn-failure",
            id="spawn-failure",
        ),
        pytest.param(
            lambda: _runner_raising(subprocess.TimeoutExpired("claude", 600.0)),
            "timeout",
            id="timeout",
        ),
        pytest.param(
            lambda: _runner_returning("this is not an envelope {"),
            "unparseable-envelope",
            id="unparseable-envelope",
        ),
    ],
)
def test_diagnostics_go_to_stderr_never_stdout(runner_factory, case, monkeypatch, capsys):
    """On every failure path stdout stays EMPTY and the cause is named on stderr.

    This is the quietest way to break A3: `SubprocessAuthor` parses the author's stdout
    as exactly one JSON object, so a stray `print()` of a diagnostic makes `_parse_check`
    fail on a run that would otherwise have produced a check — the axis silently stops
    working and nothing says so. A non-zero exit with the message on stderr is read as
    `NO_CHECK_AUTHOR`, which is honest.
    """
    runner = runner_factory()
    code, captured = _run_main(monkeypatch, capsys, runner=runner)

    assert code != 0, f"{case} must be a refusal"
    assert captured.out == "", f"{case} wrote to stdout: {captured.out[:400]!r}"
    assert captured.err.strip() != "", f"{case} must name its cause on stderr"
