"""The mutation suite: proof that the restore test can fail, and for the right reason.

Task 3's ablation test proved the three repairs are load-bearing. This proves the
other half: that **BTH-1 catches the corruptions a real restore could plausibly
introduce**, and that each one is caught by the **field under test** rather than
by some unrelated field that happened to move at the same time.

## Why "the hash changed" is not evidence

The first version of this suite reported all 12 corruptions CAUGHT and was wrong.
Several were caught by the **parent directory's mtime** moving — creating,
unlinking or renaming an entry bumps its parent — not by the property under test.
*"Symlink retargeted"* was caught by its parent dir's mtime; after that confound
was removed it was **still** confounded by the symlink's **own fresh mtime**, and
only `os.utime(..., follow_symlinks=False)` isolated it. Right verdict, wrong
reason — and it rots the instant directory mtimes are restored properly, which
Task 3 now does.

So `_mutated` neutralizes both confounds and `test_bth1_catches_the_mutation`
asserts on **which field** differs, on **which path**. The `strays` assertion is
the guard that keeps that honest: any `mtime_ns` difference the mutation did not
declare is a confound leaking back in, and fails the test even though the hash
moved and the "expected" field was present. Without it these assertions would
pass on a tree corrupted by the harness itself.

## The two mutations that exist to kill a content-only hash

**#3 (symlink replaced by a copy of its target)** and **#7 (hardlink broken into
two inodes)** are **content-identical by construction**. Every byte a naive
content-only hash would read is unchanged — `test_a_content_only_hash_is_blind_to_these`
demonstrates exactly that, against a deliberately naive implementation, and then
shows BTH-1 catching both anyway. They must never be "simplified" away: they are
the only cases here that a content-only hash silently passes, and `clonefile` was
measured committing #7 for real.

## Reading the tree twice instead of copying it

The "perfect copy" each mutation is applied to is a **second, independent build**
of the same fixture rather than a clone of the first. `build_torture_tree` is
deterministic by construction (every mtime is a constant derived from the entry's
relative path), so two builds at two roots are identical to BTH-1.
`test_the_harness_does_not_move_the_hash` is the control that keeps that true, and
it is not optional: **a hash that always differed would pass all 12 mutations.**
Building twice also means this suite does not depend on `snapshot()` — the thing
these mutations are ultimately about — to produce its own baseline.

**Never open anything without gating on `S_ISREG`.** `open(fifo, "rb").read()`
blocks forever with no writer, and has already hung a test suite in this project's
history. Mutation #11 needs a FIFO, so it gets its own two-entry tree; the torture
tree deliberately has none.
"""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from pathlib import Path
from typing import Callable, Collection, Iterator, Optional

import pytest
from fixtures.torture_tree import NFD_NAME, XATTR_NAME, build_torture_tree, remove_xattr

from belay.snapshot.bth1 import diff_records, hash_tree, scan_tree

#: A mutation damages a tree in place. It never reports what it did: what changed
#: is for BTH-1 to say, which is the entire point of the exercise.
Mutation = Callable[[Path], None]

#: `(relative path bytes, field name)`. `None` as the field means the entry exists
#: on only one side — a missing or added path, which `diff_records` reports as one
#: path-level difference rather than as a field.
Expectation = tuple[bytes, Optional[str]]

_NFD = os.fsencode(NFD_NAME)
_NFC = os.fsencode(unicodedata.normalize("NFC", NFD_NAME))


# ---------------------------------------------------------------------------
# Walking, and neutralizing the mtime confounds
# ---------------------------------------------------------------------------


def _walk(root: bytes) -> Iterator[bytes]:
    """Every entry under `root` as raw relative bytes, root itself included as `b"."`.

    A test-local walk rather than an import of `clone._walk`: this is the
    measurement side, and a confound-neutralizer that shared code with the thing
    it measures could neutralize exactly the entries that code forgets. Iterative,
    and symlinks are never followed — `absolute.link` points at `/usr/bin/true`.
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


def _mtimes(root: Path) -> dict[bytes, tuple[int, int]]:
    """Every entry's `(atime_ns, mtime_ns)`, read before the mutation touches it."""
    root_bytes = os.fsencode(root)
    times: dict[bytes, tuple[int, int]] = {}
    for rel in _walk(root_bytes):
        info = os.lstat(_full(root_bytes, rel))
        times[rel] = (info.st_atime_ns, info.st_mtime_ns)
    return times


