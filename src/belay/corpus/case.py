"""The on-disk corpus case format: a labeled, replayable failure, read fail-closed.

A `Case` is one caught failure preserved so `belay corpus run` (a later C6 phase) can
re-replay it and assert it still reaches its recorded verdict. The corpus IS the
regression suite, so a case that loaded wrong — a swallowed malformed field silently
defaulted — would regress the run against a case that is not the one that was captured.
That is the exact false result the whole axis exists to refuse, so this loader mirrors
`belay.verify.invariants.load_invariants`: every malformed input is a NAMED `ValueError`,
never a silent default. The ONE documented default is `human_label` omitted -> `pending`.

## The case directory layout (the Phase 2 contract)

A case is a DIRECTORY, not a single file. This task owns only `case.json`; the sibling
artifacts are composed by `corpus add` in a later phase, which is why they are documented
here rather than built:

    <case>/
      case.json      # this module: the case metadata (id, expected verdict, label, ...)
      trace.jsonl    # (Phase 2) the recorded trajectory the case replays
      manifest.json  # (Phase 2) the snapshot manifest, with a case-RELATIVE tree_path
      prestate/      # (Phase 2) the snapshot tree, copied in so the case is self-contained

The relative `tree_path` in `manifest.json` is what makes a case portable between
machines; `belay.replay.persist.load_snapshot` resolves it against the manifest's own
directory. `write_case`/`load_case` here handle ONLY `case.json`.

Zero runtime dependencies: stdlib `json`, `pathlib`, `dataclasses` only. No model is
consulted — this is pure data and a JSON parse.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: The four human ground-truth labels a case may carry. `pending` is the default the
#: engine writes; a human relabels it to one of the other three. Listing exactly these
#: means an unknown label is REJECTED, not silently accepted — the same fail-closed shape
#: `_KNOWN_RULES` gives `load_invariants`.
_KNOWN_LABELS = frozenset({"true-positive", "false-positive", "unverifiable", "pending"})

#: The default label when `case.json` omits `human_label`. This is the ONLY silent default
#: this loader allows; every other missing-or-malformed field is a named `ValueError`.
_DEFAULT_LABEL = "pending"

#: The reduced-verdict statuses a recorded `expected` may claim, borrowed from the verdict
#: contract. An `expected.reduced_status` outside this set is rejected, so a case cannot
#: regress against a verdict Belay would never emit.
#:
#: `NOT_COVERED` is deliberately ABSENT. It is sub-verdict-only — `verdict.reduce` filters
#: it out before ranking, so no turn can ever reduce to it — and this allowlist is one of
#: the three defenses named in the PRD against it leaking into a reduced status: with a
#: NOT_COVERED `reduced_status` in hand, `corpus/metrics.py` would fold a not-FAIL case
#: into a DECIDED non-detection and score "could not check" as "checked and cleared".
_KNOWN_STATUSES = frozenset({"PASS", "WARN", "FAIL", "UNVERIFIED"})

#: The statuses an individual entry of `expected.sub_verdicts` may carry: the reduced set
#: PLUS `NOT_COVERED`, which is exactly where that status is legal. Every case minted
#: against an `openWorldHint: false` server (the reference filesystem server, i.e. the
#: common case) now carries one, so a loader that refused it could not store the corpus.
_KNOWN_SUB_STATUSES = _KNOWN_STATUSES | {"NOT_COVERED"}

#: The `schema_version` written into every new `case.json`. Optional on load and defaulted,
#: NOT added to `_REQUIRED_FIELDS` — that tuple is closed and fail-closed, so a required
#: new field would reject every case already sitting in `corpus/local/`. Version 1 is the
#: format as of the `NOT_COVERED` change; a case written before it simply lacks the key and
#: reads back as 1, which is true (nothing about the older format differs).
CASE_SCHEMA_VERSION = 1

#: A `root_cause.key` must match this: lowercase alphanumeric words joined by single
#: hyphens. The key is what `corpus score` GROUPS ON to count independent findings, so a
#: typo'd or free-form key would silently split one finding into two and inflate the count
#: the gate is read against. Rejecting it here makes that a loud error instead.
_ROOT_CAUSE_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: The case.json keys that MUST be present (every field except `human_label`, which
#: defaults). Order is the stable field order used when constructing a `Case`.
_REQUIRED_FIELDS = (
    "id",
    "target_turn_index",
    "expected",
    "invariants",
    "server_command",
    "replays",
    "timeout",
    "provenance",
    "capture_platform",
    "capture_capabilities",
)

CASE_FILENAME = "case.json"


@dataclass(frozen=True)
class Case:
    """One labeled, replayable failure, as stored in a case directory's `case.json`.

    `expected` is the recorded verdict to regress against — plain data of shape
    `{"reduced_status": <status>, "sub_verdicts": [{"axis", "kind", "status"}, ...]}`.
    `human_label` is the human ground-truth, one of `_KNOWN_LABELS`; the engine only ever
    writes `pending`. `provenance` carries `{"source_trace_id", "captured_at"}`, both
    passed in — this module never reads a clock. `schema_version` is the on-disk format
    version, defaulted so that every existing case (and every existing constructor call)
    keeps working unchanged.
    """

    id: str
    target_turn_index: int
    expected: dict
    human_label: str
    invariants: list[dict]
    server_command: list[str]
    replays: int
    timeout: float
    provenance: dict
    capture_platform: str
    capture_capabilities: list[str]
    schema_version: int = CASE_SCHEMA_VERSION
    root_cause: Optional[dict] = None
    target_tool: Optional[str] = None


def _validate_root_cause(raw: object, path: Path) -> Optional[dict]:
    """Validate an on-disk `root_cause`, or raise a named `ValueError`.

    Shape is `{"key": <kebab-case str>, "note": <str>}`. `key` is the grouping key
    `corpus score` counts independent findings by; `note` is the human's prose, which
    nothing groups on. Absent -> `None`, the same single silence `human_label` is allowed.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"case file {path!r} field 'root_cause' must be an object with 'key' and "
            f"'note', got {type(raw).__name__}"
        )
    for key in ("key", "note"):
        if key not in raw:
            raise ValueError(f"case file {path!r} field 'root_cause' is missing {key!r}")
        if not isinstance(raw[key], str):
            raise ValueError(
                f"case file {path!r} field 'root_cause.{key}' must be a string, "
                f"got {type(raw[key]).__name__}"
            )
    if not _ROOT_CAUSE_KEY_RE.match(raw["key"]):
        raise ValueError(
            f"case file {path!r} field 'root_cause.key' is {raw['key']!r}; must be "
            f"kebab-case (lowercase words joined by single hyphens) so that grouping "
            f"independent findings cannot be split by a typo"
        )
    return raw


