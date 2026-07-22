"""Pure path-relocation primitives for faithful absolute-path replay.

Replay restores a captured pre-state into a fresh **scratch** copy and re-invokes the
server there. A server that addresses files by *absolute path* — the argv root it was
launched with, the `path` it edits — still points at the ORIGINAL workspace, so its
reads leak to live state and its writes are denied, both silently. Relocation rewrites
those in-root absolute paths to the scratch prefix so the replay lands where it should.

This module is the **logic**, isolated: pure functions, **no I/O** — no subprocess, no
network, no filesystem stat. Wiring them into the replay flow (threading the recorded
root, gating, the honest-`UNVERIFIED` fallback) is a separate phase; nothing here decides
a verdict.

## The one asymmetry (the whole point)

`arguments` are **mutated** and re-sent to the server, so they are remapped
**conservatively**: a string is swapped **only if its entire value is an absolute path
under the recorded root** (`remap_arguments`). A `path` field moves; a `newText`/`content`
field that merely *mentions* the root as a substring is file content and is left
byte-for-byte intact. A substring remap of `arguments` would corrupt content written to
the scratch and manufacture a false delta — so it is never done.

Replies are only **compared**, never re-sent, so they are normalized **liberally**:
`canonicalize_reply` replaces both roots as substrings anywhere they appear (diff headers,
`file://` URLs, nested JSON). This is transient — never persisted, never written to the
scratch — so it cannot corrupt anything, and it makes a path buried in a diff line compare
equal across the original and scratch roots.

## Why `normpath`, not `realpath`

`is_under` normalizes with `os.path.normpath`, a purely *lexical* operation, rather than
`os.path.realpath`. These functions are pure and are applied to paths that may not exist
on disk (a recorded path whose original workspace is long gone, a synthetic test path), so
they must never stat the filesystem or resolve symlinks. The cost is that a symlinked root
that is not already canonical will miss the prefix match; by design that degrades to the
caller's honest `UNVERIFIED` fallback, never to a false verdict. The recorded root and the
scratch root are both realpath'd upstream (at capture and at restore), so in the wired path
both sides are already canonical and the lexical test is exact.
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "canonicalize_reply",
    "is_under",
    "remap_argv",
    "remap_arguments",
    "remap_prefix",
    "turn_needs_relocation",
]


def is_under(path_str: str, root: str) -> bool:
    """Is `path_str` the directory `root` itself, or a path component beneath it?

    A path-component prefix test, **not** a string prefix test: `/a/bc` is NOT under
    `/a/b` (sibling, not child), even though `/a/b` is a string prefix of `/a/bc`. Both
    operands are `os.path.normpath`-normalized the *same* way — lexical only, so `..` is
    collapsed without touching the disk and non-existent paths are fine. The root is under
    itself, so an argv token that *is* the root relocates.
    """
    root_n = os.path.normpath(root)
    path_n = os.path.normpath(path_str)
    if path_n == root_n:
        return True
    # A trailing separator makes the test component-aligned: `/a/b/` never matches `/a/bc`.
    prefix = root_n if root_n.endswith(os.sep) else root_n + os.sep
    return path_n.startswith(prefix)


def remap_prefix(path_str: str, from_root: str, to_root: str) -> str:
    """Swap the `from_root` prefix of `path_str` for `to_root`. Caller guarantees is_under.

    Returns the normalized in-root suffix rebased under `to_root` (the exact-root case
    returns `to_root` itself). All three operands are lexically normalized so the result is
    a clean path pointing at the same relative location inside the new root. This function
    trusts its precondition — it does not re-check `is_under`; call it only on a token/value
    that `is_under(path_str, from_root)` has already accepted.
    """
    from_n = os.path.normpath(from_root)
    to_n = os.path.normpath(to_root)
    path_n = os.path.normpath(path_str)
    if path_n == from_n:
        return to_n
    suffix = path_n[len(from_n) :]  # begins with os.sep, since is_under held
    return to_n + suffix


def remap_argv(
    argv: list[str], from_root: str, to_root: str
) -> tuple[list[str], bool]:
    """Rewrite every argv token that is / is under `from_root`; leave all others verbatim.

    Returns a NEW list and a `changed` flag (True iff at least one token moved). The server
    root token and any in-root path argument are swapped to the scratch prefix; a flag, a
    bare command name, and an out-of-root absolute path are untouched.
    """
    new_argv: list[str] = []
    changed = False
    for token in argv:
        if is_under(token, from_root):
            new_argv.append(remap_prefix(token, from_root, to_root))
            changed = True
        else:
            new_argv.append(token)
    return new_argv, changed


def remap_arguments(
    obj: object, from_root: str, to_root: str
) -> tuple[object, bool]:
    """Recursively remap in-root **whole-value** path strings; return a NEW structure.

    Recurses `dict` and `list`. A `str` value is remapped **iff its entire value is an
    absolute path under `from_root`** — the conservative rule that swaps a `path` field but
    never a `newText`/`content` field that merely *contains* the root as a substring, so
    file content is preserved by construction. Every other scalar (int, bool, None, float)
    passes through unchanged. The input object is never mutated: containers are rebuilt, so
    the caller's recorded `arguments` stay byte-clean. Returns `(new_obj, changed)`.
    """
    if isinstance(obj, dict):
        new_dict: dict[Any, object] = {}
        changed = False
        for key, value in obj.items():
            new_value, value_changed = remap_arguments(value, from_root, to_root)
            new_dict[key] = new_value
            changed = changed or value_changed
        return new_dict, changed
    if isinstance(obj, list):
        new_list: list[object] = []
        changed = False
        for item in obj:
            new_item, item_changed = remap_arguments(item, from_root, to_root)
            new_list.append(new_item)
            changed = changed or item_changed
        return new_list, changed
    if isinstance(obj, str) and is_under(obj, from_root):
        return remap_prefix(obj, from_root, to_root), True
    return obj, False


def canonicalize_reply(
    text: str, root_a: str, root_b: str, placeholder: str
) -> str:
    """Fold both roots to `placeholder` (substring, anywhere) for COMPARISON ONLY.

    The recorded reply carries the original root; the replayed reply carries the scratch
    root, in the same positions (diff `Index:`/`---`/`+++` lines, `file://` URLs, nested
    JSON). Replacing *both* roots as plain substrings collapses the two into one comparable
    form. The two roots are disjoint by construction (one is the workspace, one a mkdtemp
    scratch), so the substitution is order-independent; the longer root is replaced first as
    a belt-and-braces guard against any accidental nesting. This result is transient — never
    persisted, never written to the scratch — so a liberal substring substitution here can
    corrupt nothing.
    """
    first, second = sorted((root_a, root_b), key=len, reverse=True)
    return text.replace(first, placeholder).replace(second, placeholder)


def turn_needs_relocation(arguments: object, argv: list[str], root: str) -> bool:
    """True iff any in-root absolute path is present — in `arguments` or the server argv.

    Drives the relocation gate: a turn with no in-root whole-value `arguments` path and no
    in-root argv token needs nothing done and keeps today's byte-for-byte replay. Uses the
    same whole-value rule as `remap_arguments` for `arguments` strings and the is/under rule
    for argv tokens, so gating and rewriting can never disagree.
    """
    if any(is_under(token, root) for token in argv):
        return True
    return _contains_in_root_string(arguments, root)


def _contains_in_root_string(obj: object, root: str) -> bool:
    """Does `obj` hold any whole-value string that `is_under(root)`? (recursion helper)."""
    if isinstance(obj, dict):
        return any(_contains_in_root_string(value, root) for value in obj.values())
    if isinstance(obj, list):
        return any(_contains_in_root_string(item, root) for item in obj)
    if isinstance(obj, str):
        return is_under(obj, root)
    return False
