"""What the snapshot cannot faithfully handle — detected, and refused by name.

Every other module in C2 is mechanism: clone the tree, hash it, contain the
process. This one is the honesty contract, and it exists because of a single
sentence:

    *Narrowing the substrate is only honest if you DETECT out-of-substrate
    entries and REFUSE loudly. Silently ignoring a FIFO is exactly the
    UNVERIFIED-rendered-as-PASS that CLAUDE.md forbids.*

**The supported substrate is regular files, directories and symlinks.** That is
not a limitation this module apologises for — it is one it *enforces*. Anything
else is refused with a named cause, before a snapshot is taken. Never skipped,
never quietly succeeded.

## Why refusal beats best-effort, concretely

A FIFO in a tree has two failure modes and both are worse than refusing. Copy the
node and you restore an empty pipe, losing the queued bytes with no record that
anything was lost. *Skip* it and the restored tree is missing an entry, and every
verdict grounded on that pre-state is grounded on a tree that never existed. Both
report success. Refusal is the only option that leaves a reader able to tell what
happened.

## Filling C1's reserved slot

`trace.py` has carried `"state_handle": {"status": "absent"}` since the first line
of trace ever written, with a comment explaining why the slot is three-state:

    *If this slot could only say present/absent, C2 would have to overload
    "absent" to mean both "recorded before snapshots existed" and "we tried and
    failed" — and that overload is how a false PASS is born.*

So `absent` keeps its meaning exactly — *no snapshot was attempted* — and this
module supplies the other two: `present_handle` and `unrestorable_handle`.
`tests/test_substrate.py::test_absent_is_not_repurposed` is that distinction, held
open by a test rather than by a comment.

**`present` names its own gaps.** A handle that said only `present` would imply a
fidelity no snapshot has: atime, ctime, birthtime and inode identity cannot be
restored by anyone, which is why BTH-1 excludes them and says so. `FIDELITY_GAPS`
is that exclusion list, restated as causes and attached to every `present` handle,
so a reader of the trace learns what did *not* come back without having to know
BTH-1's internals.

## No verdicts

C2 emits the `unrestorable` **fact** with its cause. **C4 renders UNVERIFIED.**
Nothing here decides PASS/FAIL, and the distinction is not pedantry: the moment a
mechanism grades its own fidelity, the grounding argument collapses.

## What this module cannot detect, stated rather than implied

`CAUSES_DEFERRED` is the other half of the contract. Several causes in the
taxonomy are real and named, but nothing here can produce them — a cause this
module could raise but never does would be a claim with no evidence behind it,
which is the documentation equivalent of a false PASS. Each one is mapped in
`RAISED_BY` to the capability that will raise it and the reason it cannot be
raised here, and a test asserts every member of the enum is classified exactly
once. Three of them are measured impossibilities on this substrate rather than
mere omissions — see `RAISED_BY`.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .bth1 import UnsupportedPlatform
from .clone import Snapshot, TreeRoot, restore, snapshot


class UnrestorableCause(str, Enum):
    """Every named cause C2 knows. `str` so the value lands in JSON as itself.

    A cause is a *fact about what could not be restored*, never a verdict. The
    classification below (raised here / deferred) is enforced by a test.
    """

    # --- Out-of-substrate filesystem objects: detected here, by lstat. --------
    UNRESTORABLE_FIFO = "UNRESTORABLE_FIFO"
    UNRESTORABLE_SOCKET = "UNRESTORABLE_SOCKET"
    UNRESTORABLE_DEVICE_NODE = "UNRESTORABLE_DEVICE_NODE"

    # --- Physically unsettable: excluded from BTH-1, declared on every handle.
    UNRESTORABLE_BIRTHTIME = "UNRESTORABLE_BIRTHTIME"
    UNRESTORABLE_CTIME = "UNRESTORABLE_CTIME"
    UNRESTORABLE_ATIME = "UNRESTORABLE_ATIME"
    UNRESTORABLE_INODE_IDENTITY = "UNRESTORABLE_INODE_IDENTITY"

    # --- Privilege-gated. ----------------------------------------------------
    UNRESTORABLE_OWNERSHIP = "UNRESTORABLE_OWNERSHIP"

    # --- Backend capability mismatch (S1). -----------------------------------
    UNRESTORABLE_CAPABILITY_MISMATCH = "UNRESTORABLE_CAPABILITY_MISMATCH"

    # --- Cross-filesystem impossibility: refuse, never attempt. --------------
    UNRESTORABLE_CASE_COLLISION = "UNRESTORABLE_CASE_COLLISION"
    UNRESTORABLE_INVALID_UTF8_NAME = "UNRESTORABLE_INVALID_UTF8_NAME"
    UNRESTORABLE_NORMALIZATION_COLLISION = "UNRESTORABLE_NORMALIZATION_COLLISION"

    # --- Outside the filesystem entirely: say this loudest. ------------------
    UNRESTORABLE_EXTERNAL_SERVICE = "UNRESTORABLE_EXTERNAL_SERVICE"
    UNRESTORABLE_NETWORK_EFFECT = "UNRESTORABLE_NETWORK_EFFECT"
    UNRESTORABLE_WALL_CLOCK = "UNRESTORABLE_WALL_CLOCK"
    UNRESTORABLE_RUNNING_PROCESS = "UNRESTORABLE_RUNNING_PROCESS"
    UNRESTORABLE_RANDOMNESS = "UNRESTORABLE_RANDOMNESS"


#: The fields no snapshot restores, and BTH-1 therefore excludes from the hash.
#: Declared on every `present` handle so that "present" cannot be read as "all of
#: it came back". These are not failures — they are the honest edge of the
#: mechanism, and BTH-1's module docstring is the long-form reason for each.
FIDELITY_GAPS = (
    UnrestorableCause.UNRESTORABLE_ATIME,
    UnrestorableCause.UNRESTORABLE_CTIME,
    UnrestorableCause.UNRESTORABLE_BIRTHTIME,
    UnrestorableCause.UNRESTORABLE_INODE_IDENTITY,
)

#: Causes this module can actually produce. Proven by
#: `test_each_locally_raised_cause_is_actually_produced`, which reaches every one
#: through production code rather than trusting this tuple.
CAUSES_RAISED_HERE = {
    UnrestorableCause.UNRESTORABLE_FIFO,
    UnrestorableCause.UNRESTORABLE_SOCKET,
    UnrestorableCause.UNRESTORABLE_DEVICE_NODE,
    UnrestorableCause.UNRESTORABLE_OWNERSHIP,
    UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH,
    *FIDELITY_GAPS,
}

#: Causes that are real, named, and **not raised here** — each mapped to whoever
#: raises it and why it cannot be raised now. Kept in the enum because C4 must be
#: able to name them when it renders UNVERIFIED, and a taxonomy that only listed
#: what today's code detects would quietly shrink the known unknowns.
#:
#: The first three are **measured impossibilities on this substrate**, not
#: oversights: APFS refuses to create the very entries that would trigger them
#: (`OSError 92 EILSEQ` for an invalid-UTF8 name; `EEXIST` for both a case
#: collision and an NFC/NFD pair). A macOS source tree therefore cannot contain
#: one, and they can only arise when a tree captured on a case-sensitive,
#: byte-transparent filesystem is restored onto APFS — which is C2's second,
#: Linux slice.
RAISED_BY: dict[UnrestorableCause, str] = {
    UnrestorableCause.UNRESTORABLE_CASE_COLLISION: (
        "C2's Linux/ext4 slice, on cross-filesystem restore. Unreachable here: "
        "APFS is case-insensitive, so creating `README` and `readme` in one "
        "directory fails with EEXIST (measured) — a source tree on this "
        "substrate cannot hold the collision that would be refused."
    ),
    UnrestorableCause.UNRESTORABLE_INVALID_UTF8_NAME: (
        "C2's Linux/ext4 slice, on cross-filesystem restore. Unreachable here: "
        "APFS rejects an invalid-UTF8 name at creation with OSError 92 EILSEQ "
        "(measured), so no tree on this machine can contain one."
    ),
    UnrestorableCause.UNRESTORABLE_NORMALIZATION_COLLISION: (
        "C2's Linux/ext4 slice, on cross-filesystem restore. Unreachable here: "
        "APFS normalises, so an NFC and an NFD spelling of the same name are "
        "one file and the second create fails with EEXIST (measured)."
    ),
    UnrestorableCause.UNRESTORABLE_EXTERNAL_SERVICE: (
        "C4, from the network policy C2 records as a fact. A call that already "
        "left the box cannot be un-made by restoring a directory, and no "
        "filesystem scan can see that it happened."
    ),
    UnrestorableCause.UNRESTORABLE_NETWORK_EFFECT: (
        "C4, from the network policy C2 records as a fact. Same reason: the "
        "effect is outside the tree, so the tree cannot report it."
    ),
    UnrestorableCause.UNRESTORABLE_WALL_CLOCK: (
        "C3/C4. Re-execution happens at a different time, so a time-dependent "
        "call diverges legitimately. That is a property of the replay, not of "
        "the pre-state, and it is invisible to a snapshot."
    ),
    UnrestorableCause.UNRESTORABLE_RUNNING_PROCESS: (
        "C3, at replay. Process-internal state — open fds, connection pools, "
        "auth sessions — is restorable in principle but never by a filesystem "
        "snapshot."
    ),
    UnrestorableCause.UNRESTORABLE_RANDOMNESS: (
        "C3/C4, at replay. Seatbelt is access control, not a hypervisor: it "
        "virtualises no entropy source, so a snapshot cannot make `urandom` "
        "replay the same bytes."
    ),
}

CAUSES_DEFERRED = set(RAISED_BY)

#: Where a refusal came from. The seatbelt denial records carry
#: `source: "child-stderr"` for the same reason — a fact should state how it was
#: established, so a reader never has to guess whether it was observed or
#: assumed. Everything this module refuses is established by `os.lstat`.
_SOURCE_LSTAT = "lstat"

_OUT_OF_SUBSTRATE = (
    (stat.S_ISFIFO, UnrestorableCause.UNRESTORABLE_FIFO),
    (stat.S_ISSOCK, UnrestorableCause.UNRESTORABLE_SOCKET),
    (stat.S_ISCHR, UnrestorableCause.UNRESTORABLE_DEVICE_NODE),
    (stat.S_ISBLK, UnrestorableCause.UNRESTORABLE_DEVICE_NODE),
)


class Unrestorable(Exception):
    """One named refusal, with the entry that caused it.

    Deliberately an exception rather than a returned status: a caller that
    ignores a returned status silently snapshots a tree it was told not to, and
    "silently" is the whole thing we are trying to prevent.
    """

    def __init__(
        self,
        cause: UnrestorableCause,
        detail: str,
        *,
        path: bytes = b"",
        source: str = _SOURCE_LSTAT,
    ) -> None:
        super().__init__(f"{cause.value}: {detail}")
        self.cause = cause
        self.detail = detail
        self.path = path
        self.source = source


def classify(path: TreeRoot | bytes) -> Optional[UnrestorableCause]:
    """The cause `path` would be refused for, or `None` if it is in-substrate.

    **Reads `lstat` and nothing else. Never opens the node.** Opening a FIFO with
    no writer blocks forever — that is not hypothetical, it hung this project's
    suite mid-session and needed a kill — and opening a device node is worse.
    `test_classifying_a_fifo_never_opens_it` makes `open` fatal for the duration
    of a scan so that this stays true rather than merely being intended.
    """
    info = os.lstat(path)
    mode = info.st_mode

    for predicate, cause in _OUT_OF_SUBSTRATE:
        if predicate(mode):
            return cause

    # Ownership last: an out-of-substrate node is refused for *what it is*, which
    # is the more specific and more useful fact than who owns it.
    if info.st_uid != os.geteuid() and os.geteuid() != 0:
        return UnrestorableCause.UNRESTORABLE_OWNERSHIP

    return None


def _walk(root: bytes):
    """Every entry under `root`, raw relative bytes, root included as b'.'.

    Iterative and never follows a symlink, matching `bth1._relative_paths` and
    `clone._walk`. Following one would classify the *target*, and a link pointing
    at `/dev/null` would then refuse a tree whose own contents are fine.
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