def _to_payload(case: Case) -> dict:
    """A `Case` as the JSON dict written to `case.json`.

    `root_cause` and `target_tool` are OMITTED when unset rather than written as `null`:
    a default is never a declaration, so "nobody adjudicated a cause" must stay
    distinguishable from "a cause was recorded as empty".
    """
    optional = {
        name: value
        for name, value in (("root_cause", case.root_cause), ("target_tool", case.target_tool))
        if value is not None
    }
    return {
        **optional,
        "id": case.id,
        "target_turn_index": case.target_turn_index,
        "expected": case.expected,
        "human_label": case.human_label,
        "invariants": case.invariants,
        "server_command": case.server_command,
        "replays": case.replays,
        "timeout": case.timeout,
        "provenance": case.provenance,
        "capture_platform": case.capture_platform,
        "capture_capabilities": case.capture_capabilities,
        "schema_version": case.schema_version,
    }


def write_case(case_dir: Path, case: Case) -> None:
    """Write `case`'s metadata to `<case_dir>/case.json` (indent=2, sorted keys).

    Sorted keys and a fixed indent make the on-disk form deterministic, so a re-persisted
    case is byte-identical and diffs cleanly in the corpus. Only `case.json` is written;
    the sibling artifacts (`trace.jsonl`, `manifest.json`, `prestate/`) are `corpus add`'s.
    """
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_to_payload(case), indent=2, sort_keys=True)
    (case_dir / CASE_FILENAME).write_text(text, encoding="utf-8")


