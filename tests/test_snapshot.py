"""Snapshot/restore: C2's headline acceptance test, and the guard on its repairs.

The roadmap's acceptance test for C2 is verbatim *"a turn's pre-state snapshot
restores byte-identically; a hash of the restored tree equals the hash of the
original"*. `test_pre_state_restores_byte_identically` **is** that sentence, and
everything downstream — every replayed turn, every grounded verdict — is
worthless if it does not hold: a pre-state that cannot be restored is a verdict
that cannot be grounded.

**The ablation test is the important one here.** `clonefile` silently loses
hardlink identity, setuid, and directory mtimes, and all three are invisible to a
content-only hash — a restore that lost every one of them would still look
"byte-identical" to a naive check. The three repairs exist to fix exactly those.
`test_ablating_a_repair_breaks_the_restore` disables each repair and requires the
headline test to fail, which is what makes each repair demonstrably load-bearing
rather than decoration someone can "simplify" away while the suite stays green.

Each ablation asserts **which field** broke (`link_group` / `perm` / `mtime_ns`),
not merely that the hash moved. "The hash changed" is not evidence: a restore
that corrupted something unrelated would move the hash too, and would pass an
ablation test that only checked for inequality — proving the repair matters for
the wrong reason. The assertions below pin the exact set of differing fields, so
an ablation that broke *more* than its own repair is also a failure.

`_mutate` is guarded for the same reason. If the tree were not really mutated
between snapshot and restore, `restore` could be `pass` and the headline test
would still pass, green and meaningless.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fixtures.torture_tree import build_torture_tree

from belay.snapshot.bth1 import diff_records, hash_tree, scan_tree
from belay.snapshot.clone import ALL_REPAIRS, restore, snapshot


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return build_torture_tree(tmp_path / "work")


def _fields(left: Path, right: Path) -> set[str | None]:
    """The set of field names differing between two trees."""
    return {diff.field for diff in diff_records(scan_tree(left), scan_tree(right))}


def _mutate(tree: Path) -> None:
    """Damage the tree the way a turn would: content, mode, dir mtime, symlink.

    Deliberately spread across four axes so a restore that only re-copied file
    bytes cannot pass.
    """
    (tree / "regular.txt").write_bytes(b"clobbered by the agent\n")
    os.chmod(tree / "setuid.bin", 0o711)
    os.utime(tree / "nested", ns=(1, 1))
    os.unlink(tree / "relative.link")
    os.symlink("somewhere-else.txt", tree / "relative.link")


def test_mutation_is_real(tree: Path, tmp_path: Path) -> None:
    """Anti-vacuity guard: `_mutate` must actually move the tree.

    Without this, `restore` could be a no-op and the headline test would pass.
    """
    before = build_torture_tree(tmp_path / "reference")
    _mutate(tree)
    # `size` rides along with `content`: the clobbered file is a different length.
    assert _fields(before, tree) == {"content", "size", "perm", "mtime_ns", "target"}


def test_pre_state_restores_byte_identically(tree: Path, tmp_path: Path) -> None:
    """THE headline acceptance test for C2, verbatim from the roadmap."""
    reference = build_torture_tree(tmp_path / "reference")
    original = hash_tree(tree)
    snap = snapshot(tree, tmp_path / "snap")

    _mutate(tree)
    assert hash_tree(tree) != original, "the mutation did not take"

    restore(snap, tree)

    # Named fields first: a bare hash comparison would fail with two hex strings
    # and leave the reader to guess what the restore lost.
    assert _fields(reference, tree) == set(), (
        "the restore did not round-trip these fields"
    )
    assert hash_tree(tree) == original


def test_snapshot_itself_is_faithful(tree: Path, tmp_path: Path) -> None:
    """The snapshot on disk hashes equal to the original, not merely restorable.

    A raw `clonefile` snapshot is silently lossy. Repairing the snapshot at
    capture time — rather than only on the way out — means the artifact sitting
    on disk is honest, so anyone who reads it directly gets the tree that was
    actually there.
    """
    snap = snapshot(tree, tmp_path / "snap")
    assert hash_tree(snap.path) == hash_tree(tree)


def test_snapshot_does_not_mutate_the_original(tree: Path, tmp_path: Path) -> None:
    before = hash_tree(tree)
    snapshot(tree, tmp_path / "snap")
    assert hash_tree(tree) == before


def test_snapshot_is_copy_on_write(tmp_path: Path) -> None:
    """A snapshot must cost far less disk than the tree it copies.

    A sanity check on the mechanism, not a benchmark: if this ever regressed to a
    real byte-for-byte copy, snapshotting a turn's pre-state would cost the size
    of the workspace every turn and C2 would be unusable in practice. The bound
    is deliberately loose (a quarter of the data) because free-space deltas on a
    live machine are noisy in both directions.
    """
    source = tmp_path / "bulk"
    source.mkdir()
    payload = os.urandom(1024 * 1024)  # incompressible: no dedup can fake the win
    for index in range(64):
        (source / f"{index}.bin").write_bytes(payload)
    total = 64 * 1024 * 1024

    os.sync()
    before = _free_bytes(tmp_path)
    snapshot(source, tmp_path / "snap")
    os.sync()
    used = before - _free_bytes(tmp_path)

    assert used < total // 4, (
        f"snapshot consumed {used} bytes of {total}; not copy-on-write"
    )


def _free_bytes(path: Path) -> int:
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


@pytest.mark.parametrize(
    ("disabled", "expected"),
    [
        ({"hardlinks"}, {"link_group"}),
        ({"suid"}, {"perm"}),
        ({"dirmtimes"}, {"mtime_ns"}),
        ({"hardlinks", "suid", "dirmtimes"}, {"link_group", "perm", "mtime_ns"}),
    ],
    ids=["hardlinks", "suid", "dirmtimes", "all-three"],
)
def test_ablating_a_repair_breaks_the_restore(
    tree: Path, tmp_path: Path, disabled: set[str], expected: set[str]
) -> None:
    """Every repair is load-bearing: disable it and the headline test must fail.

    This is the permanent guard against a repair being quietly removed. Each case
    names the field it breaks — see this module's docstring for why "the hash
    changed" would not be evidence.
    """
    reference = build_torture_tree(tmp_path / "reference")
    snap = snapshot(tree, tmp_path / "snap")
    _mutate(tree)

    restore(snap, tree, repairs=ALL_REPAIRS - disabled)

    assert hash_tree(tree) != hash_tree(reference), (
        f"disabling {sorted(disabled)} changed nothing — the repair is not load-bearing, "
        "or the restore is not really using it"
    )
    assert _fields(reference, tree) == expected


def test_ablation_is_exhaustive() -> None:
    """The ablation test covers every repair there is.

    Without this, adding a fourth repair would leave it silently unablated — the
    exact hole the ablation test exists to close.
    """
    assert ALL_REPAIRS == {"hardlinks", "suid", "dirmtimes"}