def guard(root: TreeRoot) -> None:
    """Refuse `root` if it holds anything the snapshot cannot faithfully restore.

    Raises on the **first** out-of-substrate entry rather than collecting every
    one: the snapshot is refused either way, and a caller that must fix the tree
    learns nothing more from the second FIFO than from the first.
    """
    root_bytes = os.fsencode(root)
    for rel in _walk(root_bytes):
        full = root_bytes if rel == b"." else os.path.join(root_bytes, rel)
        cause = classify(full)
        if cause is not None:
            raise Unrestorable(
                cause,
                f"{os.fsdecode(rel)!r} is outside the supported substrate "
                "(regular files, directories, symlinks); refusing rather than "
                "snapshotting a tree we cannot restore",
                path=rel,
                source=_SOURCE_LSTAT,
            )


class ClonefileBackend:
    """The one backend that exists today, and what it can actually promise.

    `capabilities()` is **probed, not declared**. A hardcoded list is a claim
    about the machine that stops being true the moment the code moves, and this
    set is the thing a restore refuses across — so a wrong entry here is a false
    PASS with extra steps.
    """

    name = "clonefile-apfs"

    @staticmethod
    def capabilities() -> frozenset[str]:
        caps = {
            "clonefile",  # the syscall this backend is built on
            "acls",  # CLONE_ACL carries them; without the flag they vanish
            "hardlinks",  # rebuilt from the sidecar
            "special-modes",  # setuid/setgid/sticky, re-chmod'ed
            "dir-mtimes",  # restamped deepest-first
        }
        # `os.listxattr` does not exist on macOS but does on Linux (measured).
        # BTH-1 reads xattrs through ctypes precisely because of this, and a tree
        # captured where they are native cannot be truthfully restored where they
        # are not — which is what makes this a capability rather than a detail.
        if hasattr(os, "listxattr"):
            caps.add("xattrs-os-native")
        return frozenset(caps)


