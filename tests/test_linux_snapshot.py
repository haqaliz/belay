"""The Linux snapshot/restore backend: registration, probed capabilities, fidelity.

A3 (`docs/planning/linux-sandbox/linux-snapshot/spec.md`) is the second
`SnapshotBackend` on the `ClonefileBackend` pattern: byte-identical
snapshot/restore on the Linux substrate, honest about the fidelity each
filesystem can provide. GitHub runners are ext4 — no reflink — so the copy
path with sidecar repairs is the CI path; reflink (`FICLONE`) is a probed
capability, never a declared one.

The platform split of this file is deliberate and stated:

- **Platform-neutral tests run everywhere** (including this macOS box):
  registration, capability-probing honesty, capability-differencing refusal,
  the pure name-hazard classifier, `gc()` of non-ASCII trees. These are the
  parts whose logic must be exercised even though the Linux substrate is not
  here.
- **Linux-only integration tests are `skipif`'d** to the ubuntu CI job (A4):
  the byte-identical round trips (the fixture tree needs `os.listxattr`), the
  three collision fixtures (APFS cannot even create the trees), the reflink
  path. A skipped test here is a test that exists and will run there — not a
  gap papered over.
"""

from __future__ import annotations

import errno
import os
import sys
import unicodedata
from pathlib import Path

import pytest
from fixtures.torture_tree import build_torture_tree

