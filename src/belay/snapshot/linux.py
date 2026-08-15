"""Snapshot and restore a turn's pre-state, byte-identically, on the Linux substrate.

This is the second `SnapshotBackend` behind the `ClonefileBackend` pattern
(`substrate.py`): same seam, same sidecar manifest contract, same BTH-1
acceptance — but honest about what each Linux filesystem can actually provide.
GitHub runners are ext4, which has no reflink, so the **copy path with sidecar
repairs is the CI path**; `FICLONE` reflink is probed per directory and declared
in `capabilities()`, never assumed.

## Why the copy is a *lossy mechanism with repairs*, not a plain copy

`clonefile` silently loses exactly three things — hardlink identity, setuid,
and directory mtimes — and the macOS backend repairs them from a `Sidecar`
captured from the original before the clone. The Linux copy reproduces the same
three losses **deliberately** (members are copied as independent files, special
bits are masked, directory mtimes are bumped by the creation work), so that:

- one sidecar contract and one repair set (`clone.ALL_REPAIRS`) serve both
  substrates, and the manifest round-trip is byte-compatible (PRD M4);
- `test_ablating_a_repair_breaks_the_restore` stays meaningful — a repair that
  was never load-bearing would be a decoration someone deletes while the suite
  stays green.

The on-disk artifact is repaired at snapshot time, exactly like the macOS side,
so the clone sitting on disk is itself faithful for anyone who reads it
directly.

## Reflink, and the honest fallback

`FICLONE` (`_FICLONE`) copies one file's extents copy-on-write. Whether it works
is a property of the *destination* filesystem, so it is **probed** — a scratch
pair is reflinked in the snapshot directory, and only a real success claims the
`reflink` capability. At copy time every regular file still tries FICLONE only
when the probe said so, and a per-file failure with `EXDEV`/`EOPNOTSUPP` (a
cross-mount restore, a bind mount that cannot reflink) falls back to a plain
byte copy: the fallback is fully faithful, so the capability stays honest and
the tree stays correct (OQ-5).

## The three reserved taxonomy causes

`UNRESTORABLE_CASE_COLLISION`, `UNRESTORABLE_INVALID_UTF8_NAME` and
`UNRESTORABLE_NORMALIZATION_COLLISION` were deferred by `substrate.py` because
APFS cannot even *create* the trees that trigger them (measured: EEXIST /
EILSEQ). Linux's case-sensitive, byte-transparent filesystems can — and a tree
holding such names cannot be *guaranteed* to land byte-identically on an
unknown destination filesystem. `restore()` therefore scans the snapshot tree
before touching dest and refuses by name (`_hazard_cause`, `readdir`-proven).
The workspace itself is never refused: a real agent tree with `README` and
`readme` snapshots fine, and only a later restore names the hazard.

## Out of substrate

FIFOs, sockets and devices stay refused by the substrate-neutral `Guard` at
capture; this module's copy code therefore never meets one, and the class-based
scan above never classifies one. `st_rdev` is not copied because a device node
can never be in a snapshot.
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Collection, Optional, Sequence

from .clone import ALL_REPAIRS, Snapshot, TreeRoot, _repair, _walk, capture
from .substrate import Unrestorable, UnrestorableCause

# Linux `FICLONE` ioctl: _IOW(0x94, 9, int). Built from the ioctl() macros
# rather than pasted as a magic constant, so the request is right on any
# platform where sizeof(int) is not 4.
_FICLONE = (1 << 30) | (ctypes.sizeof(ctypes.c_int) << 16) | (0x94 << 8) | 9

#: The errno family that means "this filesystem cannot reflink" — the honest
#: per-file fallback set. Anything else (EIO, ENOSPC, EPERM) is a real failure
#: and propagates.
_REFLINK_FALLBACK_ERRNOS = frozenset(
    {errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY, errno.EINVAL, errno.ENOSYS}
)

# The bits the copy deliberately masks and the sidecar repair puts back — the
# mirror of what clonefile loses on macOS (see the module docstring).
_SPECIAL_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX

#: Memo of the FICLONE probe, keyed by the real path of the directory probed.
#: A reflink capability cannot flip between calls on a live machine, and a
#: non-deterministic probe would manufacture capability mismatches.
_REF_PROBED: dict[bytes, bool] = {}

_LIBC = ctypes.CDLL(None, use_errno=True)
_LIBC.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_int]
_LIBC.ioctl.restype = ctypes.c_int


def _ficlone(src: bytes, dst: bytes) -> None:
    """Reflink the contents of `src` into a NEW inode at `dst` (`FICLONE`).

    `dst` must not exist. Raises `OSError` when the destination filesystem
    cannot reflink (`EOPNOTSUPP` on ext4/tmpfs, `EXDEV` across mounts) — the
    caller decides whether that is the honest fallback or a real failure.
    """
    src_fd = os.open(src, os.O_RDONLY)
    dst_fd = None
    try:
        dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        if _LIBC.ioctl(dst_fd, _FICLONE, src_fd) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), os.fsdecode(dst))
    finally:
        if dst_fd is not None:
            os.close(dst_fd)
        os.close(src_fd)


def _probe_reflink(directory: TreeRoot) -> bool:
    """Whether `FICLONE` works in `directory`, measured once per directory.

    Probed, never declared: ext4 and tmpfs answer `EOPNOTSUPP`, and a
    capability set that claimed reflink there would be a claim about a machine
    the code had never seen. The probe writes one scratch pair and removes it
    on every path; the result is memoized so `capabilities()` and the copy
    machinery agree for the life of the process.
    """
    key = os.path.realpath(os.fsencode(directory))
    if key in _REF_PROBED:
        return _REF_PROBED[key]
    scratch = [
        os.path.join(key, f".belay-reflink-probe-{os.getpid()}-{suffix}".encode())
        for suffix in ("src", "dst")
    ]
    ok = False
    try:
        fd = os.open(scratch[0], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b"x")
        os.close(fd)
        _ficlone(scratch[0], scratch[1])
        ok = True
    except OSError:
        ok = False
    finally:
        for name in scratch:
            try:
                os.unlink(name)
            except OSError:
                pass
    _REF_PROBED[key] = ok
    return ok


def _copy_xattrs(src: bytes, dst: bytes) -> None:
    """Copy every xattr from `src` to `dst`, never following a symlink.

    `os.listxattr` is Linux-native, so no ctypes is needed — the same branch
    BTH-1 already uses. On a platform without it (macOS test runs of this
    copy machinery) there is nothing to copy; BTH-1 still hashes xattrs there
    via its Darwin ctypes path, so a loss could not go silent.
    """
    if not hasattr(os, "listxattr"):
        return
    for name in os.listxattr(src, follow_symlinks=False):
        value = os.getxattr(src, name, follow_symlinks=False)
        os.setxattr(dst, name, value, follow_symlinks=False)


def _materialize_regular(src: bytes, dst: bytes, info: os.stat_result, reflink_ok: bool) -> None:
    """One regular file: content, then every fidelity axis, in load-bearing order.

    The order is the correctness. Writing content clears setuid (so the mode
    comes after); `setxattr` bumps mtime (so xattrs come before the restamp);
    `chown` clears setuid/setgid (so it comes before the chmod); and nothing
    may touch the file after the final `utime` — mtime is the last field
    BTH-1 reads, and a repair that restamps it later is applied by `_repair`.
    """
    if reflink_ok:
        try:
            _ficlone(src, dst)
        except OSError as exc:
            if exc.errno not in _REFLINK_FALLBACK_ERRNOS:
                raise
            shutil.copyfile(src, dst)
    else:
        shutil.copyfile(src, dst)
    _copy_xattrs(src, dst)
    if info.st_gid != os.getegid():
        os.chown(dst, -1, info.st_gid)
    os.chmod(dst, stat.S_IMODE(info.st_mode) & ~_SPECIAL_BITS)
    os.utime(dst, ns=(info.st_atime_ns, info.st_mtime_ns))


def _create_tree(src: TreeRoot, dst: Path, reflink_ok: bool) -> None:
    """Build `dst` as a faithful *shape* of `src`; the repairs come after.

    The three deliberate losses are made here, mirroring what `clonefile` does
    on macOS: hardlink members are copied as independent files, special bits
    are masked, and directory mtimes are bumped by the creation work — all
    three are put back from the sidecar by `_repair`, which is what keeps the
    repair set load-bearing on this substrate too.

    FIFOs, sockets and devices cannot appear: the substrate `Guard` refused
    them at capture, and a snapshot tree is produced by this module.
    """
    src_b = os.fsencode(src)
    dst_b = os.fsencode(dst)
    dst.mkdir()
    for rel in _walk(src_b):
        if rel == b".":
            continue
        full_src = os.path.join(src_b, rel)
        full_dst = os.path.join(dst_b, rel)
        info = os.lstat(full_src)
        mode = info.st_mode
        if stat.S_ISDIR(mode):
            os.mkdir(full_dst)
            _copy_xattrs(full_src, full_dst)
            if info.st_gid != os.getegid():
                os.chown(full_dst, -1, info.st_gid)
            os.chmod(full_dst, stat.S_IMODE(mode) & ~_SPECIAL_BITS)
        elif stat.S_ISLNK(mode):
            os.symlink(os.readlink(full_src), full_dst)
            _copy_xattrs(full_src, full_dst)
            if info.st_gid != os.getegid():
                os.lchown(full_dst, -1, info.st_gid)
            os.utime(
                full_dst,
                ns=(info.st_atime_ns, info.st_mtime_ns),
                follow_symlinks=False,
            )
        elif stat.S_ISREG(mode):
            _materialize_regular(full_src, full_dst, info, reflink_ok)


def _hazard_cause(
    names: Sequence[bytes],
) -> Optional[tuple[UnrestorableCause, bytes]]:
    """The taxonomy cause a directory's names would be refused for, or `None`.

    Pure over raw byte names, so it is testable on any platform: the hazards
    are byte-level facts about names. A name that is not valid UTF-8 is refused
    first; then, pairwise over case-folded spellings (an ASCII `README`/`readme`
    pair) and NFC-normalised spellings (an NFD/NFC pair — `casefold` does not
    reorder combining sequences, so NFD stays unequal there and falls through
    to the NFC check). Returns `(cause, offending_name_bytes)`.
    """
    decoded: list[tuple[bytes, str]] = []
    for name in names:
        try:
            decoded.append((name, name.decode("utf-8")))
        except UnicodeDecodeError:
            return UnrestorableCause.UNRESTORABLE_INVALID_UTF8_NAME, name
    for i, (_, left) in enumerate(decoded):
        for right_b, right in decoded[i + 1 :]:
            if left == right:
                continue
            if left.casefold() == right.casefold():
                return UnrestorableCause.UNRESTORABLE_CASE_COLLISION, right_b
            if unicodedata.normalize("NFC", left) == unicodedata.normalize(
                "NFC", right
            ):
                return UnrestorableCause.UNRESTORABLE_NORMALIZATION_COLLISION, right_b
    return None


def _refuse_unfaithful_tree(root: TreeRoot) -> None:
    """Refuse to restore a snapshot tree whose names cannot be faithfully promised.

    A case-collision, a normalization-collision or an invalid-UTF8 name is a
    byte-level fact the restore cannot guarantee to land on an unknown
    destination filesystem — refused **before** `dest` is touched, matching the
    capability-mismatch contract. Only `restore` refuses: a real workspace that
    holds such names snapshots fine.
    """
    root_b = os.fsencode(root)
    for dirpath, dirnames, filenames in sorted(os.walk(root_b)):
        found = _hazard_cause(sorted(dirnames + filenames))
        if found is None:
            continue
        cause, name = found
        rel = b"." if dirpath == root_b else os.path.relpath(dirpath, root_b)
        raise Unrestorable(
            cause,
            f"directory {os.fsdecode(rel)!r} holds a name "
            f"({os.fsdecode(name)!r}) that is a case-fold or unicode-normalization "
            "collision, or not valid UTF-8 — the restore cannot faithfully promise "
            "that name on every destination filesystem; refusing rather than "
            "restoring a tree that may come back missing an entry",
            path=name,
            source="readdir",
        )


class LinuxSnapshotBackend:
    """The Linux substrate backend, and what it can actually promise.

    `name` names the contract — faithful snapshot/restore via the shared
    sidecar-repair mechanism — not the mechanism: whether reflink (`FICLONE`)
    is actually used is a probed per-directory capability, never a name.
    `capabilities()` is **probed, not declared**, for the same reason as
    `ClonefileBackend`: the set is what a restore refuses across, so a wrong
    entry here is a false PASS with extra steps.
    """

    name = "copy-fidelity"

    @staticmethod
    def capabilities(probe_dir: Optional[TreeRoot] = None) -> frozenset[str]:
        """This machine's honest capability set, measured rather than listed.

        `probe_dir` is the directory whose filesystem the `reflink` claim is
        about (the snapshot directory); without one, the platform temp
        directory is probed. The static members are structural on Linux —
        `os.link`, `os.symlink`, `os.chmod`, `os.utime` and `os.listxattr` all
        exist as kernel features — and `reflink` alone is a measurement.
        """
        caps = {
            "hardlinks",  # rebuilt from the sidecar, like the macOS backend
            "special-modes",  # setuid/setgid/sticky, re-chmod'ed from the sidecar
            "dir-mtimes",  # restamped deepest-first
            "symlinks",  # recreated via os.symlink with raw targets
        }
        if hasattr(os, "listxattr"):
            caps.add("xattrs-os-native")
        if _probe_reflink(probe_dir if probe_dir is not None else tempfile.gettempdir()):
            caps.add("reflink")
        return frozenset(caps)


def snapshot(source: TreeRoot, dest: TreeRoot) -> Snapshot:
    """Copy the tree at `source` to `dest`, faithfully. `dest` must not exist.

    The sidecar is captured **before** the copy, because the copy is what
    destroys the fields it records — the same ordering as `clone.snapshot`.
    """
    sidecar = capture(source)
    dest = Path(dest)
    reflink_ok = _probe_reflink(dest.parent)
    _create_tree(Path(source), dest, reflink_ok)
    # Repair the snapshot itself, so what sits on disk is the tree that was
    # really there rather than a quietly lossy copy of it.
    _repair(dest, sidecar, ALL_REPAIRS)
    return Snapshot(path=dest, sidecar=sidecar)


def restore(
    snap: Snapshot, dest: TreeRoot, repairs: Collection[str] = ALL_REPAIRS
) -> None:
    """Replace whatever is at `dest` with the snapshotted tree.

    `repairs` exists **only** so `test_ablating_a_repair_breaks_the_restore`
    can disable one and prove the acceptance test fails without it. Production
    callers must never narrow it: a restore missing a repair is a restore that
    silently returns the wrong pre-state.
    """
    _refuse_unfaithful_tree(snap.path)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    reflink_ok = _probe_reflink(Path(snap.path).parent)
    _create_tree(snap.path, dest, reflink_ok)
    _repair(dest, snap.sidecar, repairs)


__all__ = [
    "LinuxSnapshotBackend",
    "_hazard_cause",
    "_probe_reflink",
    "restore",
    "snapshot",
]
