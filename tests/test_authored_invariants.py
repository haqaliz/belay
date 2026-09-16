"""artifact-trust: the authored invariant schema, its loader, and verify-side trust.

An authored invariant is policy WITH PROVENANCE (invariant-authoring PRD M4/M5): it
reaches A1 only when its calibration digest matches the policy set at load time. An
artifact whose calibration is absent or malformed degrades every one of its invariants
to UNVERIFIED with the named cause `AUTHORED_INVARIANT_UNCALIBRATED`; one whose policy
set was edited after calibration degrades with `AUTHORED_INVARIANT_ALTERED`. In both
cases the invariant is NEVER enforced — never PASS, never FAIL — because a rule nobody
calibrated that then manufactures a violation is worse than no rule at all (PRD Goal 2:
"authored invariants never manufacture a violation"). The trust check is pure loader
logic: no model, no subprocess, no replay.

`canonical_policy_digest` is the interface the `authoring-protocol` aspect emits
against: the digest covers the normalized `{"rule", "scope"}` policy set plus the task
and control sha256s, and nothing else — rationale text is not policy, so editing a
rationale after calibration does not invalidate (spec criterion 3).

`load_invariants` keeps its single call site and its single `path` parameter (the
provenance guard pins that signature): a JSON list is operator policy, byte-unchanged;
a JSON object is dispatched to `parse_authored_invariants`; anything else is the
existing fail-closed ValueError.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from belay.snapshot.bth1 import FieldDiff
from belay.verify.invariants import (
    AUTHORED_INVARIANT_ALTERED,
    AUTHORED_INVARIANT_UNCALIBRATED,
    AUTHORED_SCHEMA,
    Invariant,
    canonical_policy_digest,
    evaluate_invariant,
    load_invariants,
    parse_authored_invariants,
)
from belay.verify.verdict import Status


def _artifact(
    entries: list[dict],
    *,
    task_sha256: str = "task-hash",
    control_sha256: str = "control-hash",
    calibrated: bool = True,
) -> dict:
    """A well-formed authored artifact (PRD M4 shape), digest recomputed from the policy.

    `entries` carry the operator-shaped `{"scope", "rule"}` pairs plus a `rationale`
    (prose, deliberately NOT policy). The calibration digest is recomputed from the
    scope/rule pairs and the two hashes, exactly as the engine will recompute it at
    load time.
    """
    policy = [
        Invariant(scope=os.fsencode(e["scope"]), rule=e["rule"]) for e in entries
    ]
    digest = canonical_policy_digest(
        invariants=policy, task_sha256=task_sha256, control_sha256=control_sha256
    )
    return {
        "schema": AUTHORED_SCHEMA,
        "invariants": entries,
        "task": {"path": "task.md", "sha256": task_sha256},
        "control": {
            "path": "control.trace",
            "sha256": control_sha256,
            "turns": 5,
            "calibrated": calibrated,
        },
        "calibration": {"verdict": "calibrated", "digest": digest},
        "author": {"program": "fake-author", "model": "test-model"},
    }


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(payload))
    return path


def _touch(*paths: bytes) -> list[FieldDiff]:
    """A non-empty BTH-1 delta: a content mutation at each of `paths` (raw bytes)."""
    return [FieldDiff(path=p, field="content", left=b"old", right=b"new") for p in paths]


# --- Criterion 1: a calibrated artifact enforces like operator policy ----------


def test_calibrated_artifact_parses_trusted_and_enforces_identically_to_operator_list(
    tmp_path: Path,
) -> None:
    """A well-formed calibrated artifact -> trusted invariants with the same teeth as a file.

    `untrusted_cause is None` means A1 enforces it exactly like the identical scope/rule
    loaded from an operator list: the corrupt fixture FAILs at the exact turn, naming the
    invariant and the diff; the clean/out-of-scope deltas PASS. Verdicts are compared for
    full equality, not just status.
    """
    entries = [
        {"scope": "tests/", "rule": "read-only", "rationale": "the tests are the contract"}
    ]
    (authored,) = parse_authored_invariants(_artifact(entries))

    assert authored.untrusted_cause is None
    assert authored.rule == "read-only"
    assert authored.scope == os.fsencode("tests/")

    operator_path = tmp_path / "operator.json"
    operator_path.write_text(json.dumps([{"scope": "tests/", "rule": "read-only"}]))
    (operator,) = load_invariants(operator_path)

    for delta in [_touch(b"tests/test_auth.py"), [], _touch(b"src/x.py")]:
        assert evaluate_invariant(authored, delta, 0) == evaluate_invariant(
            operator, delta, 0
        )

    failing = evaluate_invariant(authored, _touch(b"tests/test_auth.py"), 0)
    assert failing.status is Status.FAIL
    assert "tests/test_auth.py" in failing.message  # names the diff
    assert "read-only" in failing.message  # names the invariant


# --- Criterion 2: uncalibrated degrades, never FAILs ---------------------------


def _uncalibrated_cases() -> list[tuple[str, dict]]:
    base = _artifact([{"scope": "tests/", "rule": "read-only"}])
    mutations = {
        "calibration block absent": lambda p: p.pop("calibration"),
        "calibration not an object": lambda p: p.__setitem__("calibration", "nonsense"),
        "calibration digest missing": lambda p: p["calibration"].pop("digest"),
        "control block absent": lambda p: p.pop("control"),
        "control.calibrated is false": lambda p: p["control"].update({"calibrated": False}),
        "control.calibrated is the string true": lambda p: p["control"].update(
            {"calibrated": "true"}
        ),
        "control.calibrated absent": lambda p: p["control"].pop("calibrated"),
        "control.sha256 missing": lambda p: p["control"].pop("sha256"),
        "task block absent": lambda p: p.pop("task"),
        "task.sha256 missing": lambda p: p["task"].pop("sha256"),
    }
    cases: list[tuple[str, dict]] = []
    for name, mutate in mutations.items():
        payload = copy.deepcopy(base)
        mutate(payload)
        cases.append((name, payload))
    return cases


_UNCALIBRATED_CASES = _uncalibrated_cases()


@pytest.mark.parametrize(
    "_name,payload", _UNCALIBRATED_CASES, ids=[c[0] for c in _UNCALIBRATED_CASES]
)
def test_uncalibrated_artifact_yields_untrusted_invariants_with_named_cause(
    _name: str, payload: dict
) -> None:
    """Absent/malformed calibration -> every invariant carries the named UNCALIBRATED cause.

    Not an error and not a silent drop: the invariants are still parsed and carried so
    the run can name WHY it abstained, but none of them may ever be enforced.
    """
    parsed = parse_authored_invariants(payload)

    assert parsed, "an uncalibrated artifact still yields its invariants"
    for inv in parsed:
        assert inv.untrusted_cause == AUTHORED_INVARIANT_UNCALIBRATED


# --- Criterion 3: altered degrades, never FAILs --------------------------------


def test_policy_edit_after_calibration_is_alteration_not_silent_enforcement() -> None:
    """Editing a scope after calibration (digest mismatch) -> AUTHORED_INVARIANT_ALTERED.

    The remedy is re-running infer; a silently enforced policy nobody calibrated is the
    exact failure M5 exists to refuse.
    """
    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["invariants"][0]["scope"] = "tests2/"  # edited after calibration

    (inv,) = parse_authored_invariants(payload)

    assert inv.untrusted_cause == AUTHORED_INVARIANT_ALTERED


# --- Criterion 4: rationale-only change stays trusted --------------------------


def test_rationale_text_edit_does_not_invalidate_calibration() -> None:
    """Rationale is prose, not policy: editing it after calibration is NOT an alteration."""
    payload = _artifact(
        [{"scope": "tests/", "rule": "read-only", "rationale": "original rationale"}]
    )
    payload["invariants"][0]["rationale"] = "rewritten after calibration"

    (inv,) = parse_authored_invariants(payload)

    assert inv.untrusted_cause is None


# --- Criterion 5: fail-closed on malformed --------------------------------------


def test_unknown_rule_inside_artifact_is_a_value_error() -> None:
    """An unknown rule in an artifact is rejected by name, exactly like an operator file."""
    payload = _artifact([{"scope": "tests/", "rule": "make-coffee"}])

    with pytest.raises(ValueError, match="make-coffee"):
        parse_authored_invariants(payload)


def test_unknown_schema_is_a_value_error() -> None:
    """An unknown schema string — including a future version — is fail-closed."""
    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["schema"] = "belay-authored-invariants/99"

    with pytest.raises(ValueError, match="belay-authored-invariants/99"):
        parse_authored_invariants(payload)


def test_missing_or_non_list_invariants_is_a_value_error() -> None:
    """`invariants` must be a list; a missing/non-list/ill-typed body is fail-closed."""
    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["invariants"] = "not-a-list"
    with pytest.raises(ValueError):
        parse_authored_invariants(payload)

    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["invariants"] = [{"scope": "tests/", "rule": 42}]  # non-string rule
    with pytest.raises(ValueError):
        parse_authored_invariants(payload)


# --- Criterion 6: load_invariants shape dispatch --------------------------------


def test_load_invariants_dispatch_operator_list_is_unchanged(tmp_path: Path) -> None:
    """A JSON list still takes the existing byte-unchanged operator path."""
    path = _write(tmp_path, [{"scope": "tests/", "rule": "read-only"}])

    (inv,) = load_invariants(path)

    assert inv == Invariant(scope=b"tests/", rule="read-only")
    assert inv.untrusted_cause is None


def test_load_invariants_dispatch_authored_object(tmp_path: Path) -> None:
    """A JSON object with the authored schema dispatches through the trust path."""
    path = _write(tmp_path, _artifact([{"scope": "tests/", "rule": "read-only"}]))

    (inv,) = load_invariants(path)

    assert inv.untrusted_cause is None


def test_load_invariants_dispatch_uncalibrated_object_still_loads(tmp_path: Path) -> None:
    """An uncalibrated artifact loads, degraded, never fail-closed at the loader."""
    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["control"]["calibrated"] = False
    path = _write(tmp_path, payload)

    (inv,) = load_invariants(path)

    assert inv.untrusted_cause == AUTHORED_INVARIANT_UNCALIBRATED


def test_load_invariants_dispatch_neither_shape_is_fail_closed(tmp_path: Path) -> None:
    """A JSON object that is neither operator list nor known schema -> ValueError (exit 2).

    Same contract as a malformed operator file; a top-level scalar keeps the existing
    fail-closed error.
    """
    path = _write(tmp_path, {"schema": "belay-authored-invariants/99"})
    with pytest.raises(ValueError):
        load_invariants(path)

    scalar = tmp_path / "scalar.json"
    scalar.write_text('"just-a-string"')
    with pytest.raises(ValueError):
        load_invariants(scalar)


# --- Criterion 7: an untrusted invariant is UNVERIFIED, never PASS/FAIL ---------


@pytest.mark.parametrize(
    "delta",
    [
        _touch(b"tests/test_auth.py"),  # a delta that would FAIL a trusted read-only
        [],  # a delta that would PASS a trusted rule
        _touch(b"src/x.py"),  # out of scope: would PASS a trusted rule
        None,  # no observed post-state: would UNVERIFY a trusted rule
    ],
    ids=["in-scope-mutation", "no-op", "out-of-scope", "no-post-state"],
)
def test_untrusted_invariant_is_never_enforced_never_passes_never_fails(
    delta: list[FieldDiff] | None,
) -> None:
    """For EVERY underlying outcome the short-circuit emits UNVERIFIED with the cause.

    The cause rides in `expected["cause"]` and is named in the message, so the phase0
    report buckets the abstention correctly. UNVERIFIED only lowers; never PASS, never
    FAIL, regardless of what the underlying evaluation would have said (spec criterion 8).
    """
    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["control"]["calibrated"] = False
    (inv,) = parse_authored_invariants(payload)
    assert inv.untrusted_cause == AUTHORED_INVARIANT_UNCALIBRATED

    verdict = evaluate_invariant(inv, delta, turn_index=7)

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == AUTHORED_INVARIANT_UNCALIBRATED
    assert AUTHORED_INVARIANT_UNCALIBRATED in verdict.message


def test_altered_invariant_evaluates_unverified_with_altered_cause() -> None:
    """A tampered invariant degrades to UNVERIFIED with ALTERED even on a FAIL-shaped delta."""
    payload = _artifact([{"scope": "tests/", "rule": "read-only"}])
    payload["invariants"][0]["scope"] = "tests2/"
    (inv,) = parse_authored_invariants(payload)
    assert inv.untrusted_cause == AUTHORED_INVARIANT_ALTERED

    verdict = evaluate_invariant(inv, _touch(b"tests/test_auth.py"), 0)

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == AUTHORED_INVARIANT_ALTERED
    assert AUTHORED_INVARIANT_ALTERED in verdict.message


# --- Criterion 8: canonical_policy_digest determinism ---------------------------


def test_canonical_policy_digest_is_deterministic_and_order_independent() -> None:
    """Same policy set -> same digest; entry ORDER is irrelevant."""
    forward = [
        Invariant(scope=b"tests/", rule="read-only"),
        Invariant(scope=b"src/", rule="no-delete"),
    ]
    backward = list(reversed(forward))

    assert canonical_policy_digest(
        invariants=forward, task_sha256="t", control_sha256="c"
    ) == canonical_policy_digest(invariants=backward, task_sha256="t", control_sha256="c")


def test_canonical_policy_digest_excludes_rationale_and_includes_hashes() -> None:
    """Rationale text is not policy; the task/control hashes are part of the digest."""
    a = _artifact([{"scope": "tests/", "rule": "read-only", "rationale": "A"}])
    b = _artifact([{"scope": "tests/", "rule": "read-only", "rationale": "B"}])
    assert a["calibration"]["digest"] == b["calibration"]["digest"]

    c = _artifact([{"scope": "tests/", "rule": "read-only"}], task_sha256="other-task")
    assert a["calibration"]["digest"] != c["calibration"]["digest"]

    d = _artifact([{"scope": "tests/", "rule": "read-only"}], control_sha256="other-control")
    assert a["calibration"]["digest"] != d["calibration"]["digest"]


def test_canonical_policy_digest_is_exactly_sha256_of_the_canonical_json() -> None:
    """The golden canonical form — the interface `authoring-protocol` emits against.

    Pins the exact envelope: `{"invariants": [sorted {"rule","scope"}], "task_sha256",
    "control_sha256"}` serialized with `sort_keys=True` and compact separators. A change
    to this form is a change to the artifact interface and must break here first.
    """
    inv = Invariant(scope=b"tests/", rule="read-only")
    canonical = json.dumps(
        {
            "invariants": [{"rule": "read-only", "scope": "tests/"}],
            "task_sha256": "t",
            "control_sha256": "c",
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    assert canonical_policy_digest(
        invariants=[inv], task_sha256="t", control_sha256="c"
    ) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_canonical_policy_digest_normalizes_duplicate_entries() -> None:
    """Duplicate (rule, scope) pairs are collapsed before hashing; enforcement keeps them."""
    dupes = [
        Invariant(scope=b"tests/", rule="read-only"),
        Invariant(scope=b"tests/", rule="read-only"),
    ]
    single = [Invariant(scope=b"tests/", rule="read-only")]

    assert canonical_policy_digest(
        invariants=dupes, task_sha256="t", control_sha256="c"
    ) == canonical_policy_digest(invariants=single, task_sha256="t", control_sha256="c")


# --- Edge cases ----------------------------------------------------------------


def test_empty_invariant_list_artifact_is_valid_and_empty() -> None:
    """`invariants: []` is a valid calibrated artifact that yields no invariants."""
    assert parse_authored_invariants(_artifact([])) == []