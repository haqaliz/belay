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

The scope is **the workspace**, plus a **`$TMPDIR` relocated inside it**.

The temp directory is the part that matters. A filesystem or shell MCP server
writes temp files, lockfiles and caches constantly — the stdlib does it without
being asked, `tempfile.mkstemp()` being the common case — and on macOS `$TMPDIR`
is a per-boot directory under `/var/folders/...`, nowhere near any workspace.
Granting `/var/folders` would be a hole big enough to drive the agent through.
Denying it kills the server. So the third option: give the child a temp directory
that is *already inside* the scope, and tell it where that is. Nothing is widened
and nothing is denied that should not be.

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

**Temp files are inside the snapshot.** The turn gate snapshots the scope, and the
scope contains `TMPDIR` — so a turn's recorded pre-state includes whatever the
server left in it. That is *true* rather than *tidy*: those files were in the tree.
It cannot be avoided without either widening the scope or excluding a subtree from
the snapshot, and both are worse.

**A socket or FIFO in TMPDIR makes the turn unrestorable.** `substrate.guard`
refuses a tree containing one, by name and on purpose. A server that opens a unix
socket under `$TMPDIR` will therefore snapshot as `unrestorable`, every turn. That
is the honesty contract working, not a bug — but it is a real consequence of
putting TMPDIR inside the snapshotted tree, and it is written down here rather
than discovered later.

**This module sets an environment, and only an environment.** It cannot alter the
profile — `seatbelt.build_profile` is the single writer of that — so the two halves
cannot drift into disagreeing about what is granted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

__all__ = [
    "DEFAULT_TMPDIR_NAME",
    "TMPDIR_VARS",
    "DefaultScope",
    "default_scope",
]

#: The temp directory's name inside the workspace. Dotted so it stays out of the
#: way, and named so that anyone reading a snapshot knows who put it there.
DEFAULT_TMPDIR_NAME = ".belay-tmp"

#: Every variable the stdlib consults, in `tempfile`'s own order. Setting only
#: `TMPDIR` would leave a child that reads `TMP` writing to `/tmp` — outside the
#: scope, refused, and for a reason the operator would have no way to guess.
TMPDIR_VARS = ("TMPDIR", "TMP", "TEMP")

_ENV = "/usr/bin/env"


@dataclass(frozen=True)
class DefaultScope:
    """A workspace and the temp directory inside it, both as the kernel sees them.

    Frozen, and both fields are already resolved: a `DefaultScope` that could be
    built holding an unresolved path would be a policy that reads correctly and
    grants nothing.
    """

    #: The `realpath`ed workspace. Hand this to `seatbelt.run(scope=...)`.
    root: str

    #: The `realpath`ed temp directory, inside `root`. Exported to the child.
    tmpdir: str

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
    """The zero-config scope for `workspace`: the tree itself, plus a temp dir in it.

    The temp directory is **created here**, before the profile is built and before
    any child runs. Both halves need it to already exist: `realpath` resolves only
    components that are there, and a child handed a `TMPDIR` that does not exist
    fails in a way that reads exactly like a denial while being the opposite of one.

    Idempotent — called twice on one workspace it returns the same paths, because
    a `TMPDIR` that moved between turns would strand the previous turn's files
    somewhere the server had already recorded a handle to.
    """
    root = os.path.realpath(str(workspace))
    if not os.path.isdir(root):
        raise ValueError(
            f"workspace {str(workspace)!r} does not exist (resolved to {root!r}). "
            f"It must exist before the scope is built: an unresolved subpath in a "
            f"profile silently grants nothing."
        )

    tmpdir = os.path.join(root, DEFAULT_TMPDIR_NAME)
    os.makedirs(tmpdir, exist_ok=True)

    return DefaultScope(root=root, tmpdir=os.path.realpath(tmpdir))
