"""The root `action.yml` is the gate's CI wrapper, and its argv order is a contract.

`--server` is a REMAINDER: every token after it is the server's own argv. A flag
written after `--server` is therefore silently misread — the defect class that has
already bitten this CLI twice — so the Action builds its argv as a bash array and
this module asserts the order structurally, from the parsed YAML, not by grepping
prose.

No network, no Docker, no subprocess: this reads a file in the repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ACTION = _REPO_ROOT / "action.yml"

#: The declared inputs and whether each is required. `trace` is the only one the
#: caller must give: the baseline dir is CWD-relative and the stored policy supplies
#: everything else.
_INPUTS = {
    "trace": True,
    "run-id": False,
    "server": False,
    "strict-shape": False,
    "version": False,
}

#: Flags that would let a caller re-resolve policy. `gate check` deliberately has
#: none of them (the policy is the banked one), so the Action must not invent them.
_FORBIDDEN_FLAGS = ("--invariants", "--replays", "--timeout")


def _action() -> dict[str, Any]:
    assert _ACTION.is_file(), f"{_ACTION} is missing"
    loaded = yaml.safe_load(_ACTION.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{_ACTION} did not parse as a mapping"
    return loaded


def _steps() -> list[dict[str, Any]]:
    runs = _action().get("runs")
    assert isinstance(runs, dict), "action.yml declares no runs block"
    steps = runs.get("steps")
    assert isinstance(steps, list) and steps, "action.yml declares no steps"
    return steps


def _run_text(step: dict[str, Any]) -> str:
    run = step.get("run")
    return run if isinstance(run, str) else ""


def _gate_script() -> str:
    hits = [step for step in _steps() if "gate check" in _run_text(step)]
    assert len(hits) == 1, f"expected one `gate check` step, found {len(hits)}"
    return _run_text(hits[0])


def test_the_action_is_composite_and_declares_exactly_the_inputs() -> None:
    action = _action()
    runs = action["runs"]
    assert runs.get("using") == "composite", runs.get("using")
    inputs = action.get("inputs")
    assert isinstance(inputs, dict), "action.yml declares no inputs"
    assert set(inputs) == set(_INPUTS), sorted(inputs)
    required = {name for name, spec in inputs.items() if spec.get("required")}
    assert required == {"trace"}, required
    assert "outputs" not in action, "the exit code is the contract; no outputs"


def test_every_input_is_referenced_and_none_is_required_but_trace() -> None:
    text = _ACTION.read_text(encoding="utf-8")
    for name in _INPUTS:
        assert f"inputs.{name}" in text, f"input {name!r} is declared but never used"


def test_the_gate_step_never_asks_for_stored_policy_flags() -> None:
    text = _ACTION.read_text(encoding="utf-8")
    for flag in _FORBIDDEN_FLAGS:
        assert flag not in text, f"the Action passes {flag}, but the policy is the banked one"


def test_strict_shape_is_conditional_and_precedes_server() -> None:
    script = _gate_script()
    strict_lines = [line for line in script.splitlines() if "--strict-shape" in line]
    assert strict_lines, "the gate step never passes --strict-shape"
    assert len(strict_lines) == 1, strict_lines
    line = strict_lines[0]
    assert '"$STRICT" = "true"' in line, f"--strict-shape is not conditional: {line!r}"

    assert "--server" in script
    assert script.index("--strict-shape") < script.index("--server"), (
        "--strict-shape is written after --server, which is a remainder and would "
        "swallow it into the server's argv"
    )


def test_the_script_fails_fast() -> None:
    assert "set -euo pipefail" in _gate_script()
