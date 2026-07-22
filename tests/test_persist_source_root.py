"""Phase 1: the manifest records the ORIGINAL workspace root (`source_root`).

The gate knows the workspace the snapshot was taken *from* (`TurnGate._scope`) but
persists only the *clone* location (`tree_path`). This aspect adds `source_root`: the
realpath'd original root, written at persist time, read back at load time, exposed on
`Manifest.source_root`, and **never consumed** — a pure capture-side, backward-compatible
addition with no verdict behavior change.

These tests pin the persist/load round-trip and the fail-closed loader, mirroring
`test_persist_relative_tree.py`'s absolute-vs-relative backward-compat style:

- BACKWARD-COMPAT: a manifest written before this field existed (no `source_root`) loads
  as `None`, no error.
- MALFORMED ≠ ABSENT: a present-but-blank / present-but-relative `source_root` is a named
  `ValueError`, never a silent `None`.
- CALLER'S REALPATH: `persist_snapshot` stores the string it is given verbatim; the gate is
  what resolves. Persist does not silently transform.

Fully offline/deterministic: a `GuardedSnapshot` is built directly (no real snapshot, no
Seatbelt, no clonefile) because `load_snapshot` reconstructs — it does not restore — so the
round-trip needs no on-disk tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.replay.persist import load_snapshot, persist_snapshot
from belay.snapshot.clone import Sidecar, Snapshot
from belay.snapshot.substrate import GuardedSnapshot, Manifest


def _snapshot(tree_path: Path) -> GuardedSnapshot:
    """A minimal well-formed `GuardedSnapshot` (empty sidecar, absolute tree_path).

    Enough for `persist_snapshot` -> `load_snapshot` to round-trip: neither touches the
    tree on disk, so no real capture is needed to test the manifest schema.
    """
    return GuardedSnapshot(
        snapshot=Snapshot(path=tree_path, sidecar=Sidecar((), (), ())),
        manifest=Manifest(
            backend="clonefile-apfs",
            capabilities=frozenset({"clonefile", "hardlinks"}),
            handle="H1",
        ),
    )


def test_manifest_records_the_source_root(tmp_path: Path) -> None:
    """A `source_root` given to persist round-trips to `manifest.source_root` on load."""
    tree = tmp_path / "snap"
    tree.mkdir()
    source_root = str(tmp_path / "work")

    manifest_path = tmp_path / "m.json"
    persist_snapshot(_snapshot(tree), manifest_path, source_root=source_root)

    # It is written into the JSON payload, exactly as given.
    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored["source_root"] == source_root

    loaded = load_snapshot(manifest_path)
    assert loaded.manifest.source_root == source_root


def test_manifest_without_source_root_loads_as_none(tmp_path: Path) -> None:
    """BACKWARD-COMPAT: an old-shaped manifest (no `source_root`) loads with `None`.

    Persist called without the keyword must OMIT the key entirely (old manifests stay
    byte-clean), and load must return `None` for the field — no error.
    """
    tree = tmp_path / "snap"
    tree.mkdir()

    manifest_path = tmp_path / "m.json"
    persist_snapshot(_snapshot(tree), manifest_path)

    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "source_root" not in stored, (
        "persist with no source_root must OMIT the key, not write null"
    )

    loaded = load_snapshot(manifest_path)
    assert loaded.manifest.source_root is None


def test_malformed_source_root_is_a_named_error(tmp_path: Path) -> None:
    """MALFORMED ≠ ABSENT: a present-but-blank / present-but-relative value raises.

    A `source_root` that is present in the payload must be a non-empty ABSOLUTE string, or
    the loader fails closed with a named `ValueError`. A silent `None` here would erase the
    distinction between "old capture" and "corrupt field".
    """
    tree = tmp_path / "snap"
    tree.mkdir()
    manifest_path = tmp_path / "m.json"
    persist_snapshot(_snapshot(tree), manifest_path)

    for bad in ("", "relative/work", "also/not/absolute"):
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored["source_root"] = bad
        manifest_path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        with pytest.raises(ValueError, match="source_root"):
            load_snapshot(manifest_path)


def test_source_root_realpath_is_the_callers_responsibility(tmp_path: Path) -> None:
    """CALLER'S REALPATH: persist stores the string verbatim; it does not resolve.

    The gate passes an already-resolved `self._scope`; normalising here too would hide a
    caller that forgot to. An absolute-but-non-canonical string is stored as-is (proof
    persist performs no silent transform), and it round-trips unchanged.
    """
    tree = tmp_path / "snap"
    tree.mkdir()
    noncanonical = str(tmp_path / "work" / ".." / "work")  # absolute, not resolved

    manifest_path = tmp_path / "m.json"
    persist_snapshot(_snapshot(tree), manifest_path, source_root=noncanonical)

    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored["source_root"] == noncanonical, "persist must not resolve/normalise"
    assert load_snapshot(manifest_path).manifest.source_root == noncanonical