def load_case(case_dir: Path) -> Case:
    """Load and validate `<case_dir>/case.json` into a `Case`, or raise a named `ValueError`.

    Fail-closed, mirroring `load_invariants`: not-JSON, a missing required field, an
    `expected` missing `reduced_status`/`sub_verdicts`, an out-of-range `reduced_status`,
    a sub-verdict status outside `_KNOWN_SUB_STATUSES`, a non-integer `schema_version`, or
    a `human_label` outside `_KNOWN_LABELS` each raise a `ValueError` naming the problem —
    never a silent default. Two fields may be omitted and defaulted: `human_label` ->
    `pending`, and `schema_version` -> `CASE_SCHEMA_VERSION` (a case written before the
    field existed). Round-trips: `load_case(write_case(dir, c))` equals `c`.
    """
    path = Path(case_dir) / CASE_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read case file {path!r}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"case file {path!r} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"case file {path!r} must contain a JSON object, got {type(raw).__name__}"
        )

    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise ValueError(f"case file {path!r} is missing required field {field!r}")

    expected = raw["expected"]
    if not isinstance(expected, dict):
        raise ValueError(
            f"case file {path!r} field 'expected' must be an object, "
            f"got {type(expected).__name__}"
        )
    for key in ("reduced_status", "sub_verdicts"):
        if key not in expected:
            raise ValueError(
                f"case file {path!r} field 'expected' is missing {key!r}"
            )
    reduced_status = expected["reduced_status"]
    if reduced_status not in _KNOWN_STATUSES:
        known = ", ".join(sorted(_KNOWN_STATUSES))
        raise ValueError(
            f"case file {path!r} field 'expected.reduced_status' is {reduced_status!r}; "
            f"must be one of: {known}"
        )

    sub_verdicts = expected["sub_verdicts"]
    if not isinstance(sub_verdicts, list):
        raise ValueError(
            f"case file {path!r} field 'expected.sub_verdicts' must be a list, "
            f"got {type(sub_verdicts).__name__}"
        )
    for sub in sub_verdicts:
        if not isinstance(sub, dict) or "status" not in sub:
            raise ValueError(
                f"case file {path!r} field 'expected.sub_verdicts' entry {sub!r} "
                f"must be an object with a 'status'"
            )
        if sub["status"] not in _KNOWN_SUB_STATUSES:
            known = ", ".join(sorted(_KNOWN_SUB_STATUSES))
            raise ValueError(
                f"case file {path!r} field 'expected.sub_verdicts' entry has status "
                f"{sub['status']!r}; must be one of: {known}"
            )

    # Absent -> the default, the same single silence `human_label` is allowed. Present but
    # not an int (a `"1"`, a float, a bool) is a NAMED error: a version we cannot compare
    # is worse than no version, because a later reader would branch on it.
    schema_version = raw.get("schema_version", CASE_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError(
            f"case file {path!r} field 'schema_version' is {schema_version!r}; "
            f"must be an integer"
        )

    root_cause = _validate_root_cause(raw.get("root_cause"), path)

    target_tool = raw.get("target_tool")
    if target_tool is not None and not isinstance(target_tool, str):
        raise ValueError(
            f"case file {path!r} field 'target_tool' is {target_tool!r}; must be a string"
        )

    human_label = raw.get("human_label", _DEFAULT_LABEL)
    if human_label not in _KNOWN_LABELS:
        known = ", ".join(sorted(_KNOWN_LABELS))
        raise ValueError(
            f"case file {path!r} field 'human_label' is {human_label!r}; "
            f"must be one of: {known}"
        )

    return Case(
        id=raw["id"],
        target_turn_index=raw["target_turn_index"],
        expected=expected,
        human_label=human_label,
        invariants=raw["invariants"],
        server_command=raw["server_command"],
        replays=raw["replays"],
        timeout=raw["timeout"],
        provenance=raw["provenance"],
        capture_platform=raw["capture_platform"],
        capture_capabilities=raw["capture_capabilities"],
        schema_version=schema_version,
        root_cause=root_cause,
        target_tool=target_tool,
    )


__all__ = ["Case", "load_case", "write_case", "CASE_FILENAME", "CASE_SCHEMA_VERSION"]
