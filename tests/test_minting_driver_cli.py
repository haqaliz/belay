"""The argv surface of the mint: `python -m eval.minting_driver {one,batch}`.

This is the phase that authorizes live spend, so what is asserted here is mostly about
what CANNOT happen by accident:

* `--root` has **no default** — a default root is how two mints silently share one batch
  directory, and the second one's bridge either collides or contaminates the first's
  denominator;
* `--request-timeout` defaults to the mint's 120s, never the transport's 10s (which a
  live model turn plus a cold `node` start under Seatbelt does not fit into);
* `--provider` is an explicit argument with an explicit default, so no key in the
  operator's shell can change which model mints;
* `--model` has **no default at all** — the old `gemini-flash-latest` default was
  measured minting nothing (`STAGE2_FINDINGS.md:25-39`), which publishes a 0% violation
  rate that means "the agent did nothing";
* a missing server install exits 2 with the `npm install` command on stderr, not a
  traceback and not an hour of contained per-instance failures; and
* importing the CLI does **not** import `belay` — `eval/` is not a product surface, and
  `belay` is imported lazily, only inside the optional in-process verify.

Everything runs offline: no git, no network, no model call, no spend. The only
subprocess is the `sys.modules` isolation check, which follows the precedent of
`tests/test_minting_driver_clients_import.py`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from eval.minting_driver import transport as transport_module
from eval.minting_driver.cli import build_config, build_parser, main
from eval.minting_driver.entrypoint import (
    DEFAULT_CLONES_DIR,
    DEFAULT_MAX_STEPS,
    DEFAULT_PROVIDER,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_REQUEST_TIMEOUT,
    PROVIDERS,
    MintConfigError,
)
from eval.minting_driver.resilience import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
)
from eval.minting_driver.servers import PINNED_SERVERS

REPO_ROOT = Path(__file__).parent.parent

#: Every argv below names a model, because `--model` is required and has no default.
#: A placeholder id is right here — nothing in this file makes a live call; what is
#: under test is that the operator must *say* which model mints.
TEST_MODEL = "test-pro-model"


def _install_stub_server(server_root: Path, name: str = "filesystem") -> Path:
    """A fake 'installed' server: an empty file at the pinned entrypoint path."""
    entrypoint = server_root / PINNED_SERVERS[name].entrypoint
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("// stub\n", encoding="utf-8")
    return entrypoint


# --------------------------------------------------------------------------------------
# argv -> MintConfig
# --------------------------------------------------------------------------------------


def test_cli_parses_into_a_mint_config(tmp_path: Path) -> None:
    """The defaults an operator gets when they type the documented command.

    `--root` and `--model` are not among them: both are required, so the shortest legal
    argv already names them.
    """
    cfg = build_config(
        [
            "one",
            "octo__repo-1",
            "--root",
            str(tmp_path / "stage1"),
            "--model",
            TEST_MODEL,
        ]
    )

    assert cfg.root == tmp_path / "stage1"
    assert cfg.checkpoint_path == tmp_path / "stage1" / "checkpoint.json"
    assert cfg.batch_dir == tmp_path / "stage1" / "batch"
    # The defaults are relative constants, resolved once at the config boundary — every
    # consumer is a child process with a CWD of its own.
    assert cfg.registry_path == DEFAULT_REGISTRY_PATH.resolve()
    assert cfg.clones_dir == DEFAULT_CLONES_DIR.resolve()
    assert cfg.provider == DEFAULT_PROVIDER
    # The model is whatever argv said — there is no `DEFAULT_MODEL` to compare against
    # any more, and that absence is the point (see `test_cli_requires_an_explicit_model`).
    assert cfg.model == TEST_MODEL
    assert cfg.request_timeout == DEFAULT_REQUEST_TIMEOUT
    assert cfg.max_steps == DEFAULT_MAX_STEPS
    assert cfg.server_root is None
    # The retry budget defaults to `resilience.py`'s, IMPORTED not restated — a second
    # copy of the number here would let the documented and the built default drift.
    assert cfg.max_attempts == DEFAULT_MAX_ATTEMPTS
    assert cfg.retry_base_delay == DEFAULT_BASE_DELAY_SECONDS


def test_cli_overrides_every_config_field(tmp_path: Path) -> None:
    """Each flag reaches the config it names — including the batch subcommand."""
    cfg = build_config(
        [
            "batch",
            "--root",
            str(tmp_path / "stage3"),
            "--registry",
            str(tmp_path / "selected.json"),
            "--clones-dir",
            str(tmp_path / "clones"),
            "--checkpoint",
            str(tmp_path / "elsewhere.json"),
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-4-5",
            "--request-timeout",
            "90",
            "--max-steps",
            "6",
            "--max-attempts",
            "5",
            "--retry-base-delay",
            "0.25",
            "--server-root",
            str(tmp_path / "servers"),
        ]
    )

    assert cfg.root == tmp_path / "stage3"
    assert cfg.registry_path == tmp_path / "selected.json"
    assert cfg.clones_dir == tmp_path / "clones"
    assert cfg.checkpoint_path == tmp_path / "elsewhere.json"
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-4-5"
    assert cfg.request_timeout == 90.0
    assert cfg.max_steps == 6
    assert cfg.max_attempts == 5
    assert cfg.retry_base_delay == 0.25
    assert cfg.server_root == tmp_path / "servers"


def test_cli_resolves_every_path_flag_to_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relative path flags become absolute before anything is spawned.

    Defense in depth for the bug the live Stage-1 mint hit: a relative `--root` was
    handed to `git -C <bare_clone> worktree add`, which resolved it against the clone.
    Any relative path handed to a sandboxed child process (a server's `allowed_dir`,
    `BELAY_SANDBOX_SCOPE`, the snapshot root) is the same footgun.
    """
    monkeypatch.chdir(tmp_path)

    cfg = build_config(
        [
            "batch",
            "--root",
            "mint/stage1",
            "--model",
            TEST_MODEL,
            "--registry",
            "reg/selected.json",
            "--clones-dir",
            "clones",
            "--checkpoint",
            "ck.json",
            "--server-root",
            "servers",
        ]
    )

    for path in (
        cfg.root,
        cfg.registry_path,
        cfg.clones_dir,
        cfg.checkpoint_path,
        cfg.server_root,
        cfg.batch_dir,
    ):
        assert path is not None and path.is_absolute(), path

    assert cfg.root == tmp_path / "mint" / "stage1"
    assert cfg.checkpoint_path == tmp_path / "ck.json"
    assert cfg.batch_dir == tmp_path / "mint" / "stage1" / "batch"


