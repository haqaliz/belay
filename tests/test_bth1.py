"""BTH-1: does the measuring instrument actually measure?

Everything C2 later claims — "the pre-state restored byte-identically" — is this
hash's word. So these tests are split deliberately between the two ways a hash
can be worthless, because **a hash that always differs passes a "it
discriminates" test just as convincingly as a correct one**:

- `test_discriminates` / `test_hashes_raw_path_bytes` prove it NOTICES things.
- `test_atime_churn_does_not_move_the_hash`, `test_no_op_rehash_is_stable`, and
  `test_inode_churn_does_not_move_the_hash` prove it does not notice things it
  MUST NOT — they are the negative controls, and they are not optional. Without
  them a `hash_tree` returning `os.urandom(32)` passes the discrimination tests.

`test_fixture_is_still_a_torture_tree` is the anti-vacuity guard the repo norm
requires (see `test_fixture_guard.py`): every assertion below is only as good as
the tree it runs against, and a fixture that quietly stopped creating the
hardlink or the setuid bit would leave these tests green and meaningless.
"""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path

import pytest
from fixtures.torture_tree import (
    HIDDEN_FLAG,
    NFD_NAME,
    XATTR_NAME,
    build_torture_tree,
    remove_xattr,
)

from belay.snapshot.bth1 import diff_records, hash_tree, scan_tree


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return build_torture_tree(tmp_path / "tree")


def _records_by_path(root: Path) -> dict[bytes, object]:
    return {record.path: record for record in scan_tree(root)}


def test_fixture_is_still_a_torture_tree(tree: Path) -> None:
    """Anti-vacuity: the tree still carries every property the tests below probe.

    If the fixture degrades, the interesting tests keep passing while proving
    nothing. This is the repo norm, and it is real history here: a differential
    in this project once passed because the fixture had a syntax error and both
    sides compared empty to empty.
    """
    assert os.lstat(tree / "hardlink_a.txt").st_nlink == 2, (
        "fixture lost its hardlink pair — nothing below can show that BTH-1 "
        "notices hardlink identity, which is exactly what clonefile drops"
    )
    assert os.lstat(tree / "hardlink_a.txt").st_ino == os.lstat(tree / "nested" / "hardlink_b.txt").st_ino

    assert stat.S_IMODE(os.lstat(tree / "setuid.bin").st_mode) == 0o4711, (
        "fixture lost its setuid bit — the mode axis is now untested"
    )
    assert os.lstat(tree / "hidden.txt").st_flags & HIDDEN_FLAG, "fixture lost its st_flags"

    # macOS injects `com.apple.provenance` onto every file it creates, so
    # "the file has xattrs" is TRUE even on a tree that lost every real one.
    # The guard has to name the attribute it expects, or it passes vacuously.
    from belay.snapshot.bth1 import read_xattrs

    names = [name for name, _ in read_xattrs(os.fsencode(tree / "xattred.txt"))]
    assert XATTR_NAME in names, (
        f"fixture lost its real xattr {XATTR_NAME!r} (found {names!r}) — note that "
        "com.apple.provenance is injected by macOS and proves nothing"
    )

    assert (tree / NFD_NAME).exists(), "fixture lost its NFD-named file"

    sparse = os.lstat(tree / "sparse.bin")
    assert sparse.st_blocks * 512 < sparse.st_size, (
        f"sparse.bin is not actually sparse (st_blocks={sparse.st_blocks}, "
        f"st_size={sparse.st_size}) — it has already been written the obvious way "
        "once (seek past the end and write), which on APFS allocates the whole "
        "range and leaves no hole at all"
    )


def test_deterministic(tree: Path) -> None:
    """The same tree, hashed twice, is the same digest."""
    assert hash_tree(tree) == hash_tree(tree)


