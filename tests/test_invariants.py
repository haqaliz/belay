"""C5 / A1: the invariant declaration format and its operator-file loader.

A1 is the axis that catches a CHEATING agent whose trace is perfectly faithful (it
really did weaken the test), by holding the run to a TASK-scoped policy the OPERATOR
declared. That only works if the policy and the evidence never mix: the invariant is the
operator's, the trace is the agent's. If a run could write a permissive invariant into
its own trace and have A1 honour it, A1 is defeated by construction — the agent grades its
own homework.

So the load-bearing test here is `test_no_invariant_is_ever_sourced_from_a_trace`: it
asserts an ABSENCE — that this module offers no path from trace records to policy — and is
written to FAIL the moment such a path is introduced. The rest pin the format (scope is raw
bytes, mirroring BTH-1's raw-path discipline) and the fail-closed loader (malformed input
and an unknown rule are named errors, never a silent empty list).
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

import belay.verify.invariants as invariants
from belay.verify.invariants import Invariant, load_invariants


def _write(tmp_path: Path, payload: str) -> Path:
    path = tmp_path / "invariants.json"
    path.write_text(payload)
    return path


def test_valid_file_loads_one_invariant_with_bytes_scope(tmp_path: Path) -> None:
    """A well-formed operator file yields Invariants; scope is RAW BYTES, not a str.

    Scope is bytes so a later byte-prefix match (`b"tests/"` covers
    `b"tests/test_auth.py"`) uses the same encoding BTH-1 and effect._paths use on paths —
    `os.fsencode` — and inherits the unicode-normalisation safety that buys.
    """
    path = _write(tmp_path, json.dumps([{"scope": "tests/", "rule": "read-only"}]))

    result = load_invariants(path)

    assert result == [Invariant(scope=b"tests/", rule="read-only")]
    (only,) = result
    assert only.scope == b"tests/"
    assert isinstance(only.scope, bytes)
    assert only.scope == os.fsencode("tests/")
    assert only.rule == "read-only"


def test_no_invariant_is_ever_sourced_from_a_trace(tmp_path: Path) -> None:
    """The provenance boundary: policy comes ONLY from an operator file, never the trace.

    A trace record that happens to look like an invariant is agent-produced EVIDENCE, not
    operator POLICY. This module must expose no way to turn such a record into an
    Invariant. The assertion is structural so a future "read invariants from the trace
    records" loader breaks it: the only public loader is `load_invariants`, and it takes a
    filesystem path, not records.
    """
    # An invariant-shaped record riding inside a trace. If any code path honoured this, a
    # run could grant itself a permissive policy and A1 would be defeated by construction.
    trace = [{"kind": "invariant", "scope": "anything", "rule": "read-only"}]

    public = {
        name: obj
        for name, obj in vars(invariants).items()
        if not name.startswith("_")
        and callable(obj)
        and getattr(obj, "__module__", None) == invariants.__name__
    }

    # The ONE public loader is load_invariants. A new callable whose name speaks of
    # invariants (a second loader) is a new provenance surface and must fail this.
    loaders = {
        name for name in public if "invariant" in name.lower() and name != "Invariant"
    }
    assert loaders == {"load_invariants"}, (
        f"a second invariant-producing callable appeared: {loaders - {'load_invariants'}}. "
        "Policy must be sourced only from load_invariants(operator_file)."
    )

    # It takes a file path, not records. A loader that accepted a trace/records argument
    # would be exactly the trace-to-policy path this boundary forbids.
    params = list(inspect.signature(load_invariants).parameters)
    assert params == ["path"], (
        f"load_invariants parameters are {params}; it must take only a file path. "
        "A records/trace parameter would open a trace-to-policy path."
    )

    # No public callable is named for reading a trace/records into policy.
    for name in public:
        lowered = name.lower()
        assert "trace" not in lowered and "record" not in lowered, (
            f"public callable {name!r} names the trace/records — the module must expose no "
            "trace-to-invariant path."
        )

    # And there is no way to hand the trace to the loader in place of a file: passing
    # records where a path is expected is an error, not a silently honoured policy.
    with pytest.raises((TypeError, ValueError, OSError)):
        load_invariants(trace)  # type: ignore[arg-type]


def test_malformed_json_is_a_named_error_not_a_crash_or_empty_list(tmp_path: Path) -> None:
    """A file that is not JSON -> a clean ValueError, never [] and never a raw traceback.

    Returning [] on malformed input is a silent coverage loss: the operator declared a
    policy, and swallowing it reports the run against no policy at all — a false PASS the
    fail-closed loader exists to refuse.
    """
    path = _write(tmp_path, "this is not json {")

    with pytest.raises(ValueError) as excinfo:
        load_invariants(path)

    assert str(excinfo.value)  # a message, not a bare raise


def test_unknown_rule_is_rejected_by_name_not_silently_dropped(tmp_path: Path) -> None:
    """An unknown rule -> ValueError naming it. Silently ignoring it loses coverage.

    v0 supports only `read-only`. A rule the operator declared that Belay does not
    understand must be surfaced, not dropped — dropping it verifies the run against less
    than the operator asked for while reporting success.
    """
    path = _write(tmp_path, json.dumps([{"scope": "x", "rule": "make-coffee"}]))

    with pytest.raises(ValueError) as excinfo:
        load_invariants(path)

    assert "make-coffee" in str(excinfo.value)


def test_empty_list_is_valid_and_yields_no_invariants(tmp_path: Path) -> None:
    """`[]` is a valid file: the operator declared no invariants. Distinct from malformed."""
    path = _write(tmp_path, json.dumps([]))

    assert load_invariants(path) == []
