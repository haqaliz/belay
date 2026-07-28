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

The same rule governs the clone retry: `sleep` is an injected seam and every backoff
assertion is on the recorded **sequence of requested delays**. No test here sleeps, and
none measures elapsed wall time — a timing-based assertion would be both slow and flaky,
and it would not actually pin the backoff schedule.
"""

from __future__ import annotations

import inspect
import subprocess
import time
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


class _FlakyCloneRunner(_FakeRunner):
    """Fails the bare clone its first `failures` times, then behaves like `_FakeRunner`.

    Models the Stage-2 attrition case verbatim: `django__django-15400` exited 128 at
    `git clone --bare` and *"the same clone succeeded on retry"*
    (`docs/planning/phase0-mint-execution/mint-execution/STAGE2_FINDINGS.md:44-52`).
    Only the clone is made flaky — every other git shape is inherited unchanged, so a
    test that sees a repeated `worktree add` is seeing the code retry it, not the fake.
    """

    def __init__(self, *, failures: int, raise_failure: bool = True) -> None:
        super().__init__()
        self._remaining_failures = failures
        self._raise_clone_failure = raise_failure

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        if "clone" in argv and self._remaining_failures > 0:
            self._remaining_failures -= 1
            self.calls.append(argv)
            if self._raise_clone_failure:
                raise subprocess.CalledProcessError(returncode=128, cmd=argv)
            return subprocess.CompletedProcess(argv, returncode=128, stdout="", stderr="boom")
        return super().__call__(argv, **kwargs)


class _RecordingSleep:
    """A `time.sleep` stand-in that records each requested delay and returns at once.

    Every backoff assertion in this file reads `.delays`. Nothing here ever blocks, so
    the retry tests cost no wall time and assert the *schedule* rather than its effect.
    """

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _clone_calls(runner: _FakeRunner) -> list[list[str]]:
    return [call for call in runner.calls if "clone" in call]


def _worktree_calls(runner: _FakeRunner) -> list[list[str]]:
    return [call for call in runner.calls if "worktree" in call and "add" in call]


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


def test_prepare_resolves_relative_paths_before_invoking_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A RELATIVE `--root` must not put the worktree inside the bare clone.

    Found by running the live Stage-1 mint with `--root eval/mint/stage1-remint`:
    `git -C <bare_clone> worktree add --detach <relative work_dir>` resolves the target
    **against `-C`**, not against the process CWD, so the tree landed at
    `eval/clones/pallets__flask.git/eval/mint/stage1-remint/.../workspace`, the intended
    `work_dir` never existed, the filesystem server was handed a nonexistent
    `allowed_dir` and exited — surfacing as the misleading "server's stdout closed
    before a matching reply arrived". The paths git is given must be ABSOLUTE.
    """
    monkeypatch.chdir(tmp_path)
    runner = _FakeRunner()

    layout = workspace.prepare_workspace(
        _record(),
        root=Path("mint/stage1"),
        clones_dir=Path("clones"),
        runner=runner,
    )

    clone_call = next(c for c in runner.calls if "clone" in c)
    worktree_call = next(c for c in runner.calls if "worktree" in c and "add" in c)

    # The load-bearing assertion: every path in git's argv is absolute, so `-C` cannot
    # reinterpret it.
    assert Path(clone_call[-1]).is_absolute()
    assert Path(worktree_call[-2]).is_absolute()
    assert Path(worktree_call[worktree_call.index("-C") + 1]).is_absolute()

    # And it is the intended location, not one nested under the bare clone.
    expected = tmp_path / "mint" / "stage1" / "django__django-12345" / "workspace"
    assert Path(worktree_call[-2]) == expected
    assert layout.work_dir == expected
    assert layout.work_dir.is_dir()

    # The layout the gate is handed carries absolute paths throughout.
    assert layout.trace_dir.is_absolute()
    assert layout.snapshot_dir.is_absolute()
    assert layout.trace_dir.is_dir()
    assert layout.snapshot_dir.is_dir()


