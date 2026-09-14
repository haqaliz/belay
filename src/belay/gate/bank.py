"""The baseline store: the on-disk record a gate run is later diffed against.

`belay gate baseline` verifies a capture and stores its EXPECTED verdict set, keyed
by the run's identity, under a baseline DIRECTORY:

    <baseline>/baseline.json   # schema 1: run_id, provenance, expected, stored policy
    <baseline>/trace.jsonl     # a COPY of the capture
    <baseline>/manifests/      # the run's snapshot manifests, tree_path REWRITTEN
    <baseline>/snapshots/      # the snapshot trees the rewritten tree_paths point at

## Self-contained by COPY, not reference (the corpus precedent)

The copy+rewrite mechanics are exactly `add_case`'s (`src/belay/corpus/add.py`):
a manifest joins a handle to an ABSOLUTE `tree_path` plus the sidecar bytes
(`src/belay/replay/persist.py`), so the tree is `copytree`-d into the baseline's
own `snapshots/` and the manifest's `tree_path` rewritten to the relative
`../snapshots/<handle>` — which `load_snapshot` resolves against the manifest's own
directory. Delete the original run's manifest dir and snapshot tree and the
baseline still reconstructs every pre-state. That is what makes a baseline portable
between machines and durable past a run's cleanup.

## Fail-closed, never a silent drop

A baseline that loaded wrong — a swallowed malformed field silently defaulted —
would gate against a record that is not the one that was banked. So this loader
mirrors `belay.corpus.case.load_case`: every malformed input is a named
`ValueError`, never a silent default. The ONE documented default is an omitted
`schema` reading back as 1 (a baseline written before the key existed IS version
1). And the COPY fails closed too: a manifest whose tree does not exist raises
before any baseline.json is written, and a failed copy removes its partial
directory — a baseline with dangling pre-state is never left on disk.

## No verdicts

This module writes and reads facts. Whether a re-run's verdicts match the stored
`expected` is the gate's decision (aspect 3), never decided here.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from belay.replay.persist import load_snapshot

#: The baseline document's schema version. Bumped only when the CONTRACT changes
#: deliberately; an omitted key reads back as 1 (see `_UNVERSIONED`).
BASELINE_SCHEMA = 1

BASELINE_FILENAME = "baseline.json"
_TRACE_FILENAME = "trace.jsonl"
_MANIFESTS_DIRNAME = "manifests"
_SNAPSHOTS_DIRNAME = "snapshots"

#: The baseline.json keys that MUST be present. A missing one is a named error,
#: never a silent drop.
_REQUIRED_FIELDS = ("run_id", "provenance", "expected", "policy")

#: What an OMITTED `schema` reads back as. A baseline with no version key was
#: written before the key existed, so it is version 1 and nothing else.
_UNVERSIONED = 1

#: The run id directory key safety rule, the same character set `add_case`'s case
#: ids use: alphanumerics plus `-`/`_`/`.`. A manifest's `handle` becomes a
#: directory name under `snapshots/`, so a handle outside this set (a hand-crafted
#: manifest) is refused rather than allowed to escape the baseline dir.
_SAFE_KEY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


@dataclass(frozen=True)
class Baseline:
    """One banked run's expected verdicts and the policy it was verified under.

    `run_id` is the identity the gate joins on; `provenance` records engine
    version, platform, the resolved server command(s) and — when the capture held
    manifests — the snapshot capabilities (absent-never-zero: no manifests, no
    key); `expected` is the verify surface's own machine contract (per-turn
    records via `belay.verify.json.turn_record`, plus the trajectory and claim
    dispositions); `policy` is the RESOLVED A1 invariant list, the replays count,
    the per-replay timeout, and the manifest convention used — stored, never
    re-resolved, so a later gate check is drift-free against this bank.
    """

    run_id: str
    provenance: dict
    expected: dict
    policy: dict
    schema_version: int = BASELINE_SCHEMA


def _to_payload(baseline: Baseline) -> dict:
    return {
        "schema": baseline.schema_version,
        "run_id": baseline.run_id,
        "provenance": baseline.provenance,
        "expected": baseline.expected,
        "policy": baseline.policy,
    }


def save_baseline(baseline_dir: Path, baseline: Baseline) -> None:
    """Write `baseline`'s document to `<baseline_dir>/baseline.json`.

    Sorted keys and a fixed indent make the on-disk form deterministic, so a
    re-bank of the same trace is byte-identical and diffs cleanly. Only
    `baseline.json` is written; the sibling artifacts (`trace.jsonl`,
    `manifests/`, `snapshots/`) are `copy_trace_artifacts`'s.
    """
    baseline_dir = Path(baseline_dir)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_to_payload(baseline), indent=2, sort_keys=True)
    (baseline_dir / BASELINE_FILENAME).write_text(text, encoding="utf-8")


def load_baseline(baseline_dir: Path) -> Baseline:
    """Load and validate `<baseline_dir>/baseline.json`, or raise a named `ValueError`.

    Fail-closed, mirroring `load_case`: not-JSON, a non-object document, a missing
    required field, a non-integer `schema`, a non-string `run_id`, a
    `provenance`/`expected`/`policy` that is not an object, or a nested field
    gate-check will consume that is malformed — an `expected.turns` that is not a
    list, a `policy.invariants` that is not a list of `{"scope", "rule"}` objects,
    a `policy.replays` that is not an integer, a `policy.timeout` that is not a
    number, a `policy.manifest_dir` that is not a string, a
    `provenance.engine_version`/`platform` that is not a string, a
    `provenance.server_command` that is not a list of strings — each raises a
    `ValueError` naming the problem, never a silent default. One field may be
    omitted and defaulted: `schema` -> 1 (a baseline written before the field
    existed IS version 1). `capabilities` and `shell_server_command` are omitted
    when unset and read back as absent.
    """
    path = Path(baseline_dir) / BASELINE_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read baseline file {path!r}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"baseline file {path!r} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"baseline file {path!r} must contain a JSON object, got {type(raw).__name__}"
        )

    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise ValueError(f"baseline file {path!r} is missing required field {field!r}")

    schema_version = raw.get("schema", _UNVERSIONED)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError(
            f"baseline file {path!r} field 'schema' is {schema_version!r}; must be an integer"
        )

    run_id = raw["run_id"]
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(
            f"baseline file {path!r} field 'run_id' is {run_id!r}; must be a non-empty string"
        )

    provenance = _validated_dict(raw["provenance"], path, "provenance")
    for key in ("engine_version", "platform"):
        value = provenance.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"baseline file {path!r} field 'provenance.{key}' is {value!r}; "
                f"must be a non-empty string"
            )
    server_command = provenance.get("server_command")
    if not isinstance(server_command, list) or not all(
        isinstance(part, str) for part in server_command
    ):
        raise ValueError(
            f"baseline file {path!r} field 'provenance.server_command' is "
            f"{server_command!r}; must be a list of strings"
        )
    shell_server_command = provenance.get("shell_server_command")
    if shell_server_command is not None and (
        not isinstance(shell_server_command, list)
        or not all(isinstance(part, str) for part in shell_server_command)
    ):
        raise ValueError(
            f"baseline file {path!r} field 'provenance.shell_server_command' is "
            f"{shell_server_command!r}; must be a list of strings or absent"
        )
    capabilities = provenance.get("capabilities")
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or not all(isinstance(cap, str) for cap in capabilities)
    ):
        raise ValueError(
            f"baseline file {path!r} field 'provenance.capabilities' is "
            f"{capabilities!r}; must be a list of strings or absent"
        )

    expected = _validated_dict(raw["expected"], path, "expected")
    turns = expected.get("turns")
    if not isinstance(turns, list):
        raise ValueError(
            f"baseline file {path!r} field 'expected.turns' is {turns!r}; must be a list"
        )
    trajectory = expected.get("trajectory")
    if trajectory is not None and not isinstance(trajectory, dict):
        raise ValueError(
            f"baseline file {path!r} field 'expected.trajectory' is {trajectory!r}; "
            f"must be an object or null"
        )
    claim = expected.get("claim")
    if claim is not None and not isinstance(claim, dict):
        raise ValueError(
            f"baseline file {path!r} field 'expected.claim' is {claim!r}; "
            f"must be an object or absent"
        )

    policy = _validated_dict(raw["policy"], path, "policy")
    invariants = policy.get("invariants")
    if not isinstance(invariants, list) or not all(
        isinstance(inv, dict) and isinstance(inv.get("scope"), str)
        and isinstance(inv.get("rule"), str)
        for inv in invariants
    ):
        raise ValueError(
            f"baseline file {path!r} field 'policy.invariants' is {invariants!r}; "
            f"must be a list of {{'scope', 'rule'}} objects"
        )
    replays = policy.get("replays")
    if not isinstance(replays, int) or isinstance(replays, bool):
        raise ValueError(
            f"baseline file {path!r} field 'policy.replays' is {replays!r}; must be an integer"
        )
    timeout = policy.get("timeout")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError(
            f"baseline file {path!r} field 'policy.timeout' is {timeout!r}; must be a number"
        )
    manifest_dir = policy.get("manifest_dir")
    if not isinstance(manifest_dir, str) or not manifest_dir:
        raise ValueError(
            f"baseline file {path!r} field 'policy.manifest_dir' is {manifest_dir!r}; "
            f"must be a non-empty string"
        )

    return Baseline(
        run_id=run_id,
        provenance=provenance,
        expected=expected,
        policy=policy,
        schema_version=schema_version,
    )


def _validated_dict(raw: object, path: Path, field: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(
            f"baseline file {path!r} field {field!r} must be an object, "
            f"got {type(raw).__name__}"
        )
    return raw


def copy_trace_artifacts(
    trace_path: Path,
    manifest_dir: Path,
    dest: Path,
) -> Optional[list[str]]:
    """Copy the trace, manifests and snapshot trees into `dest`; return the sorted
    union of the copied manifests' capabilities, or `None` when the capture held
    no manifests (absent-never-zero).

    The manifests are copied with their `tree_path` rewritten to the RELATIVE
    `../snapshots/<handle>` and each manifest's snapshot tree copied into
    `dest/snapshots/<handle>`, exactly mirroring `add_case`'s copy+rewrite: the
    baseline restores from itself alone. A `*.json` in `manifest_dir` without a
    `handle` key, or a manifest whose tree does not exist, is a fail-closed
    `ValueError` — and any failure removes the partial copy, so a baseline with
    dangling pre-state is never left on disk.
    """
    dest = Path(dest)
    manifests_dest = dest / _MANIFESTS_DIRNAME
    snapshots_dest = dest / _SNAPSHOTS_DIRNAME
    try:
        manifests_dest.mkdir(parents=True)
        snapshots_dest.mkdir(parents=True)
        shutil.copy2(trace_path, dest / _TRACE_FILENAME)

        capabilities: set[str] = set()
        for manifest_path in sorted(Path(manifest_dir).glob("*.json")):
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            handle = payload.get("handle")
            if not isinstance(handle, str) or not handle:
                raise ValueError(
                    f"{manifest_path} is not a snapshot manifest: it carries no 'handle' key"
                )
            if not all(c in _SAFE_KEY_CHARS for c in handle):
                raise ValueError(
                    f"manifest {manifest_path} carries an unsafe handle {handle!r}; "
                    f"it cannot name a directory inside the baseline"
                )
            snap = load_snapshot(manifest_path)
            if not snap.snapshot.path.is_dir():
                raise ValueError(
                    f"manifest {manifest_path} names tree {snap.snapshot.path} which "
                    f"does not exist; the pre-state cannot be bundled into a "
                    f"self-contained baseline"
                )
            payload["tree_path"] = f"../{_SNAPSHOTS_DIRNAME}/{handle}"
            (manifests_dest / manifest_path.name).write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            shutil.copytree(snap.snapshot.path, snapshots_dest / handle)
            capabilities.update(snap.manifest.capabilities)
        if not capabilities:
            return None
        return sorted(capabilities)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


__all__ = [
    "BASELINE_FILENAME",
    "BASELINE_SCHEMA",
    "Baseline",
    "copy_trace_artifacts",
    "load_baseline",
    "save_baseline",
]