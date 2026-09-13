"""The gate's quickstart surface is machine-checked — the README's claims parse.

Aspect `surface-docs` (`docs/planning/ci-regression-gate/surface-docs/`). The
ci-regression-gate ships as `belay gate baseline` / `belay gate check`; a
stranger must be able to wire it into CI from the README alone, so the
quickstart section's commands are asserted to exist in the CLI, the documented
exit-code table (0/1/2) is asserted to equal the implementation's mapping, the
`--help` texts of both gate subcommands state the stored-policy rule and the
honest coverage line, and the published Phase-0 numbers stay byte-unchanged
wherever they appear in the files this unit touches. Every assertion is a
deterministic string/parse check on committed files — no network, no clock, no
replay.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
from pathlib import Path

import pytest

from belay import cli
from belay.gate.compare import CLEAN, PREFLIGHT, REGRESSION

#: The four frozen published numbers. The guard's job: this unit edits prose
#: around them and must never move them — and README.md carries only the
#: 11/60 = 18.3% headline, so the other three must stay absent there.
_FROZEN_NUMBERS = ("11/60 = 18.3%", "precision 0.00", "1/15", "4/16")
_TOUCHED_DOCS = (
    "README.md",
    "docs/STATUS.md",
    "CLAUDE.md",
    "docs/planning/launch-readiness/CHECKLIST.md",
)
_GATE_STEP_HEADER = "### 4 · Gate your agent upgrades"
_MEASURE_HEADER = "### 5 · Measure at scale — the violation rate"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    """Return the UTF-8 text of a repo-root-relative file."""
    return (_repo_root() / rel).read_text(encoding="utf-8")


def _gate_section() -> str:
    """The README's gate quickstart step, from its header to the next `### ` header.

    Returns "" when the step does not exist yet, so the failing assertions
    name the missing content rather than erroring on extraction.
    """
    lines = _read("README.md").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(_GATE_STEP_HEADER)]
    if not starts:
        return ""
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _gate_commands(section: str) -> list[tuple[str, str]]:
    """Every `belay gate <subcommand>` invocation in the section's fenced blocks."""
    commands: list[tuple[str, str]] = []
    for block in re.finditer(r"```[^\n]*\n(.*?)```", section, re.DOTALL):
        for line in block.group(1).splitlines():
            for match in re.finditer(r"\bbelay gate (\S+)", line):
                commands.append(("gate", match.group(1)))
    return commands


def _gate_help(sub: str) -> str:
    """The rendered `belay gate <sub> --help` text, argparse's actual output."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["gate", sub, "--help"])
    assert excinfo.value.code == 0
    return buf.getvalue()


def test_gate_quickstart_step_exists_and_keeps_the_existing_steps() -> None:
    """The quickstart carries the gate step, and the measure step renumbers to fit."""
    readme = _read("README.md")
    assert _GATE_STEP_HEADER in readme
    assert _MEASURE_HEADER in readme
    section = _gate_section()
    assert "BELAY_RUN_ID" in section
    assert "baselines/local" in section
    assert "never fail the gate alone" in section


def test_gate_quickstart_commands_parse_through_the_cli() -> None:
    """Every `belay gate …` command in the section exists in the CLI's argparse."""
    commands = _gate_commands(_gate_section())
    assert commands, "the gate quickstart section carries no `belay gate` command"
    parser: argparse.ArgumentParser = cli._parser()
    for subcommand in sorted({sub for _, sub in commands}):
        namespace, _ = parser.parse_known_args(["gate", subcommand, "unused-trace.jsonl"])
        assert namespace.action == subcommand


def test_gate_quickstart_exit_codes_match_the_implementation() -> None:
    """The README's exit-code table equals `compare.py`'s reasons and `cli.py`'s codes.

    The table rows render the reason bolded in the second cell; the reasons must
    be exactly the compare module's `clean`/`regression`/`preflight`, and the
    codes 0/1/2 must be the mapping the CLI dispatches on.
    """
    table: dict[int, str] = {}
    for line in _gate_section().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].isdigit():
            reason = re.match(r"\*\*(\w+)\*\*", cells[1])
            assert reason is not None, f"exit-code row lacks a bolded reason: {line!r}"
            table[int(cells[0])] = reason.group(1)
    assert table == {0: CLEAN, 1: REGRESSION, 2: PREFLIGHT}
    mapping = re.search(
        r'\{"clean": 0, "regression": 1, "preflight": 2\}', _read("src/belay/cli.py")
    )
    assert mapping is not None, "the CLI's exit mapping literal is missing from cli.py"


def test_gate_check_help_states_the_stored_policy_and_the_coverage_line() -> None:
    """`gate check --help` names the stored-policy rule and the honest coverage line."""
    help_text = _gate_help("check")
    assert "deliberately no --invariants" in help_text
    assert "re-banks with `belay gate baseline`" in help_text
    assert "crosses the MCP boundary" in help_text
    assert "never fail the gate alone" in help_text


def test_gate_baseline_help_mentions_run_identity_and_the_coverage_line() -> None:
    """`gate baseline --help` names BELAY_RUN_ID/--run-id and the coverage line."""
    help_text = _gate_help("baseline")
    assert "BELAY_RUN_ID" in help_text
    assert "--run-id" in help_text
    assert "crosses the MCP boundary" in help_text
    assert "never fail the gate alone" in help_text


def test_published_numbers_stay_byte_unchanged_in_touched_files() -> None:
    """The four frozen figures read byte-identical wherever they appear in the files
    this unit touches — and stay absent where they were absent (README carries only
    the 11/60 = 18.3% headline)."""
    for rel in _TOUCHED_DOCS:
        text = _read(rel)
        for figure in _FROZEN_NUMBERS:
            if rel == "README.md" and figure != "11/60 = 18.3%":
                assert figure not in text, f"{rel} must not gain {figure!r}"
            else:
                assert figure in text, f"{figure!r} missing from {rel}"