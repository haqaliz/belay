"""The default scope: the boundary the user does not have to author.

## Why a default is a correctness feature, not a convenience

`seatbelt.py` can contain a process. That is worth nothing if the contained
process cannot run. An over-tight profile does not fail politely — the child dies
on a write it had every right to expect, and the operator's only recourse is to
widen the scope by hand until the symptom stops.

That recourse is the failure. A boundary a user widens until their server starts
is a **user-authored** boundary, and it will be authored under pressure, by
someone who wants the error to go away, with no way to tell a legitimate need from
an agent escaping. Belay's A1 axis is only grounded if the invariant it enforces
came from somewhere better than that. So the default has to be right out of the
box, and `tests/test_default_scope.py` is where that claim is made falsifiable
rather than asserted.

## What the default grants, and the one non-obvious part

The scope is **the workspace**, plus a **`$TMPDIR` relocated into a directory
Belay owns**.

The temp directory is the part that matters. A filesystem or shell MCP server
writes temp files, lockfiles and caches constantly — the stdlib does it without
being asked, `tempfile.mkstemp()` being the common case — and on macOS `$TMPDIR`
is a per-boot directory under `/var/folders/...`, nowhere near any workspace.
Granting `/var/folders` would be a hole big enough to drive the agent through.
Denying it kills the server. So the third option: give the child a temp directory
of its own, grant that one subpath, and tell it where that is. Nothing is widened
and nothing is denied that should not be.

## The write scope and the snapshot scope are NOT the same thing

This is the distinction the whole module now turns on, and conflating the two is
the mistake that looks tidiest:

- **write scope** — what Seatbelt permits: the workspace **and** the temp
  directory (`write_roots`). The server needs temp files or it dies.
- **snapshot scope** — what the turn gate clones: the workspace **only**
  (`snapshot_root`). The temp directory is not in it.

So the temp directory lives **beside** the workspace rather than inside it, and
that placement is what buys both halves at once. Temp files stay writable and stay
out of every turn's snapshot, so temp churn cannot pollute a state diff — and, the
one that matters more, **a unix socket in the server's temp directory cannot
poison a turn**. `substrate.guard` refuses a tree containing a socket, by name and
on purpose; with `$TMPDIR` inside the snapshotted tree, a server that opens one
would report `unrestorable` on *every* turn. That is the honesty contract working
as designed, and it would make Belay useless for that server. Excluded by
construction, `guard` never sees it. `tests/test_proxy_containment.py` measures
both halves on a real proxy run.

`test_the_sandboxed_tmpdir_is_load_bearing` is the ablation — the same child,
without the redirect, refused — so this stays a mechanism with evidence rather
than a story about one.

## realpath is not hygiene here

Every path this module returns is `realpath`ed, and that is load-bearing twice:

- `/tmp` is a symlink to `private/tmp`. A profile granting `(subpath "/tmp/x")`
  grants **nothing** — measured in `seatbelt.py`, which refuses an unresolvable
  scope for the same reason.
- `$TMPDIR` on macOS is handed out as `/var/folders/...`, which is itself a
  symlink into `/private/var/folders/...` (measured on this machine). A default
  that resolved the workspace but not the temp dir would deny the very directory
  it just created.

## The costs, stated because they are real

**Temp files survive the run.** The temp directory is created here and never
removed: it is derived from the workspace so that two turns agree on where it is,
which means nothing in a single run knows it is the last one. It is named after
Belay and reported by `belay sandbox check`, so it is findable and safe to delete.

**A temp file is invisible to a state diff.** That is the point — it is not
snapshotted — but it is also a limit: whatever the server does under `$TMPDIR` is
outside what any later verdict can see. What Belay contains and what Belay
snapshots are two different questions, and this module answers them differently on
purpose.

**This module sets an environment and names paths; it does not author policy.** It
cannot alter the profile — `seatbelt.build_profile` is the single writer of that —
so the two halves cannot drift into disagreeing about what is granted.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

__all__ = [
    "TMPDIR_PREFIX",
    "TMPDIR_VARS",
    "DefaultScope",
    "default_scope",
]

#: The temp directory's name, minus the digest that ties it to one workspace.
#: Named after Belay so that anyone who finds one knows who put it there.
TMPDIR_PREFIX = "belay-tmp-"

#: Every variable the stdlib consults, in `tempfile`'s own order. Setting only
#: `TMPDIR` would leave a child that reads `TMP` writing to `/tmp` — outside the
#: scope, refused, and for a reason the operator would have no way to guess.
TMPDIR_VARS = ("TMPDIR", "TMP", "TEMP")

_ENV = "/usr/bin/env"


@dataclass(frozen=True)
class DefaultScope:
    """A workspace and the temp directory beside it, both as the kernel sees them.

    The two fields are named for the two questions they answer, because one path
    used for both is exactly the conflation this module exists to prevent.

    Frozen, and both fields are already resolved: a `DefaultScope` that could be
    built holding an unresolved path would be a policy that reads correctly and
    grants nothing.
    """

    #: The `realpath`ed workspace: what the agent works in, and the ONLY thing the
    #: turn gate clones. Hand this to `TurnGate(scope=...)`.
    snapshot_root: str

    #: The `realpath`ed temp directory, OUTSIDE `snapshot_root`. Writable by the
    #: child, exported to it, and never snapshotted.
    tmpdir: str

    @property
    def write_roots(self) -> tuple[str, ...]:
        """Every subpath the profile grants writes to. Hand this to `seatbelt`.

        Deliberately wider than `snapshot_root` and deliberately not interchangeable
        with it: the server needs a temp directory to live, and a state diff needs
        one it never sees.
        """
        return (self.snapshot_root, self.tmpdir)

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """`base` (default: this process's environment) with the temp vars redirected."""
        merged = dict(os.environ if base is None else base)
        merged.update({var: self.tmpdir for var in TMPDIR_VARS})
        return merged

    def wrap(self, command: Sequence[str]) -> list[str]:
        """`command`, prefixed so it starts with the temp vars pointing inside the scope.

        Why `/usr/bin/env` rather than an `env=` argument to the subprocess:
        `seatbelt.run` does not take one, and it is deliberately not being given
        one. Its job is to build a profile and observe a child, and an env
        parameter would put a second, unenforced notion of "what the child gets"
        next to the one the kernel enforces. `env` is a real program doing exactly
        the documented thing, and `test_wrap_exports_every_variable_the_stdlib_consults`
        observes the result in the child rather than trusting the argv.

        No `--` terminator, and that is measured, not sloppy: macOS `env` accepts
        `env -- cmd`, but after an assignment it takes `--` as the command name and
        fails `env: --: No such file or directory`. Which leaves the first argument
        ambiguous if it contains `=`, so that case is refused below rather than
        silently exec'ing whatever came after it.
        """
        argv = list(command)
        if not argv:
            raise ValueError("wrap() needs a command to wrap")
        if "=" in argv[0]:
            raise ValueError(
                f"refusing to wrap a command whose first argument is {argv[0]!r}: "
                f"`env` reads a leading NAME=VALUE as an assignment and would exec "
                f"the NEXT argument instead — a different program than the caller "
                f"named. macOS `env` has no `--` terminator after an assignment "
                f"(measured), so there is no way to disambiguate this."
            )
        return [_ENV, *(f"{var}={self.tmpdir}" for var in TMPDIR_VARS), *argv]


def default_scope(workspace: Path | str) -> DefaultScope:
    """The zero-config scope for `workspace`: the tree itself, plus a temp dir beside it.

    The temp directory is **created here**, before the profile is built and before
    any child runs. Both halves need it to already exist: `realpath` resolves only
    components that are there, and a child handed a `TMPDIR` that does not exist
    fails in a way that reads exactly like a denial while being the opposite of one.

    It is placed under the machine's own temp root — never inside the workspace —
    so that `snapshot_root` excludes it *by construction* rather than by a subtree
    filter someone could forget to apply. Its name carries a digest of the
    workspace, which is what makes this **idempotent**: called twice on one
    workspace it returns the same paths, and a `TMPDIR` that moved between turns
    would strand the previous turn's files somewhere the server had already
    recorded a handle to. Owner-only, because the child writes its scratch there
    and it sits in a directory shared with everything else on the machine.

    Idempotent and predictable are one property seen from two sides: what lets the
    second run find the first run's directory lets anyone else be there first. So
    an existing one is **adopted only if it is provably ours** — see
    `_make_private_dir`, which is why this is a `mkdir` and not a `makedirs`.
    """
    root = os.path.realpath(str(workspace))
    if not os.path.isdir(root):
        raise ValueError(
            f"workspace {str(workspace)!r} does not exist (resolved to {root!r}). "
            f"It must exist before the scope is built: an unresolved subpath in a "
            f"profile silently grants nothing."
        )

    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]
    tmpdir = os.path.join(os.path.realpath(tempfile.gettempdir()), f"{TMPDIR_PREFIX}{digest}")
    _make_private_dir(tmpdir)

    return DefaultScope(snapshot_root=root, tmpdir=os.path.realpath(tmpdir))