def test_layout_for_is_absolute_even_from_a_relative_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`WorkspaceLayout` always carries absolute paths — every caller, not just the CLI.

    These paths become `BELAY_SANDBOX_SCOPE`/`BELAY_TRACE_DIR`/`BELAY_SNAPSHOT_DIR` and
    a server's `allowed_dir` argv: a relative path handed to a child process with a
    different CWD is a silent mis-target.
    """
    monkeypatch.chdir(tmp_path)

    layout = workspace.layout_for("astropy__astropy-7008", Path("mint/stage1"))

    assert layout.work_dir == tmp_path / "mint" / "stage1" / "astropy__astropy-7008" / "workspace"
    assert layout.trace_dir.is_absolute()
    assert layout.snapshot_dir.is_absolute()


def test_prepare_refuses_a_workspace_git_did_not_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero-exit git that left no `work_dir` is a named error, not a doomed server.

    This is the guard that would have named the bug above at its source: the alternative
    is spawning the filesystem server on a nonexistent `allowed_dir` and reading its
    immediate exit as "server's stdout closed".
    """

    class _LyingRunner(_FakeRunner):
        def __call__(self, argv, **kwargs):
            argv = list(argv)
            self.calls.append(argv)
            if "clone" in argv:
                Path(argv[-1]).mkdir(parents=True, exist_ok=True)
            # `worktree add` reports success but creates nothing.
            return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.chdir(tmp_path)

    with pytest.raises(workspace.WorkspacePrepError) as excinfo:
        workspace.prepare_workspace(
            _record(),
            root=Path("mint/stage1"),
            clones_dir=Path("clones"),
            runner=_LyingRunner(),
        )

    message = str(excinfo.value)
    assert "django__django-12345" in message
    assert "workspace" in message


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


def test_a_transient_clone_failure_is_retried_and_succeeds(tmp_path: Path) -> None:
    """The Stage-2 attrition case: one flaky clone must cost a retry, not the instance.

    `django__django-15400` exited 128 at `git clone --bare` with 362 GB free and GitHub
    reachable throughout, and the identical clone succeeded when re-run by hand
    (`STAGE2_FINDINGS.md:44-52`). Without this the instance is recorded `failed` — an
    observation that never happened — and the denominator quietly shrinks by one.
    """
    runner = _FlakyCloneRunner(failures=1)
    sleep = _RecordingSleep()

    layout = workspace.prepare_workspace(
        _record(),
        root=tmp_path / "root",
        clones_dir=tmp_path / "clones",
        runner=runner,
        sleep=sleep,
    )

    # The clone really was re-issued, and the workspace really was prepared.
    assert len(_clone_calls(runner)) == 2
    assert len(_worktree_calls(runner)) == 1
    assert layout.work_dir.is_dir()
    # One retry, one backoff — asserted on the requested delay, never on elapsed time.
    assert sleep.delays == [workspace.CLONE_RETRY_BASE_DELAY_SECONDS]


def test_a_returned_nonzero_clone_is_retried_too(tmp_path: Path) -> None:
    # A runner that reports failure by *returning* non-zero (rather than raising) is the
    # other half of `_run`'s two failure conventions; the retry must cover both, or the
    # convention a caller happens to use decides whether the mint is resilient.
    runner = _FlakyCloneRunner(failures=1, raise_failure=False)
    sleep = _RecordingSleep()

    layout = workspace.prepare_workspace(
        _record(),
        root=tmp_path / "root",
        clones_dir=tmp_path / "clones",
        runner=runner,
        sleep=sleep,
    )

    assert len(_clone_calls(runner)) == 2
    assert layout.work_dir.is_dir()
    assert sleep.delays == [workspace.CLONE_RETRY_BASE_DELAY_SECONDS]


def test_a_persistent_clone_failure_still_raises_the_same_named_error(tmp_path: Path) -> None:
    """Retrying must not change what a *real* clone failure looks like to the caller.

    `run_mint` records the instance `failed` with `str(exc)`; if the retry reworded or
    re-wrapped the message, the batch's containment path would start reporting something
    other than the git invocation that actually failed. The message is compared against
    the un-retried spelling byte-for-byte rather than pattern-matched.
    """
    retried = _FlakyCloneRunner(failures=99)
    once = _FlakyCloneRunner(failures=99)
    sleep = _RecordingSleep()

    # Identical `root`/`clones_dir` for both: the message embeds the clone's destination,
    # so anything else would make this a comparison of paths rather than of wording. A
    # failing clone creates nothing, so the second call is not served from a cache.
    root = tmp_path / "root"
    clones = tmp_path / "clones"

    with pytest.raises(workspace.WorkspacePrepError) as retried_exc:
        workspace.prepare_workspace(
            _record(),
            root=root,
            clones_dir=clones,
            runner=retried,
            clone_attempts=3,
            sleep=sleep,
        )
    with pytest.raises(workspace.WorkspacePrepError) as once_exc:
        workspace.prepare_workspace(
            _record(),
            root=root,
            clones_dir=clones,
            runner=once,
            clone_attempts=1,
            sleep=sleep,
        )

    assert str(retried_exc.value) == str(once_exc.value)
    assert "django__django-12345" in str(retried_exc.value)
    assert "cloning the bare repo" in str(retried_exc.value)
    # Every attempt was spent, and the backoff doubled between them.
    assert len(_clone_calls(retried)) == 3
    assert sleep.delays == [
        workspace.CLONE_RETRY_BASE_DELAY_SECONDS,
        workspace.CLONE_RETRY_BASE_DELAY_SECONDS * 2,
    ]
    # A persistent failure never reaches the worktree step.
    assert _worktree_calls(retried) == []


