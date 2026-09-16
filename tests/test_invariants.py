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
and an unknown rule are named errors, never a silent empty list). The guard names every
producer by hand: `load_invariants` (operator file), `default_invariants` (a constant),
`resolve_library_entry` (the library table) and `parse_authored_invariants` (the authored
artifact's payload — never a trace).
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
    records" loader breaks it: the only loaders are `load_invariants`, which takes a
    filesystem path, not records; `default_invariants`, which takes nothing at all;
    `resolve_library_entry`, which consults only the module-level LIBRARY table (the
    deliberate third producer, admitted here by name per PRD M2 / the library-surface
    plan); and `parse_authored_invariants`, which parses only the authored artifact's
    payload — the operator-controlled JSON the author command emitted, never a trace
    (the deliberate fourth producer, admitted here by name per invariant-authoring PRD
    M6, pinned below to take exactly `["payload"]`).
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

    # A provenance surface is a callable that PRODUCES policy — one that RETURNS an Invariant
    # (or a list of them). Keying on the return type, not the name, is what makes this
    # precise: a new trace->policy loader still returns Invariants and so still trips this,
    # while a legitimate CONSUMER of an already-loaded Invariant (`evaluate_invariant`, which
    # takes an `inv` and returns a Verdict) is not a second source and is correctly excluded.
    producers = {
        name
        for name, obj in public.items()
        if "Invariant" in str(inspect.signature(obj).return_annotation)
    }
    # Exactly four producers, and ALL FOUR are provenance-safe by construction:
    # `load_invariants` reads an OPERATOR FILE (a path the operator controls, asserted
    # below to take only a path), `default_invariants` reads NOTHING — it returns a
    # hardcoded constant and takes no arguments at all, so it cannot source policy from a
    # trace — `resolve_library_entry` (the DELIBERATE, review-approved third producer,
    # PRD M2 / library-surface) consults ONLY the module-level LIBRARY table, asserted
    # below to take only the entry name and to perform no file I/O, and
    # `parse_authored_invariants` (the DELIBERATE, review-approved fourth producer,
    # invariant-authoring PRD M4/M5/M6) parses ONLY the AUTHORED ARTIFACT's payload —
    # the operator-controlled JSON the author command emitted, asserted below to take
    # only that payload, never records. None is a trace->policy path. A FIFTH producer,
    # or one of these growing a records/trace parameter, still trips this.
    assert producers == {
        "load_invariants",
        "default_invariants",
        "resolve_library_entry",
        "parse_authored_invariants",
    }, (
        "an unexpected invariant-producing callable appeared: "
        f"{producers - {'load_invariants', 'default_invariants', 'resolve_library_entry', 'parse_authored_invariants'}}."
        " Policy must be sourced only from load_invariants(operator_file), the "
        "argument-free default_invariants(), the LIBRARY table via "
        "resolve_library_entry(name), or parse_authored_invariants(authored payload)."
    )
    # The default reads nothing: its provenance safety is that it takes no input at all, so
    # there is no argument through which a trace could ever reach it.
    assert list(inspect.signature(invariants.default_invariants).parameters) == [], (
        "default_invariants must take no arguments — a records/trace parameter would turn "
        "the zero-config default into a trace-to-policy path."
    )

    # It takes a file path, not records. A loader that accepted a trace/records argument
    # would be exactly the trace-to-policy path this boundary forbids.
    params = list(inspect.signature(load_invariants).parameters)
    assert params == ["path"], (
        f"load_invariants parameters are {params}; it must take only a file path. "
        "A records/trace parameter would open a trace-to-policy path."
    )

    # The library resolver (the deliberate third producer) takes ONLY the entry name.
    # There is no second argument — no path, no records — through which a trace could
    # ever reach the table.
    resolver_params = list(inspect.signature(invariants.resolve_library_entry).parameters)
    assert resolver_params == ["name"], (
        f"resolve_library_entry parameters are {resolver_params}; it must take only the "
        "entry name. A records/trace parameter would open a trace-to-policy path."
    )

    # The authored-artifact parser (the deliberate fourth producer) takes ONLY the parsed
    # JSON payload. There is no second argument — no path, no records — through which a
    # trace could ever reach it; the control trace is calibration evidence only, never a
    # policy source.
    authored_params = list(inspect.signature(invariants.parse_authored_invariants).parameters)
    assert authored_params == ["payload"], (
        f"parse_authored_invariants parameters are {authored_params}; it must take only "
        "the authored artifact payload. A records/trace parameter would open a "
        "trace-to-policy path."
    )

    # The resolver performs NO file I/O: policy comes from the module-level LIBRARY
    # table, never from a file path that could be pointed at trace records. Asserted on
    # the bytecode's referenced names, so a future `Path(...)`/`open(...)` addition
    # breaks the build rather than silently widening the surface.
    resolver_names = set(invariants.resolve_library_entry.__code__.co_names)
    file_io_names = {
        "open", "Path", "read_text", "read_bytes", "write_text",
        "json", "load", "iterdir", "glob", "scandir",
    }
    assert not (resolver_names & file_io_names), (
        f"resolve_library_entry references {sorted(resolver_names & file_io_names)}, "
        "which are file-I/O names; the resolver must consult ONLY the module table."
    )

    # No callable in this module — public OR private — with "trace"/"record" in its name
    # may CALL the resolver. A trace-shaped reader that reached into the library table
    # would be exactly the trace->policy path the boundary forbids, in private clothing.
    for name, obj in vars(invariants).items():
        if not callable(obj) or getattr(obj, "__module__", None) != invariants.__name__:
            continue
        lowered = name.lower()
        if "trace" in lowered or "record" in lowered:
            assert "resolve_library_entry" not in set(obj.__code__.co_names), (
                f"{name!r} calls resolve_library_entry — library selection must never "
                "come from a trace/records-named path."
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