def _neutralize(
    root: Path, before: dict[bytes, tuple[int, int]], keep: set[bytes]
) -> None:
    """Put every mtime the mutation was not *about* back the way it was.

    This is the whole trap, in one function. Creating, unlinking or renaming an
    entry bumps its **parent directory's** mtime, and replacing an entry gives the
    replacement a **fresh mtime of its own** — so seven of these twelve mutations
    move the hash whether or not BTH-1 notices the property under test. Measured
    here before this existed: *"symlink retargeted"* differed at `(b'.', 'mtime_ns')`
    and `(b'relative.link', 'mtime_ns')`, and not one of those is `target`.

    `follow_symlinks=False` is load-bearing and not a detail: without it, restoring
    `relative.link`'s mtime would stamp whatever it points *at* — leaving the
    symlink's own fresh mtime in place, still confounding the `target` assertion,
    and quietly corrupting a second entry to boot.

    Entries created *by* the mutation have no recorded mtime and are left alone;
    an entry the mutation removed is simply not walked.
    """
    root_bytes = os.fsencode(root)
    for rel in _walk(root_bytes):
        if rel in keep or rel not in before:
            continue
        atime_ns, mtime_ns = before[rel]
        os.utime(_full(root_bytes, rel), ns=(atime_ns, mtime_ns), follow_symlinks=False)


def _pairs(left: Path, right: Path) -> set[Expectation]:
    """Every `(path, field)` that differs between two trees, per BTH-1."""
    return {
        (diff.path, diff.field)
        for diff in diff_records(scan_tree(left), scan_tree(right))
    }


def _mutated(
    builder: Callable[[Path], Path],
    mutate: Mutation,
    expected: Collection[Expectation],
    tmp_path: Path,
) -> tuple[Path, Path]:
    """Build two identical trees, damage one, and hand both back for comparison.

    The mutation's declared expectations are what exempt an entry from mtime
    neutralization: mutation #9 *is* an mtime change, so restoring its mtime would
    silently undo it. Deriving the exemption from `expected` rather than from a
    second parameter means an mtime the mutation did not declare can never be
    quietly preserved — it will surface as a `strays` failure instead.
    """
    reference = builder(tmp_path / "reference")
    victim = builder(tmp_path / "victim")

    before = _mtimes(victim)
    mutate(victim)
    _neutralize(
        victim, before, keep={path for path, field in expected if field == "mtime_ns"}
    )
    return reference, victim


# ---------------------------------------------------------------------------
# The 12 mutations
# ---------------------------------------------------------------------------


def _lost_a_mode_bit(root: Path) -> None:
    os.chmod(root / "mode642.bin", 0o643)


def _lost_setuid(root: Path) -> None:
    """`clonefile`'s real, measured bug: 0o4711 comes back as 0o0711."""
    os.chmod(root / "setuid.bin", 0o711)


def _symlink_replaced_by_a_copy_of_its_target(root: Path) -> None:
    """Content-identical by construction — see this module's docstring.

    A hash that read every path's *dereferenced* bytes sees the same bytes at
    `relative.link` before and after. Only `kind` says one is a symlink.
    """
    link = root / "relative.link"
    payload = (root / "regular.txt").read_bytes()  # a regular file by construction
    link.unlink()
    link.write_bytes(payload)


def _symlink_retargeted(root: Path) -> None:
    """The confounded one. Its own fresh mtime hid the `target` change twice over."""
    link = root / "relative.link"
    link.unlink()
    os.symlink("mode642.bin", link)


def _filename_normalized(root: Path) -> None:
    """NFD -> NFC. APFS is normalization-*preserving*: the stored bytes really change.

    Measured on this machine: `cafe\\xcc\\x81` becomes `caf\\xc3\\xa9`. A BTH-1 that
    sorted or compared decoded `str` paths would call these two trees identical.
    """
    os.rename(root / NFD_NAME, root / unicodedata.normalize("NFC", NFD_NAME))


def _xattr_dropped(root: Path) -> None:
    """`shutil.copytree`'s real, measured bug."""
    remove_xattr(root / "xattred.txt", XATTR_NAME)


def _hardlink_broken(root: Path) -> None:
    """`clonefile`'s real, measured bug: one inode with two names becomes two inodes.

    Content-identical by construction — the replacement carries the same bytes and
    the same mode, so nothing a content-only hash reads has moved. Only the
    *shape* is gone.
    """
    other = root / "nested" / "hardlink_b.txt"
    info = os.lstat(other)
    assert stat.S_ISREG(info.st_mode), "refusing to open a non-regular file"
    payload = other.read_bytes()
    other.unlink()
    other.write_bytes(payload)
    os.chmod(other, stat.S_IMODE(info.st_mode))


def _flags_dropped(root: Path) -> None:
    os.chflags(root / "hidden.txt", 0)