def test_worktree_add_is_never_retried(tmp_path: Path) -> None:
    """`git worktree add` is local and deterministic — retrying it would hide a bug.

    The retry exists for ONE observed failure mode: a network-bound `git clone --bare`
    (`STAGE2_FINDINGS.md:44-52`). `worktree add` touches no network; it fails on a bad
    `base_commit`, a dirty target dir, or a corrupt clone — conditions the identical
    second invocation reproduces exactly. Retrying it would spend attempts to arrive at
    the same error, and, worse, would make a genuine data bug look intermittent.
    """
    runner = _FakeRunner(fail_on="worktree", raise_failure=True)
    sleep = _RecordingSleep()

    with pytest.raises(workspace.WorkspacePrepError):
        workspace.prepare_workspace(
            _record(base_commit="badc0ffee"),
            root=tmp_path / "root",
            clones_dir=tmp_path / "clones",
            runner=runner,
            clone_attempts=5,
            sleep=sleep,
        )

    # Exactly one attempt, despite `clone_attempts=5` — and no backoff was ever waited.
    assert len(_worktree_calls(runner)) == 1
    assert sleep.delays == []


def test_a_cached_bare_clone_skips_the_clone_and_never_sleeps(tmp_path: Path) -> None:
    # Stage 3 pre-caches all seven bare clones, so it performs no clone at all
    # (`STAGE2_FINDINGS.md:50-52`). The retry must be inert on that path: no clone call,
    # and above all no backoff — a sleep here would tax the common case for nothing.
    clones = tmp_path / "clones"
    (clones / "django__django.git").mkdir(parents=True)
    runner = _FakeRunner(fail_on="clone", raise_failure=True)
    sleep = _RecordingSleep()

    layout = workspace.prepare_workspace(
        _record(),
        root=tmp_path / "root",
        clones_dir=clones,
        runner=runner,
        sleep=sleep,
    )

    assert _clone_calls(runner) == []
    assert len(_worktree_calls(runner)) == 1
    assert layout.work_dir.is_dir()
    assert sleep.delays == []


def test_clone_attempts_of_one_disables_the_retry(tmp_path: Path) -> None:
    # The escape hatch: an operator who wants a cold clone failure to surface immediately
    # (a wrong repo name, say) gets exactly one attempt and no wait.
    runner = _FlakyCloneRunner(failures=1)
    sleep = _RecordingSleep()

    with pytest.raises(workspace.WorkspacePrepError):
        workspace.prepare_workspace(
            _record(),
            root=tmp_path / "root",
            clones_dir=tmp_path / "clones",
            runner=runner,
            clone_attempts=1,
            sleep=sleep,
        )

    assert len(_clone_calls(runner)) == 1
    assert sleep.delays == []


def test_clone_attempts_below_one_is_refused(tmp_path: Path) -> None:
    # A zero/negative budget would fall out of the attempt loop having run NO clone, and
    # the failure would surface much later as "git reported success but no workspace
    # exists" — a misleading message for a caller-side mistake. Refuse it at the door.
    with pytest.raises(ValueError):
        workspace.prepare_workspace(
            _record(),
            root=tmp_path / "root",
            clones_dir=tmp_path / "clones",
            runner=_FakeRunner(),
            clone_attempts=0,
        )


def test_retry_defaults_are_one_retry_and_the_real_sleep(tmp_path: Path) -> None:
    # The default is a single retry — enough for the observed one-off, few enough that a
    # genuinely unreachable host is not waited on repeatedly for every instance in the
    # batch. And the default sleep is the real one; this suite never calls it.
    parameters = inspect.signature(workspace.prepare_workspace).parameters
    assert parameters["clone_attempts"].default == 2
    assert parameters["sleep"].default is time.sleep