from belay.snapshot.bth1 import diff_records, hash_tree, scan_tree
from belay.snapshot.linux import LinuxSnapshotBackend, _hazard_cause, _probe_reflink
from belay.snapshot.substrate import (
    ClonefileBackend,
    Manifest,
    Unrestorable,
    UnrestorableCause,
    gc,
    guarded_restore,
    take_snapshot,
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return build_torture_tree(tmp_path / "work")


def _platform_backend_name() -> str:
    if sys.platform == "darwin":
        return ClonefileBackend.name
    return LinuxSnapshotBackend.name


# --------------------------------------------------------------------------
# Registration: the backend exists, has a name, and the seam dispatches to it.
# --------------------------------------------------------------------------


def test_backend_registration_name() -> None:
    """The backend's name is the contract, not the mechanism.

    `copy-fidelity` names what the backend promises (a faithful copy with
    sidecar repairs); whether reflink is used is probed per directory and
    declared in `capabilities()`, never in the name.
    """
    assert LinuxSnapshotBackend.name == "copy-fidelity"


def test_take_snapshot_dispatches_to_the_platform_backend(
    tree: Path, tmp_path: Path
) -> None:
    """`take_snapshot` records whichever backend this platform selects.

    On darwin that is `ClonefileBackend`; everywhere else the Linux backend.
    The manifest is what a later restore refuses across, so the recorded name
    must be the dispatch's answer, not a hardcoded one.
    """
    snap = take_snapshot(tree, tmp_path / "snap")
    assert snap.manifest.backend == _platform_backend_name()
    assert snap.manifest.capabilities, "a backend with an empty capability set"
    assert snap.manifest.handle


def test_the_linux_backend_has_no_snapshot_on_macos_substrate(
    tree: Path, tmp_path: Path
) -> None:
    """The cross-substrate vocabulary is real: the two sets can never match.

    If they ever matched, a macOS-banked case would silently restore on Linux
    (or the mirror), which is the one thing the capability-mismatch rule
    exists to prevent. This pins the *vocabulary*, not a machine.
    """
    ours = take_snapshot(tree, tmp_path / "snap").manifest.capabilities
    if sys.platform == "darwin":
        foreign = LinuxSnapshotBackend.capabilities(tmp_path)
    else:
        foreign = ClonefileBackend.capabilities()
    assert ours != foreign, "the two substrates' capability sets must differ"


# --------------------------------------------------------------------------
# Capability probing: probed, never declared.
# --------------------------------------------------------------------------


def test_capabilities_are_probed_never_declared(tmp_path: Path) -> None:
    """Every claim in `capabilities()` is either structural or measured.

    `reflink` in particular must equal what a REAL FICLONE probe on that
    directory's filesystem says — ext4 and tmpfs cannot reflink, and a backend
    that claimed it there would be asserting a machine it never saw.
    """
    caps = LinuxSnapshotBackend.capabilities(tmp_path)
    assert ("reflink" in caps) is _probe_reflink(tmp_path)
    assert ("xattrs-os-native" in caps) is hasattr(os, "listxattr")
    for expected in ("hardlinks", "special-modes", "dir-mtimes", "symlinks"):
        assert expected in caps, f"the Linux backend must declare {expected!r}"


def test_capability_probing_leaves_no_scratch_in_the_probe_dir(
    tmp_path: Path,
) -> None:
    """The probe writes a scratch pair to measure FICLONE, and removes it.

    A probe that littered the snapshot directory would pollute the very tree
    it exists to measure.
    """
    before = set(os.listdir(tmp_path))
    LinuxSnapshotBackend.capabilities(tmp_path)
    assert set(os.listdir(tmp_path)) == before


def test_capabilities_default_to_the_platform_tmp_dir() -> None:
    """`capabilities()` with no argument still probes somewhere real.

    The Linux backend's signature takes a probe dir because reflink is a
    filesystem property; without one, the platform temp directory is the
    honest default (same rule as the per-directory probe, same memo).
    """
    caps = LinuxSnapshotBackend.capabilities()
    assert caps  # non-empty, deterministic on a given machine
    assert isinstance(caps, frozenset)


# --------------------------------------------------------------------------
# Capability-mismatch refusal: preserved, never loosened (spec criterion 3).
# --------------------------------------------------------------------------


def test_restore_across_differing_capabilities_refuses(
    tree: Path, tmp_path: Path
) -> None:
    """A manifest whose capability set differs is refused before dest is touched.

    The sentinel capability is guaranteed absent from every real backend, so
    this holds on both substrates; the detail must name it.
    """
    snap = take_snapshot(tree, tmp_path / "snap")
    foreign = Manifest(
        backend="someone-else",
        capabilities=snap.manifest.capabilities | {"not-a-real-capability"},
    )
    alien = type(snap)(snapshot=snap.snapshot, manifest=foreign)

    with pytest.raises(Unrestorable) as caught:
        guarded_restore(alien, tmp_path / "out")

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH
    assert "not-a-real-capability" in caught.value.detail
    assert not (tmp_path / "out").exists()  # refused, not half-attempted


def test_a_case_banked_on_the_other_substrate_is_refused_never_guessed(
    tree: Path, tmp_path: Path
) -> None:
    """The eval-data line: a macOS-banked case on Linux — and the mirror — stays
    UNVERIFIED-by-capability-mismatch, never a guessed restore.

    The foreign manifest is built from the OTHER backend's REAL capability
    set, so this is the cross-substrate rule with production vocabularies, not
    a sentinel.
    """
    if sys.platform == "darwin":
        foreign_backend = LinuxSnapshotBackend
        foreign_caps = foreign_backend.capabilities(tmp_path)
    else:
        foreign_backend = ClonefileBackend
        foreign_caps = foreign_backend.capabilities()

    snap = take_snapshot(tree, tmp_path / "snap")
    assert snap.manifest.capabilities != foreign_caps
    alien = type(snap)(
        snapshot=snap.snapshot,
        manifest=Manifest(backend=foreign_backend.name, capabilities=foreign_caps),
    )

    with pytest.raises(Unrestorable) as caught:
        guarded_restore(alien, tmp_path / "out")

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------
# Byte-identical round trip, copy path — platform-neutral (runs on macOS).
# --------------------------------------------------------------------------


def _build_fixture(root: Path) -> Path:
    """Nested dirs, symlinks, hardlinks, setuid/setgid/sticky, non-ASCII names.

    Deliberately xattr-free: `os.listxattr` is Linux-only, and the full torture
    tree (xattrs included) round-trips in the linux-gated test below. Every
    other axis of the BTH-1 field set is present, on both platforms.
    """
    root.mkdir(parents=True)
    (root / "regular.txt").write_bytes(b"plain content\n")
    nested = root / "nested"
    nested.mkdir()
    (nested / "child.txt").write_bytes(b"child content\n")
    (root / "setuid.bin").write_bytes(b"suid payload\n")
    os.chmod(root / "setuid.bin", 0o4711)
    (root / "setgid.bin").write_bytes(b"sgid payload\n")
    os.chmod(root / "setgid.bin", 0o2755)
    (root / "sticky_dir").mkdir()
    os.chmod(root / "sticky_dir", 0o1777)
    (root / "hard_a.txt").write_bytes(b"one inode, two names\n")
    os.link(root / "hard_a.txt", nested / "hard_b.txt")
    os.symlink("regular.txt", root / "rel.link")
    os.symlink("/nonexistent/target", root / "abs.link")
    nfd = unicodedata.normalize("NFD", "café")
    (root / nfd).write_bytes(b"nfd named\n")
    return root


def _mutate(tree: Path) -> None:
    """Damage the tree the way a turn would: content, mode, dir mtime, symlink."""
    (tree / "regular.txt").write_bytes(b"clobbered by the agent\n")
    os.chmod(tree / "setuid.bin", 0o711)
    os.utime(tree / "nested", ns=(1, 1))
    os.unlink(tree / "rel.link")
    os.symlink("somewhere-else.txt", tree / "rel.link")


def test_copy_path_round_trips_byte_identically_on_any_platform(
    tmp_path: Path,
) -> None:
    """The copy machinery itself — the CI path — round-trips, on ANY platform.

    The Linux backend's copy code is platform-neutral (everything it uses —
    os.link, os.symlink, os.chmod, os.utime, FICLONE-or-copyfile — exists on
    macOS too, modulo xattrs which this fixture omits), so its fidelity is
    exercised on this box rather than only in the Linux CI job.
    """
    from belay.snapshot.linux import restore as linux_restore
    from belay.snapshot.linux import snapshot as linux_snapshot

    src = _build_fixture(tmp_path / "src")
    original = hash_tree(src)

    snap = linux_snapshot(src, tmp_path / "snap")
    assert hash_tree(snap.path) == original, "the snapshot on disk must be faithful"

    _mutate(src)
    assert hash_tree(src) != original, "the mutation did not take"

    linux_restore(snap, src)
    fields = {diff.field for diff in diff_records(scan_tree(src), scan_tree(src))}
    assert fields == set()
    assert hash_tree(src) == original


# --------------------------------------------------------------------------
# Byte-identical round trip, full field set — Linux only.
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="the full fixture carries xattrs, which need os.listxattr (Linux-only)",
)
def test_linux_full_fixture_round_trips_byte_identically(tmp_path: Path) -> None:
    """Spec criterion 1: hash-of-tree equality over the BTH-1 field set.

    The torture tree — nested dirs, symlinks, hardlinks, setuid, non-ASCII and
    normalization-edge names, xattrs — snapshotted, mutated, restored, and
    must hash equal to the original, with the differing-field set empty.
    """
    src = build_torture_tree(tmp_path / "work")
    reference = build_torture_tree(tmp_path / "reference")
    original = hash_tree(src)

    snap = take_snapshot(src, tmp_path / "snap")
    assert hash_tree(snap.path) == original, "the snapshot on disk must be faithful"

    _mutate(src)
    assert hash_tree(src) != original, "the mutation did not take"

    guarded_restore(snap, src)
    fields = {diff.field for diff in diff_records(scan_tree(reference), scan_tree(src))}
    assert fields == set(), f"the restore did not round-trip: {sorted(fields)}"
    assert hash_tree(src) == original


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="reflink is a Linux ioctl; the probe needs a Linux filesystem",
)
def test_reflink_path_round_trips_when_the_substrate_claims_it(
    tmp_path: Path,
) -> None:
    """Spec criterion 2: the reflink path round-trips where FICLONE works.

    Runs only when the probe says so (btrfs/xfs hosts); the ext4 CI runners
    exercise the copy path, and this test skips there with the reason stated.
    """
    if "reflink" not in LinuxSnapshotBackend.capabilities(tmp_path):
        pytest.skip(
            "this Linux filesystem does not support FICLONE; "
            "the copy path is the CI path (OQ-5)"
        )
    from belay.snapshot.linux import restore as linux_restore
    from belay.snapshot.linux import snapshot as linux_snapshot

    src = _build_fixture(tmp_path / "src")
    original = hash_tree(src)
    snap = linux_snapshot(src, tmp_path / "snap")
    assert hash_tree(snap.path) == original
    _mutate(src)
    linux_restore(snap, src)
    assert hash_tree(src) == original