@dataclass(frozen=True)
class Manifest:
    """What produced a snapshot, recorded so a restore can refuse across a gap.

    This is honesty, not portability. The alternative — restore anyway, drop what
    the destination cannot hold — returns a tree that is missing a field and
    reports a pre-state it did not restore.
    """

    backend: str
    capabilities: frozenset[str]
    handle: str = ""


@dataclass(frozen=True)
class GuardedSnapshot:
    """A `clone.Snapshot` plus the manifest naming what took it."""

    snapshot: Snapshot
    manifest: Manifest


def take_snapshot(source: TreeRoot, dest: TreeRoot) -> GuardedSnapshot:
    """Guard the tree, then snapshot it, recording what did the work.

    The guard runs **first**. Snapshotting and then noticing is not detection —
    it is a lossy artifact on disk plus an apology.
    """
    guard(source)
    snap = snapshot(source, dest)
    return GuardedSnapshot(
        snapshot=snap,
        manifest=Manifest(
            backend=ClonefileBackend.name,
            capabilities=ClonefileBackend.capabilities(),
            handle=uuid.uuid4().hex,
        ),
    )


def guarded_restore(snap: GuardedSnapshot, dest: TreeRoot) -> None:
    """Restore, or refuse across a capability set that differs.

    Note the refusal happens before `dest` is touched: a half-restored tree is
    indistinguishable from a restored one to everything downstream.
    """
    here = ClonefileBackend.capabilities()
    if snap.manifest.capabilities != here:
        missing = sorted(snap.manifest.capabilities - here)
        extra = sorted(here - snap.manifest.capabilities)
        raise Unrestorable(
            UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH,
            f"snapshot was taken by {snap.manifest.backend!r} with capabilities "
            f"{sorted(snap.manifest.capabilities)}; this machine has {sorted(here)}. "
            f"Absent here: {missing}. Only here: {extra}. Refusing rather than "
            "restoring a tree whose missing properties nothing would have reported.",
            source="capabilities",
        )
    restore(snap.snapshot, dest)


