"""Where are the two trees a content-grounded A1 rule compares?

`no-assertion-weakening` judges the RESULTING content against the **task** pre-state, so
it needs two directories on disk: turn 0's snapshot tree, and the post-replay workspace.
Both are already alive at the call site (`verify/turn.py`, REPLAYED branch), but finding
turn 0's tree means walking `records -> state_handle -> manifest -> snapshot`. This module
is that walk, and it exists as its own module for one reason:

**`invariants.py` must stay ignorant of traces.** Its public surface is pinned by
`test_no_invariant_is_ever_sourced_from_a_trace` — the provenance boundary that keeps an
agent from authoring its own policy — and handing it `records` would push trace-shaped data
into the layer that guard protects, even though the read is read-only and the POLICY still
comes only from the operator. So the resolution happens HERE, at the call site's elbow, and
`evaluate_invariant` receives two paths and nothing else.

**Every failure is a NAMED cause, never a guess and never a default.** A trace whose turn 0
was never snapshotted, a manifest directory that does not hold the matching manifest, and a
snapshot tree that has since been deleted are three different findings; an operator acts on
them differently and `phase0 report` counts them apart. They share the vocabulary defined in
`invariants.py` so a cause travels from here into the verdict message unchanged.

Reads only: `load_snapshot` reconstructs the manifest, and the tree is read where it lies.
No `guarded_restore` — restore exists to put back hardlinks, setuid bits and directory
mtimes (`replay/persist.py`), none of which reading a file's content touches, and restoring
a whole tree per turn to read one file would be the expensive way to learn nothing extra.

Zero runtime dependencies; stdlib only. The zero-LLM AST guard covers `src/belay/verify/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from belay.index import derive_correlation, tool_calls
from belay.replay.engine import _manifest_for
from belay.replay.persist import load_snapshot
from belay.verify.invariants import (
    NO_POST_STATE_TREE,
    NO_TASK_PRESTATE_HANDLE,
    NO_TASK_PRESTATE_MANIFEST,
    NO_TASK_PRESTATE_TREE,
    ContentRoots,
)

__all__ = ["content_roots"]


@dataclass(frozen=True)
class _Handle:
    """Turn 0's `state_handle`, or the reason there is none."""

    value: Optional[dict] = None
    cause: Optional[str] = None


def content_roots(
    records: Sequence[dict],
    manifest_dir: Union[Path, str],
    workspace: Optional[str],
) -> ContentRoots:
    """The task pre-state tree and the post-replay tree — or a named reason there are none.

    The pre-state is **turn 0's** snapshot, never the turn's own and never the previous
    turn's. That choice is the rule's precision: an agent editing a scratch test it wrote
    earlier in the same run has weakened nothing, and a file absent from turn 0's tree is
    exactly how that case stops reading as cheating.

    Fail-closed at every step. A missing handle, an unrestorable one, an unresolvable
    manifest, a vanished tree and an unobserved workspace each return a `ContentRoots`
    carrying its own cause and no paths, which `evaluate_invariant` renders as UNVERIFIED.
    Nothing here ever guesses a tree.
    """
    handle = _turn_zero_handle(records)
    if handle.value is None:
        return ContentRoots(cause=handle.cause)

    manifest_path = _manifest_for(handle.value.get("handle"), Path(manifest_dir))
    if manifest_path is None:
        return ContentRoots(cause=NO_TASK_PRESTATE_MANIFEST)
    try:
        snap = load_snapshot(manifest_path)
    except (OSError, ValueError, KeyError):
        # A manifest that is present but unreadable or malformed is the same finding as one
        # that is absent — in both cases there is no reconstructable pre-state — and it is
        # emphatically not a reason to proceed against a guessed tree.
        return ContentRoots(cause=NO_TASK_PRESTATE_MANIFEST)

    pre = Path(snap.snapshot.path)
    if not pre.is_dir():
        return ContentRoots(cause=NO_TASK_PRESTATE_TREE)

    if workspace is None:
        return ContentRoots(cause=NO_POST_STATE_TREE)
    post = Path(workspace)
    if not post.is_dir():
        return ContentRoots(cause=NO_POST_STATE_TREE)

    return ContentRoots(pre=pre, post=post)


def _turn_zero_handle(records: Sequence[dict]) -> _Handle:
    """The FIRST `tools/call`'s pre-state handle, if it is `present`.

    Selects the turn the way the replay engine does — by the correlation index over
    `method == tools/call`, never by scanning for a handle — so "turn 0" means the same
    thing here as everywhere else in the verdict path. Any status other than `present`
    (`absent`, `unrestorable`, or an unrecognised one) is the same fact for this purpose:
    there is no task pre-state to read, and the answer is UNVERIFIED.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if not calls:
        return _Handle(cause=NO_TASK_PRESTATE_HANDLE)
    request_seq = calls[0].get("request_seq")
    if request_seq is None:
        return _Handle(cause=NO_TASK_PRESTATE_HANDLE)
    for record in records:
        if record.get("kind") != "frame" or record.get("seq") != request_seq:
            continue
        handle = record.get("state_handle") or {}
        if handle.get("status") != "present":
            return _Handle(cause=NO_TASK_PRESTATE_HANDLE)
        return _Handle(value=handle)
    return _Handle(cause=NO_TASK_PRESTATE_HANDLE)
