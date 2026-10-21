"""Issue #58: the shareable PATTERN CATALOG — a strict whitelist, never a raw case.

Phase 2's third goal is "the team's failure corpus as a queryable, growing asset", but a
case bundles the trace, the pre-state tree and the server command. The no-raw-data-egress
guardrail forbids moving those, so what travels is the *pattern*: the whitelisted facts
that made the case a case. This file pins that whitelist in three ways:

1. **The key set is exact.** `pattern_of` emits exactly the PRD's eight keys, and the
   sub-verdict entries carry exactly `axis`/`kind`/`status`. An extra key is a leak by
   construction, so it is a test failure, not a review question.
2. **Nothing forbidden reaches the bytes.** The serialized bundle is searched for
   sentinels planted in every non-whitelisted field (trace, manifest, pre-state, server
   command, case id, provenance, paths, arguments, content, cause strings, miss notes).
3. **Import is fail-closed.** A bundle that is not exactly this schema is refused whole,
   with a named `ValueError` — never partially merged, never silently defaulted.

And the rule the whole feature rests on: **imported patterns are NOT cases.** They are
never replayed and never scored; `patterns.json` is a file beside the case directories, and
`corpus run`/`score`/`list` are byte-identical with it present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import Case
from belay.corpus.share import (
    PATTERN_SCHEMA,
    build_bundle,
    parse_bundle,
    pattern_id,
    pattern_of,
)

#: The exact whitelist. If this changes, the PRD changed.
FACTS = {"label", "reduced_status", "sub_verdicts", "tools", "invariant_rules", "trajectory", "claim"}
ENTRY_KEYS = FACTS | {"pattern_id"}


def _case(
    cid: str = "case-a",
    label: str = "true-positive",
    *,
    status: str = "FAIL",
    tool: str | None = "edit_file",
    rules: tuple[str, ...] = ("read-only",),
    scope: str = "tests/",
    trajectory: dict | None = None,
    claim: dict | None = None,
) -> Case:
    """A case carrying every field, with the forbidden ones set to unique sentinels.

    The sentinels are what the leak test searches for; the whitelisted values are ordinary
    so the exact-key assertions stay readable.
    """
    return Case(
        id=cid,
        target_turn_index=7,
        expected={
            "reduced_status": status,
            "sub_verdicts": [
                {"axis": "A2", "kind": "effect", "status": "PASS"},
                {"axis": "A1", "kind": "invariant", "status": "FAIL"},
            ],
        },
        human_label=label,
        invariants=[{"scope": scope, "rule": rule} for rule in rules],
        server_command=["SECRET-SERVER-COMMAND", "editor_server.py"],
        replays=3,
        timeout=30.0,
        provenance={
            "source_trace_id": "SECRET-TRACE-ID",
            "captured_at": "SECRET-CAPTURED-AT",
        },
        capture_platform="darwin",
        capture_capabilities=["SECRET-CAPABILITY"],
        root_cause={"key": "secret-cause-key", "note": "SECRET-CAUSE-NOTE"},
        target_tool=tool,
        recorded_miss=None,
        trajectory=trajectory,
        claim=claim,
    )


# --- Task 1: the whitelist and the bundle ------------------------------------------------


def test_pattern_is_exactly_the_whitelist() -> None:
    """`pattern_of` emits the eight facts and nothing else — sub-verdicts are axis/kind/status."""
    case = _case(
        trajectory={"status": "FAIL", "cause": "SECRET-TRAJECTORY-CAUSE"},
        rules=("read-only", "no-assertion-weakening", "read-only"),
    )

    pattern = pattern_of(case)

    assert set(pattern) == FACTS
    assert pattern["label"] == "true-positive"
    assert pattern["reduced_status"] == "FAIL"
    assert pattern["tools"] == ["edit_file"]
    # The RULE NAMES only — the scope (a path) is never part of a pattern.
    assert pattern["invariant_rules"] == ["no-assertion-weakening", "read-only"]
    # Deterministic order, so two cases that saw the same pattern serialize identically.
    assert pattern["sub_verdicts"] == [
        {"axis": "A1", "kind": "invariant", "status": "FAIL"},
        {"axis": "A2", "kind": "effect", "status": "PASS"},
    ]
    # The STATUS only: a trajectory/claim cause is a string the pattern never carries.
    assert pattern["trajectory"] == "FAIL"
    assert pattern["claim"] is None


def test_pattern_of_a_plainer_case_uses_empty_lists_and_none() -> None:
    """No tool, no invariants, no instance-level verdict -> `[]`/`None`, never a default claim."""
    pattern = pattern_of(_case(tool=None, rules=()))

    assert pattern["tools"] == []
    assert pattern["invariant_rules"] == []
    assert pattern["trajectory"] is None
    assert pattern["claim"] is None


def test_pattern_id_is_stable_across_case_instances_and_label_sensitive() -> None:
    """Same facts -> same id (dedupe), a different label -> a different id (no laundering)."""
    a = pattern_of(_case(cid="case-a"))
    b = pattern_of(_case(cid="completely-different-case-name"))
    assert pattern_id(a) == pattern_id(b)

    assert pattern_id(a).startswith("sha256:")
    assert len(pattern_id(a)) == len("sha256:") + 64
    int(pattern_id(a)[len("sha256:"):], 16)  # hex, not a case id

    c = pattern_of(_case(cid="case-a", label="false-positive"))
    assert pattern_id(a) != pattern_id(c)


def test_bundle_is_sorted_deduped_and_self_describing() -> None:
    """Two identical cases collapse to one entry; entries are sorted by id."""
    bundle = build_bundle(
        [
            _case(cid="z", tool="write_file"),
            _case(cid="a", tool="edit_file"),
            _case(cid="dup-of-a", tool="edit_file"),
        ]
    )

    assert bundle["schema"] == PATTERN_SCHEMA == "belay-corpus-patterns/1"
    ids = [entry["pattern_id"] for entry in bundle["patterns"]]
    assert ids == sorted(ids)
    assert len(ids) == 2
    assert all(set(entry) == ENTRY_KEYS for entry in bundle["patterns"])


def test_empty_corpus_builds_a_valid_empty_bundle() -> None:
    """AC-6: an empty corpus exports an empty bundle that parses back to nothing."""
    bundle = build_bundle([])

    assert bundle == {"schema": PATTERN_SCHEMA, "patterns": []}
    assert parse_bundle(bundle) == []


def test_parse_bundle_round_trips_build_bundle() -> None:
    """What `build_bundle` writes, `parse_bundle` accepts and returns unchanged."""
    bundle = build_bundle([_case(cid="a"), _case(cid="b", tool="write_file")])

    assert parse_bundle(json.loads(json.dumps(bundle))) == bundle["patterns"]


def test_no_forbidden_fact_reaches_the_serialized_bundle() -> None:
    """The byte-level leak proof, for every field the whitelist excludes.

    Every sentinel is a string this feature must never move: the trace and manifest (which
    are not even fields of `Case` — the export test covers the files), the server command,
    the case id, provenance, the invariant *scope* (a path), a root-cause note, a recorded
    miss note, and every trajectory/claim cause or check source.
    """
    cases = [
        _case(cid="SECRET-CASE-ID", trajectory={"status": "UNVERIFIED", "cause": "SECRET-TRAJECTORY-CAUSE"}),
        _case(
            cid="SECRET-CASE-ID-2",
            status="PASS",
            claim={
                "status": "UNVERIFIED",
                "cause": "SECRET-CLAIM-CAUSE",
                "check": {"source": "SECRET-CHECK-SOURCE", "exit_code": 1},
            },
        ),
    ]
    cases.append(
        Case(
            **{
                **_case(cid="SECRET-CASE-ID-3").__dict__,
                "recorded_miss": {"note": "SECRET-MISS-NOTE"},
            }
        )
    )

    serialized = json.dumps(build_bundle(cases), sort_keys=True)

    for forbidden in (
        "SECRET-CASE-ID",
        "SECRET-SERVER-COMMAND",
        "SECRET-TRACE-ID",
        "SECRET-CAPTURED-AT",
        "SECRET-CAPABILITY",
        "SECRET-CAUSE-NOTE",
        "SECRET-MISS-NOTE",
        "SECRET-TRAJECTORY-CAUSE",
        "SECRET-CLAIM-CAUSE",
        "SECRET-CHECK-SOURCE",
        "tests/",  # the invariant SCOPE, a path — only the rule name travels
        "secret-cause-key",
        "provenance",
        "server_command",
        "manifest",
        "prestate",
        "trace",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "raw, needle",
    [
        ([], "object"),
        ({"patterns": []}, "schema"),
        ({"schema": "belay-corpus-patterns/2", "patterns": []}, "schema"),
        ({"schema": PATTERN_SCHEMA, "patterns": [], "extra": 1}, "unknown"),
        ({"schema": PATTERN_SCHEMA, "patterns": {}}, "list"),
        ({"schema": PATTERN_SCHEMA, "patterns": ["nope"]}, "object"),
        ({"schema": PATTERN_SCHEMA, "patterns": [{"label": "pending"}]}, "missing"),
    ],
)
def test_parse_bundle_refuses_a_malformed_bundle(raw, needle: str) -> None:
    """A bundle that is not exactly this schema is refused whole, named, never repaired."""
    with pytest.raises(ValueError) as exc:
        parse_bundle(raw)
    assert needle in str(exc.value)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p.update(label="bogus"), "label"),
        (lambda p: p.update(reduced_status="NOT_COVERED"), "reduced_status"),
        (lambda p: p.update(sub_verdicts=[{"axis": "A1", "kind": "x", "status": "MAYBE"}]), "sub_verdicts"),
        (lambda p: p.update(sub_verdicts=[{"axis": "A1", "kind": "x", "status": "FAIL", "extra": 1}]), "sub_verdicts"),
        (lambda p: p.update(tools="edit_file"), "tools"),
        (lambda p: p.update(tools=[1]), "tools"),
        (lambda p: p.update(invariant_rules="read-only"), "invariant_rules"),
        (lambda p: p.update(trajectory="NOT_COVERED"), "trajectory"),
        (lambda p: p.update(trajectory="bogus"), "trajectory"),
        (lambda p: p.update(claim="PASS"), "claim"),
        (lambda p: p.update(unknown_fact="x"), "unknown"),
        (lambda p: p.pop("claim"), "missing"),
        (lambda p: p.update(pattern_id="sha256:deadbeef"), "pattern_id"),
    ],
)
def test_parse_bundle_refuses_a_malformed_entry(mutate, needle: str) -> None:
    """Each whitelisted key is required and typed; an extra key or a bad id refuses the whole."""
    pattern = pattern_of(_case())
    pattern["claim"] = "UNVERIFIED"
    entry = {"pattern_id": pattern_id(pattern), **pattern}
    mutate(entry)

    with pytest.raises(ValueError) as exc:
        parse_bundle({"schema": PATTERN_SCHEMA, "patterns": [entry]})
    assert needle in str(exc.value)
