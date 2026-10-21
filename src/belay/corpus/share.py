"""Issue #58: the shareable pattern catalog — a strict whitelist of facts, never a case.

Phase 2's third goal is "the team's failure corpus as a queryable, growing asset". A case
cannot travel: it bundles the trace, the target turn's pre-state tree, the server command
and the case id, so moving one would move raw workspace data (the no-raw-data-egress
guardrail, R12). What travels instead is the **pattern** — the whitelisted facts that made
the case a case:

    pattern_id        sha256 over the canonical facts below; not reversible to a case
    label             the human ground-truth label
    reduced_status    the stored verdict's reduced status
    sub_verdicts      [{"axis", "kind", "status"}] only
    tools             tool NAMES only
    invariant_rules   rule NAMES only (never the scope bytes — a scope is a path)
    trajectory        the instance-level status only (never its cause)
    claim             the instance-level status only (never its cause or check source)

**Never exported:** trace, manifests, pre-state, server command, case id, provenance,
paths, arguments, content, cause strings, recorded-miss notes. `pattern_of` is the one
place that reads a `Case`; the bundle is built from its output alone, so a field that is
not in the whitelist has no route into the bytes.

## Imported patterns are NOT cases

They live in `<corpus-dir>/patterns.json`, a FILE beside the case directories. They are
never replayed (`corpus run` iterates directories, and a pattern has no trace or pre-state
to replay) and never scored (`corpus score` reads `*/case.json`). Mixing a stranger's
labels into your own precision/recall would launder their provenance into your measurement,
so the separation is structural, not a flag.

`pattern_id` is a sha256 over the canonical whitelisted facts: two teams that saw the same
pattern dedupe to one entry, and no instance name can be recovered from the id.

Zero runtime dependencies (stdlib `hashlib`/`json`/`os`/`tempfile`/`pathlib`). No model is
consulted; the export is deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from belay.corpus.case import (
    Case,
    _KNOWN_CLAIM_STATUSES,
    _KNOWN_LABELS,
    _KNOWN_STATUSES,
    _KNOWN_SUB_STATUSES,
)

#: The bundle schema. An unknown or absent schema is refused whole, never repaired.
PATTERN_SCHEMA = "belay-corpus-patterns/1"

#: Where a corpus stores its imported patterns. A file, deliberately: `corpus run` iterates
#: directories, so a pattern can never be mistaken for something replayable.
PATTERNS_FILENAME = "patterns.json"

#: The facts a pattern carries, and therefore the exact keys of a bundle entry (plus
#: `pattern_id`). Order is the human reading order used in messages, not a byte contract.
_FACTS = (
    "label",
    "reduced_status",
    "sub_verdicts",
    "tools",
    "invariant_rules",
    "trajectory",
    "claim",
)
_ENTRY_KEYS = frozenset(_FACTS) | {"pattern_id"}
_SUB_KEYS = frozenset({"axis", "kind", "status"})


def _fail(message: str) -> ValueError:
    """A named, fail-closed refusal. The caller (CLI) turns it into exit 2."""
    return ValueError(f"pattern bundle {message}")


def pattern_of(case: Case) -> dict:
    """The whitelisted facts of one case — and nothing else.

    Raises a named `ValueError` when a fact the whitelist needs is malformed (a sub-verdict
    without `axis`/`kind`/`status`, an invariant without a rule name). Refusing beats
    exporting a pattern that names no dimension: this is a share surface, not a reporter.
    Sub-verdicts and rule names are sorted so the serialized bytes are deterministic.
    """
    sub_verdicts = []
    for sub in case.expected["sub_verdicts"]:
        axis = sub.get("axis") if isinstance(sub, dict) else None
        kind = sub.get("kind") if isinstance(sub, dict) else None
        status = sub.get("status") if isinstance(sub, dict) else None
        if not all(isinstance(value, str) for value in (axis, kind, status)):
            raise ValueError(
                f"case {case.id!r} sub-verdict {sub!r} does not name a string "
                f"'axis'/'kind'/'status'; a shared pattern must name its dimension"
            )
        sub_verdicts.append({"axis": axis, "kind": kind, "status": status})
    sub_verdicts.sort(key=lambda entry: (entry["axis"], entry["kind"], entry["status"]))

    rules = []
    for invariant in case.invariants:
        rule = invariant.get("rule") if isinstance(invariant, dict) else None
        if not isinstance(rule, str) or not rule:
            raise ValueError(
                f"case {case.id!r} has an invariant with no rule name; a shared pattern "
                f"carries rule names only, never scope bytes"
            )
        rules.append(rule)

    tool = case.target_tool
    if tool is not None and (not isinstance(tool, str) or not tool):
        raise ValueError(
            f"case {case.id!r} field 'target_tool' is {tool!r}; a shared pattern carries "
            f"tool names only"
        )

    trajectory = case.trajectory.get("status") if case.trajectory else None
    claim = case.claim.get("status") if case.claim else None
    return {
        "label": case.human_label,
        "reduced_status": case.expected["reduced_status"],
        "sub_verdicts": sub_verdicts,
        "tools": [tool] if tool else [],
        "invariant_rules": sorted(set(rules)),
        "trajectory": trajectory,
        "claim": claim,
    }


def pattern_id(pattern: dict) -> str:
    """`sha256:` + the hex digest of `pattern`'s canonical JSON.

    Canonical means `sort_keys=True` over the whitelisted facts ALONE: the id is stable
    across runs, machines and case names, and two identical patterns dedupe to one entry.
    It cannot be walked back to a case id — the input carries no name, path or trace.
    """
    canonical = json.dumps(pattern, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _entry(pattern: dict) -> dict:
    return {"pattern_id": pattern_id(pattern), **pattern}


def build_bundle(cases: Iterable[Case]) -> dict:
    """The `belay-corpus-patterns/1` document for `cases`: sorted by id, deduped.

    Two cases that saw the same pattern collapse to one entry — the id IS the pattern —
    and the result is sorted by id so the same corpus always serializes to the same bytes.
    """
    entries = {pattern_id(p): _entry(p) for p in (pattern_of(case) for case in cases)}
    return {
        "schema": PATTERN_SCHEMA,
        "patterns": [entries[key] for key in sorted(entries)],
    }


def _require_str(value: object, where: str, field: str) -> str:
    if not isinstance(value, str):
        raise _fail(f"entry {where} field {field!r} is {value!r}; must be a string")
    return value


def _require_str_list(value: object, where: str, field: str) -> list:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _fail(f"entry {where} field {field!r} is {value!r}; must be a list of strings")
    return value


def _validate_entry(raw: object, where: str) -> dict:
    """Validate one entry against the whitelist; return it in canonical key order.

    Every whitelisted key is REQUIRED and every other key is refused: a bundle cannot
    smuggle a trace behind a valid schema, and a reader cannot silently drop a fact it did
    not understand.
    """
    if not isinstance(raw, dict):
        raise _fail(f"entry {where} must be an object, got {type(raw).__name__}")

    missing = _ENTRY_KEYS - raw.keys()
    if missing:
        raise _fail(f"entry {where} is missing required key(s): {', '.join(sorted(missing))}")
    unknown = raw.keys() - _ENTRY_KEYS
    if unknown:
        raise _fail(f"entry {where} carries unknown key(s): {', '.join(sorted(unknown))}")

    label = _require_str(raw["label"], where, "label")
    if label not in _KNOWN_LABELS:
        raise _fail(
            f"entry {where} field 'label' is {label!r}; must be one of: "
            f"{', '.join(sorted(_KNOWN_LABELS))}"
        )

    reduced_status = _require_str(raw["reduced_status"], where, "reduced_status")
    if reduced_status not in _KNOWN_STATUSES:
        raise _fail(
            f"entry {where} field 'reduced_status' is {reduced_status!r}; must be one of: "
            f"{', '.join(sorted(_KNOWN_STATUSES))}"
        )

    sub_verdicts = raw["sub_verdicts"]
    if not isinstance(sub_verdicts, list):
        raise _fail(f"entry {where} field 'sub_verdicts' is {sub_verdicts!r}; must be a list")
    validated_subs = []
    for sub in sub_verdicts:
        if not isinstance(sub, dict) or set(sub) != _SUB_KEYS:
            raise _fail(
                f"entry {where} field 'sub_verdicts' entry {sub!r} must be an object with "
                f"exactly 'axis', 'kind' and 'status'"
            )
        for key in _SUB_KEYS:
            _require_str(sub[key], where, f"sub_verdicts.{key}")
        if sub["status"] not in _KNOWN_SUB_STATUSES:
            raise _fail(
                f"entry {where} field 'sub_verdicts' entry has status {sub['status']!r}; "
                f"must be one of: {', '.join(sorted(_KNOWN_SUB_STATUSES))}"
            )
        validated_subs.append(
            {"axis": sub["axis"], "kind": sub["kind"], "status": sub["status"]}
        )

    tools = _require_str_list(raw["tools"], where, "tools")
    invariant_rules = _require_str_list(raw["invariant_rules"], where, "invariant_rules")

    trajectory = raw["trajectory"]
    if trajectory is not None and (not isinstance(trajectory, str) or trajectory not in _KNOWN_STATUSES):
        raise _fail(
            f"entry {where} field 'trajectory' is {trajectory!r}; must be null or one of: "
            f"{', '.join(sorted(_KNOWN_STATUSES))}"
        )

    claim = raw["claim"]
    if claim is not None and (not isinstance(claim, str) or claim not in _KNOWN_CLAIM_STATUSES):
        raise _fail(
            f"entry {where} field 'claim' is {claim!r}; must be null or one of: "
            f"{', '.join(sorted(_KNOWN_CLAIM_STATUSES))}"
        )

    facts = {
        "label": label,
        "reduced_status": reduced_status,
        "sub_verdicts": validated_subs,
        "tools": sorted(set(tools)),
        "invariant_rules": sorted(set(invariant_rules)),
        "trajectory": trajectory,
        "claim": claim,
    }

    declared_id = _require_str(raw["pattern_id"], where, "pattern_id")
    expected_id = pattern_id(facts)
    if declared_id != expected_id:
        raise _fail(
            f"entry {where} field 'pattern_id' is {declared_id!r}, which does not match "
            f"its facts ({expected_id}); the id is the pattern, so a mismatch is a "
            f"hand-edited or corrupted entry"
        )

    return {"pattern_id": expected_id, **facts}


def parse_bundle(raw: object) -> list:
    """Validate a whole bundle and return its entries, sorted by `pattern_id`.

    Fail-closed and whole: not JSON, a non-object, an absent/wrong schema, an unknown
    top-level key, `patterns` not a list, or one malformed entry refuses the ENTIRE bundle
    with a named `ValueError`. A partial import would merge a stranger's labels without the
    facts that made them a pattern, so there is no partial path.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _fail(f"is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise _fail(f"must be an object, got {type(raw).__name__}")

    schema = raw.get("schema")
    if schema != PATTERN_SCHEMA:
        raise _fail(f"schema is {schema!r}; must be {PATTERN_SCHEMA!r}")

    unknown = raw.keys() - {"schema", "patterns"}
    if unknown:
        raise _fail(f"carries unknown top-level key(s): {', '.join(sorted(unknown))}")

    patterns = raw.get("patterns")
    if not isinstance(patterns, list):
        raise _fail(f"field 'patterns' is {patterns!r}; must be a list")

    entries = [_validate_entry(entry, f"#{index}") for index, entry in enumerate(patterns)]
    return sorted(entries, key=lambda entry: entry["pattern_id"])


def _document(patterns: list) -> str:
    """The deterministic on-disk text for a catalog of `patterns`.

    `indent=2, sort_keys=True` and a trailing newline: the same catalog always produces the
    same bytes, in a file diff and in a bundle a human inspects before sending it.
    """
    return (
        json.dumps(
            {"schema": PATTERN_SCHEMA, "patterns": patterns}, indent=2, sort_keys=True
        )
        + "\n"
    )


def _write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` via a same-directory temp file and `os.replace`.

    Atomic so a failed or interrupted write never leaves a half-document where a reader
    would take it for the whole catalog. The temp file is removed on failure.
    """
    path = Path(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def write_bundle(path: Path, patterns: list) -> None:
    """Write a deterministic patterns document to `path`, atomically.

    Used by `share export --out` and by the catalog file itself; both carry the same
    schema, so an exported bundle can be dropped straight into `<corpus-dir>/patterns.json`.
    """
    _write_atomic(Path(path), _document(merge_patterns([], patterns)))


def load_patterns(corpus_dir: Path) -> list:
    """The catalog at `<corpus_dir>/patterns.json`, or `[]` when there is none.

    Fail-closed: an unreadable or malformed file is a named `ValueError`, never an empty
    read. Silently returning `[]` would make the next import overwrite a catalog whose
    patterns the operator could no longer see.
    """
    path = Path(corpus_dir) / PATTERNS_FILENAME
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        return parse_bundle(text)
    except (OSError, ValueError) as exc:
        raise ValueError(f"pattern catalog {path}: {exc}") from exc


def merge_patterns(existing: list, new: list) -> list:
    """Union of two catalogs, deduped by `pattern_id` and sorted by it.

    Idempotent: importing the same bundle twice changes nothing. The id IS the pattern, so
    two entries with one id carry identical facts; the first wins (they agree).
    """
    merged = {entry["pattern_id"]: entry for entry in existing}
    for entry in new:
        merged.setdefault(entry["pattern_id"], entry)
    return [merged[key] for key in sorted(merged)]


def save_patterns(corpus_dir: Path, patterns: list) -> None:
    """Write `<corpus_dir>/patterns.json` (deterministic, atomic), creating the dir.

    A file, never a directory: `corpus run` iterates directories, so nothing here can be
    mistaken for a replayable case.
    """
    corpus_dir = Path(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    write_bundle(corpus_dir / PATTERNS_FILENAME, patterns)


__all__ = [
    "PATTERN_SCHEMA",
    "PATTERNS_FILENAME",
    "build_bundle",
    "load_patterns",
    "merge_patterns",
    "parse_bundle",
    "pattern_id",
    "pattern_of",
    "save_patterns",
    "write_bundle",
]
