"""Snapshot persistence: the join that lets `belay replay` restore in a later process.

C2 takes a snapshot every turn and keeps the sidecar `clone.restore` needs **in
memory** — `gate.snapshots[handle] = snap`. The trace records only the handle, the
disk holds only `turn-NNNN/`, and nothing joins them, so no later process can turn a
recorded handle back into a restorable pre-state. `belay replay` runs in a later
process by definition. This module is that join: a manifest on disk carrying the
handle, the tree path, and — the delicate part — the sidecar bytes.

## The cardinal sin these tests exist to make impossible

`clone.restore` silently *needs* the sidecar to rebuild hardlink identity, setuid,
and directory mtimes — the three things `clonefile` destroys and a content-only hash
cannot see. A persistence layer that reconstructed a `Snapshot` from the on-disk tree
with a **synthesized empty sidecar** would still restore, still hash, and still look
correct, while having dropped exactly the divergence BTH-1 exists to catch. So:

- `test_snapshot_survives_its_process` (A6) restores from a persisted manifest in a
  **fresh subprocess** that holds nothing in memory. A load that synthesized an empty
  sidecar fails it, because the restored tree no longer hashes equal to the original.
- `test_an_empty_sidecar_is_caught_by_bth1` (A5) is the guard on that guard: it shows
  an empty sidecar is not silently equal — restoring from one diverges on
  `link_group`/`perm`/`mtime_ns`, and BTH-1 names all three. If it could not fail,
  A6 passing would prove nothing.
- `test_persisted_sidecar_bytes_survive_byte_for_byte` pins the bytes: base64,
  never decoded, round-tripping identically.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import CLIENT_LINES
from fixtures.torture_tree import build_torture_tree

from belay.snapshot.bth1 import diff_records, hash_tree, scan_tree
from belay.snapshot.substrate import GuardedSnapshot, guarded_restore, take_snapshot
from belay.replay.persist import load_snapshot, persist_snapshot

TOOLS_CALL = CLIENT_LINES[3]
CLIENT_TO_SERVER = "c2s"


@pytest.fixture
def guarded(tmp_path: Path) -> tuple[Path, GuardedSnapshot]:
    """A torture tree and a real snapshot of it, sidecar populated on all three axes."""
    tree = build_torture_tree(tmp_path / "work")
    snap = take_snapshot(tree, tmp_path / "snap")
    sidecar = snap.snapshot.sidecar
    # Anti-vacuity: every persistence claim below is about carrying these three,
    # so a run where the torture tree stopped producing them would prove nothing.
    assert sidecar.link_groups, "no hardlink group captured - persistence test is vacuous"
    assert sidecar.special_modes, "no setuid captured - persistence test is vacuous"
    assert sidecar.dir_times, "no dir mtimes captured - persistence test is vacuous"
    return tree, snap


def test_persisted_sidecar_bytes_survive_byte_for_byte(
    guarded: tuple[Path, GuardedSnapshot], tmp_path: Path
) -> None:
    """The sidecar is raw bytes; persistence base64s them and never decodes them.

    Dataclass equality compares the sidecar's fields by value, so an equal sidecar
    is a byte-for-byte equal sidecar. The manifest is inspected directly too, to
    prove the bytes were stored as base64 rather than decoded through some encoding
    that would silently normalise a non-UTF-8 name.
    """
    tree, snap = guarded
    manifest_path = tmp_path / "manifest.json"

    persist_snapshot(snap, manifest_path)
    loaded = load_snapshot(manifest_path)

    assert loaded.snapshot.sidecar == snap.snapshot.sidecar
    assert loaded.manifest == snap.manifest

    # The stored value is base64 of the raw bytes, not the decoded name.
    stored = json.loads(manifest_path.read_text(encoding="utf-8"))["sidecar"]
    primary_b64 = stored["link_groups"][0][0]
    assert base64.b64decode(primary_b64) == snap.snapshot.sidecar.link_groups[0][0]


def test_snapshot_survives_its_process(
    guarded: tuple[Path, GuardedSnapshot], tmp_path: Path
) -> None:
    """A6: a persisted snapshot restores byte-identically in a FRESH process.

    The subprocess is given only the manifest path — nothing from this process's
    memory. It loads the snapshot, restores it, and prints the BTH-1 hash of the
    restored tree, which must equal the original. This is the whole point of the
    task: a snapshot that outlives the process that took it. A load that synthesized
    an empty sidecar would restore a tree missing the three repairs and fail here.
    """
    tree, snap = guarded
    original = hash_tree(tree)
    manifest_path = tmp_path / "manifest.json"
    persist_snapshot(snap, manifest_path)

    restore_dest = tmp_path / "restored"
    program = (
        "import sys\n"
        "from belay.replay.persist import load_snapshot\n"
        "from belay.snapshot.substrate import guarded_restore\n"
        "from belay.snapshot.bth1 import hash_tree\n"
        "manifest_path, restore_dest = sys.argv[1], sys.argv[2]\n"
        "snap = load_snapshot(manifest_path)\n"
        "guarded_restore(snap, restore_dest)\n"
        "print(hash_tree(restore_dest))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(manifest_path), str(restore_dest)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"fresh-process restore failed:\n{result.stderr}"
    assert result.stdout.strip() == original, (
        "the tree restored in a fresh process did not hash equal to the original: "
        "the sidecar did not survive its process"
    )


def test_an_empty_sidecar_is_caught_by_bth1(
    guarded: tuple[Path, GuardedSnapshot], tmp_path: Path
) -> None:
    """A5, THE GUARD: an empty sidecar is not silently equal — BTH-1 names the loss.

    First the real persisted sidecar is shown to restore to a match (the "pass on a
    real one"). Then the same manifest is rewritten with a synthesized **empty**
    sidecar — the cardinal sin — loaded, and restored. The restored tree must
    diverge, and `diff_records` must name `link_group`, `perm` and `mtime_ns`: the
    hardlink pair, the setuid bit and the directory mtimes `clonefile` drops and no
    empty sidecar puts back. If this could not fail, A6 passing would prove nothing.
    """
    tree, snap = guarded
    manifest_path = tmp_path / "manifest.json"
    persist_snapshot(snap, manifest_path)

    # Pass on a real one: the persisted bytes restore to a byte-identical tree.
    good = load_snapshot(manifest_path)
    good_dest = tmp_path / "good"
    guarded_restore(good, good_dest)
    assert hash_tree(good_dest) == hash_tree(tree), (
        "the real persisted sidecar failed to restore - this is A6's failure, not A5's"
    )

    # The cardinal sin: a manifest whose sidecar was synthesized empty.
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["sidecar"] = {"link_groups": [], "special_modes": [], "dir_times": []}
    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text(json.dumps(data), encoding="utf-8")

    empty = load_snapshot(empty_manifest)
    empty_dest = tmp_path / "empty_restore"
    guarded_restore(empty, empty_dest)

    fields = {diff.field for diff in diff_records(scan_tree(tree), scan_tree(empty_dest))}
    assert {"link_group", "perm", "mtime_ns"} <= fields, (
        "an empty sidecar restored without diverging on the three repair fields: "
        f"BTH-1 did not catch the cardinal sin. differing fields: {sorted(f for f in fields if f)}"
    )


def test_gate_leaves_a_resolvable_manifest(tmp_path: Path) -> None:
    """Wiring: a gated turn leaves a manifest a later process can resolve and restore.

    The gate snapshots the scope on a `tools/call` and keeps the snapshot in memory.
    Persistence is wired in so the same turn also writes a manifest to disk. Here the
    manifest is loaded straight off disk — not from the gate's in-memory map — and
    restored, proving the on-disk artifact is self-sufficient.
    """
    from belay.sandbox.gate import TurnGate

    scope = build_torture_tree(tmp_path / "work")
    before = hash_tree(scope)
    gate = TurnGate(scope=scope, snapshot_root=tmp_path / "snaps")

    gate.before_frame(TOOLS_CALL, CLIENT_TO_SERVER)

    assert len(gate.snapshots) == 1, "the gate did not snapshot the tools/call"

    manifests = sorted(gate.manifest_root.glob("*.json"))
    assert len(manifests) == 1, f"expected one persisted manifest, found {manifests!r}"

    loaded = load_snapshot(manifests[0])
    assert loaded.manifest.handle in gate.snapshots, (
        "the persisted manifest names a handle the gate never recorded"
    )

    restore_dest = tmp_path / "restored"
    guarded_restore(loaded, restore_dest)
    assert hash_tree(restore_dest) == before, (
        "the snapshot resolved from disk did not restore the gate's pre-state"
    )
