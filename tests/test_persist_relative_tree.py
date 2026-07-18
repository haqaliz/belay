"""M2: a persisted manifest's `tree_path` resolves relative to the manifest's own dir.

For a corpus case to be self-contained and portable, `corpus add` (a later C6 phase)
copies the snapshot tree into `<case>/prestate/` and writes `manifest.json` with a
RELATIVE `tree_path` (`"prestate"`). `load_snapshot` must resolve that against the
manifest's directory, not the process cwd — otherwise a case restored from a different
working directory silently reads the wrong tree (or nothing).

Two claims, and the pair is the point:

- BACKWARD-COMPAT (e): an ABSOLUTE `tree_path` — what `persist_snapshot` writes today and
  every existing C1-C5 caller relies on — still restores to the same tree. Watched
  PASSING before AND after the change: proof existing callers are undisturbed.
- RELATIVE (f): a `tree_path` of `"prestate"`, tree sitting next to the manifest, loaded
  from a DIFFERENT cwd, restores correctly. Watched FAILING first (today a relative Path
  resolves against cwd) then passing after the change.

Not darwin-gated, matching `tests/test_snapshot_persist.py`: the clonefile substrate runs
on this machine there, so it runs here too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixtures.torture_tree import build_torture_tree

from belay.replay.persist import load_snapshot, persist_snapshot
from belay.snapshot.bth1 import hash_tree
from belay.snapshot.substrate import GuardedSnapshot, guarded_restore, take_snapshot


@pytest.fixture
def snapped_in_case_dir(tmp_path: Path) -> tuple[Path, Path, str]:
    """Snapshot a torture tree straight into a case dir's `prestate/`, manifest beside it.

    Returns `(manifest_path, case_dir, original_hash)`. The tree physically lives at
    `<case_dir>/prestate`, so a relative `tree_path` of `"prestate"` and the absolute one
    `persist_snapshot` writes name the SAME bytes — the only difference under test is how
    `load_snapshot` resolves the string.
    """
    work = build_torture_tree(tmp_path / "work")
    original = hash_tree(work)
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    snap = take_snapshot(work, case_dir / "prestate")
    # Anti-vacuity: the fidelity repairs must actually be present, or a restore that
    # "matched" would prove nothing about tree_path resolution.
    assert snap.snapshot.sidecar.link_groups, "no hardlink captured - test is vacuous"
    assert snap.snapshot.sidecar.special_modes, "no setuid captured - test is vacuous"

    manifest_path = case_dir / "manifest.json"
    persist_snapshot(snap, manifest_path)
    return manifest_path, case_dir, original


def test_absolute_tree_path_still_restores(
    snapped_in_case_dir: tuple[Path, Path, str], tmp_path: Path
) -> None:
    """(e) BACKWARD-COMPAT: the absolute tree_path persist writes restores unchanged.

    Passes before and after the change. `persist_snapshot` writes an absolute path; this
    is exactly the existing C1-C5 contract, and it must keep resolving to the same tree.
    """
    manifest_path, _case_dir, original = snapped_in_case_dir

    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert Path(stored["tree_path"]).is_absolute(), (
        "persist_snapshot must still write an ABSOLUTE tree_path"
    )

    loaded = load_snapshot(manifest_path)
    dest = tmp_path / "restored-abs"
    guarded_restore(loaded, dest)
    assert hash_tree(dest) == original, (
        "an absolute tree_path did not restore to the original tree - the change broke "
        "the existing C1-C5 persist contract"
    )


def test_relative_tree_path_resolves_against_manifest_dir(
    snapped_in_case_dir: tuple[Path, Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(f) A relative tree_path resolves against the manifest dir, not the cwd.

    RED before the change: `Path("prestate")` resolves against the process cwd (here an
    empty `elsewhere/` with no `prestate`), so the load/restore cannot find the tree.
    GREEN after: `load_snapshot` joins it onto the manifest's own directory.
    """
    manifest_path, _case_dir, original = snapped_in_case_dir

    # Rewrite the persisted absolute tree_path to a case-relative one. The tree already
    # sits at <case_dir>/prestate, so only the resolution rule changes.
    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    stored["tree_path"] = "prestate"
    manifest_path.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    # Run from a cwd that is NOT the manifest dir and holds no `prestate/`. If resolution
    # used the cwd, the tree would be unreachable from here.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    loaded = load_snapshot(manifest_path)
    dest = tmp_path / "restored-rel"
    guarded_restore(loaded, dest)
    assert hash_tree(dest) == original, (
        "a relative tree_path did not resolve against the manifest's directory"
    )
