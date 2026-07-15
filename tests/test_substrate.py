"""The substrate guard: what C2 refuses, and why refusing loudly is the product.

This file is the honesty contract as executable code. Everything else in C2 is
mechanism — clone it, hash it, contain it. This is the part that decides whether
Belay ever lies, so the tests below are written against the failure mode rather
than the feature: **a silently skipped FIFO is a false PASS**, and a false PASS
in the pre-state is a false PASS in every verdict grounded on it.

Three tests carry the weight, and it is worth saying which and why:

- `test_the_torture_tree_passes_the_guard` is the **positive control**, and it is
  first on purpose. Every refusal test below would pass if `guard` simply raised
  on everything. Without a tree that is *accepted*, this file could be green
  while C2 refused to snapshot anything at all — refusal is only honest if
  acceptance is still possible.
- `test_absent_is_not_repurposed` is the exact false PASS C1 reserved the
  `state_handle` slot to prevent. `absent` means *"no snapshot was attempted"*;
  `unrestorable` means *"we tried and could not"*. A reader that cannot tell
  those apart reads our failure as our silence.
- `test_classifying_a_fifo_never_opens_it` guards a trap that has already been
  sprung in this project's history: `open(fifo, "rb").read()` **blocks forever**
  with no writer, and it hung a suite mid-session. Classification reads `lstat`
  and nothing else, and that is pinned here rather than left to reviewer memory.

**No verdicts in this file.** C2 emits the `unrestorable` *fact* with its cause;
C4 is what turns that fact into UNVERIFIED. If a PASS/FAIL assertion ever appears
below, it is in the wrong capability.
"""

from __future__ import annotations

import builtins
import json
import os
import socket
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from fixtures.torture_tree import build_torture_tree

from belay.snapshot.substrate import (
    CAUSES_DEFERRED,
    CAUSES_RAISED_HERE,
    FIDELITY_GAPS,
    RAISED_BY,
    ClonefileBackend,
    Manifest,
    Unrestorable,
    UnrestorableCause,
    classify,
    gc,
    guard,
    guarded_restore,
    present_handle,
    take_snapshot,
    unrestorable_handle,
)
from belay.trace import TraceWriter


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return build_torture_tree(tmp_path / "work")


@contextmanager
def unix_socket_in(directory: Path, name: str = "sock"):
    """Bind an `AF_UNIX` socket inside `directory`, whatever its path length.

    `sockaddr_un.sun_path` is ~104 bytes on Darwin and pytest's `tmp_path` eats
    most of that, so binding the absolute path raises `OSError: AF_UNIX path too
    long` — a fixture limitation that has nothing to do with what is under test.
    Binding a relative name from inside the directory sidesteps it.
    """
    sock = socket.socket(socket.AF_UNIX)
    previous = os.getcwd()
    try:
        os.chdir(directory)
        sock.bind(name)
        yield sock
    finally:
        os.chdir(previous)
        sock.close()


# --------------------------------------------------------------------------
# The positive control. Read the module docstring before touching this.
# --------------------------------------------------------------------------


def test_the_torture_tree_passes_the_guard(tree: Path, tmp_path: Path) -> None:
    """A tree of only regular files, directories and symlinks is ACCEPTED.

    The anti-vacuity control for every refusal test in this file: a `guard` that
    raised unconditionally would satisfy all of them. The torture tree is
    deliberately nasty — hardlinks, setuid, symlinks pointing out of the tree,
    xattrs — and all of it is in-substrate, so the guard must let it through.
    """
    guard(tree)  # must not raise
    snap = take_snapshot(tree, tmp_path / "snap")
    assert snap.manifest.backend == ClonefileBackend.name


# --------------------------------------------------------------------------
# A4 — out-of-substrate entries are DETECTED and REFUSED with a named cause.
# --------------------------------------------------------------------------


def test_a_fifo_in_the_tree_is_detected_and_refused(tree: Path) -> None:
    """Not skipped. Not ignored. Refused, by name, pointing at the entry."""
    os.mkfifo(tree / "pipe")

    with pytest.raises(Unrestorable) as caught:
        guard(tree)

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_FIFO
    assert b"pipe" in caught.value.path
    # The fact states how it was established, the way seatbelt's denial records
    # carry `source: "child-stderr"`. A fact whose provenance is implicit is a
    # fact a later reader has to take on trust.
    assert caught.value.source == "lstat"


def test_a_socket_in_the_tree_is_detected_and_refused(tree: Path) -> None:
    with unix_socket_in(tree):
        with pytest.raises(Unrestorable) as caught:
            guard(tree)

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_SOCKET


def test_a_device_node_is_detected_and_refused() -> None:
    """`/dev/null` is classified, because `mknod` needs root and we are not it.

    Creating a device node in a fixture would need privileges the suite does not
    have, so rather than skip the case — and leave the cause unreachable, which
    is the documentation equivalent of a false PASS — the classifier is pointed
    at a real character device the OS already provides.
    """
    assert classify(Path("/dev/null")) is UnrestorableCause.UNRESTORABLE_DEVICE_NODE