# --------------------------------------------------------------------------
# The three reserved taxonomy causes — real fixtures on Linux, pure classifier
# everywhere.
# --------------------------------------------------------------------------


def test_hazard_detection_classifies_the_three_causes_on_any_platform() -> None:
    """The pure name classifier: every reserved cause, reachable anywhere.

    The three causes (`UNRESTORABLE_CASE_COLLISION`, `UNRESTORABLE_INVALID_UTF8_NAME`,
    `UNRESTORABLE_NORMALIZATION_COLLISION`) are byte-level facts about names,
    so the classifier that raises them is exercised here; the linux-gated
    tests below prove the same function fires through the real restore path.
    """
    assert _hazard_cause([b"README", b"readme"])[0] is (
        UnrestorableCause.UNRESTORABLE_CASE_COLLISION
    )
    pair = [
        unicodedata.normalize("NFD", "café").encode("utf-8"),
        unicodedata.normalize("NFC", "café").encode("utf-8"),
    ]
    assert _hazard_cause(pair)[0] is UnrestorableCause.UNRESTORABLE_NORMALIZATION_COLLISION
    assert _hazard_cause([b"caf\xe9.txt"])[0] is (
        UnrestorableCause.UNRESTORABLE_INVALID_UTF8_NAME
    )
    # No false positives: a single NFD name (the torture tree's) is not a
    # collision, and plainly distinct names are fine.
    assert _hazard_cause([unicodedata.normalize("NFD", "café").encode("utf-8")]) is None
    assert _hazard_cause([b"a.txt", b"b.txt"]) is None


