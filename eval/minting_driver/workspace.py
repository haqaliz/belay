"""Per-instance workspace prep: the repo at `base_commit`, in the gate's sibling layout.

The mint drives one instance at a time inside Belay's gated proxy, which needs three
directories per instance:

- `work_dir`     — the agent's workspace, i.e. `BELAY_SANDBOX_SCOPE`. The repo is checked
                   out here at the instance's `base_commit`.
- `trace_dir`    — where the proxy writes the trace, i.e. `BELAY_TRACE_DIR`.
- `snapshot_dir` — where each turn's pre-state is snapshotted, i.e. `BELAY_SNAPSHOT_DIR`.

`snapshot_dir` MUST be a **sibling** of `work_dir`, never inside it. The gate refuses at
startup if the snapshot root equals the scope or sits under it, because then turn 1 would
clone turn 0's snapshot into itself and every later turn would carry all the ones before —
recording a pre-state the agent never had, and grounding every verdict on a tree that
never existed (`src/belay/sandbox/gate.py:303-315`). `layout_for` places the three paths so
that refusal can never trigger; it is a pure function of `(instance_id, root)` — no clock,
no randomness — and is tested directly.

`prepare_workspace` composes `layout_for` with git acquisition. All git/network I/O goes
through an injectable `runner` seam (default `subprocess.run`) so the tests substitute a
fake and never run git or reach the network. Acquisition reuses a **cached bare clone per
repo** and adds the instance's `work_dir` as a `git worktree add --detach <work_dir>
<base_commit>`: a bare clone plus one worktree per instance shares the object store, so 50
django instances cost one clone and 50 cheap worktrees rather than 50 full clones. (`git
clone --shared` would also share objects but leaves a fragile `alternates` link into a
non-bare source and warns against pruning the source; a bare clone as the shared origin of
detached worktrees is the git-native, self-contained form.)

A git failure — the runner raising `CalledProcessError` or returning a non-zero result —
surfaces as a named `WorkspacePrepError` identifying the instance and its `base_commit`,
never a silent partial workspace, mirroring the fail-closed idiom of
`eval.minting_driver.servers.MissingServerError`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

from eval.instances.registry import InstanceRecord

StrPath = Union[str, "Path"]

#: The acquisition seam: anything call-compatible with `subprocess.run`. Injected in
#: tests so no git runs and nothing reaches the network.
Runner = Callable[..., "subprocess.CompletedProcess"]


class WorkspacePrepError(RuntimeError):
    """Repo acquisition for one instance failed (e.g. a bad `base_commit`).

    Raised instead of leaving a half-created workspace behind. The message names the
    instance and the commit so the batch driver can record the instance `failed` and the
    selection layer can draw a replacement.
    """


@dataclass(frozen=True)
class WorkspaceLayout:
    """The three per-instance directories the gated proxy is handed.

    `work_dir` is `BELAY_SANDBOX_SCOPE`, `trace_dir` is `BELAY_TRACE_DIR`, `snapshot_dir`
    is `BELAY_SNAPSHOT_DIR`. `snapshot_dir` is deliberately a sibling of `work_dir` (never
    inside it) — see the module docstring and `gate.py:303-315`.
    """

    work_dir: Path
    trace_dir: Path
    snapshot_dir: Path


def layout_for(instance_id: str, root: StrPath) -> WorkspaceLayout:
    """The per-instance directory layout under `root` — pure, deterministic.

    A plain function of `(instance_id, root)`: `<root>/<instance_id>/{workspace,traces,
    snapshots}`. `snapshots` is a sibling of `workspace`, so the gate's snapshot-inside-
    scope refusal can never trigger. Reads no clock, draws no randomness.
    """
    instance_root = Path(root) / instance_id
    return WorkspaceLayout(
        work_dir=instance_root / "workspace",
        trace_dir=instance_root / "traces",
        snapshot_dir=instance_root / "snapshots",
    )


def _repo_slug(repo: str) -> str:
    """A filesystem-safe name for a `owner/name` repo, matching SWE-bench's `owner__name`.

    Used to name the cached bare clone so two repos never collide on one clone dir.
    """
    return repo.replace("/", "__")


def _repo_url(repo: str) -> str:
    """The clone URL for an `owner/name` GitHub repo."""
    return f"https://github.com/{repo}.git"


def _run(
    runner: Runner,
    argv: list[str],
    *,
    record: InstanceRecord,
    what: str,
) -> None:
    """Invoke `runner(argv)`, turning any failure into a named `WorkspacePrepError`.

    Handles both failure conventions: a raised `CalledProcessError` and a returned
    non-zero `CompletedProcess` (a fake, or a runner called without `check=True`).
    """
    try:
        result = runner(argv, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise WorkspacePrepError(
            f"workspace prep for instance {record.instance_id!r} failed while {what} "
            f"at base_commit {record.base_commit!r}: {' '.join(argv)!r} exited "
            f"{exc.returncode}"
        ) from exc

    returncode = getattr(result, "returncode", 0)
    if returncode != 0:
        raise WorkspacePrepError(
            f"workspace prep for instance {record.instance_id!r} failed while {what} "
            f"at base_commit {record.base_commit!r}: {' '.join(argv)!r} exited "
            f"{returncode}"
        )


def prepare_workspace(
    record: InstanceRecord,
    *,
    root: StrPath,
    clones_dir: StrPath,
    runner: Runner = subprocess.run,
) -> WorkspaceLayout:
    """Materialize `record`'s repo at `base_commit` in the gate's sibling layout.

    Computes the layout with `layout_for`, then acquires the repo through `runner`:

    1. A cached **bare** clone of the repo lives under `clones_dir` (created once per
       repo, reused across every instance of that repo).
    2. The instance's `work_dir` is added as a detached worktree of that bare clone at
       `record.base_commit`.

    All git/network I/O goes through `runner` (default `subprocess.run`); tests inject a
    fake and never run git. Any git failure raises `WorkspacePrepError` — the workspace is
    never left silently partial. Returns the `WorkspaceLayout` on success.
    """
    layout = layout_for(record.instance_id, root)

    clones = Path(clones_dir)
    clones.mkdir(parents=True, exist_ok=True)
    bare_clone = clones / f"{_repo_slug(record.repo)}.git"

    # The per-instance dir must exist; `git worktree add` creates work_dir itself and
    # refuses a pre-existing non-empty target, so we create only its parent.
    layout.work_dir.parent.mkdir(parents=True, exist_ok=True)

    if not bare_clone.exists():
        _run(
            runner,
            ["git", "clone", "--bare", _repo_url(record.repo), str(bare_clone)],
            record=record,
            what="cloning the bare repo",
        )

    _run(
        runner,
        [
            "git",
            "-C",
            str(bare_clone),
            "worktree",
            "add",
            "--detach",
            str(layout.work_dir),
            record.base_commit,
        ],
        record=record,
        what="checking out the worktree",
    )

    # The trace and snapshot dirs are the gate's to write into; create them so the proxy
    # never has to. Both are siblings of work_dir, never inside it.
    layout.trace_dir.mkdir(parents=True, exist_ok=True)
    layout.snapshot_dir.mkdir(parents=True, exist_ok=True)

    return layout


__all__ = [
    "Runner",
    "WorkspaceLayout",
    "WorkspacePrepError",
    "layout_for",
    "prepare_workspace",
]
