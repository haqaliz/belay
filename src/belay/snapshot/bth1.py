"""BTH-1: a deterministic, versioned hash of a directory tree's full identity.

This is the measuring instrument for C2. The roadmap's acceptance test is
literally *"a turn's pre-state snapshot restores byte-identically; a hash of the
restored tree equals the hash of the original"* — this module **is** that claim.
Everything C2 later reports green is green according to BTH-1, so a flaw here is
not one bug among many: it is a false PASS manufactured by the instrument itself,
which is the worst failure available in a project whose entire thesis is that a
verdict must be grounded in execution rather than asserted.

**Why not just hash the contents.** Measured on this machine, against real copy
mechanisms:

- `clonefile` silently loses **hardlink identity**, **setuid** (`0o4711` becomes
  `0o0711`), and **directory mtimes**.
- `shutil.copytree` silently loses **xattrs**.

Every one of those is invisible to a content-only hash. A content-only BTH-1
would call each of those copies "byte-identical" while the restored tree had lost
the setuid bit — reporting PASS on precisely the divergence a security-relevant
restore most needs to catch.

**BTH-1 reports facts, never verdicts.** A digest, the per-entry records behind
it, and which fields differ. It never emits PASS/WARN/FAIL/UNVERIFIED; C4/C5
judge. It is deliberately possible to look at a BTH-1 diff and decide the
difference does not matter — that decision is not this module's to make.

## In the hash

version tag `BTH-1` · raw readdir **path bytes** · kind · `S_IMODE` (carrying
setuid/setgid/sticky) · `mtime_ns` · `st_flags` · uid/gid · size and sha256 of
content for **regular files only** · symlink target as **raw bytes** · `st_rdev`
for devices · sorted `(xattr_name, sha256(value))` · hardlink **group id**.

## Out of the hash — every exclusion, and why

Each of these is excluded on purpose. An exclusion is a place where BTH-1 will
call two trees identical, so each one is a deliberate, documented narrowing of
what "byte-identical" is allowed to mean here.

- **inode numbers and `st_dev`** — unstable across a restore *by construction*: a
  restored tree gets whatever inodes the filesystem hands out. Including them
  would make every restore report a mismatch, which is not a strict hash but a
  useless one. Hardlink *structure* is preserved instead (see below), which is
  the part that actually carries meaning.
- **atime** — **self-invalidating.** Hashing the tree reads every file, which
  updates atime, so a BTH-1 that hashed atime could not reproduce its own digest.
  `test_atime_churn_does_not_move_the_hash` is the control that keeps this true.
- **ctime** — unsettable. No restore can reproduce it, so including it would
  guarantee a permanent false mismatch.
- **birthtime** — unsettable by *anyone*, including `tar`. APFS additionally
  clamps it to mtime, so it is not even independently observable here.
- **`st_blocks`** — sparseness is a *storage* property, not identity. A sparse
  file and a fully-materialised file with the same bytes have the same content.
  This belongs in a separate WARN (a restore that silently inflated a sparse file
  is worth reporting), never in an identity diff.
- **raw `st_nlink`** — implied by the group structure, and on its own it is
  misleading: every directory has `nlink > 1`, and the count alone cannot say
  *which* entries share an inode.

## Hardlink identity: the group id, not the inode

A hardlinked group is recorded as the **first path in the group** (in raw-byte
order), not the inode number. The inode is unstable across restore; the *shape*
— "these two names are the same file" — is exactly what must survive, and is what
`clonefile` was measured destroying. `st_dev`/`st_ino` are used only as a
transient grouping key while scanning and never reach the hash.

## Ordering, and the normalisation trap

Records sort by **raw path bytes**. readdir order is not stable, so an unsorted
hash would be non-deterministic. Sorting by `str` would be worse than useless: it
would reintroduce unicode normalisation into the comparison. APFS is
normalization-*preserving* and normalization-*insensitive*, so NFD bytes
round-trip verbatim — "byte-identical" is an honest claim here **only** because
this module never lets a path touch `str`. A BTH-1 built on decoded paths would
call two trees with genuinely different filename bytes identical, and that drift
would be invisible from then on.

## Structure

`sha256("BTH-1\\n" + concat(sha256(record) for record in sorted_records))`, over
the records' raw 32-byte digests. Each record is `\\x00`-joined `key=value`
fields, so a difference **names the field** (`perm`) rather than printing two
differing hex strings and leaving the reader to guess. `scan_tree` exposes the
records and `diff_records` the per-field differences, so a caller can always ask
*what* changed rather than only *that* something did.

The version tag is in the hash because the record format is an interchange
contract: a future BTH-2 must be visibly different rather than silently
incomparable.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from typing import Iterator, Optional, Sequence

TREE_HASH_VERSION = "BTH-1"

# macOS stamps `com.apple.provenance` onto files it creates, on its own, with no
# involvement from whatever wrote the file. It therefore says nothing about the
# tree's identity — but the trap it sets is nastier than mere noise: because macOS
# injects it universally, a naive "does this file still have xattrs?" check
# answers YES on a tree that lost every real xattr it had. Hashing it would also
# make trees non-comparable across machines, for no gain.
IGNORED_XATTRS = frozenset({b"com.apple.provenance"})

_XATTR_NOFOLLOW = 0x0001

_KINDS = (
    (stat.S_ISDIR, "dir"),
    (stat.S_ISREG, "file"),
    (stat.S_ISLNK, "link"),
    (stat.S_ISFIFO, "fifo"),
    (stat.S_ISSOCK, "sock"),
    (stat.S_ISBLK, "blk"),
    (stat.S_ISCHR, "chr"),
)

_CONTENT_CHUNK = 1024 * 1024

# CPython does not define this one: it is Darwin's "no such attribute".
_ENOATTR = getattr(errno, "ENOATTR", 93)


class UnsupportedPlatform(RuntimeError):
    """Raised where BTH-1 cannot read a property it claims to hash.

    Deliberately loud. The alternative — quietly reporting no xattrs on a
    platform whose xattrs we cannot read — would make a tree that lost every
    xattr hash equal to one that kept them: a false PASS invented by the
    instrument, which is the one outcome this module exists to prevent.
    """


@dataclass(frozen=True)
class Record:
    """One filesystem entry, as the ordered fields that define its identity.

    `path` is relative to the scanned root and is always raw bytes.
    """

    path: bytes
    fields: tuple[tuple[str, bytes], ...]

    def field(self, name: str) -> Optional[bytes]:
        for key, value in self.fields:
            if key == name:
                return value
        return None

    @property
    def encoded(self) -> bytes:
        # surrogateescape: an xattr name is bytes and need not be valid UTF-8.
        # It round-trips losslessly, so an undecodable name still reaches the
        # hash exactly as the filesystem gave it.
        return b"\x00".join(
            key.encode("utf-8", "surrogateescape") + b"=" + value for key, value in self.fields
        )

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.encoded).hexdigest()


@dataclass(frozen=True)
class FieldDiff:
    """One field of one entry, differing between two scans.

    `field` is None when the entry exists on only one side; `left`/`right` is
    None on the side where it is absent.
    """

    path: bytes
    field: Optional[str]
    left: Optional[bytes]
    right: Optional[bytes]


def _libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    # Darwin's signatures carry two arguments Linux's do not: `position` (for
    # resource forks) and `options` (XATTR_NOFOLLOW). Declared explicitly —
    # letting ctypes guess an argument's width is how a pointer gets truncated.
    libc.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
    libc.listxattr.restype = ctypes.c_ssize_t
    libc.getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    libc.getxattr.restype = ctypes.c_ssize_t
    return libc


def _raise_errno(path: bytes) -> None:
    err = ctypes.get_errno()
    raise OSError(err, os.strerror(err), os.fsdecode(path))


def _darwin_xattrs(path: bytes) -> list[tuple[bytes, bytes]]:
    """Read xattrs via libc, because `os.listxattr` does not exist on macOS.

    CPython gates `os.listxattr`/`os.getxattr` to Linux. `ctypes` is stdlib, so
    reaching for libc here costs nothing against the zero-runtime-dependency
    constraint.

    `XATTR_NOFOLLOW` throughout: an entry's xattrs are its own, and following a
    symlink would silently attribute its target's xattrs to the link.
    """
    libc = _libc()
    size = libc.listxattr(path, None, 0, _XATTR_NOFOLLOW)
    if size < 0:
        _raise_errno(path)
    if size == 0:
        return []
    buffer = ctypes.create_string_buffer(size)
    written = libc.listxattr(path, buffer, size, _XATTR_NOFOLLOW)
    if written < 0:
        _raise_errno(path)

    out: list[tuple[bytes, bytes]] = []
    for name in buffer.raw[:written].split(b"\x00"):
        if not name:
            continue
        value = _darwin_getxattr(libc, path, name)
        if value is not None:
            out.append((name, value))
    return out


def _darwin_getxattr(libc: ctypes.CDLL, path: bytes, name: bytes) -> Optional[bytes]:
    """One xattr's value, or None if it vanished between listing and reading."""
    for _ in range(5):
        size = libc.getxattr(path, name, None, 0, 0, _XATTR_NOFOLLOW)
        if size < 0:
            if ctypes.get_errno() == _ENOATTR:
                return None
            _raise_errno(path)
        buffer = ctypes.create_string_buffer(size + 1)
        written = libc.getxattr(path, name, buffer, size, 0, _XATTR_NOFOLLOW)
        if written >= 0:
            return buffer.raw[:written]
        err = ctypes.get_errno()
        if err == _ENOATTR:
            return None
        if err != errno.ERANGE:
            _raise_errno(path)
        # ERANGE: the value grew between sizing and reading. Re-size and retry.
    raise OSError(errno.ERANGE, "xattr kept changing size while being read", os.fsdecode(path))


