"""A1 / C5, invariant-library aspect 2: the named library table and its guarded resolver.

R3's mitigation seam: named, pre-authored, user-selectable invariant declarations with
zero JSON authoring. `LIBRARY` is module-level plain data; `resolve_library_entry(name)`
is a DELIBERATELY amended third producer of `Invariant` policy — admitted by name in
`test_no_invariant_is_ever_sourced_from_a_trace` (the guard's purpose survives: policy
still never comes from a trace) — and it constructs `Invariant` objects DIRECTLY, never
via `_parse_invariant`, so the curated `network-egress` entry can exist while operator
FILES declaring the rule are still rejected by the loader (fail-closed, exit 2).

The honesty line: `network-egress` is the one entry Belay can never ground — it has no
egress instrument (no outbound bytes are observed) and the sandbox denies egress by
construction. Its evaluation is UNVERIFIED-with-named-cause on every turn, never PASS,
never FAIL.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import belay.verify.invariants as invariants
from belay.verify.invariants import (
    LIBRARY,
    RULE_NETWORK_EGRESS,
    Invariant,
    evaluate_invariant,
    load_invariants,
    resolve_library_entry,
)
from belay.verify.verdict import Status


def test_library_has_exactly_the_five_v1_entries() -> None:
    """`LIBRARY` holds exactly the five v1 presets with their declared scope/rule pairs.

    The declarations are the OPERATOR-SHAPED strings (the same shape an `--invariants`
    file carries), each entry carries a non-empty one-line description, and the grounding
    marker says what A1 can actually stand behind: `no-create`/`no-delete` are delta
    rules, the two read-only presets are the delta-grounded `read-only` rule, and
    `network-egress` is ungrounded — the table must say so before selection, never after.
    """
    expected = {
        "no-create": {
            "declarations": ({"scope": "", "rule": "no-create"},),
            "grounding": "delta",
        },
        "no-delete": {
            "declarations": ({"scope": "", "rule": "no-delete"},),
            "grounding": "delta",
        },
        "tests-read-only": {
            "declarations": ({"scope": "tests/", "rule": "read-only"},),
            "grounding": "delta(read-only)",
        },
        "source-read-only": {
            "declarations": ({"scope": "src/", "rule": "read-only"},),
            "grounding": "delta(read-only)",
        },
        "network-egress": {
            "declarations": ({"scope": "", "rule": RULE_NETWORK_EGRESS},),
            "grounding": "ungrounded",
        },
    }

    assert set(LIBRARY) == set(expected)
    for name, wants in expected.items():
        entry = LIBRARY[name]
        assert entry.declarations == wants["declarations"], name
        assert entry.grounding == wants["grounding"], name
        assert entry.description.strip(), name

    # The curated rule name stays OUT of the loader's known set: an operator FILE
    # declaring it must still be rejected (exit 2), never silently accepted.
    assert RULE_NETWORK_EGRESS not in invariants._KNOWN_RULES


def test_resolve_library_entry_resolves_each_name_to_the_expected_invariant() -> None:
    """Each of the five names resolves to `Invariant` objects with rule + BYTE scope.

    The scope strings are `os.fsencode`-encoded exactly as the file loader encodes them,
    so a resolved entry and a file-loaded declaration of the same scope/rule are
    byte-identical policies. The whole-tree presets (`no-create`, `no-delete`,
    `network-egress`) declare an EMPTY scope — the whole-tree analogue of `read-only`'s
    empty prefix.
    """
    expected = {
        "no-create": [Invariant(scope=b"", rule="no-create")],
        "no-delete": [Invariant(scope=b"", rule="no-delete")],
        "tests-read-only": [Invariant(scope=b"tests/", rule="read-only")],
        "source-read-only": [Invariant(scope=b"src/", rule="read-only")],
        "network-egress": [Invariant(scope=b"", rule=RULE_NETWORK_EGRESS)],
    }

    for name, want in expected.items():
        assert resolve_library_entry(name) == want, name


def test_resolve_library_entry_unknown_name_is_fail_closed() -> None:
    """An unknown name is a named `ValueError` — never a silent no-policy run.

    The fail-closed contract of the file loader (a malformed file is a named error, never
    a dropped policy) applies to the library by name: a typo must not verify the run
    against nothing while reporting success.
    """
    with pytest.raises(ValueError) as excinfo:
        resolve_library_entry("bogus")

    assert "bogus" in str(excinfo.value)


def test_resolve_library_entry_takes_only_the_name() -> None:
    """The resolver's signature is exactly `["name"]` — no path, no records, nothing else.

    Pinned structurally (mirroring the loader's own `["path"]` pin in the producer
    guard): there is no second argument through which a trace or a file could ever reach
    the table.
    """
    assert list(inspect.signature(resolve_library_entry).parameters) == ["name"]


def test_network_egress_evaluates_unverified_with_named_cause_never_pass(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """`network-egress` is UNVERIFIED-with-cause on every turn — never PASS, never FAIL.

    The sandbox denies egress by construction (seccomp deny-all), and Belay has no egress
    instrument — it observes no outbound bytes — so the invariant can never be grounded.
    The honest answer is UNVERIFIED with a cause that names the boundary, exactly the
    `NOT_COVERED`/UNVERIFIED discipline everywhere else in the engine.
    """
    [inv] = resolve_library_entry("network-egress")

    # A real observed delta — even a clean no-op — cannot ground egress.
    verdict = evaluate_invariant(inv, [], turn_index=0)
    assert verdict.axis == "A1"
    assert verdict.kind == "invariant"
    assert verdict.status is Status.UNVERIFIED
    assert verdict.status is not Status.PASS
    assert verdict.status is not Status.FAIL
    assert verdict.expected["cause"] == "network-egress-unobservable"
    assert "network-egress-unobservable" in verdict.message
    assert "no egress instrument" in verdict.message
    assert "denies egress by construction" in verdict.message

    # And an UNOBSERVED delta (no post-state at all) abstains the same way — the
    # catch-all precedes the delta-None branch, so the cause is stable across both.
    unobserved = evaluate_invariant(inv, None, turn_index=0)
    assert unobserved.status is Status.UNVERIFIED
    assert unobserved.expected["cause"] == "network-egress-unobservable"


def test_operator_file_declaring_network_egress_is_still_rejected(tmp_path: Path) -> None:
    """An operator FILE declaring `network-egress` still raises — the curated entry is the
    only path, and the loader's fail-closed rejection is untouched.

    If the loader accepted the rule, the abstention loophole — "accepted by the loader,
    grounded by none" — would open for operator files, and a file could silently yield an
    invariant that never fires. The library entry is the only way to select it, and it is
    honest about being ungrounded.
    """
    path = tmp_path / "invariants.json"
    path.write_text(
        json.dumps([{"scope": "", "rule": RULE_NETWORK_EGRESS}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        load_invariants(path)

    assert RULE_NETWORK_EGRESS in str(excinfo.value)