def _mtime_off_by_one_nanosecond(root: Path) -> None:
    """One nanosecond. APFS timestamps really are that fine — measured."""
    target = root / "regular.txt"
    info = os.lstat(target)
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 1))


def _empty_dir_dropped(root: Path) -> None:
    """An empty directory has no content at all, so no content-driven hash can miss it."""
    (root / "empty_dir").rmdir()


def _fifo_replaced_by_an_empty_regular_file(root: Path) -> None:
    pipe = root / "pipe"
    pipe.unlink()
    pipe.write_bytes(b"")
    os.chmod(pipe, 0o644)  # the FIFO's mode, so `kind` is what catches this


def _content_changed_by_one_byte(root: Path) -> None:
    """One byte, same length: `size` cannot be what catches this — `content` must."""
    target = root / "regular.txt"
    payload = bytearray(target.read_bytes())
    payload[0] ^= 0x01
    target.write_bytes(bytes(payload))


# ---------------------------------------------------------------------------
# A FIFO tree, because the torture tree deliberately has none
# ---------------------------------------------------------------------------

_FIFO_TREE_MTIME_NS = 1_700_000_000_000_000_000


def build_fifo_tree(root: Path) -> Path:
    """A two-entry tree whose only interesting property is that `pipe` is a FIFO.

    Local and tiny on purpose. The torture tree has no FIFO because
    `open(fifo, "rb").read()` blocks forever with no writer; nothing here ever
    opens it, and BTH-1 gates content reads on `S_ISREG`.

    Modes are stamped explicitly rather than left to the umask, so the FIFO and
    the regular file that replaces it in mutation #11 carry the *same* mode under
    any umask — otherwise `perm` could be what catches that mutation and `kind`
    would be along for the ride.
    """
    root.mkdir(parents=True, exist_ok=True)
    os.mkfifo(root / "pipe")
    os.chmod(root / "pipe", 0o644)
    for path in (root / "pipe", root):
        os.utime(
            path, ns=(_FIFO_TREE_MTIME_NS, _FIFO_TREE_MTIME_NS), follow_symlinks=False
        )
    return root


# ---------------------------------------------------------------------------
# The table. Each row: what to break, and the field that must catch it.
# ---------------------------------------------------------------------------

#: The two content-identical mutations, shared with `test_a_content_only_hash_is_blind_to_these`
#: so that the field a case claims to catch and the field that test relies on can never drift.
_SYMLINK_DEREF: tuple[Mutation, frozenset[Expectation]] = (
    _symlink_replaced_by_a_copy_of_its_target,
    frozenset({(b"relative.link", "kind")}),
)
_HARDLINK_BREAK: tuple[Mutation, frozenset[Expectation]] = (
    _hardlink_broken,
    frozenset(
        {(b"hardlink_a.txt", "link_group"), (b"nested/hardlink_b.txt", "link_group")}
    ),
)

_MUTATIONS = [
    (build_torture_tree, _lost_a_mode_bit, frozenset({(b"mode642.bin", "perm")})),
    (build_torture_tree, _lost_setuid, frozenset({(b"setuid.bin", "perm")})),
    (build_torture_tree, *_SYMLINK_DEREF),
    (
        build_torture_tree,
        _symlink_retargeted,
        frozenset({(b"relative.link", "target")}),
    ),
    (build_torture_tree, _filename_normalized, frozenset({(_NFD, None), (_NFC, None)})),
    (
        build_torture_tree,
        _xattr_dropped,
        frozenset({(b"xattred.txt", "xattr:" + XATTR_NAME.decode("ascii"))}),
    ),
    (build_torture_tree, *_HARDLINK_BREAK),
    (build_torture_tree, _flags_dropped, frozenset({(b"hidden.txt", "flags")})),
    (
        build_torture_tree,
        _mtime_off_by_one_nanosecond,
        frozenset({(b"regular.txt", "mtime_ns")}),
    ),
    (build_torture_tree, _empty_dir_dropped, frozenset({(b"empty_dir", None)})),
    (
        build_fifo_tree,
        _fifo_replaced_by_an_empty_regular_file,
        frozenset({(b"pipe", "kind")}),
    ),
    (
        build_torture_tree,
        _content_changed_by_one_byte,
        frozenset({(b"regular.txt", "content")}),
    ),
]

_IDS = [
    "01-lost-a-mode-bit",
    "02-lost-setuid",
    "03-symlink-replaced-by-its-target",
    "04-symlink-retargeted",
    "05-filename-nfd-to-nfc",
    "06-xattr-dropped",
    "07-hardlink-broken",
    "08-flags-dropped",
    "09-mtime-off-by-one-ns",
    "10-empty-dir-dropped",
    "11-fifo-replaced-by-a-file",
    "12-content-changed-by-one-byte",
]