def test_no_op_rehash_is_stable(tree: Path) -> None:
    """NEGATIVE CONTROL: nothing touched, many re-hashes, no movement.

    Weaker than the atime control but it fails differently: it catches a hash
    that mixes in the clock, a random nonce, or readdir order.
    """
    digests = {hash_tree(tree) for _ in range(5)}
    assert len(digests) == 1, f"hash moved with no change to the tree: {digests!r}"


def test_atime_churn_does_not_move_the_hash(tree: Path) -> None:
    """NEGATIVE CONTROL: atime is excluded, and this is what proves it.

    atime is SELF-INVALIDATING for a tree hash: hashing reads every file, which
    updates atime, so a BTH-1 that included atime would be unable to reproduce
    its own digest — every restore check in C2 would report a spurious diff.

    The control does not merely read the files and hope the filesystem moved
    atime (a `noatime` mount, or a future filesystem, would silently make that a
    no-op and this control vacuous). It reads them AND stamps atime explicitly,
    then ASSERTS atime really moved before re-hashing. mtime is preserved
    verbatim, so atime is the only thing that changed.
    """
    before = hash_tree(tree)

    target = tree / "regular.txt"
    atime_before = os.lstat(target).st_atime_ns
    mtime_before = os.lstat(target).st_mtime_ns

    for path in sorted(tree.rglob("*")):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            continue  # never open a non-regular file: a FIFO read blocks forever
        with open(path, "rb") as handle:
            handle.read()
        os.utime(path, ns=(atime_before + 999_000_000_000, info.st_mtime_ns))

    assert os.lstat(target).st_atime_ns != atime_before, (
        "atime did not actually move, so this control proves nothing — it would "
        "pass against a BTH-1 that hashed atime"
    )
    assert os.lstat(target).st_mtime_ns == mtime_before, (
        "mtime moved too, so this control is no longer isolating atime: a BTH-1 "
        "that hashed atime could still pass it for the wrong reason"
    )

    assert hash_tree(tree) == before, (
        "the hash moved when only atime changed — BTH-1 is hashing atime, which "
        "makes it self-invalidating: it cannot reproduce its own digest"
    )


