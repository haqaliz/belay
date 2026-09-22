"""Aspect `calibration-math` — exact pins for the reliability curve, ECE, and the sweep.

Everything here is pure arithmetic over an in-memory, hand-constructed fixture: no
replay, no server, no clock, no randomness. The asserted values are computed BY HAND
in this file — each one stated as a literal with its derivation in a comment — the
code under test is never used to compute its own expected value.

The fixture (ordinal, score, confidence, violated), N = 8 rows spread across the
deciles with three deciles deliberately empty:

    row 0: score 0.1  conf 0.0625  clean        -> decile 0
    row 1: score 0.2  conf 0.25    VIOLATED     -> decile 2
    row 2: score 0.4  conf 0.4375  VIOLATED     -> decile 4
    row 3: score 0.4  conf 0.5625  clean        -> decile 5   (ties with row 2 on score)
    row 4: score 0.6  conf 0.6875  VIOLATED     -> decile 6
    row 5: score 0.7  conf 0.875   VIOLATED     -> decile 8
    row 6: score 0.8  conf 0.875   clean        -> decile 8
    row 7: score 0.9  conf 1.0     VIOLATED     -> decile 9

Deciles 1, 3 and 7 are empty: their rate must be None with a "no data" marker, never
0. All confidences are binary-exact (x/16 or 1.0) and N is a power of two, so every
hand-computed value below is exactly representable and the `==` pins are exact, not
tolerance-based. The tie between rows 2 and 3 (both score 0.4) pins the top-N
tie-break: lowest ordinal first, mirroring the budget aspect.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from belay.verify.calibration import (
    EmptyRowsError,
    LedgerRow,
    ReliabilityBin,
    ThresholdSweepPoint,
    TopNSweepPoint,
    ece,
    reliability_curve,
    threshold_sweep,
    top_n_sweep,
)

_FIXTURE = (
    LedgerRow(0, 0.1, 0.0625, False),
    LedgerRow(1, 0.2, 0.25, True),
    LedgerRow(2, 0.4, 0.4375, True),
    LedgerRow(3, 0.4, 0.5625, False),
    LedgerRow(4, 0.6, 0.6875, True),
    LedgerRow(5, 0.7, 0.875, True),
    LedgerRow(6, 0.8, 0.875, False),
    LedgerRow(7, 0.9, 1.0, True),
)


def test_reliability_curve_hand_computed_bins() -> None:
    """Per-decile n, mean confidence, and observed rate, computed by hand.

    Decile 8 holds rows 5 and 6 (both conf 0.875, one violated): n=2, mean 0.875,
    rate 1/2. Deciles 1, 3 and 7 hold nothing: n=0, both values None, no_data True.
    """
    assert reliability_curve(_FIXTURE) == [
        ReliabilityBin(0.0, 0.1, 1, 0.0625, 0.0, False),
        ReliabilityBin(0.1, 0.2, 0, None, None, True),
        ReliabilityBin(0.2, 0.3, 1, 0.25, 1.0, False),
        ReliabilityBin(0.3, 0.4, 0, None, None, True),
        ReliabilityBin(0.4, 0.5, 1, 0.4375, 1.0, False),
        ReliabilityBin(0.5, 0.6, 1, 0.5625, 0.0, False),
        ReliabilityBin(0.6, 0.7, 1, 0.6875, 1.0, False),
        ReliabilityBin(0.7, 0.8, 0, None, None, True),
        ReliabilityBin(0.8, 0.9, 2, 0.875, 0.5, False),
        ReliabilityBin(0.9, 1.0, 1, 1.0, 1.0, False),
    ]


def test_decile_edges_pinned_and_confidence_one_lands_in_the_last_bin() -> None:
    """Equal-width deciles, edges [0.0-0.1) ... [0.9-1.0]; exactly 1.0 is the last bin."""
    curve = reliability_curve([LedgerRow(0, 0.5, 1.0, False)])
    assert [(bin_.lo, bin_.hi) for bin_ in curve] == [
        (0.0, 0.1),
        (0.1, 0.2),
        (0.2, 0.3),
        (0.3, 0.4),
        (0.4, 0.5),
        (0.5, 0.6),
        (0.6, 0.7),
        (0.7, 0.8),
        (0.8, 0.9),
        (0.9, 1.0),
    ]
    assert [bin_.n for bin_ in curve] == [0, 0, 0, 0, 0, 0, 0, 0, 0, 1]


def test_empty_bin_is_no_data_never_zero() -> None:
    """An empty bin is None + a marker; a REAL zero rate (decile 0) stays 0.0."""
    curve = reliability_curve(_FIXTURE)
    empty = [bin_ for bin_ in curve if bin_.no_data]
    assert [bin_.n for bin_ in empty] == [0, 0, 0]
    assert all(bin_.observed_rate is None for bin_ in empty)
    assert all(bin_.mean_confidence is None for bin_ in empty)
    nonempty = [bin_ for bin_ in curve if not bin_.no_data]
    assert all(bin_.observed_rate is not None for bin_ in nonempty)
    assert curve[0].observed_rate == 0.0


def test_ece_hand_computed_exact() -> None:
    """Sum over non-empty bins of (n_bin/N x |rate_bin - conf_bin|), by hand.

    (1/8)*|0.0-0.0625| + (1/8)*|1.0-0.25| + (1/8)*|1.0-0.4375| + (1/8)*|0.0-0.5625|
      + (1/8)*|1.0-0.6875| + (2/8)*|0.5-0.875| + (1/8)*|1.0-1.0|
    = 0.0078125 + 0.09375 + 0.0703125 + 0.0703125 + 0.0390625 + 0.09375 + 0.0
    = 0.375  (exactly representable; the assertion is not tolerance-based)
    """
    assert ece(_FIXTURE) == 0.375


def test_threshold_sweep_exact() -> None:
    """Per candidate: violations-skipped (violated rows with score < threshold) and
    budget-saved (skipped rows / total), by hand.

    threshold 0.3: skipped rows 0, 1 (scores 0.1, 0.2) -> 2/8; violated among them: row 1.
    threshold 0.5: skipped rows 0, 1, 2, 3 (scores 0.1, 0.2, 0.4, 0.4) -> 4/8; rows 1, 2.
    threshold 0.7: skipped rows 0-4 (scores 0.1..0.6) -> 5/8; rows 1, 2, 4.
    Row 5's score is exactly 0.7 and is NOT skipped at threshold 0.7.
    """
    assert threshold_sweep(_FIXTURE, (0.3, 0.5, 0.7)) == [
        ThresholdSweepPoint(0.3, 1, 0.25),
        ThresholdSweepPoint(0.5, 2, 0.5),
        ThresholdSweepPoint(0.7, 3, 0.625),
    ]


def test_top_n_sweep_exact_and_tie_break_lowest_ordinal() -> None:
    """The N lowest-score rows; ties broken by lowest ordinal (mirror the budget aspect).

    top-1: row 0 (0.1) -> 0 violations, 1/8 saved.
    top-2: rows 0, 1 -> row 1 violated, 2/8 saved.
    top-3: rows 0, 1, then the 0.4 tie between row 2 (violated) and row 3 (clean) ->
    lowest ordinal wins -> row 2 -> 2 violations, 3/8 saved. Choosing row 3 instead
    would report 1 violation, which is the failure this pin exists to catch.
    """
    assert top_n_sweep(_FIXTURE, (1, 2, 3)) == [
        TopNSweepPoint(1, 0, 0.125),
        TopNSweepPoint(2, 1, 0.25),
        TopNSweepPoint(3, 2, 0.375),
    ]


def test_same_input_twice_is_identical_output() -> None:
    """Determinism: no clock, no randomness — the same rows yield the same output."""
    assert reliability_curve(_FIXTURE) == reliability_curve(_FIXTURE)
    assert ece(_FIXTURE) == ece(_FIXTURE)
    assert threshold_sweep(_FIXTURE, (0.3, 0.5, 0.7)) == threshold_sweep(
        _FIXTURE, (0.3, 0.5, 0.7)
    )
    assert top_n_sweep(_FIXTURE, (1, 2, 3)) == top_n_sweep(_FIXTURE, (1, 2, 3))


def test_empty_row_set_raises_a_named_error_never_a_fabricated_zero() -> None:
    """An empty row set is the caller's refusal point, never an ECE of 0.0 or an empty curve."""
    with pytest.raises(EmptyRowsError):
        ece([])
    with pytest.raises(EmptyRowsError):
        reliability_curve([])


def test_sweep_over_empty_rows_returns_none_budget_never_one() -> None:
    """The 0-denominator discipline: skipped/0 is None, never 1.0 (metrics.py:149-155)."""
    assert threshold_sweep([], (0.5,)) == [ThresholdSweepPoint(0.5, 0, None)]
    assert top_n_sweep([], (1,)) == [TopNSweepPoint(1, 0, None)]


def test_module_imports_are_stdlib_only_structural() -> None:
    """The module's import list is stdlib only — no clock, no randomness, no filesystem.

    Read with ast (never imported twice for the check): the zero-LLM guard walks the
    same directory, and a stray `import time` or `import random` here would silently
    make the ledger non-reproducible, which is the one property it cannot lose.
    """
    module_path = (
        Path(__file__).parent.parent / "src" / "belay" / "verify" / "calibration.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imported.add(node.module)
    roots = {name.split(".")[0] for name in imported}
    allowed = {"__future__", "dataclasses", "typing", "math", "statistics"}
    assert roots <= allowed, f"non-stdlib import roots: {sorted(roots - allowed)}"
    assert not (roots & {"time", "random", "os", "sys", "pathlib", "subprocess", "json"})