def absent_handle() -> dict[str, Any]:
    """No snapshot was attempted. **Not** "we tried and failed" — see the module docstring."""
    return {"status": "absent"}


def present_handle(snap: GuardedSnapshot) -> dict[str, Any]:
    """A snapshot exists and restores — along with what it did *not* preserve."""
    return {
        "status": "present",
        "handle": snap.manifest.handle,
        "backend": snap.manifest.backend,
        "capabilities": sorted(snap.manifest.capabilities),
        "fidelity_gaps": [gap.value for gap in FIDELITY_GAPS],
    }


def unrestorable_handle(error: Unrestorable) -> dict[str, Any]:
    """We tried and could not, and here is the named reason."""
    handle: dict[str, Any] = {
        "status": "unrestorable",
        "cause": error.cause.value,
        "detail": error.detail,
        "source": error.source,
    }
    if error.path:
        # Raw bytes are not JSON, and decoding is what BTH-1 refuses to do to a
        # path. `surrogateescape` round-trips through `os.fsencode`, so the name
        # survives even when it is not valid UTF-8.
        handle["path"] = os.fsdecode(error.path)
    return handle


def _clear_flags(root: Path) -> None:
    """Clear `uchg` and friends, deepest-first.

    Before the ACLs, not after: an immutable file refuses to have its ACL
    changed, so the other order fixes nothing and reports success.
    """
    for parent, dirs, files in os.walk(root, topdown=False):
        for name in files + dirs:
            try:
                os.chflags(os.path.join(parent, name), 0, follow_symlinks=False)
            except OSError:
                # Best-effort by design: this is the *repair* path, and the
                # rmtree that follows is what decides whether it worked. Raising
                # here would replace a real error with a speculative one.
                pass
    try:
        os.chflags(root, 0, follow_symlinks=False)
    except OSError:
        pass


