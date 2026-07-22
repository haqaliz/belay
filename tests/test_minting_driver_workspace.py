"""Per-instance workspace prep — deterministic, offline, CI-safe.

The mint materializes each instance's repo at its `base_commit` in the *sibling* layout
Belay's gate requires: the snapshot dir MUST NOT sit inside the sandbox scope, or every
turn would snapshot the previous turns' snapshots and record a pre-state the agent never
had (`src/belay/sandbox/gate.py:303-315`). `layout_for` is the pure function that places
those paths; `prepare_workspace` composes it with git acquisition behind an injectable
`runner` seam.

Every test here fakes the `runner`: nothing runs git, nothing spawns a process, nothing
reaches the network. The one place a real `subprocess.run` is referenced is an assertion
about the *default* — never a call.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from eval.instances.registry import InstanceRecord
from eval.minting_driver import workspace


def _record(
    instance_id: str = "django__django-12345",
    repo: str = "django/django",
    base_commit: str = "0abc1230abc1230abc1230abc1230abc1230abc1",
) -> InstanceRecord:
    """A minimal `InstanceRecord` — only the acquisition fields matter here."""
    return InstanceRecord(
        instance_id=instance_id,
        repo=repo,
        base_commit=base_commit,
        problem_statement="issue text",
        task_string="do the thing",
    )


class _FakeRunner:
    """A stand-in for `subprocess.run` that records argv and fakes git's dir effects.

    It NEVER runs git and NEVER touches the network. It recognises the two git shapes
    `prepare_workspace` issues — a bare `clone` and a `worktree add` — and creates the
    directory each would have created, so the composed function can be exercised end to
    end offline. `fail_on` forces a non-zero result (or a raised `CalledProcessError`) to
    exercise the failure path.
    """

    def __init__(self, *, fail_on: str | None = None, raise_failure: bool = True) -> None:
        self.calls: list[list[str]] = []
        self._fail_on = fail_on
        self._raise = raise_failure

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)

        if self._fail_on is not None and self._fail_on in argv:
            if self._raise:
                raise subprocess.CalledProcessError(returncode=128, cmd=argv)
            return subprocess.CompletedProcess(argv, returncode=128, stdout="", stderr="boom")

        # Fake the filesystem effect of the recognised git subcommands.
        if "clone" in argv:
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
        elif "worktree" in argv and "add" in argv:
            # `... worktree add --detach <work_dir> <base_commit>` — work_dir precedes
            # the commit-ish (the final token).
            Path(argv[-2]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")


def test_snapshot_dir_is_a_sibling_of_the_scope_never_inside_it(tmp_path: Path) -> None:
    layout = workspace.layout_for("django__django-12345", tmp_path)

    work = layout.work_dir.resolve()
    snap = layout.snapshot_dir.resolve()

    # The exact refusal the gate encodes: snapshot_root must not equal the scope, and the
    # scope must not be an ancestor of it (`gate.py:303-315`).
    assert snap != work
    assert work not in snap.parents
    # Positively: they are siblings under the same per-instance dir.
    assert snap.parent == work.parent


def test_layout_paths_are_deterministic_for_an_instance_id(tmp_path: Path) -> None:
    first = workspace.layout_for("astropy__astropy-7008", tmp_path)
    second = workspace.layout_for("astropy__astropy-7008", tmp_path)

    # A frozen dataclass compares by value: identical inputs -> identical layout.
    assert first == second
    # No clock, no randomness — the paths are a plain function of (instance_id, root).
    assert first.work_dir == tmp_path / "astropy__astropy-7008" / "workspace"
    assert first.trace_dir == tmp_path / "astropy__astropy-7008" / "traces"
    assert first.snapshot_dir == tmp_path / "astropy__astropy-7008" / "snapshots"


def test_prepare_invokes_git_with_the_base_commit(tmp_path: Path) -> None:
    record = _record(base_commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    runner = _FakeRunner()

    layout = workspace.prepare_workspace(
        record,
        root=tmp_path / "root",
        clones_dir=tmp_path / "clones",
        runner=runner,
    )

    assert isinstance(layout, workspace.WorkspaceLayout)
    # The base_commit must appear in some git invocation — that is what pins the checkout.
    flat = [token for call in runner.calls for token in call]
    assert record.base_commit in flat
    # And it is git that was invoked, not npx or a shell.
    assert all(call[0] == "git" for call in runner.calls)
    assert layout.work_dir.is_dir()


def test_prepare_is_offline_in_tests(tmp_path: Path) -> None:
    # The default runner is the real subprocess.run — but this suite never calls it.
    default = inspect.signature(workspace.prepare_workspace).parameters["runner"].default
    assert default is subprocess.run

    runner = _FakeRunner()
    workspace.prepare_workspace(
        _record(),
        root=tmp_path / "root",
        clones_dir=tmp_path / "clones",
        runner=runner,
    )
    # Every acquisition went through the injected fake — proof nothing shelled out.
    assert runner.calls, "prepare_workspace must route acquisition through the runner"


def test_prepare_reuses_a_cached_bare_clone_across_instances(tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    runner = _FakeRunner()

    workspace.prepare_workspace(
        _record(instance_id="django__django-1"),
        root=tmp_path / "root",
        clones_dir=clones,
        runner=runner,
    )
    workspace.prepare_workspace(
        _record(instance_id="django__django-2"),
        root=tmp_path / "root",
        clones_dir=clones,
        runner=runner,
    )

    # The bare clone for django/django is created once, then reused: exactly one `clone`.
    clone_calls = [c for c in runner.calls if "clone" in c]
    assert len(clone_calls) == 1
    worktree_calls = [c for c in runner.calls if "worktree" in c and "add" in c]
    assert len(worktree_calls) == 2


def test_prepare_surfaces_a_git_failure_as_a_named_error(tmp_path: Path) -> None:
    # A bad base_commit makes `git worktree add` exit non-zero; that must surface as a
    # named error, not a silent partial workspace.
    runner = _FakeRunner(fail_on="worktree", raise_failure=True)

    with pytest.raises(workspace.WorkspacePrepError) as excinfo:
        workspace.prepare_workspace(
            _record(base_commit="badc0ffee"),
            root=tmp_path / "root",
            clones_dir=tmp_path / "clones",
            runner=runner,
        )

    message = str(excinfo.value)
    assert "django__django-12345" in message
    assert "badc0ffee" in message


def test_prepare_surfaces_a_returned_failure_as_a_named_error(tmp_path: Path) -> None:
    # Some runners report failure by returning a non-zero CompletedProcess rather than
    # raising; that must be a named error too, never treated as success.
    runner = _FakeRunner(fail_on="worktree", raise_failure=False)

    with pytest.raises(workspace.WorkspacePrepError):
        workspace.prepare_workspace(
            _record(),
            root=tmp_path / "root",
            clones_dir=tmp_path / "clones",
            runner=runner,
        )