def read_xattrs(path: bytes) -> list[tuple[bytes, bytes]]:
    """Every xattr on `path` itself, sorted by name, minus `IGNORED_XATTRS`.

    Takes raw bytes, never a `str`, for the same reason the rest of this module
    does.
    """
    if sys.platform == "darwin":
        pairs = _darwin_xattrs(path)
    elif hasattr(os, "listxattr"):
        pairs = [
            (os.fsencode(name), os.getxattr(path, name, follow_symlinks=False))
            for name in os.listxattr(path, follow_symlinks=False)
        ]
    else:
        raise UnsupportedPlatform(
            f"cannot read xattrs on {sys.platform!r}: neither the Darwin libc path nor "
            "os.listxattr is available. BTH-1 will not silently report 'no xattrs' on a "
            "platform where it cannot look — a tree that lost every xattr would then hash "
            "equal to one that kept them."
        )
    return sorted((name, value) for name, value in pairs if name not in IGNORED_XATTRS)


def _kind(mode: int) -> str:
    for predicate, name in _KINDS:
        if predicate(mode):
            return name
    return "unknown"  # pragma: no cover - no eighth st_mode type exists


def _relative_paths(root: bytes) -> Iterator[bytes]:
    """Every entry under `root` as raw relative bytes, root itself included as b'.'.

    Iterative rather than recursive: a deep tree must not depend on Python's
    recursion limit. Symlinks are never followed — `is_dir(follow_symlinks=False)`
    — because following one would hash the target's contents under the link's
    name, and a link pointing outside the tree (or at a cycle) would take the
    scan with it.
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


def _content_hash(path: bytes) -> bytes:
    """sha256 of a regular file's bytes.

    Callers MUST gate on `S_ISREG` before reaching here. Opening a FIFO with no
    writer **blocks forever** — that is not hypothetical, it hung a test suite in
    this project's history — and opening a device is worse.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CONTENT_CHUNK):
            digest.update(chunk)
    return digest.hexdigest().encode("ascii")


