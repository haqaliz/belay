"""A tree exercising every axis BTH-1 claims to measure.

The fixture is the other half of the measuring instrument. A tree hash can only
be shown to notice a property that is actually *present* in the tree it is handed,
so every axis in BTH-1's spec has a corresponding feature here, and each one is
here because a real copy mechanism was measured losing it:

- **setuid (`0o4711`)** and **dir mtimes** — `clonefile` drops both.
- **hardlink identity** — `clonefile` turns a hardlink pair into two files.
- **xattrs** — `shutil.copytree` drops them.

All of the above are invisible to a content-only hash. That is the whole reason
BTH-1 exists, and it is why this fixture is not "some files".

**Deterministic by construction.** Every mtime is an explicit constant; nothing
here reads the wall clock, so two builds of this tree at two different paths and
two different times are identical to BTH-1 except for the paths. The inode-churn
control depends on that being true.

**No FIFOs, sockets, or devices.** Those are Phase 5's refusal tests. A FIFO here
would be actively dangerous: `open(fifo, "rb").read()` blocks forever with no
reader, and has already hung a test suite in this project's history.

**No `Foo`/`foo` pair.** APFS is case-insensitive; they cannot coexist, and the
second create would silently land on the first.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import stat
import unicodedata
from pathlib import Path

# A filename in NFD: 'e' followed by COMBINING ACUTE ACCENT, not the precomposed
# 'é'. Written via normalize() rather than pasted, because an editor or a git
# filter that silently normalises a pasted literal is precisely the drift this
# fixture exists to expose — and a pasted NFC 'é' would look identical here while
# testing nothing. APFS is normalization-preserving, so these bytes round-trip
# verbatim and readdir hands back the NFD form.
NFD_NAME = unicodedata.normalize("NFD", "café")

XATTR_NAME = b"user.belay.torture"
XATTR_VALUE = b"a value no copy mechanism may silently drop"

# Distinct, explicit, and never the wall clock. Distinct per path so that a hash
# which mixed two entries' mtimes together would still be caught.
_MTIME_BASE_NS = 1_700_000_000_000_000_000

# Set on `hidden.txt`. UF_HIDDEN specifically, and NOT UF_IMMUTABLE: an immutable
# file in a tmp tree cannot be deleted, and would leak a permanently undeletable
# directory into the runner on every test run.
HIDDEN_FLAG = stat.UF_HIDDEN

_XATTR_NOFOLLOW = 0x0001


def _libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.setxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    libc.setxattr.restype = ctypes.c_int
    return libc


def set_xattr(path: Path, name: bytes, value: bytes) -> None:
    """Write an xattr. `os.setxattr` does not exist on macOS, so this is ctypes.

    The write side lives in the fixture rather than in `belay.snapshot`: nothing
    in the shipped package has any business writing xattrs today. Restore (a
    later task) will need it and can promote it then.
    """
    if os.uname().sysname != "Darwin":  # pragma: no cover - this suite runs on macOS
        os.setxattr(os.fsencode(path), name, value, follow_symlinks=False)
        return
    libc = _libc()
    rc = libc.setxattr(os.fsencode(path), name, value, len(value), 0, _XATTR_NOFOLLOW)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))


def remove_xattr(path: Path, name: bytes) -> None:
    """Drop an xattr — the exact thing `shutil.copytree` was measured doing silently."""
    if os.uname().sysname != "Darwin":  # pragma: no cover - this suite runs on macOS
        os.removexattr(os.fsencode(path), name, follow_symlinks=False)
        return
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    libc.removexattr.restype = ctypes.c_int
    if libc.removexattr(os.fsencode(path), name, _XATTR_NOFOLLOW) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))


def build_torture_tree(root: Path) -> Path:
    """Build the torture tree under `root` (created if absent) and return it.

    Order is load-bearing. Every mtime is stamped in a final pass, deepest
    first, because creating or linking a child updates its parent directory's
    mtime — stamping a directory before filling it would leave the wall clock in
    the tree and make the hash non-deterministic across builds.
    """
    root.mkdir(parents=True, exist_ok=True)

    (root / "regular.txt").write_bytes(b"the plain case: content that must hash\n")
    os.chmod(root / "regular.txt", 0o644)

    # A non-trivial mode: write-by-group, write-by-other, readable by none of
    # them. Nothing about this is a default, so a restore that applies a umask
    # instead of the recorded mode cannot round-trip it by luck.
    (root / "mode642.bin").write_bytes(b"non-trivial mode\n")
    os.chmod(root / "mode642.bin", 0o642)

    # setuid. `clonefile` was measured turning 0o4711 into 0o0711 — the bit that
    # matters most for security is exactly the bit that is silently lost, and a
    # content-only hash calls that copy identical.
    (root / "setuid.bin").write_bytes(b"setuid payload\n")
    os.chmod(root / "setuid.bin", 0o4711)

    (root / "xattred.txt").write_bytes(b"carries a user xattr\n")
    set_xattr(root / "xattred.txt", XATTR_NAME, XATTR_VALUE)

    # A genuinely sparse file. st_blocks is deliberately NOT in the hash
    # (sparseness is a storage property, not identity), so this entry must hash
    # equal to a fully-materialised file of the same content. It is here to keep
    # that decision honest and visible, not to be discriminated.
    #
    # `truncate`, NOT the usual seek-past-the-end-and-write: measured on APFS,
    # seek+write allocates the whole range (st_blocks 2056, identical to a dense
    # file of the same size) and produces NO hole at all. Only truncate leaves
    # one. The obvious idiom would have made this entry a sparse file in name
    # only, and `test_sparseness_is_not_an_identity_difference` would have
    # compared two dense files and proved nothing.
    with open(root / "sparse.bin", "wb") as handle:
        handle.write(b"head")
        handle.truncate(1024 * 1024)

    nested = root / "nested"
    nested.mkdir()
    (nested / "child.txt").write_bytes(b"nested child\n")

    deeper = nested / "deeper"
    deeper.mkdir()
    (deeper / "leaf.txt").write_bytes(b"leaf\n")

    # An empty directory. It has no content to hash, so a hash driven by file
    # contents alone would not notice its disappearance at all.
    (root / "empty_dir").mkdir()

    # A hardlink pair spanning two directories: one inode, two names. `clonefile`
    # was measured breaking this into two independent inodes, which no content
    # hash can see. Cross-directory so that the group's identity cannot be
    # confused with "two entries that happen to sit side by side".
    (root / "hardlink_a.txt").write_bytes(b"one inode, two names\n")
    os.link(root / "hardlink_a.txt", nested / "hardlink_b.txt")

    # Relative and absolute symlinks. The absolute one points outside the tree
    # and at a path that need not exist: a symlink's identity is its target
    # bytes, and BTH-1 must never follow it to find out.
    os.symlink("regular.txt", root / "relative.link")
    os.symlink("/usr/bin/true", root / "absolute.link")

    # NFD filename, created from the raw encoded bytes.
    (root / NFD_NAME).write_bytes(b"nfd-named\n")

    # st_flags. Set after the content is written: the flag is metadata, and
    # writing through it later would be a different test.
    (root / "hidden.txt").write_bytes(b"flagged UF_HIDDEN\n")
    os.chflags(root / "hidden.txt", HIDDEN_FLAG)

    _stamp_mtimes(root)
    return root


def _stamp_mtimes(root: Path) -> None:
    """Stamp every entry with a distinct, constant mtime, deepest first.

    Deepest first because stamping a child does not disturb its parent, but
    *creating* one does. Directories therefore have to be stamped after
    everything inside them is final, or the tree would carry the wall clock.

    Each entry's mtime is derived from its **relative path**, not from its
    position in the walk: `os.walk` order is not guaranteed stable, so assigning
    mtimes by enumeration order would hand the same tree different mtimes on two
    builds and make the fixture itself non-deterministic — which would surface as
    a mysterious failure of the very determinism test that is supposed to be
    checking the hash. Deriving from the relative path also means a tree built at
    a different root gets identical mtimes, which is what the inode-churn control
    requires.

    Symlinks are stamped with `follow_symlinks=False`: stamping through a link
    would silently re-stamp its target, and `absolute.link` points at
    `/usr/bin/true`.
    """
    relatives = [
        (Path(dirpath) / name).relative_to(root)
        for dirpath, dirnames, filenames in os.walk(root)
        for name in list(dirnames) + list(filenames)
    ]
    # Deepest first, then by raw path bytes: a total, deterministic order.
    relatives.sort(key=lambda rel: (-len(rel.parts), os.fsencode(rel)))
    for offset, rel in enumerate(relatives):
        mtime = _MTIME_BASE_NS + offset * 1_000_000_000
        os.utime(root / rel, ns=(mtime, mtime), follow_symlinks=False)
    # The root last: every create inside it has already touched its mtime.
    os.utime(root, ns=(_MTIME_BASE_NS, _MTIME_BASE_NS), follow_symlinks=False)
