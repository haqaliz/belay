"""Snapshot and restore a turn's pre-state, byte-identically, via `clonefile(2)`.

This is the floor everything downstream stands on. A replayed turn is only
grounded if it runs against the state that was really there — so a pre-state that
cannot be restored is not a weaker verdict, it is *no* verdict. C2's acceptance
test is the roadmap's sentence verbatim: *"a turn's pre-state snapshot restores
byte-identically; a hash of the restored tree equals the hash of the original."*
`tests/test_snapshot.py` is that sentence, measured by BTH-1.

**Why `clonefile`.** It clones a whole directory tree recursively in one call,
copy-on-write: measured on this machine, 412MB / 4804 files in **71ms for 3.1MB
of real disk** (verified with `df`, not `du`). A per-turn snapshot that cost the
size of the workspace would make C2 unusable in practice, so the cheapness is not
a nicety — it is what lets a snapshot happen on *every* turn.

`ctypes` rather than a subprocess: `os.clonefile` does not exist, and `ctypes` is
stdlib, so Belay's zero-runtime-dependency constraint holds. **Not `cp -Rc`**,
which was measured worse — it recreates non-regular files fresh and loses symlink
mtimes.

**`CLONE_ACL` is mandatory.** With `flags=0`, `clonefile` **silently drops ACLs**.
Measured. There is no error and no warning; the tree simply comes back with its
access control weakened, which is precisely the kind of loss a restore must never
make quietly.

## The three repairs, and why a sidecar is unavoidable

`clonefile` silently loses exactly three things — measured here against the
torture tree, and nothing else in it:

| Lost | Measured | Repair |
|---|---|---|
| hardlink identity | `nlink=2` becomes two independent, content-identical inodes | relink |
| setuid | `0o4711` -> `0o0711`, security-motivated and silent | re-chmod |
| directory mtimes | reset on any directory written into | restamp, deepest-first |

**All three are invisible to a content-only hash.** A restore that lost every one
of them would still look "byte-identical" to a naive check — a false PASS on
exactly the security-relevant divergence a restore most needs to catch. That is
why BTH-1 hashes `link_group`, `perm` and `mtime_ns`, and why
`test_ablating_a_repair_breaks_the_restore` is permanent: it disables each repair
and requires the acceptance test to fail, naming the field. A repair without that
guard is a repair someone deletes in a year while the suite stays green.

The losses happen **at clone time**, which means the snapshot on disk has already
lost them and cannot be the source of its own repair. So the truth is captured
from the **original** into a `Sidecar` and carried alongside. `snapshot()` then
repairs the clone immediately, so the artifact on disk is itself faithful rather
than silently lossy for anyone who reads it directly.

**The sidecar is captured independently of BTH-1, on purpose.** Deriving the
repairs from `scan_tree`'s records would be less code and would guarantee the two
agreed — which is exactly the problem. A field BTH-1 misread would then be a
field the repair skipped in the same way, and the hash would report PASS on a
tree it had mis-measured: the instrument grading its own homework. Two independent
readings of the filesystem can disagree, and BTH-1 is what catches it when they do.

**No verdicts here.** Snapshot and restore report facts and raise on failure. The
PASS/WARN/FAIL/UNVERIFIED contract belongs to C4/C5; a mechanism that judged its
own fidelity would be the same mistake in a smaller box.

## Limits, stated plainly

- **macOS/APFS only.** `clonefile` is Darwin's. Elsewhere this raises
  `UnsupportedPlatform` rather than falling back to a copy that would silently
  lose the very fields the repairs exist to preserve.
- **The sidecar lives in memory**, so a `Snapshot` does not outlive its process.
  Persisting it is a later task; nothing today needs a snapshot to survive a
  restart.
- **FIFOs, sockets and devices are not handled** — the torture tree has none, and
  refusing them explicitly is Task 6. Until then this module does not claim to
  restore them.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Iterator, Union

from .bth1 import UnsupportedPlatform

#: What `pathlib.Path` accepts. Deliberately NOT `bytes`: a `Snapshot` carries a
#: `Path`, and a bytes root could not round-trip through it. The paths that must
#: stay raw bytes are the ones *inside* the tree — every walk below fsencodes the
#: root and never lets an entry name touch `str`.
TreeRoot = Union[str, "os.PathLike[str]"]

#: Every repair `restore` knows how to apply. The ablation test pins this set:
#: a fourth repair added without a matching ablation case is a repair no test
#: proves load-bearing.
ALL_REPAIRS = frozenset({"hardlinks", "suid", "dirmtimes"})

# From the real SDK header, sys/clonefile.h. CLONE_ACL is the only one used:
# without it, ACLs are dropped silently. The rest are here so the next reader
# does not have to go find the header.
CLONE_NOFOLLOW = 0x0001
CLONE_NOOWNERCOPY = 0x0002
CLONE_ACL = 0x0004
CLONE_NOFOLLOW_ANY = 0x0008
CLONE_RESOLVE_BENEATH = 0x0010

# The bits clonefile drops. setuid is the one that was measured and the one that
# matters most; setgid and sticky are captured with it because they are dropped
# by the same security-motivated logic, and re-applying a mode that was never
# lost is a no-op either way.
_SPECIAL_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX


@dataclass(frozen=True)
class Sidecar:
    """What `clonefile` will lose, read from the original before it is lost.

    Paths are raw bytes relative to the tree root, for the reason BTH-1 gives at
    length: decoding a path would reintroduce unicode normalisation into a
    comparison whose whole claim is that it is byte-exact.
    """

    #: (primary, other members) per hardlink group, primary in raw-byte order.
    link_groups: tuple[tuple[bytes, tuple[bytes, ...]], ...]
    #: (path, S_IMODE) for entries carrying setuid/setgid/sticky.
    special_modes: tuple[tuple[bytes, int], ...]
    #: (path, (atime_ns, mtime_ns)) for directories, **deepest first**.
    dir_times: tuple[tuple[bytes, tuple[int, int]], ...]


@dataclass(frozen=True)
class Snapshot:
    """A cloned tree plus the truth `clonefile` could not carry."""

    path: Path
    sidecar: Sidecar


def _require_darwin() -> None:
    if sys.platform != "darwin":
        raise UnsupportedPlatform(
            f"clonefile-based snapshot needs Darwin/APFS; this is {sys.platform!r}. "
            "Refusing rather than falling back to a plain copy: every fallback available "
            "here silently loses hardlink identity, setuid, or xattrs, and a restore that "
            "quietly dropped those would report a byte-identical pre-state it had not "
            "actually restored."
        )


def _clonefile(source: Path, dest: Path) -> None:
    """One recursive, copy-on-write clone of `source` to `dest` (must not exist)."""
    _require_darwin()
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    # Declared explicitly: letting ctypes infer an argument's width is how a
    # pointer gets truncated.
    libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    libc.clonefile.restype = ctypes.c_int
    if libc.clonefile(os.fsencode(source), os.fsencode(dest), CLONE_ACL) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(source), None, str(dest))


def _walk(root: bytes) -> Iterator[bytes]:
    """Every entry under `root` as raw relative bytes, root included as `b"."`.

    Iterative, so a deep tree does not depend on Python's recursion limit, and
    symlinks are never followed: following one would walk into the target's
    contents under the link's name, and `absolute.link` points at `/usr/bin/true`.
    """
    yield b"."
    stack = [b""]
    while stack:
        prefix = stack.pop()
        with os.scandir(os.path.join(root, prefix) if prefix else root) as entries:
            for entry in entries:
                rel = os.path.join(prefix, entry.name) if prefix else entry.name
                yield rel
                if entry.is_dir(follow_symlinks=False):
                    stack.append(rel)


def _full(root: bytes, rel: bytes) -> bytes:
    return root if rel == b"." else os.path.join(root, rel)


def _depth(rel: bytes) -> int:
    return 0 if rel == b"." else rel.count(b"/") + 1


def capture(root: TreeRoot) -> Sidecar:
    """Read the three properties `clonefile` is about to destroy."""
    root_bytes = os.fsencode(root)
    by_inode: dict[tuple[int, int], list[bytes]] = {}
    special: list[tuple[bytes, int]] = []
    dirs: list[tuple[bytes, tuple[int, int]]] = []

    for rel in _walk(root_bytes):
        info = os.lstat(_full(root_bytes, rel))
        mode = info.st_mode

        # Regular files only. Every directory has nlink > 1 (`.` and `..`), so
        # including them would invent a hardlink group for each one.
        if stat.S_ISREG(mode) and info.st_nlink > 1:
            by_inode.setdefault((info.st_dev, info.st_ino), []).append(rel)

        # Never a symlink: chmod would follow it and re-mode the target instead.
        if not stat.S_ISLNK(mode) and mode & _SPECIAL_BITS:
            special.append((rel, stat.S_IMODE(mode)))

        if stat.S_ISDIR(mode):
            dirs.append((rel, (info.st_atime_ns, info.st_mtime_ns)))

    groups: list[tuple[bytes, tuple[bytes, ...]]] = []
    for members in by_inode.values():
        if len(members) < 2:
            continue  # the other names live outside the tree; nothing to rebuild
        primary, *others = sorted(members)  # raw-byte order, stable across scans
        groups.append((primary, tuple(others)))

    # Deepest first: restamping a child never disturbs its parent, but writing
    # one does. Sorted here, at capture, so the ordering cannot be lost by a
    # caller reordering the repair.
    dirs.sort(key=lambda item: (-_depth(item[0]), item[0]))

    return Sidecar(
        link_groups=tuple(sorted(groups)),
        special_modes=tuple(sorted(special)),
        dir_times=tuple(dirs),
    )


def _repair(root: TreeRoot, sidecar: Sidecar, repairs: Collection[str]) -> None:
    """Put back what `clonefile` dropped.

    Order is load-bearing, and `dirmtimes` is last for a reason: relinking a
    hardlink writes into its parent directory and bumps that directory's mtime,
    so restamping before the relink would restore a mtime the relink then
    destroys.
    """
    root_bytes = os.fsencode(root)

    if "hardlinks" in repairs:
        for primary, others in sidecar.link_groups:
            for other in others:
                target = _full(root_bytes, other)
                # The clone left an independent, content-identical inode here.
                # Drop it and point the name back at the primary: the shape
                # ("these two names are one file") is what has to survive, and
                # all metadata rides on the shared inode.
                os.unlink(target)
                os.link(_full(root_bytes, primary), target)

    if "suid" in repairs:
        for rel, mode in sidecar.special_modes:
            os.chmod(_full(root_bytes, rel), mode)

    if "dirmtimes" in repairs:
        for rel, (atime_ns, mtime_ns) in sidecar.dir_times:
            os.utime(
                _full(root_bytes, rel), ns=(atime_ns, mtime_ns), follow_symlinks=False
            )


def snapshot(source: TreeRoot, dest: TreeRoot) -> Snapshot:
    """Clone the tree at `source` to `dest`, faithfully. `dest` must not exist.

    The sidecar is captured **before** the clone, because the clone is what
    destroys the fields it records.
    """
    _require_darwin()
    sidecar = capture(source)
    _clonefile(Path(source), Path(dest))
    # Repair the snapshot itself, so what sits on disk is the tree that was
    # really there rather than a quietly lossy copy of it.
    _repair(dest, sidecar, ALL_REPAIRS)
    return Snapshot(path=Path(dest), sidecar=sidecar)


def restore(
    snap: Snapshot, dest: TreeRoot, repairs: Collection[str] = ALL_REPAIRS
) -> None:
    """Replace whatever is at `dest` with the snapshotted tree.

    `repairs` exists **only** so `test_ablating_a_repair_breaks_the_restore` can
    disable one and prove the acceptance test fails without it. Production
    callers must never narrow it: a restore missing a repair is a restore that
    silently returns the wrong pre-state, which is worse than no restore at all,
    because everything downstream would still call it grounded.
    """
    _require_darwin()
    dest = Path(dest)
    if dest.exists():
        # clonefile refuses an existing destination, and this is the point where
        # the mutated turn state is discarded.
        shutil.rmtree(dest)
    _clonefile(snap.path, dest)
    _repair(dest, snap.sidecar, repairs)
