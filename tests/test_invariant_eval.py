"""A1 / C5: the invariant evaluator, grounded on the observed replay delta.

`evaluate_invariant` turns an operator-declared `Invariant` and the OBSERVED filesystem
effect (a BTH-1 delta from replay) into an A1 `Verdict`. It judges the observed effect,
never the agent's prose and never a static lint of the trace — the whole claim of A1 is
"grounded by construction".

Two honesty rules mirror C4's effect check exactly:

- `delta is None` means no post-state was observed -> UNVERIFIED, never PASS. An unobserved
  effect cannot satisfy an invariant.
- a rule A1 cannot ground in the filesystem delta (a network `no-egress`, the same EPERM gap
  C4 hit on `openWorldHint`) -> UNVERIFIED, never a fabricated PASS or FAIL.

The subtle correctness detail is the BYTE-PREFIX scope match: `b"tests/"` must match
`b"tests/test_auth.py"` but NOT `b"testsuite/x"`. The trailing slash in the operator's
scope makes it a directory prefix; a naive `startswith(b"tests")` would wrongly flag
`testsuite`. `test_near_miss_scope_prefix_is_not_a_violation` is watched failing against
that naive match.
"""

from __future__ import annotations

from belay.snapshot.bth1 import FieldDiff
from belay.verify.invariants import Invariant, evaluate_invariant
from belay.verify.verdict import Status, Verdict


def _touch(*paths: bytes) -> list[FieldDiff]:
    """A non-empty BTH-1 delta: a content mutation at each of `paths` (raw bytes)."""
    return [
        FieldDiff(path=p, field="content", left=b"old", right=b"new") for p in paths
    ]


# --- 1. A6 violation: read-only scope touched -> FAIL (positive control) -------


def test_read_only_scope_touched_is_a_grounded_fail() -> None:
    """`read-only {scope: b"tests/"}` + a delta touching `tests/test_auth.py` -> FAIL.

    The message must NAME the violating path and the invariant, because a grounded verdict
    points at the evidence rather than merely asserting a status. This is the positive
    control: watched failing against a stub whose `evaluate_invariant` returns PASS for
    everything, proving FAIL is reachable and not vacuously unreachable.
    """
    inv = Invariant(scope=b"tests/", rule="read-only")
    delta = _touch(b"tests/test_auth.py")

    verdict = evaluate_invariant(inv, delta, turn_index=3)

    assert isinstance(verdict, Verdict)
    assert verdict.axis == "A1"
    assert verdict.kind == "invariant"
    assert verdict.status is Status.FAIL
    assert "tests/test_auth.py" in verdict.message
    assert "read-only" in verdict.message
    assert "3" in verdict.message  # the turn is named


# --- 2. A6 respected: a mutation OUTSIDE scope -> PASS -------------------------


def test_mutation_outside_scope_is_a_pass() -> None:
    """Same invariant, but the delta touches `src/x.py` (outside `tests/`) -> PASS."""
    inv = Invariant(scope=b"tests/", rule="read-only")
    delta = _touch(b"src/x.py")

    verdict = evaluate_invariant(inv, delta, turn_index=0)

    assert verdict.status is Status.PASS


# --- 3. A6 near-miss: the byte-prefix subtlety -> PASS -------------------------


def test_near_miss_scope_prefix_is_not_a_violation() -> None:
    """`b"tests/"` must NOT match `b"testsuite/x"` — a directory prefix, not a substring.

    A naive `startswith(b"tests")` (stripping the trailing slash) wrongly flags
    `testsuite/x` as under `tests/` and FAILs. The operator's scope `b"tests/"` carries the
    trailing slash precisely to prevent this. Watched failing against the naive match.
    """
    inv = Invariant(scope=b"tests/", rule="read-only")
    delta = _touch(b"testsuite/x")

    verdict = evaluate_invariant(inv, delta, turn_index=1)

    assert verdict.status is Status.PASS


# --- 4. A4 delta None -> UNVERIFIED, never PASS --------------------------------


def test_delta_none_is_unverified_never_pass() -> None:
    """`delta is None` (no post-state observed) -> UNVERIFIED. An unobserved effect cannot
    satisfy an invariant, so it is never PASS.

    Positive control: `test_read_only_scope_touched_is_a_grounded_fail` still FAILs on a
    real violation, so UNVERIFIED is not swallowing every verdict into a bland default.
    """
    inv = Invariant(scope=b"tests/", rule="read-only")

    verdict = evaluate_invariant(inv, None, turn_index=2)

    assert verdict.status is Status.UNVERIFIED
    assert verdict.status is not Status.PASS


# --- 5. A4 unevaluable/network rule -> UNVERIFIED with an honest cause ---------


def test_network_rule_a1_cannot_ground_is_unverified() -> None:
    """A rule A1 cannot ground in a filesystem delta (a future `no-egress`) -> UNVERIFIED.

    Mirrors C4's `openWorldHint` discipline: Belay observes no network egress, so the rule
    is neither a fabricated PASS nor a fabricated FAIL — it is honestly UNVERIFIED, and the
    message says why. `evaluate_invariant` must handle this even though v0's loader only
    emits `read-only`, because a future rule must fail-safe rather than be silently PASSed.
    """
    inv = Invariant(scope=b"tests/", rule="no-egress")
    delta = _touch(b"tests/test_auth.py")  # a real delta; still cannot ground egress

    verdict = evaluate_invariant(inv, delta, turn_index=4)

    assert verdict.status is Status.UNVERIFIED
    assert verdict.status is not Status.PASS
    assert "no-egress" in verdict.message


# --- 6. Empty delta (observed no-op) -> PASS, distinct from None ---------------


def test_empty_delta_is_pass_distinct_from_none() -> None:
    """`delta == []` is an OBSERVED no-op: replay ran and saw no mutation -> PASS.

    This is distinct from `delta is None` (test 4), which is unobserved -> UNVERIFIED. The
    two are asserted side by side so the observed-nothing / unobserved distinction — the
    same one C4's effect check draws — cannot silently collapse.
    """
    inv = Invariant(scope=b"tests/", rule="read-only")

    empty = evaluate_invariant(inv, [], turn_index=5)
    unobserved = evaluate_invariant(inv, None, turn_index=5)

    assert empty.status is Status.PASS
    assert unobserved.status is Status.UNVERIFIED
    assert empty.status is not unobserved.status
