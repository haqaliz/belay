"""The quickstart install path is the LIVE PyPI channel — docs claims are machine-checked.

Aspect `quickstart-flip` (`docs/planning/pypi-publish/quickstart-flip/`). The
`belay-harness` package has been live on PyPI since 0.1.0 (2026-07-18), so the
README's install block must name the real distribution (`belay-harness`, the
`belay` command) and must not carry the stale "until then, run from source"
caveat. The distribution name and CLI entrypoint are the truth held by
`pyproject.toml`; the README, RELEASING.md, and the stranger-timing runbook must
agree with it. Every assertion is a deterministic string/parse check on
committed docs — no network, no clock.

The `stranger-timing` runbook-consistency test is live: it asserts the runbook
exists and that its install command equals the README's headline install command.
"""

from __future__ import annotations

import re
from pathlib import Path

_RUNBOOK = "docs/planning/pypi-publish/stranger-timing/runbook.md"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    """Return the UTF-8 text of a repo-root-relative file."""
    return (_repo_root() / rel).read_text(encoding="utf-8")


def _install_block_region() -> str:
    """The README lines immediately around the headline `uv tool install` command."""
    lines = _read("README.md").splitlines()
    install_idx = next(
        i for i, line in enumerate(lines) if line.strip().startswith("uv tool install")
    )
    return "\n".join(lines[install_idx - 3 : install_idx + 4])


def _headline_install_command() -> str:
    """The README's headline install command, comments stripped, whitespace-folded."""
    readme = _read("README.md")
    line = next(
        line for line in readme.splitlines() if line.strip().startswith("uv tool install")
    )
    return line.strip().split("#")[0].strip()


def test_readme_has_no_run_from_source_install_caveat() -> None:
    """The quickstart must not tell a stranger the package is unpublished."""
    readme = _read("README.md")
    assert "until then, run from source" not in readme
    assert "once v0.1.0 is published" not in readme


def test_readme_install_commands_name_the_real_distribution() -> None:
    """The install block names the real dist (`belay-harness`) and the `belay` command."""
    region = _install_block_region()
    assert "belay-harness" in region
    assert "belay --help" in region
    assert "the command is `belay`" in region


def test_readme_and_releasing_agree_on_the_distribution_name() -> None:
    """README and RELEASING.md name the same PyPI distribution."""
    assert "belay-harness" in _read("README.md")
    assert "belay-harness" in _read("RELEASING.md")


def test_pyproject_distribution_name_matches_readme_claims() -> None:
    """pyproject.toml is the truth: `name = "belay-harness"` + a `belay` script entry."""
    pyproject = _read("pyproject.toml")
    name_match = re.search(r'^name = "([^"]+)"', pyproject, re.MULTILINE)
    assert name_match is not None, "pyproject.toml carries no project name"
    assert name_match.group(1) == "belay-harness"
    script_match = re.search(
        r'^\[project\.scripts\]\s*\n\s*belay\s*=\s*"[^"]+"', pyproject, re.MULTILINE
    )
    assert script_match is not None, "pyproject.toml declares no `belay` script entry"


def test_stranger_timing_runbook_install_command_matches_readme() -> None:
    """The runbook's install command must equal the README headline command.

    Cross-aspect consistency with `stranger-timing`: a stranger following the
    runbook must install the same way the README's quickstart does. Live since
    the stranger-timing runbook landed — the runbook must exist, and its install
    command must equal the README's headline install command verbatim.
    """
    assert (_repo_root() / _RUNBOOK).exists(), (
        f"{_RUNBOOK} does not exist — the stranger-timing aspect must create it"
    )
    lines = _read(_RUNBOOK).splitlines()
    runbook_cmd = next(
        line for line in lines if line.strip().startswith("uv tool install")
    )
    assert runbook_cmd.strip().split("#")[0].strip() == _headline_install_command()