def test_cli_resolves_the_verify_output_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--ledger` and `--corpus-dir` reach `run_verify` absolute, too."""
    from eval.minting_driver import cli as cli_module
    from eval.minting_driver.checkpoint import Checkpoint
    from eval.minting_driver.entrypoint import MintReport

    _install_stub_server(tmp_path / "servers")
    seen: dict = {}

    def fake_mint_one(instance_id: str, cfg: object, **seams: object) -> MintReport:
        return MintReport(
            batch_dir=tmp_path / "mint" / "batch",
            checkpoint_path=tmp_path / "mint" / "checkpoint.json",
            checkpoint=Checkpoint(),
            instance_ids=(instance_id,),
            counts={"captured": 1, "failed": 0},
            verify_command="belay phase0 run ...",
        )

    def fake_run_verify(report: MintReport, **kwargs: object) -> int:
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli_module, "mint_one", fake_mint_one)
    monkeypatch.setattr(cli_module, "run_verify", fake_run_verify)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "one",
            "octo__repo-1",
            "--root",
            "mint",
            "--model",
            TEST_MODEL,
            "--server-root",
            "servers",
            "--ledger",
            "runs/phase0.json",
            "--corpus-dir",
            "corpus/local",
            "--verify",
        ]
    )

    assert code == 0
    assert seen["ledger_path"] == tmp_path / "runs" / "phase0.json"
    assert seen["corpus_dir"] == tmp_path / "corpus" / "local"


def test_cli_default_request_timeout_is_not_the_transport_default() -> None:
    """The 10s ceiling is unreachable from the command line, and `None` is unspellable."""
    parser = build_parser()
    args = parser.parse_args(["batch", "--root", "r", "--model", TEST_MODEL])

    assert isinstance(args.request_timeout, float)
    assert args.request_timeout == DEFAULT_REQUEST_TIMEOUT
    assert args.request_timeout != transport_module.DEFAULT_TIMEOUT

    # `--request-timeout none` is a parse error, not a silent fall-through to 10s.
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["batch", "--root", "r", "--model", TEST_MODEL, "--request-timeout", "none"]
        )


def test_cli_requires_root(capsys: pytest.CaptureFixture[str]) -> None:
    """No implicit `--root`: a default root is how two mints share one batch dir."""
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["batch"])
    assert excinfo.value.code != 0
    assert "--root" in capsys.readouterr().err


def test_cli_requires_an_explicit_model(capsys: pytest.CaptureFixture[str]) -> None:
    """No implicit `--model`: the default was `gemini-flash-latest`, and it is known-bad.

    `STAGE2_FINDINGS.md:25-39` measured it: two flash-class models hit the step cap doing
    **only reads and searches** on `pallets__flask-4045` and never edited anything. An
    agent that never mutates produces turns that all verify clean, so the mint publishes a
    **0% violation rate that means "the agent did nothing"** — worse than
    `INSTRUMENT SUSPECT`, because it *looks like a result* and the pre-registered gate
    would read it as a PIVOT on a premise that was never tested. Naming the model is also
    what makes the published number attributable (`prd.md:153-155`).

    Exit 2, from argparse itself, before a workspace is prepped or a token is spent —
    the same code `MintConfigError` / `MissingCredentialsError` / `MissingServerError`
    exit with in `main`.
    """
    for argv in (["batch", "--root", "r"], ["one", "octo__repo-1", "--root", "r"]):
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(argv)
        assert excinfo.value.code == 2
        assert "--model" in capsys.readouterr().err


def test_cli_help_renders_for_every_subcommand() -> None:
    """`--help` must actually format — argparse `%`-expands every help string.

    Not hypothetical: the `--model` help quotes Stage 2's *"0% violation rate"*, and a
    bare `%` in a help string makes `--help` die with
    `ValueError: unsupported format character` instead of printing. `--help` is the
    documented authority on the flags (`eval/README.md`), and it is what an operator
    reaches for at exactly the moment they are least able to debug argparse.
    """
    parser = build_parser()

    for argv in (["one", "--help"], ["batch", "--help"], ["--help"]):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(argv)  # formats and prints the help, then exits 0
        assert excinfo.value.code == 0


def test_cli_retry_knobs_are_typed_and_bounded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--max-attempts` / `--retry-base-delay` are refused at config time, not mid-mint.

    Both are consumed hours into a live run — `max_attempts` on the first 429,
    `retry_base_delay` in a `time.sleep` inside the very handler that exists to keep the
    mint alive. A bad value must fail before a byte is spent, and it must fail as a
    named `MintConfigError` (exit 2, one line) rather than as a traceback.
    """
    parser = build_parser()

    # Non-numeric is an argparse type error, like `--request-timeout none`.
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["batch", "--root", "r", "--model", TEST_MODEL, "--max-attempts", "lots"]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["batch", "--root", "r", "--model", TEST_MODEL, "--retry-base-delay", "soon"]
        )

    # `1` is the honest spelling of "no retries"; `0` would never call the model at all.
    with pytest.raises(MintConfigError, match="max_attempts"):
        build_config(
            [
                "batch",
                "--root",
                str(tmp_path / "m"),
                "--model",
                TEST_MODEL,
                "--max-attempts",
                "0",
            ]
        )

    # `0` seconds is legitimate (retry immediately); negative is not — `time.sleep`
    # would raise from inside the quota handler, hours in.
    zero_delay = build_config(
        [
            "batch",
            "--root",
            str(tmp_path / "m"),
            "--model",
            TEST_MODEL,
            "--retry-base-delay",
            "0",
        ]
    )
    assert zero_delay.retry_base_delay == 0.0
    with pytest.raises(MintConfigError, match="retry_base_delay"):
        build_config(
            [
                "batch",
                "--root",
                str(tmp_path / "m"),
                "--model",
                TEST_MODEL,
                "--retry-base-delay",
                "-1",
            ]
        )

    # And through `main`, a bad value is exit 2 with one legible line.
    code = main(
        [
            "batch",
            "--root",
            str(tmp_path / "mint"),
            "--model",
            TEST_MODEL,
            "--server-root",
            str(tmp_path / "servers"),
            "--max-attempts",
            "0",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "max_attempts" in captured.err
    assert "Traceback" not in captured.err


def test_cli_rejects_an_unknown_provider(capsys: pytest.CaptureFixture[str]) -> None:
    """The provider is a closed set, checked by argparse before anything runs."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["batch", "--root", "r", "--model", TEST_MODEL, "--provider", "openai"]
        )
    assert "openai" in capsys.readouterr().err


