"""A1 / C5: the invariant declaration format and its operator-file loader.

A1 is the axis that catches a **cheating** agent — one whose trace is perfectly faithful
(it really did delete the test) and so sails past A2 replay-conformance as a correct PASS.
What A2 cannot see, a declared invariant can: the run was held to a TASK-scoped policy
(`tests/` is read-only for this task), and the mutation violated it. That is corrupt
success caught with zero model involvement.

**The provenance boundary is the whole reason this module is a separate loader.** The
invariant is the OPERATOR's policy; the trace is the AGENT's evidence. They must never
mix. If a run could author a permissive invariant into its own trace and have A1 honour
it, A1 is defeated by construction — the agent grades its own homework. So the only way to
obtain an Invariant here is `load_invariants(operator_file)`. Nothing reads policy from a
trace, and `test_no_invariant_is_ever_sourced_from_a_trace` asserts that absence
structurally, so a future trace-reading loader breaks the build rather than silently
opening the hole.

**Scope is raw bytes, mirroring BTH-1.** A path decoded to `str` reintroduces the unicode
normalisation trap BTH-1 goes to lengths to avoid: two genuinely different filename byte
sequences can compare equal once decoded. The later byte-prefix match (`b"tests/"` covers
`b"tests/test_auth.py"`) must run on the same raw bytes BTH-1 and `effect._paths` use, so
the JSON scope string is encoded with `os.fsencode` — the one encoding paths take
everywhere else in `src/belay`.

**Fail-closed.** A malformed file, the wrong shape, or a rule Belay does not understand is
a named `ValueError`, never a silent empty list. An operator who declared a policy Belay
then swallowed would be reporting the run against *no* policy — the exact false PASS this
axis exists to refuse. `read-only` is the only rule v0 implements; `no-create`/`no-delete`
are reserved names, deliberately NOT accepted yet, so an unimplemented rule cannot pass for
an enforced one.

Zero runtime dependencies: stdlib `json` only. No model is consulted — this is pure data
and a JSON parse, and the zero-LLM AST guard covers `src/belay/verify/`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: The rules v0 understands. Only `read-only` is enforced today; the reserved names are
#: listed nowhere here on purpose — an unimplemented rule must be REJECTED, not quietly
#: accepted as if it were enforced, so the set of accepted rules is exactly the set that
#: works.
_KNOWN_RULES = frozenset({"read-only"})


@dataclass(frozen=True)
class Invariant:
    """One operator-declared policy: a `rule` scoped to a subtree by raw path bytes.

    `scope` is raw bytes (a `os.fsencode`-encoded path prefix) so a later byte-prefix
    match runs on the same bytes BTH-1 records, keeping the unicode-normalisation safety
    BTH-1 buys. `rule` is a validated member of `_KNOWN_RULES`.
    """

    scope: bytes
    rule: str


def load_invariants(path: Path) -> list[Invariant]:
    """Load operator-declared invariants from a JSON file. The ONLY way to obtain policy.

    The file is a JSON list of `{"scope": "<str>", "rule": "<str>"}` objects. Each scope
    string is encoded to raw bytes with `os.fsencode` (matching BTH-1 / `effect._paths`);
    each rule is checked against `_KNOWN_RULES`. `[]` is valid — the operator declared no
    invariants. Anything malformed (not JSON, not a list, wrong item shape, or an unknown
    rule) raises `ValueError` with a message that names the problem — never a silent `[]`,
    never a raw traceback.

    It takes a filesystem `path`, never trace records. That signature IS the provenance
    boundary: policy is sourced from a file the operator controls, not from the
    agent-produced trace.
    """
    file_path = Path(path)
    try:
        text = file_path.read_text()
    except OSError as exc:
        raise ValueError(f"could not read invariant file {file_path!r}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invariant file {file_path!r} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, list):
        raise ValueError(
            f"invariant file {file_path!r} must contain a JSON list of invariants, "
            f"got {type(raw).__name__}"
        )

    invariants: list[Invariant] = []
    for i, item in enumerate(raw):
        invariants.append(_parse_invariant(item, index=i, source=file_path))
    return invariants


def _parse_invariant(item: object, *, index: int, source: Path) -> Invariant:
    """One list entry -> a validated `Invariant`, or a `ValueError` naming what was wrong."""
    where = f"invariant #{index} in {source!r}"

    if not isinstance(item, dict):
        raise ValueError(f"{where} must be an object, got {type(item).__name__}")

    scope = item.get("scope")
    if not isinstance(scope, str):
        raise ValueError(
            f"{where} has a non-string scope ({scope!r}); scope must be a path string"
        )

    rule = item.get("rule")
    if not isinstance(rule, str):
        raise ValueError(
            f"{where} has a non-string rule ({rule!r}); rule must be a string"
        )
    if rule not in _KNOWN_RULES:
        known = ", ".join(sorted(_KNOWN_RULES))
        raise ValueError(
            f"{where} declares unknown rule {rule!r}; Belay v0 understands only: {known}. "
            "An unknown rule is rejected, not ignored — silently dropping it would verify "
            "the run against less than the operator declared."
        )

    return Invariant(scope=os.fsencode(scope), rule=rule)


__all__ = ["Invariant", "load_invariants"]
