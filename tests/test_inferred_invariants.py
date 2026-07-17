"""C5 / A1: the zero-config default invariant, and THE COLLAPSE GUARD.

C5's entire justification is that A1 (a TASK-scoped invariant) catches a cheating agent
that C4's A2 (per-tool effect-conformance) structurally cannot. `default_invariants()` is
the R3 mitigation: a policy that fires with ZERO operator authoring, so A1 protects the
common case out of the box. But a zero-config default is only worth shipping if it catches
something C4 does not — hence the collapse guard below.

The collapse guard (`test_a1_diverges_from_c4_on_the_weakening_turn`) is the single most
important test in C5. On one turn — a tool that DECLARES `readOnlyHint: false` and writes
`tests/test_auth.py` — C4 correctly returns PASS (the tool declared it mutates; there is no
read-only contract to violate) while A1 must return FAIL (the task said `tests/` is
read-only). Same turn, same delta, DIVERGENT verdicts. If A1 merely re-ran C4's
effect-conformance the two would agree, C5 would be redundant, and it must not ship. So the
guard asserts the two statuses DIFFER, and its mandated positive control proves that
assertion has teeth: swap A1 for a second call to C4 and the differ-assertion fails.

The records are constructed by reusing C4's OWN `readOnlyHint: false` fixture path:
`test_verify_effect.test_declared_false_plus_mutation_is_pass` builds exactly this turn
(`trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])`, where `write_file`
declares `readOnlyHint: false` in `fixtures/annotation_frames`). Reusing it verbatim keeps
the records known-valid for `annotation_for_turn` — not a hand-rolled dict it might parse
differently than C4's real path.
"""

from __future__ import annotations

import json
import os

from conftest import trace_of
from fixtures.annotation_frames import TOOLS_LIST_REQUEST, TOOLS_LIST_RESPONSE

from belay.snapshot.bth1 import FieldDiff
from belay.verify.effect import render_effect_verdict
from belay.verify.invariants import default_invariants, evaluate_invariant
from belay.verify.verdict import Status

# Reused verbatim from tests/test_verify_effect.py — the C4 construction the guard leans on.
# The canned tools/list declares `write_file` with `readOnlyHint: false` (declared-false,
# NOT absent, NOT true), so C4's effect-conformance PASSes any observed mutation for it.
LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]


def _call(msg_id: int, name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


def _tests_write() -> list[FieldDiff]:
    """The weakening delta: the turn wrote `tests/test_auth.py`, gutting its assertion.

    This is the delta that CONTAINS the write (not a later reading turn with an empty
    delta) — the mutation the read-only-`tests/` invariant is there to catch.
    """
    return [
        FieldDiff(
            path=b"tests/test_auth.py",
            field="content",
            left=b"assert x == 1",
            right=b"assert True",
        )
    ]


# --- A3: the zero-config default fires with no operator file ---------------------------


def test_default_invariants_declares_tests_read_only():
    """`default_invariants()` returns a non-empty list holding the one documented default:
    `tests/` is read-only. This is what A1 runs when no `--invariants` file is given."""
    defaults = default_invariants()

    assert defaults, "the zero-config default must be non-empty — it is the R3 mitigation"
    inv = defaults[0]
    assert inv.scope == os.fsencode("tests/"), inv
    assert inv.rule == "read-only", inv


# --- A5: THE COLLAPSE GUARD — A1 diverges from C4 on the weakening turn ----------------


def test_a1_diverges_from_c4_on_the_weakening_turn(tmp_path):
    """The whole thesis of C5, on ONE turn. A `readOnlyHint: false` tool writes
    `tests/test_auth.py`. C4 effect-conformance PASSes it (the tool declared it mutates —
    no read-only contract to violate); the task-scoped default invariant FAILs it
    (`tests/` is read-only). Same records, same delta, DIVERGENT verdicts.

    The `is not` assertion is the load-bearing one: it states the divergence AS the
    property, so a hypothetical A1 that merely re-ran C4's effect-conformance — which would
    also PASS here — MUST fail this test. The mandated positive control
    (`test_the_collapse_guard_has_teeth`) proves that assertion is not vacuous.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])
    delta = _tests_write()

    # C4 (A2 effect-conformance): declared-false + a write -> PASS. There is no read-only
    # contract to violate, so C4 cannot catch the weakening. This is the C4 side of the guard.
    c4 = render_effect_verdict(records, 0, delta)
    assert c4.status is Status.PASS, c4

    # A1 (the task-scoped default invariant): `tests/` is read-only and the turn wrote under
    # it -> FAIL, naming the offending path.
    a1 = evaluate_invariant(default_invariants()[0], delta, 0)
    assert a1.status is Status.FAIL, a1
    assert "tests/test_auth.py" in a1.message, a1.message

    # The divergence IS the non-redundancy: C4 PASSes the weakening turn, only the
    # task-scoped invariant catches it. A test that would still pass if A1 re-ran C4 must
    # fail — hence this asserts they DIFFER, not just their two incidental statuses.
    assert c4.status is not a1.status, (
        "A1 and C4 must render DIFFERENT verdicts on the weakening turn: if A1 merely "
        "re-ran C4's effect-conformance both would PASS and C5 would be redundant. Only "
        f"the task-scoped invariant catches corrupt success (C4={c4.status}, A1={a1.status})"
    )


# --- the positive control: prove the collapse guard's divergence assertion can fail ----


def test_the_collapse_guard_has_teeth(tmp_path):
    """Positive control for `test_a1_diverges_from_c4_on_the_weakening_turn`.

    The collapse guard's load-bearing line is `c4.status is not a1.status`. That assertion
    is only meaningful if it CAN fail — i.e. if A1 collapsing into C4 would actually be
    caught. Here we stand a second C4 effect-conformance call in for A1 (the exact collapse
    C5 must never ship) and show the two statuses are then IDENTICAL — so the guard's
    `is not` would be False and the guard would fail. This locks the teeth in permanently:
    if a future refactor ever made `evaluate_invariant` alias C4's effect-conformance, the
    collapse guard would flip red instead of silently passing.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])
    delta = _tests_write()

    c4 = render_effect_verdict(records, 0, delta)
    collapsed_a1 = render_effect_verdict(records, 0, delta)  # A1 == C4 stand-in (the collapse)

    # Both PASS -> identical -> the guard's `c4.status is not a1.status` would be False and
    # the collapse guard would fail. That is exactly the teeth: the collapse is detectable.
    assert c4.status is collapsed_a1.status, (
        "the collapse stand-in must render the SAME status as C4 (both PASS) — that is what "
        "the collapse guard's `is not` assertion catches; if they differed here the guard "
        "would be vacuous"
    )
    assert c4.status is Status.PASS, c4


# --- A5b: the default's FAIL is tool-independent — it never reads the annotation -------


def test_default_invariant_fail_is_tool_independent():
    """The default invariant's FAIL does not depend on the tool's annotation — because
    `evaluate_invariant` takes NO records at all, only the delta. There is no annotation to
    flip: whether the writing tool declared `readOnlyHint: true`, `false`, or nothing, the
    verdict on the same `tests/` write is FAIL. That tool-independence is exactly what makes
    the default non-redundant with C4's per-tool effect-conformance (which C4 alone reads).
    """
    a1 = evaluate_invariant(default_invariants()[0], _tests_write(), 0)

    assert a1.status is Status.FAIL, a1