def test_classifying_a_fifo_never_opens_it(tree: Path, monkeypatch) -> None:
    """The trap, pinned: classification reads `lstat` and never opens a node.

    `open(fifo, "rb").read()` blocks forever with no writer — it hung a suite in
    this project's history and needed a kill. A test that merely called `guard`
    on a FIFO would hang rather than fail, so `open` is made fatal for the
    duration: if the guard reaches for it, this fails loudly instead of
    wedging CI.
    """
    os.mkfifo(tree / "pipe")

    def refuse_to_open(*args, **kwargs):
        raise AssertionError(f"substrate scan opened a node: {args!r}")

    monkeypatch.setattr(builtins, "open", refuse_to_open)

    with pytest.raises(Unrestorable) as caught:
        guard(tree)
    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_FIFO


def test_ownership_is_refused_because_non_root_cannot_restore_it(tree: Path) -> None:
    """A foreign uid is a fidelity loss the restore would make silently.

    `/usr/bin/true` is root-owned and a hardlink of it into a fixture is EPERM
    (measured), so the classifier is pointed at the real file. Without this the
    clone would come back owned by us and nothing would have said so.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root: foreign ownership is restorable, nothing to refuse")
    assert classify(Path("/usr/bin/true")) is UnrestorableCause.UNRESTORABLE_OWNERSHIP


# --------------------------------------------------------------------------
# Filling C1's reserved slot — and keeping its three states distinct.
# --------------------------------------------------------------------------


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_exact_cause_string_reaches_the_trace(tmp_path: Path, tree: Path) -> None:
    os.mkfifo(tree / "pipe")
    writer = TraceWriter(tmp_path / "t.jsonl")
    try:
        with pytest.raises(Unrestorable) as caught:
            guard(tree)
        writer.set_state_handle(unrestorable_handle(caught.value))
        writer.observer("c2s")(b'{"jsonrpc":"2.0"}', False)
    finally:
        writer.close()

    frame = [r for r in _records(writer.path) if r["kind"] == "frame"][-1]
    assert frame["state_handle"]["status"] == "unrestorable"
    assert frame["state_handle"]["cause"] == "UNRESTORABLE_FIFO"
    assert frame["state_handle"]["detail"]


def test_absent_is_not_repurposed(tmp_path: Path, tree: Path) -> None:
    """The false PASS C1 wrote the slot to prevent, asserted explicitly.

    A frame recorded with no snapshot attempt says `absent`. A frame recorded
    after a failed attempt says `unrestorable`. If C2 had reused `absent` for
    the second, a reader could not distinguish *"snapshots did not exist yet"*
    from *"we tried and failed"* — and would be entitled to read our failure as
    a frame that simply predates the feature.
    """
    writer = TraceWriter(tmp_path / "t.jsonl")
    try:
        writer.observer("c2s")(b'{"before":1}', False)  # no attempt yet
        os.mkfifo(tree / "pipe")
        with pytest.raises(Unrestorable) as caught:
            guard(tree)
        writer.set_state_handle(unrestorable_handle(caught.value))
        writer.observer("c2s")(b'{"after":1}', False)
    finally:
        writer.close()

    before, after = [r for r in _records(writer.path) if r["kind"] == "frame"]
    assert before["state_handle"] == {"status": "absent"}
    assert after["state_handle"]["status"] == "unrestorable"
    assert before["state_handle"] != after["state_handle"]


def test_the_writer_refuses_an_unrestorable_with_no_cause(tmp_path: Path) -> None:
    """An `unrestorable` with no cause is a refusal that names nothing.

    The writer does not know what any cause *means* — that stays in C2 — but it
    can insist the slot never carries the word without one.
    """
    writer = TraceWriter(tmp_path / "t.jsonl")
    try:
        with pytest.raises(ValueError):
            writer.set_state_handle({"status": "unrestorable"})
        with pytest.raises(ValueError):
            writer.set_state_handle({"status": "restored-probably"})
    finally:
        writer.close()


def test_a_present_handle_declares_the_gaps_it_cannot_restore(
    tree: Path, tmp_path: Path
) -> None:
    """`present` must not read as "everything came back".

    atime, ctime, birthtime and inode identity are unrestorable by anyone — BTH-1
    excludes them and says why. A handle that said only `present` would imply a
    fidelity the snapshot does not have, so it names its own gaps.
    """
    snap = take_snapshot(tree, tmp_path / "snap")
    handle = present_handle(snap)

    assert handle["status"] == "present"
    assert handle["handle"]
    assert set(handle["fidelity_gaps"]) == {gap.value for gap in FIDELITY_GAPS}


# --------------------------------------------------------------------------
# S1 — capabilities, and refusing across a set that differs.
# --------------------------------------------------------------------------


def test_capabilities_report_what_this_machine_actually_has() -> None:
    """Probed, not assumed: `os.listxattr` does not exist on macOS (measured)."""
    caps = ClonefileBackend.capabilities()
    assert ("xattrs-os-native" in caps) is hasattr(os, "listxattr")
    assert "clonefile" in caps


def test_restore_across_differing_capabilities_refuses(
    tree: Path, tmp_path: Path
) -> None:
    """Honesty, not portability.

    A tree captured where xattrs exist cannot be truthfully restored where they
    do not. Best-effort restore is exactly the lie: it would return a tree
    missing a field, and report a grounded pre-state it had not restored.
    """
    snap = take_snapshot(tree, tmp_path / "snap")
    foreign = Manifest(
        backend="clonefile-apfs",
        capabilities=snap.manifest.capabilities | {"xattrs-os-native"},
    )
    alien = type(snap)(snapshot=snap.snapshot, manifest=foreign)

    with pytest.raises(Unrestorable) as caught:
        guarded_restore(alien, tmp_path / "out")

    assert caught.value.cause is UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH
    assert "xattrs-os-native" in caught.value.detail
    assert not (tmp_path / "out").exists()  # refused, not half-attempted


def test_restore_within_one_capability_set_works(tree: Path, tmp_path: Path) -> None:
    """The control for the test above: matching capabilities still restore."""
    snap = take_snapshot(tree, tmp_path / "snap")
    guarded_restore(snap, tmp_path / "out")
    assert (tmp_path / "out").is_dir()


# --------------------------------------------------------------------------
# S2 — GC must survive the trees a real agent leaves behind.
# --------------------------------------------------------------------------


def test_gc_removes_an_acld_tree(tmp_path: Path) -> None:
    """`everyone deny delete` made a researcher's own scratch dir undeletable.

    Measured here: it defeats both `rm -rf` and `shutil.rmtree` with EACCES.
    Without this, C2 strands disk on every run that touches such a tree.
    """
    victim = tmp_path / "victim"
    (victim / "sub").mkdir(parents=True)
    (victim / "sub" / "f.txt").write_text("hi")
    subprocess.run(
        ["/bin/chmod", "+a", "everyone deny delete", str(victim / "sub" / "f.txt")],
        check=True,
    )
    subprocess.run(
        ["/bin/chmod", "+a", "everyone deny delete", str(victim)], check=True
    )

    gc(victim)
    assert not victim.exists()


def test_gc_removes_a_uchg_tree(tmp_path: Path) -> None:
    """The `uchg` immutable flag, the other half of the same stranding."""
    victim = tmp_path / "victim"
    victim.mkdir()
    locked = victim / "f.txt"
    locked.write_text("hi")
    os.chflags(locked, stat.UF_IMMUTABLE)

    gc(victim)
    assert not victim.exists()


def test_gc_is_a_no_op_on_a_missing_tree(tmp_path: Path) -> None:
    gc(tmp_path / "never-existed")


# --------------------------------------------------------------------------
# The discipline: no cause may exist that nothing can produce.
# --------------------------------------------------------------------------


def test_every_cause_is_either_reachable_here_or_documented_as_deferred() -> None:
    """A constant nothing can produce is a claim we cannot back.

    Every member must be classified exactly once. This is the guard that makes
    adding a cause without either a test or an owner a failing build, rather
    than a plausible-looking constant that ships forever.
    """
    assert CAUSES_RAISED_HERE.isdisjoint(CAUSES_DEFERRED)
    assert CAUSES_RAISED_HERE | CAUSES_DEFERRED == set(UnrestorableCause)
    for cause in CAUSES_DEFERRED:
        # Not "documented" in a docstring a test cannot read: each deferred
        # cause names the capability that will raise it, and why not here.
        assert RAISED_BY[cause].strip(), f"{cause} is deferred to nobody"


def test_each_locally_raised_cause_is_actually_produced(tmp_path: Path) -> None:
    """Reachability, proven by production code rather than asserted in prose.

    The mapping above only claims these are raised here; this produces every one
    of them. If a cause is moved into `CAUSES_RAISED_HERE` without a way to
    reach it, this fails.
    """
    produced = set()

    fifo_tree = tmp_path / "fifo-tree"
    fifo_tree.mkdir()
    os.mkfifo(fifo_tree / "pipe")
    with pytest.raises(Unrestorable) as caught:
        guard(fifo_tree)
    produced.add(caught.value.cause)

    sock_tree = tmp_path / "sock-tree"
    sock_tree.mkdir()
    with unix_socket_in(sock_tree):
        with pytest.raises(Unrestorable) as caught:
            guard(sock_tree)
        produced.add(caught.value.cause)

    produced.add(classify(Path("/dev/null")))
    if os.geteuid() != 0:
        produced.add(classify(Path("/usr/bin/true")))
    else:  # pragma: no cover - the suite does not run as root
        produced.add(UnrestorableCause.UNRESTORABLE_OWNERSHIP)

    src = build_torture_tree(tmp_path / "w")
    snap = take_snapshot(src, tmp_path / "snap")
    alien = type(snap)(
        snapshot=snap.snapshot,
        manifest=Manifest(backend="clonefile-apfs", capabilities=frozenset({"nothing"})),
    )
    with pytest.raises(Unrestorable) as caught:
        guarded_restore(alien, tmp_path / "out")
    produced.add(caught.value.cause)

    produced |= set(FIDELITY_GAPS)  # declared on every `present` handle

    assert produced == CAUSES_RAISED_HERE
