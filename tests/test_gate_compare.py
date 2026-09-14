"""The gate's pure decision table: capture-vs-baseline verdict transitions.

The gate is a WORSEN-DETECTOR, not an equality checker. `corpus run` compares one
trace against its own stored expected (exact equality — detector regression); the
gate compares TWO captures of the same run, which legitimately differ in shape. So
the core is a pure decision table over per-dimension status transitions, and this
module pins every transition class EXHAUSTIVELY:

- **REGRESSION (exit 1):** a dimension that was PASS/WARN moves to FAIL — per turn
  ordinal (common ordinals only), the instance-level trajectory status (PASS ->
  FAIL), the claim dimension when the baseline declared one (A3 never PASSes, so a
  stored WARN -> FAIL is the only failing claim transition), and a NEW turn beyond
  the baseline's count that FAILs.
- **Named, reported, NEVER fail (exit 0):** PASS/WARN -> UNVERIFIED (coverage loss,
  R7 discipline), any transition INTO WARN, FAIL -> FAIL (still failing, not newly
  failing), any -> PASS, UNVERIFIED -> anything (an abstention becoming a failure is
  a fix, not a regression), new-turn PASS/WARN/UNVERIFIED, shape divergences (turn
  count, tool rename), and baseline-drift (stored expected vs baseline
  re-verification — engine-change evidence, named, never failing).
- **SKIP (exit 2, rendered UNVERIFIED + named cause):** the baseline cannot be
  re-verified — its re-verification turns are UNVERIFIED with unrestorable causes
  (`BASELINE_UNRESTORABLE`) or the cross-substrate `UNRESTORABLE_CAPABILITY_MISMATCH`
  (`BASELINE_CAPABILITY_MISMATCH`). Never a false clean, never a false regression.

Every row names its dimension with expected->got; the empty comparison is clean.
Pure: no I/O, no replay, no server — plain dicts in, a `GateComparison` out.
"""

from __future__ import annotations

import pytest

from belay.gate.compare import (
    BASELINE_CAPABILITY_MISMATCH,
    BASELINE_UNRESTORABLE,
    Divergence,
    compare,
    compare_claim,
    compare_trajectory,
    compare_verdict_sets,
    shape_divergences,
)


def _turn(n: int, status: str, tool: str = "echo") -> dict:
    return {
        "ordinal": n,
        "tool": tool,
        "status": status,
        "cause": None,
        "sub_verdicts": [],
    }


def _trajectory(status: str) -> dict:
    return {"status": status, "cause": None, "message": f"{status} message"}


def _claim(status: str) -> dict:
    return {
        "axis": "A3",
        "kind": "claim",
        "status": status,
        "cause": None,
        "check": {"source": "the check", "exit_code": 1},
    }


def _set(turns: list[dict], trajectory=None, claim=None) -> dict:
    payload: dict = {"turns": turns, "trajectory": trajectory}
    if claim is not None:
        payload["claim"] = claim
    return payload


# --- 1. REGRESSION rows ---------------------------------------------------------