def test_cli_accepts_the_claude_cli_provider(tmp_path: Path) -> None:
    """`--provider claude-cli` parses and reaches the config — with NO edit to `cli.py`.

    The flag's `choices=list(PROVIDERS)` is what makes registering a provider in
    `entrypoint.py` register its CLI value too. Asserted because "no edit was needed" is a
    claim about this parser, and the way it stops being true is a future refactor that
    hard-codes the two original names back into the `choices` list.

    Every registered provider is walked, so the same slip on any of them fails here.
    """
    for provider in PROVIDERS:
        cfg = build_config(
            [
                "batch",
                "--root",
                str(tmp_path / provider),
                "--model",
                TEST_MODEL,
                "--provider",
                provider,
            ]
        )
        assert cfg.provider == provider

    assert "claude-cli" in PROVIDERS


# --------------------------------------------------------------------------------------
# main() — exit codes and messages
# --------------------------------------------------------------------------------------


def test_cli_missing_servers_exits_with_the_install_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A forgotten `npm install` is exit 2 and one legible line — never a traceback,
    and never 65 contained failures that read as INSTRUMENT SUSPECT an hour later."""
    code = main(
        [
            "batch",
            "--root",
            str(tmp_path / "mint"),
            "--model",
            TEST_MODEL,
            "--server-root",
            str(tmp_path / "servers"),
            "--registry",
            str(tmp_path / "selected.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "npm install" in captured.err
    assert "@modelcontextprotocol/server-filesystem@2026.7.10" in captured.err
    assert "Traceback" not in captured.err


def test_cli_missing_registry_exits_two_naming_the_instance_pool_aspect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An absent selection file is a named exit-2 message, not a traceback."""
    _install_stub_server(tmp_path / "servers")

    code = main(
        [
            "batch",
            "--root",
            str(tmp_path / "mint"),
            "--model",
            TEST_MODEL,
            "--server-root",
            str(tmp_path / "servers"),
            "--registry",
            str(tmp_path / "nope.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "instance-pool" in captured.err
    assert "Traceback" not in captured.err


def test_cli_prints_the_verify_command_on_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finished mint always prints the reproduce-the-number command.

    The mint itself is a live observation and is not reproducible; the ledger -> report
    path is. This printed line is what makes the second half true, so it is asserted at
    the argv surface rather than only at the library one.
    """
    from eval.minting_driver import cli as cli_module
    from eval.minting_driver.entrypoint import WORKSPACE_PLACEHOLDER, MintReport
    from eval.minting_driver.checkpoint import Checkpoint

    entrypoint = _install_stub_server(tmp_path / "servers")

    def fake_mint_one(instance_id: str, cfg: object, **seams: object) -> MintReport:
        return MintReport(
            batch_dir=Path("b"),
            checkpoint_path=Path("c"),
            checkpoint=Checkpoint(),
            instance_ids=(instance_id,),
            counts={"captured": 1, "failed": 0},
            verify_command=f"belay phase0 run b --server node x '{WORKSPACE_PLACEHOLDER}'",
        )

    monkeypatch.setattr(cli_module, "mint_one", fake_mint_one)

    code = main(
        [
            "one",
            "octo__repo-1",
            "--root",
            str(tmp_path / "mint"),
            "--model",
            TEST_MODEL,
            "--server-root",
            str(tmp_path / "servers"),
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "belay phase0 run" in out
    assert WORKSPACE_PLACEHOLDER in out
    assert entrypoint.is_file()


# --------------------------------------------------------------------------------------
# Guardrails: `eval/` is not a product surface
# --------------------------------------------------------------------------------------


def test_cli_module_imports_without_belay_installed() -> None:
    """Importing the CLI must not pull `belay` in — it is imported lazily, only inside
    the optional in-process verify. Checked in a fresh interpreter because `sys.modules`
    state leaks across tests in a shared process."""
    code = (
        "import eval.minting_driver.cli\n"
        "import sys\n"
        "assert 'belay' not in sys.modules, 'belay leaked into the eval CLI import graph'\n"
        "assert 'belay.phase0.runner' not in sys.modules\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout


def test_no_belay_subcommand_is_registered(capsys: pytest.CaptureFixture[str]) -> None:
    """The guardrail, asserted rather than trusted: the mint is NOT a `belay` command.

    `eval/` is evaluation machinery, not a product surface (`CLAUDE.md` guardrail #1).
    """
    from belay import cli as belay_cli

    with pytest.raises(SystemExit):
        belay_cli.main(["--help"])
    help_text = capsys.readouterr().out

    assert "mint" not in help_text


def test_eval_package_declares_no_console_script() -> None:
    """No `[project.scripts]` entry point may expose the mint as an installed command."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = pyproject.split("[project.scripts]")[1].split("\n[")[0]

    assert "eval" not in scripts
    assert "mint" not in scripts


def test_main_module_is_wired_for_python_dash_m() -> None:
    """`python -m eval.minting_driver` resolves to the CLI's `main` — the documented
    command actually exists, rather than being a README aspiration."""
    import eval.minting_driver.__main__ as main_module

    assert main_module.main is main


def test_verify_flag_runs_the_batch_in_process_with_the_placeholder_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--verify` scores the mint it just produced, with the SAME command it printed.

    The server command is the static `node <abs entrypoint> {workspace}` one — the
    placeholder is substituted per trace with that trace's own recorded `source_root`,
    so one command verifies a batch captured from many workspaces.
    """
    from eval.minting_driver import cli as cli_module
    from eval.minting_driver.checkpoint import Checkpoint
    from eval.minting_driver.entrypoint import WORKSPACE_PLACEHOLDER, MintReport

    entrypoint = _install_stub_server(tmp_path / "servers")
    seen: dict = {}

    def fake_mint_one(instance_id: str, cfg: object, **seams: object) -> MintReport:
        return MintReport(
            batch_dir=tmp_path / "mint" / "batch",
            checkpoint_path=tmp_path / "mint" / "checkpoint.json",
            checkpoint=Checkpoint(),
            instance_ids=(instance_id,),
            counts={"captured": 1, "failed": 0},
            verify_command="belay phase0 run ...",
        )

    def fake_run_verify(report: MintReport, **kwargs: object) -> int:
        seen["batch_dir"] = report.batch_dir
        seen["server_command"] = kwargs["server_command"]
        return 0

    monkeypatch.setattr(cli_module, "mint_one", fake_mint_one)
    monkeypatch.setattr(cli_module, "run_verify", fake_run_verify)

    code = main(
        [
            "one",
            "octo__repo-1",
            "--root",
            str(tmp_path / "mint"),
            "--model",
            TEST_MODEL,
            "--server-root",
            str(tmp_path / "servers"),
            "--verify",
        ]
    )

    assert code == 0
    assert seen["batch_dir"] == tmp_path / "mint" / "batch"
    assert seen["server_command"] == ["node", str(entrypoint), WORKSPACE_PLACEHOLDER]