def _link_groups(root: bytes, paths: Sequence[bytes]) -> dict[bytes, bytes]:
    """Map each hardlinked path to its group id: the first path in the group.

    `(st_dev, st_ino)` is the grouping key and stays here — it never reaches a
    record. The inode cannot survive a restore; the fact that two names share one
    is what must.

    Regular files only. Directories always have `st_nlink > 1` (`.`, `..`), so
    including them would invent a "hardlink group" for every directory.
    """
    by_inode: dict[tuple[int, int], list[bytes]] = {}
    for rel in paths:
        info = os.lstat(os.path.join(root, rel) if rel != b"." else root)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink < 2:
            continue
        by_inode.setdefault((info.st_dev, info.st_ino), []).append(rel)

    groups: dict[bytes, bytes] = {}
    for members in by_inode.values():
        if len(members) < 2:
            continue  # the other names live outside the tree; nothing to compare
        first = min(members)  # raw-byte order, so the id is stable across scans
        for member in members:
            groups[member] = first
    return groups


def _record(root: bytes, rel: bytes, groups: dict[bytes, bytes]) -> Record:
    full = os.path.join(root, rel) if rel != b"." else root
    info = os.lstat(full)
    kind = _kind(info.st_mode)

    fields: list[tuple[str, bytes]] = [
        ("path", rel),
        ("kind", kind.encode("ascii")),
        ("perm", f"{stat.S_IMODE(info.st_mode):#o}".encode("ascii")),
        ("uid", str(info.st_uid).encode("ascii")),
        ("gid", str(info.st_gid).encode("ascii")),
        ("mtime_ns", str(info.st_mtime_ns).encode("ascii")),
        # st_flags is BSD-only; 0 on Linux, where there is nothing to lose.
        ("flags", str(getattr(info, "st_flags", 0)).encode("ascii")),
    ]

    if kind == "file":
        fields.append(("size", str(info.st_size).encode("ascii")))
        fields.append(("content", b"sha256:" + _content_hash(full)))
    elif kind == "link":
        # Bytes in, bytes out: readlink on a bytes path returns the target's raw
        # bytes, never a decoded str. A symlink target is data, not a path to
        # resolve; it need not exist or even be valid UTF-8.
        fields.append(("target", os.readlink(full)))
    elif kind in ("blk", "chr"):
        fields.append(("rdev", str(info.st_rdev).encode("ascii")))

    if rel in groups:
        fields.append(("link_group", groups[rel]))

    for name, value in read_xattrs(full):
        key = "xattr:" + name.decode("utf-8", "surrogateescape")
        fields.append((key, b"sha256:" + hashlib.sha256(value).hexdigest().encode("ascii")))

    return Record(path=rel, fields=tuple(fields))


