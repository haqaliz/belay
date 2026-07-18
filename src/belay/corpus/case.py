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
from dataclasses import dataclass
from pathlib import Path

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
_KNOWN_STATUSES = frozenset({"PASS", "WARN", "FAIL", "UNVERIFIED"})

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
    passed in — this module never reads a clock.
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


def _to_payload(case: Case) -> dict:
    """A `Case` as the JSON dict written to `case.json` (every field, `human_label` too)."""
    return {
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
    or a `human_label` outside `_KNOWN_LABELS` each raise a `ValueError` naming the
    problem — never a silent default. The one allowed default is `human_label` omitted ->
    `pending`. Round-trips: `load_case(write_case(dir, c))` equals `c`.
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
    )


__all__ = ["Case", "load_case", "write_case", "CASE_FILENAME"]
