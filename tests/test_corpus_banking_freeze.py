"""The corpus-banking post-run recompute invocations are frozen before they run.

`docs/planning/phase0-corpus-mint/corpus-banking/spec.md` (deterministic seam): the
exact `corpus run` / `corpus score` commands are committed containing no result and
pinned here by shape, so the recompute cannot be mis-invoked after the run. The
invocations are parsed by the REAL `belay` parser — a flag the CLI does not carry
(the plan once named `--corpus-dir` and `--server`, neither of which `corpus run`
has) fails here rather than at run time.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from belay.cli import _parser

BANKING = (
    Path(__file__).resolve().parents[1]
    / "docs/planning/phase0-corpus-mint/corpus-banking"
)
CORPUS_RUN = BANKING / "acceptance-cm-run2-corpus-run.sh"
CORPUS_SCORE = BANKING / "acceptance-cm-run2-corpus-score.sh"

# Result shapes a frozen script must never contain (the mint-run freeze check).
_RESULT_SHAPES = re.compile(
    r"VERIFIED_|INSTRUMENT|NO_VERIFIABLE|STOPPED|\bMATCH\b|REGRESSION\b|\bPASS\b|\bFAIL\b"
)


def _belay_invocations(script: Path) -> list[list[str]]:
    """Every `uv run belay …` command in the script, continuation lines joined."""
    joined = script.read_text().replace("\\\n", " ")
    return [
        shlex.split(line.strip())[3:]
        for line in joined.splitlines()
        if line.strip().startswith("uv run belay ")
    ]


def _code_lines(script: Path) -> str:
    return "\n".join(
        line for line in script.read_text().splitlines() if not line.lstrip().startswith("#")
    )


@pytest.mark.parametrize("script", [CORPUS_RUN, CORPUS_SCORE], ids=lambda p: p.name)
def test_frozen_script_contains_no_result(script: Path) -> None:
    assert not _RESULT_SHAPES.search(script.read_text())


@pytest.mark.parametrize("script", [CORPUS_RUN, CORPUS_SCORE], ids=lambda p: p.name)
def test_frozen_script_fails_fast(script: Path) -> None:
    assert "set -euo pipefail" in script.read_text()


def test_corpus_run_recomputes_the_holder_corpus_with_the_shell_server() -> None:
    (argv,) = _belay_invocations(CORPUS_RUN)
    args = _parser().parse_args(argv)
    assert args.corpus_dir == "$HOLDER/corpus-local"
    # Without it a two-boundary trajectory case SKIPs with a named cause
    # (corpus-shell-routing) — the placement this seam exists to prevent losing.
    assert args.shell_server == "node $SHELL_SERVER"
    assert args.no_claim_axis is False


def test_corpus_run_names_the_same_shell_server_the_mint_used() -> None:
    code = _code_lines(CORPUS_RUN)
    assert 'HOLDER="$HOME/dev/at/holder/belay"' in code
    assert (
        'SHELL_SERVER="$HOLDER/servers/node_modules/mcp-server-commands/build/index.js"'
        in code
    )


def test_corpus_score_scores_the_same_corpus() -> None:
    (argv,) = _belay_invocations(CORPUS_SCORE)
    args = _parser().parse_args(argv)
    assert argv[:2] == ["corpus", "score"]
    assert args.corpus_dir == "$HOLDER/corpus-local"
    assert 'HOLDER="$HOME/dev/at/holder/belay"' in _code_lines(CORPUS_SCORE)