def scan_tree(root) -> list[Record]:
    """Every entry under `root` as a `Record`, sorted by raw path bytes.

    Sorted by bytes, not by `str`: readdir order is not stable, and decoding to
    sort would reintroduce the normalisation trap this module exists to avoid.
    """
    root_bytes = os.fsencode(root)
    paths = sorted(_relative_paths(root_bytes))
    groups = _link_groups(root_bytes, paths)
    return [_record(root_bytes, rel, groups) for rel in paths]


def hash_tree(root) -> str:
    """The BTH-1 digest of the tree at `root`."""
    digest = hashlib.sha256()
    digest.update(TREE_HASH_VERSION.encode("ascii") + b"\n")
    for record in scan_tree(root):
        digest.update(hashlib.sha256(record.encoded).digest())
    return "sha256:" + digest.hexdigest()


def diff_records(left: Sequence[Record], right: Sequence[Record]) -> list[FieldDiff]:
    """Field-level differences between two scans, sorted by path then field.

    The point of the whole record structure: a caller must be able to learn that
    a restore lost `perm`, not merely that two hex strings disagree.
    """
    left_by_path = {record.path: record for record in left}
    right_by_path = {record.path: record for record in right}

    diffs: list[FieldDiff] = []
    for path in sorted(set(left_by_path) | set(right_by_path)):
        before = left_by_path.get(path)
        after = right_by_path.get(path)
        if before is None or after is None:
            diffs.append(
                FieldDiff(
                    path=path,
                    field=None,
                    left=None if before is None else before.encoded,
                    right=None if after is None else after.encoded,
                )
            )
            continue
        before_fields = dict(before.fields)
        after_fields = dict(after.fields)
        for key in sorted(set(before_fields) | set(after_fields)):
            if before_fields.get(key) != after_fields.get(key):
                diffs.append(
                    FieldDiff(
                        path=path,
                        field=key,
                        left=before_fields.get(key),
                        right=after_fields.get(key),
                    )
                )
    return diffs