@pytest.mark.parametrize(("builder", "mutate", "expected"), _MUTATIONS, ids=_IDS)
def test_bth1_catches_the_mutation(
    builder: Callable[[Path], Path],
    mutate: Mutation,
    expected: frozenset[Expectation],
    tmp_path: Path,
) -> None:
    """Each corruption is caught, and caught by the field it is about.

    Two assertions, and the second is the one that matters. `expected <= observed`
    says BTH-1 noticed the property. `strays` says nothing *else* moved an mtime —
    which is what stops a parent directory's bumped mtime from taking the credit.
    See this module's docstring: that confound already fooled this suite once.
    """
    reference, victim = _mutated(builder, mutate, expected, tmp_path)
    observed = _pairs(reference, victim)

    strays = {pair for pair in observed if pair[1] == "mtime_ns"} - expected
    assert not strays, (
        f"undeclared mtime differences {sorted(strays)} — a confound is leaking in, "
        "and this mutation may be caught for the wrong reason"
    )
    assert expected <= observed, (
        f"BTH-1 did not catch this mutation by its own field; it reported {sorted(observed)}"
    )
    assert hash_tree(reference) != hash_tree(victim)


# ---------------------------------------------------------------------------
# The negative control. Without it, all 12 above are worthless.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder", [build_torture_tree, build_fifo_tree], ids=["torture", "fifo"]
)
def test_the_harness_does_not_move_the_hash(
    builder: Callable[[Path], Path], tmp_path: Path
) -> None:
    """A hash that always differs passes every mutation test. This is that guard.

    Runs the harness's whole copy-and-neutralize path with a mutation that does
    nothing, and requires the result to be **stable**. If the harness itself
    touched the tree — or if a builder were not deterministic across roots — all
    12 mutations above would "pass" while proving nothing at all.
    """
    reference, victim = _mutated(builder, lambda root: None, frozenset(), tmp_path)
    assert _pairs(reference, victim) == set()
    assert hash_tree(reference) == hash_tree(victim)


# ---------------------------------------------------------------------------
# The two that a content-only hash silently passes
# ---------------------------------------------------------------------------


def _content_only_hash(root: Path) -> str:
    """What a hash that looked only at file contents would see.

    Deliberately naive, and deliberately **dereferences** symlinks: this is the
    implementation BTH-1 exists to refute, so it has to be the plausible wrong
    one rather than a straw man. `S_ISREG` gates every open — a FIFO would block
    forever, and a device would be worse.
    """
    root_bytes = os.fsencode(root)
    digest = hashlib.sha256()
    for rel in sorted(_walk(root_bytes)):
        digest.update(rel + b"\x00")
        full = _full(root_bytes, rel)
        try:
            info = os.stat(full)  # follows symlinks, on purpose
        except OSError:
            digest.update(b"unresolvable\x00")
            continue
        if stat.S_ISREG(info.st_mode):
            with open(full, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
        digest.update(b"\x00")
    return digest.hexdigest()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [_SYMLINK_DEREF, _HARDLINK_BREAK],
    ids=["03-symlink-deref", "07-hardlink-break"],
)
def test_a_content_only_hash_is_blind_to_these(
    mutate: Mutation, expected: frozenset[Expectation], tmp_path: Path
) -> None:
    """The whole argument for BTH-1 hashing more than bytes, in one test.

    Both mutations are content-identical by construction, so the naive hash calls
    the corrupted tree "byte-identical" — and `clonefile` commits #7 for real, on
    this machine. BTH-1 catches both. Delete these two cases and a content-only
    hash would pass this entire suite.
    """
    reference, victim = _mutated(build_torture_tree, mutate, expected, tmp_path)

    assert _content_only_hash(reference) == _content_only_hash(victim), (
        "this mutation is supposed to be content-identical by construction; it is not, "
        "so it no longer proves anything about a content-only hash"
    )
    assert hash_tree(reference) != hash_tree(victim), (
        "BTH-1 missed a content-identical corruption"
    )


def test_breaking_a_hardlink_changes_nothing_but_the_link_group(tmp_path: Path) -> None:
    """The sharpest statement available here: `link_group` is *all* that moved.

    Not a subset assertion. If breaking a hardlink also moved `perm` or `mtime_ns`,
    the parametrized case above would still pass while `link_group` was merely
    riding along — and the one field `clonefile` was measured destroying would have
    no test that isolates it.
    """
    reference, victim = _mutated(build_torture_tree, *_HARDLINK_BREAK, tmp_path)
    assert _pairs(reference, victim) == _HARDLINK_BREAK[1]