def _make_private_dir(path: str) -> None:
    """Create `path` 0700, or adopt it only if it is provably ours.

    The name above is a pure function of the workspace and is documented as one,
    so it is **predictable**: anyone who knows where the agent works knows this
    path. Whatever is here gets `realpath`ed into `write_roots` and becomes
    `(allow file-write* (subpath ...))` in the profile — which makes this the one
    path in Belay whose resolution decides what the sandbox grants.

    `os.makedirs(..., mode=0o700, exist_ok=True)` was doing this job and validates
    nothing about a path that already exists: not that it is a directory rather
    than a **symlink**, not who owns it, and not the mode — `mode=` is ignored
    outright on an existing path. A link planted here before the run sends the
    grant wherever it points (measured: `realpath` follows it and the profile
    grants the target).

    So: `mkdir` rather than `makedirs`, and on `FileExistsError` an `lstat` — which
    does not follow a link — must show a real directory, owned by us, at exactly
    0700. Anything else is refused **loudly**, the same posture `_resolved_scope`
    takes, because the alternative is a boundary that reads correctly and grants
    somewhere else.

    Refusing costs a run; adopting costs the boundary. The failure this prevents
    needs a same-uid attacker on stock macOS (`gettempdir()` is the per-user
    `/var/folders/.../T`, mode 0700) — but a `TMPDIR` that is unset or points at
    world-writable `/tmp`, which is CI, containers, launchd and cron, needs no
    such thing.
    """
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    else:
        # `mkdir`'s mode is masked by the umask, so a hostile or merely unusual
        # one could leave the directory we just made failing the check below on
        # the NEXT run. Said outright rather than inherited.
        os.chmod(path, 0o700)
        return

    info = os.lstat(path)  # lstat, never stat: a symlink must be seen as itself
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(
            f"refusing to adopt {path!r} as the sandbox temp directory: it exists "
            f"but is not a directory (it is {stat.filemode(info.st_mode)!r}). This "
            f"path is a pure function of the workspace and so is predictable; a "
            f"symlink planted here would redirect the profile's write grant to "
            f"wherever it points. Remove it and re-run."
        )
    if info.st_uid != os.geteuid():
        raise ValueError(
            f"refusing to adopt {path!r} as the sandbox temp directory: it is "
            f"owned by uid {info.st_uid}, not by uid {os.geteuid()} which is "
            f"running Belay. Belay would grant the contained server write access "
            f"to a directory somebody else created at a path they could predict."
        )
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError(
            f"refusing to adopt {path!r} as the sandbox temp directory: its mode "
            f"is {oct(stat.S_IMODE(info.st_mode))}, not 0o700. The child's scratch "
            f"— which is the agent's data — would be readable or replaceable by "
            f"others on this machine. Fix the mode or remove the directory."
        )