def _strip_acls(root: Path) -> None:
    """Remove every ACL in the tree.

    `/bin/chmod -R -N` rather than ctypes: `acl_delete_link_np` returns
    `ENOTSUP` (errno 45) on APFS here — measured — so the ctypes route that would
    have matched `clonefile`'s style does not actually work. One process for the
    whole tree, and the binary is addressed absolutely so `$PATH` cannot decide
    what runs.
    """
    subprocess.run(
        ["/bin/chmod", "-R", "-N", str(root)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,  # rmtree below is the real check
    )


def gc(path: TreeRoot) -> None:
    """Delete a snapshot tree, including ones the OS says you may not delete.

    An ACL of *"everyone deny delete"* made a researcher's own scratch dir
    undeletable — `rm -rf` and `shutil.rmtree` both fail with EACCES (measured
    here, not recalled). An agent under test can set exactly that, on a tree we
    snapshot every turn. Without this, C2 strands disk on every such run.

    The repair is attempted **only after** a plain delete fails, so the common
    case never pays for a spawn, and the flag/ACL clearing is never applied to a
    tree that did not need it.
    """
    path = Path(path)
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        return
    except PermissionError:
        pass
    _clear_flags(path)
    _strip_acls(path)
    shutil.rmtree(path)  # if this still fails, it raises: no silent stranding


__all__ = [
    "CAUSES_DEFERRED",
    "CAUSES_RAISED_HERE",
    "FIDELITY_GAPS",
    "RAISED_BY",
    "ClonefileBackend",
    "GuardedSnapshot",
    "Manifest",
    "Unrestorable",
    "UnrestorableCause",
    "UnsupportedPlatform",
    "absent_handle",
    "classify",
    "gc",
    "guard",
    "guarded_restore",
    "present_handle",
    "take_snapshot",
    "unrestorable_handle",
]