def test_inode_churn_does_not_move_the_hash(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: identity is the relative path, never the inode number.

    Inode numbers and st_dev cannot survive a restore by construction, so a hash
    that included them would report every restore as a mismatch. Two builds of
    the same tree at different paths must agree.
    """
    left = build_torture_tree(tmp_path / "left")
    right = build_torture_tree(tmp_path / "right")

    assert os.lstat(left / "regular.txt").st_ino != os.lstat(right / "regular.txt").st_ino, (
        "the two trees share an inode — this control is vacuous, as there is no "
        "inode churn for the hash to be insensitive to"
    )

    assert hash_tree(left) == hash_tree(right), (
        "the hash differs between two identical trees at different paths — it is "
        "hashing inode numbers or absolute paths, so no restore could ever verify"
    )


def test_sparseness_is_not_an_identity_difference(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: `st_blocks` is excluded, so a hole is not a diff.

    Sparseness is a storage property, not identity: the same bytes are the same
    bytes whether or not the filesystem materialised the zeros. The module
    docstring commits to this exclusion and routes it to a separate WARN instead;
    without a test, that commitment is just a comment, and the first person to add
    `st_blocks` to a record would make every restore of a sparse file report a
    false mismatch.
    """
    content_len = 1024 * 1024 + 18

    # `truncate`, not seek-past-the-end-and-write: on APFS the latter allocates
    # the whole range and leaves no hole, so the "sparse" side would in fact be
    # dense and this control would compare two identical files. The anti-vacuity
    # assertion below is what caught that.
    sparse_dir = tmp_path / "sparse"
    sparse_dir.mkdir()
    with open(sparse_dir / "f", "wb") as handle:
        handle.truncate(content_len)

    dense_dir = tmp_path / "dense"
    dense_dir.mkdir()
    (dense_dir / "f").write_bytes(b"\0" * content_len)

    for directory in (sparse_dir, dense_dir):
        os.chmod(directory / "f", 0o644)
        os.utime(directory / "f", ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        os.utime(directory, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

    assert os.lstat(sparse_dir / "f").st_blocks != os.lstat(dense_dir / "f").st_blocks, (
        "the two files have identical st_blocks, so the filesystem did not "
        "actually create a hole — this control is vacuous"
    )
    assert os.lstat(sparse_dir / "f").st_size == os.lstat(dense_dir / "f").st_size

    assert hash_tree(sparse_dir) == hash_tree(dense_dir), (
        "a sparse file hashed differently from a materialised file with identical "
        "content — BTH-1 is hashing st_blocks, so every restore of a sparse file "
        "would report a false identity mismatch"
    )


def test_discriminates_and_names_the_differing_field(tree: Path) -> None:
    """Flip ONE mode bit: the hash moves, and the diff says `perm`.

    Naming the field is the point. A hash that only reports "these two hex
    strings differ" cannot tell a restore that lost setuid from one that lost a
    byte of content, and the whole reason BTH-1 exists is that mode bits are the
    thing silently dropped.

    Asserting the differing field set is EXACTLY {"perm"} is deliberately
    stronger than asserting "perm" is in it: chmod also moves ctime, so this
    simultaneously proves ctime is excluded, and it fails a hash that gives up
    and reports every field as different.
    """
    before = scan_tree(tree)
    before_digest = hash_tree(tree)

    os.chmod(tree / "mode642.bin", 0o643)

    after = scan_tree(tree)
    assert hash_tree(tree) != before_digest, "one mode bit flipped and the hash did not move"

    diffs = diff_records(before, after)
    assert [diff.path for diff in diffs] == [b"mode642.bin"], (
        f"expected exactly one changed entry, got {[d.path for d in diffs]!r}"
    )
    assert {diff.field for diff in diffs} == {"perm"}, (
        f"expected the differing field to be named `perm`, got {[d.field for d in diffs]!r}"
    )
    assert diffs[0].left == b"0o642" and diffs[0].right == b"0o643"


def _restore_meta(path: Path, info: os.stat_result) -> None:
    """Put back everything except the one axis a mutation is exercising.

    Mutations below have side effects that are not the point: rewriting a file
    moves its parent directory's mtime, unlinking and recreating resets the mode.
    Left alone, those would show up as extra diffs and the "exactly these fields
    differ" assertions would have to be weakened to "at least these" — which is
    the weaker claim that lets a hash reporting EVERY field as different pass.
    """
    os.chmod(path, stat.S_IMODE(info.st_mode))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns), follow_symlinks=False)


def _drop_setuid(tree: Path) -> None:
    os.chmod(tree / "setuid.bin", 0o0711)


def _drop_xattr(tree: Path) -> None:
    remove_xattr(tree / "xattred.txt", XATTR_NAME)


def _clear_flags(tree: Path) -> None:
    os.chflags(tree / "hidden.txt", 0)


def _touch_dir_mtime(tree: Path) -> None:
    os.utime(tree / "nested", ns=(1, 1))


def _rewrite_content(tree: Path) -> None:
    """Same length, different bytes — so `content` differs and `size` does not."""
    target = tree / "regular.txt"
    info = os.lstat(target)
    parent = os.lstat(tree)
    original = target.read_bytes()
    target.write_bytes(b"X" * len(original))
    _restore_meta(target, info)
    _restore_meta(tree, parent)


def _retarget_symlink(tree: Path) -> None:
    link = tree / "relative.link"
    info = os.lstat(link)
    parent = os.lstat(tree)
    link.unlink()
    os.symlink("mode642.bin", link)
    os.utime(link, ns=(info.st_atime_ns, info.st_mtime_ns), follow_symlinks=False)
    _restore_meta(tree, parent)


def _break_hardlink(tree: Path) -> None:
    """Replace one name of a hardlink pair with an independent copy.

    This is precisely what `clonefile` was measured doing: identical content,
    identical metadata, two inodes where there was one. **A content-only hash
    cannot see this at all** — which is the single clearest argument for BTH-1's
    existence, so it had better be a test.
    """
    link = tree / "nested" / "hardlink_b.txt"
    info = os.lstat(link)
    parent = os.lstat(tree / "nested")
    content = link.read_bytes()
    link.unlink()
    link.write_bytes(content)
    _restore_meta(link, info)
    _restore_meta(tree / "nested", parent)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        pytest.param(_drop_setuid, {b"setuid.bin": {"perm"}}, id="setuid-lost"),
        pytest.param(
            _drop_xattr,
            {b"xattred.txt": {"xattr:" + XATTR_NAME.decode()}},
            id="xattr-lost",
        ),
        pytest.param(_clear_flags, {b"hidden.txt": {"flags"}}, id="st_flags-lost"),
        pytest.param(_touch_dir_mtime, {b"nested": {"mtime_ns"}}, id="dir-mtime-lost"),
        pytest.param(_rewrite_content, {b"regular.txt": {"content"}}, id="content-changed"),
        pytest.param(_retarget_symlink, {b"relative.link": {"target"}}, id="symlink-retargeted"),
        pytest.param(
            _break_hardlink,
            {b"hardlink_a.txt": {"link_group"}, b"nested/hardlink_b.txt": {"link_group"}},
            id="hardlink-broken",
        ),
    ],
)
def test_discriminates_every_axis(tree: Path, mutate, expected) -> None:
    """Each axis BTH-1 claims to measure, damaged one at a time.

    `test_discriminates_and_names_the_differing_field` only exercises `perm`. A
    BTH-1 that silently ignored xattrs, st_flags, symlink targets and hardlink
    structure would pass every other test in this file — including all three
    negative controls, which reward insensitivity. These are the tests that make
    the claim in the module docstring ("clonefile loses hardlink identity and
    setuid; copytree loses xattrs; BTH-1 catches exactly that") a checked fact
    rather than a comment.

    The expectation is the EXACT set of differing fields per path, not a subset:
    a hash that gave up and reported everything as different would satisfy a
    subset check.
    """
    before = scan_tree(tree)
    before_digest = hash_tree(tree)

    mutate(tree)

    after = scan_tree(tree)
    assert hash_tree(tree) != before_digest, (
        "the tree lost a property BTH-1 claims to hash and the digest did not "
        "move — this is the false PASS the module exists to prevent"
    )

    diffs = diff_records(before, after)
    observed: dict[bytes, set[str]] = {}
    for diff in diffs:
        observed.setdefault(diff.path, set()).add(diff.field)
    assert observed == expected, f"expected exactly {expected!r}, got {observed!r}"


def test_hashes_raw_path_bytes(tree: Path) -> None:
    """An NFD filename is hashed by its raw readdir bytes, not a normalised form.

    APFS is normalization-PRESERVING: it hands back the NFD bytes verbatim, so
    "byte-identical" is an honest claim — PROVIDED the hash never round-trips a
    path through `str` normalisation. A BTH-1 built on normalised paths would
    call two trees with genuinely different filename bytes identical, and that
    drift would be invisible forever after.
    """
    nfd_bytes = os.fsencode(NFD_NAME)
    nfc_bytes = os.fsencode(unicodedata.normalize("NFC", NFD_NAME))
    assert nfd_bytes != nfc_bytes, "the fixture's name is normalisation-insensitive; it tests nothing"

    records = _records_by_path(tree)

    assert nfd_bytes in records, (
        f"no record carries the raw NFD bytes {nfd_bytes!r} — got {sorted(records)!r}"
    )
    assert nfc_bytes not in records, (
        f"a record carries NFC bytes {nfc_bytes!r}: the path was normalised somewhere, "
        "so real filename drift is now invisible to the hash"
    )
    assert records[nfd_bytes].field("path") == nfd_bytes