class TestRegressionRows:
    def test_pass_to_fail_regresses(self):
        expected = _set([_turn(0, "PASS"), _turn(1, "PASS")])
        recomputed = _set([_turn(0, "FAIL"), _turn(1, "PASS")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "regression", result
        assert result.divergences == [Divergence("turn 0 (echo)", "PASS", "FAIL", True)]

    def test_warn_to_fail_regresses(self):
        result = compare("run", _set([_turn(0, "WARN")]), _set([_turn(0, "FAIL")]))
        assert result.exit_reason == "regression", result
        (row,) = result.divergences
        assert row.expected == "WARN" and row.got == "FAIL" and row.regression

    def test_new_failing_turn_is_a_regression(self):
        expected = _set([_turn(0, "PASS")])
        recomputed = _set([_turn(0, "PASS"), _turn(1, "FAIL")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "regression", result
        (row,) = result.divergences
        assert row.dimension == "turn 1 (echo)"
        assert row.expected is None and row.got == "FAIL" and row.regression

    def test_trajectory_pass_to_fail_regresses(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("FAIL"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "regression", result
        (row,) = result.divergences
        assert row.dimension == "trajectory"
        assert row.expected == "PASS" and row.got == "FAIL" and row.regression

    def test_claim_warn_to_fail_regresses_when_declared(self):
        expected = _set([_turn(0, "PASS")], claim=_claim("WARN"))
        recomputed = _set([_turn(0, "PASS")], claim=_claim("FAIL"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "regression", result
        (row,) = result.divergences
        assert row.dimension == "claim"
        assert row.expected == "WARN" and row.got == "FAIL" and row.regression

    def test_claim_declared_fail_on_both_sides_is_not_a_regression(self):
        expected = _set([_turn(0, "PASS")], claim=_claim("FAIL"))
        recomputed = _set([_turn(0, "PASS")], claim=_claim("FAIL"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences == []


# --- 2. Named, reported, NEVER fail -------------------------------------------------


class TestNonFailingRows:
    def test_pass_to_unverified_is_named_not_failing(self):
        result = compare("run", _set([_turn(0, "PASS")]), _set([_turn(0, "UNVERIFIED")]))
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == "PASS" and row.got == "UNVERIFIED" and not row.regression

    def test_warn_to_unverified_is_named_not_failing(self):
        result = compare("run", _set([_turn(0, "WARN")]), _set([_turn(0, "UNVERIFIED")]))
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == "WARN" and row.got == "UNVERIFIED" and not row.regression

    def test_fail_to_fail_is_equality_no_row(self):
        result = compare("run", _set([_turn(0, "FAIL")]), _set([_turn(0, "FAIL")]))
        assert result.exit_reason == "clean", result
        assert result.divergences == []

    def test_pass_to_warn_is_named_not_failing(self):
        result = compare("run", _set([_turn(0, "PASS")]), _set([_turn(0, "WARN")]))
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == "PASS" and row.got == "WARN" and not row.regression

    @pytest.mark.parametrize("expected", ["FAIL", "WARN", "UNVERIFIED"])
    def test_anything_to_pass_is_named_not_failing(self, expected):
        result = compare("run", _set([_turn(0, expected)]), _set([_turn(0, "PASS")]))
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == expected and row.got == "PASS" and not row.regression

    def test_unverified_to_fail_is_a_fix_not_a_regression(self):
        result = compare("run", _set([_turn(0, "UNVERIFIED")]), _set([_turn(0, "FAIL")]))
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == "UNVERIFIED" and row.got == "FAIL" and not row.regression

    def test_unverified_to_warn_is_named_not_failing(self):
        result = compare("run", _set([_turn(0, "UNVERIFIED")]), _set([_turn(0, "WARN")]))
        assert result.exit_reason == "clean", result

    def test_new_turn_pass_warn_unverified_are_shape_not_regression(self):
        expected = _set([_turn(0, "PASS")])
        for status in ("PASS", "WARN", "UNVERIFIED"):
            recomputed = _set([_turn(0, "PASS"), _turn(1, status)])
            result = compare("run", expected, recomputed)
            assert result.exit_reason == "clean", (status, result)
            assert result.divergences == []
            (shape,) = result.shape
            assert shape.kind == "new-turn"
            assert shape.expected is None and shape.got == status

    def test_turn_count_shrink_is_shape_not_regression(self):
        expected = _set([_turn(0, "PASS"), _turn(1, "PASS")])
        recomputed = _set([_turn(0, "PASS")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences == []
        (shape,) = result.shape
        assert shape.kind == "missing-turn"
        assert shape.dimension == "turn 1 (echo)"
        assert shape.expected == "PASS" and shape.got is None

    def test_tool_rename_is_shape_not_regression(self):
        expected = _set([_turn(0, "PASS", tool="echo")])
        recomputed = _set([_turn(0, "PASS", tool="clobber")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences == []
        (shape,) = result.shape
        assert shape.kind == "tool-rename"
        assert shape.dimension == "turn 0"
        assert shape.expected == "echo" and shape.got == "clobber"

    def test_baseline_drift_is_named_never_failing(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        baseline_recomputed = _set([_turn(0, "UNVERIFIED")], trajectory=_trajectory("FAIL"))
        result = compare(
            "run", expected, recomputed, baseline_recomputed=baseline_recomputed
        )
        assert result.exit_reason == "clean", result
        assert result.divergences == []
        assert result.drift == [
            Divergence("turn 0 (echo)", "PASS", "UNVERIFIED", False),
            Divergence("trajectory", "PASS", "FAIL", False),
        ]

    def test_drift_never_changes_the_exit(self):
        expected = _set([_turn(0, "PASS")])
        recomputed = _set([_turn(0, "PASS")])
        baseline_recomputed = _set([_turn(0, "FAIL")])
        result = compare(
            "run", expected, recomputed, baseline_recomputed=baseline_recomputed
        )
        assert result.exit_reason == "clean", result
        assert result.drift != []

    def test_no_drift_when_baseline_replays_identically(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        result = compare(
            "run", expected, recomputed, baseline_recomputed=expected
        )
        assert result.drift == []

    def test_claim_stored_fail_to_unverified_is_reported_not_failing(self):
        expected = _set([_turn(0, "PASS")], claim=_claim("FAIL"))
        recomputed = _set([_turn(0, "PASS")], claim=_claim("UNVERIFIED"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.dimension == "claim"
        assert row.expected == "FAIL" and row.got == "UNVERIFIED" and not row.regression

    def test_claim_declared_but_absent_on_the_capture_is_named_not_failing(self):
        expected = _set([_turn(0, "PASS")], claim=_claim("FAIL"))
        recomputed = _set([_turn(0, "PASS")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.dimension == "claim"
        assert row.expected == "FAIL" and row.got is None and not row.regression

    def test_claim_not_declared_is_not_compared(self):
        expected = _set([_turn(0, "PASS")])
        recomputed = _set([_turn(0, "PASS")], claim=_claim("FAIL"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences == []

    def test_trajectory_fail_to_pass_is_named_not_failing(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("FAIL"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.dimension == "trajectory"
        assert row.expected == "FAIL" and row.got == "PASS" and not row.regression

    def test_trajectory_pass_to_unverified_is_named_not_failing(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("UNVERIFIED"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == "PASS" and row.got == "UNVERIFIED" and not row.regression

    def test_trajectory_unverified_to_fail_is_a_fix_not_a_regression(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("UNVERIFIED"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("FAIL"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        (row,) = result.divergences
        assert row.expected == "UNVERIFIED" and row.got == "FAIL" and not row.regression

    def test_empty_baseline_of_a_zero_turn_trace_yields_shape_not_regression(self):
        expected = _set([])
        recomputed = _set([_turn(0, "PASS"), _turn(1, "UNVERIFIED")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences == []
        assert len(result.shape) == 2


# --- 3. SKIP inputs ----------------------------------------------------------------


class TestSkip:
    def test_unrestorable_baseline_skips_with_named_reason(self):
        expected = _set([_turn(0, "PASS")])
        recomputed = _set([_turn(0, "PASS")])
        baseline_recomputed = _set(
            [{**_turn(0, "UNVERIFIED"), "cause": "UNRESTORABLE_SNAPSHOT_FAILED"}]
        )
        result = compare(
            "run", expected, recomputed, baseline_recomputed=baseline_recomputed
        )
        assert result.exit_reason == "preflight", result
        assert result.skip_reason == BASELINE_UNRESTORABLE, result
        assert result.divergences == []
        assert result.shape == []
        assert result.drift == []

    def test_capability_mismatch_baseline_skips_with_named_reason(self):
        expected = _set([_turn(0, "PASS")])
        recomputed = _set([_turn(0, "PASS")])
        baseline_recomputed = _set(
            [_turn(0, "UNVERIFIED", tool="echo")],
        )
        baseline_recomputed["turns"][0]["cause"] = "UNRESTORABLE_CAPABILITY_MISMATCH"
        result = compare(
            "run", expected, recomputed, baseline_recomputed=baseline_recomputed
        )
        assert result.exit_reason == "preflight", result
        assert result.skip_reason == BASELINE_CAPABILITY_MISMATCH, result

    def test_capability_mismatch_outranks_unrestorable(self):
        expected = _set([_turn(0, "PASS")])
        recomputed = _set([_turn(0, "PASS")])
        baseline_recomputed = _set(
            [
                {**_turn(0, "UNVERIFIED"), "cause": "UNRESTORABLE_SNAPSHOT_FAILED"},
                {**_turn(1, "UNVERIFIED"), "cause": "UNRESTORABLE_CAPABILITY_MISMATCH"},
            ]
        )
        result = compare(
            "run", expected, recomputed, baseline_recomputed=baseline_recomputed
        )
        assert result.exit_reason == "preflight", result
        assert result.skip_reason == BASELINE_CAPABILITY_MISMATCH, result

    def test_absent_handles_on_the_baseline_are_not_a_skip(self):
        expected = _set([_turn(0, "UNVERIFIED")])
        recomputed = _set([_turn(0, "UNVERIFIED")])
        baseline_recomputed = _set(
            [{**_turn(0, "UNVERIFIED"), "cause": "unrestorable (no recorded cause)"}]
        )
        result = compare(
            "run", expected, recomputed, baseline_recomputed=baseline_recomputed
        )
        assert result.exit_reason == "clean", result
        assert result.skip_reason is None
        assert result.drift == []

    def test_no_baseline_recomputed_means_no_skip(self):
        result = compare(
            "run",
            _set([_turn(0, "PASS")]),
            _set([_turn(0, "PASS")]),
        )
        assert result.exit_reason == "clean", result
        assert result.skip_reason is None


# --- 4. exit_reason and the empty comparison -----------------------------------------


class TestExitReason:
    def test_empty_comparison_is_clean(self):
        expected = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        recomputed = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences == []
        assert result.shape == []
        assert result.drift == []
        assert result.skip_reason is None

    def test_a_named_abstention_keeps_the_exit_clean(self):
        expected = _set([_turn(0, "PASS"), _turn(1, "PASS")])
        recomputed = _set([_turn(0, "UNVERIFIED"), _turn(1, "PASS")])
        result = compare("run", expected, recomputed)
        assert result.exit_reason == "clean", result
        assert result.divergences and not any(row.regression for row in result.divergences)

    def test_description_is_carried(self):
        result = compare("my-run", _set([]), _set([]))
        assert result.description == "my-run"


# --- 5. The component functions, pinned -------------------------------------------------


class TestComponents:
    def test_compare_verdict_sets_splits_regressions_from_shape(self):
        expected = [_turn(0, "PASS", tool="echo"), _turn(1, "PASS")]
        recomputed = [_turn(0, "FAIL", tool="echo"), _turn(1, "PASS", tool="b")]
        divergences, shape = compare_verdict_sets(expected, recomputed)
        assert [d.got for d in divergences] == ["FAIL"]
        assert divergences[0].regression
        assert [s.kind for s in shape] == ["tool-rename"]

    def test_shape_divergences_names_renames_and_new_turns(self):
        expected = [_turn(0, "PASS", tool="echo"), _turn(1, "PASS", tool="a")]
        recomputed = [_turn(0, "PASS", tool="echo"), _turn(1, "PASS", tool="b"), _turn(2, "WARN")]
        shape = shape_divergences(expected, recomputed)
        kinds = [s.kind for s in shape]
        assert kinds == ["tool-rename", "new-turn"], kinds

    def test_compare_trajectory_absent_on_both_sides_is_no_row(self):
        assert compare_trajectory(None, None) is None

    def test_compare_trajectory_declared_to_absent_is_named_not_failing(self):
        row = compare_trajectory(_trajectory("PASS"), None)
        assert row is not None
        assert row.expected == "PASS" and row.got is None and not row.regression

    def test_compare_claim_not_declared_is_no_row(self):
        assert compare_claim(None, _claim("FAIL")) is None
        assert compare_claim(None, None) is None


# --- 6. The report surface ------------------------------------------------------------


def test_gate_comparison_renders_expected_got_on_every_row():
    expected = _set([_turn(0, "PASS")], trajectory=_trajectory("PASS"))
    recomputed = _set([_turn(0, "FAIL")], trajectory=_trajectory("PASS"))
    baseline_recomputed = _set([_turn(0, "UNVERIFIED")], trajectory=_trajectory("PASS"))
    result = compare(
        "run", expected, recomputed, baseline_recomputed=baseline_recomputed
    )
    assert result.exit_reason == "regression"
    for row in result.divergences:
        assert row.expected is not None or row.got is not None
        assert row.dimension
    for row in result.drift:
        assert row.expected is not None and row.got is not None