def _collision_fixture(root: Path, names: list[bytes]) -> Path:
    """Build a directory holding every raw byte name, or skip with a reason.

    On a case-insensitive or normalising filesystem the second create fails
    with EEXIST and the fixture CANNOT exist — that is a property of the
    filesystem, not a silent non-collision, so it skips loudly rather than
    letting the cause pass unreached.
    """
    root.mkdir(parents=True)
    for name in names:
        path = os.path.join(os.fsencode(root), name)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                pytest.skip(
                    f"this filesystem cannot hold the distinct names {names!r}; "
                    "the collision fixture cannot exist here"
                )
            raise
        os.write(fd, name)
        os.close(fd)
    for name in names:
        if not os.path.exists(os.path.join(os.fsencode(root), name)):
            pytest.skip(
                f"the names {names!r} collapsed into one entry on this filesystem; "
                "the collision fixture cannot exist here"
            )
    return root


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="collision trees need a case-sensitive, byte-transparent filesystem",
)
def test_case_collision_tree_is_refused_at_restore(tmp_path: Path) -> None:
    """A tree holding `README` and `readme` snapshots fine and refuses at restore.

    The workspace really contains both (ext4 is case-sensitive) — the snapshot
    must succeed, because the agent's tree is what it is. What the restore
    cannot faithfully promise is landing both names on an unknown destination
    filesystem, so it refuses by name before touching dest.
    """
    src = _collision_fixture(tmp_path / "src", [b"README", b"readme"])
    snap = take_snapshot(src, tmp_path / "snap")  # must not raise

    with pytest.raises(Unrestorable) as caught:
        guarded_restore(snap, tmp_path / "out")

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_CASE_COLLISION
    assert not (tmp_path / "out").exists()  # refused before dest was touched


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="collision trees need a case-sensitive, byte-transparent filesystem",
)
def test_normalization_collision_tree_is_refused_at_restore(tmp_path: Path) -> None:
    """An NFC/NFD pair in one directory is refused at restore, by name."""
    pair = [
        unicodedata.normalize("NFD", "café").encode("utf-8"),
        unicodedata.normalize("NFC", "café").encode("utf-8"),
    ]
    src = _collision_fixture(tmp_path / "src", pair)
    snap = take_snapshot(src, tmp_path / "snap")  # must not raise

    with pytest.raises(Unrestorable) as caught:
        guarded_restore(snap, tmp_path / "out")

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_NORMALIZATION_COLLISION
    assert caught.value.path  # the offending name is named


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="an invalid-UTF8 name needs a byte-transparent filesystem",
)
def test_invalid_utf8_name_is_refused_at_restore(tmp_path: Path) -> None:
    """A name that is not valid UTF-8 is refused at restore, by name."""
    src = tmp_path / "src"
    src.mkdir()
    name = b"caf\xe9.txt"
    fd = os.open(
        os.path.join(os.fsencode(src), name), os.O_WRONLY | os.O_CREAT, 0o600
    )
    os.close(fd)
    snap = take_snapshot(src, tmp_path / "snap")  # must not raise

    with pytest.raises(Unrestorable) as caught:
        guarded_restore(snap, tmp_path / "out")

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_INVALID_UTF8_NAME
    assert caught.value.path == name


# --------------------------------------------------------------------------
# gc(): a Linux-safe removal, including non-ASCII names (spec criterion 4).
# --------------------------------------------------------------------------


def test_gc_removes_a_tree_with_non_ascii_names(tmp_path: Path) -> None:
    """`gc()` must remove a snapshot tree wholesale, whatever its names are.

    Runs on both platforms: the Linux branch (plain removal, no chflags /
    /bin/chmod -N) is exercised on Linux; the same removal contract holds here.
    The names are distinct spellings only — an NFC/NFD pair would be one file
    on APFS and is the collision fixture's job, not gc's.
    """
    victim = tmp_path / "victim"
    (victim / "café").mkdir(parents=True)
    (victim / "café" / "naïve.txt").write_text("hi")
    (victim / "ελληνικά").write_bytes(b"x")
    (victim / "ру́сский").write_bytes(b"nfd\n")

    gc(victim)
    assert not victim.exists()
