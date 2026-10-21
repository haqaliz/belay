"""The release pipeline may never publish an artifact nothing measured.

PyPI is safe by construction: `release.yml` builds the wheel, checks the tag against
`pyproject.toml`'s version, and uploads *that* artifact. The container channel is the
one with a real footgun — `docker build` followed by `docker push` with nothing in
between ships a stranger an image no test ever ran inside — and `RELEASING.md`
pre-registered the rule against it before the job existed:

    "when it lands, add a `ghcr` job here and to `release.yml`, and it should push the
    SAME image the `docker` job already validated rather than rebuilding an unvalidated
    one."

Shipping something unverified is the exact failure this project exists to catch. It does
not get an exception inside our own release pipeline, and "we'll remember" is not a
control — this module is.

**Structural, not textual.** The workflow is parsed as YAML and the assertions are about
step ORDER, scope, and the reference that is pushed. A regex over the file would pass on a
workflow whose steps had been reordered, which is precisely the defect worth catching.

No network, no Docker, no subprocess: this reads a file in the repo. It runs everywhere,
including on a machine that could never build the image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RELEASE_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release.yml"

#: The registry and image the channel publishes. Written out rather than derived, so
#: that moving the package silently is impossible: this test has to be edited too.
_IMAGE = "ghcr.io/${{ github.repository_owner }}/belay"

#: The two references every release must publish: the version, which is the honest one
#: to pin, and `latest`, which is the one a reader types first.
_PUBLISHED_SUFFIXES = ("${{ github.ref_name }}", "latest")

#: What makes a step the MEASUREMENT: it runs the same pytest modules the `docker` CI
#: job runs against the image. Named by their filenames, because the assertion is that
#: the real measurement runs — not that some step is called "test".
_MEASUREMENT_MODULES = (
    "tests/test_docker_image.py",
    "tests/test_docker_inimage.py",
)


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(_RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{_RELEASE_WORKFLOW} did not parse as a mapping"
    return loaded


def _jobs() -> dict[str, Any]:
    jobs = _workflow().get("jobs")
    assert isinstance(jobs, dict) and jobs, "release.yml declares no jobs"
    return jobs


def _ghcr_job() -> dict[str, Any]:
    jobs = _jobs()
    job = jobs.get("ghcr")
    assert job is not None, (
        "release.yml has no `ghcr` job — the container channel is what this module "
        f"guards. Jobs present: {sorted(jobs)}"
    )
    return job


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, "the ghcr job declares no steps"
    return steps


def _run_text(step: dict[str, Any]) -> str:
    run = step.get("run")
    return run if isinstance(run, str) else ""


def _env_of(scope: dict[str, Any]) -> dict[str, str]:
    """A job's or a step's `env` mapping, as strings. Absent reads as empty."""
    env = scope.get("env")
    if not isinstance(env, dict):
        return {}
    return {str(k): str(v) for k, v in env.items()}


def _resolve(text: str, env: dict[str, str]) -> str:
    """Expand `$NAME` / `${NAME}` from `env`, so a reference declared once in `env` and
    used as a variable reads the same to this module as one written out inline.

    Assertions are about the reference the job PUBLISHES, never about where the author
    chose to write it down. Declaring it once in `env` is better practice than repeating
    it, and a guard that forced the repetition would be pushing for worse code.
    """
    for name, value in env.items():
        text = text.replace(f"${{{name}}}", value).replace(f"${name}", value)
    return text


def _index_of(steps: list[dict[str, Any]], needle: str) -> int:
    """The index of the one step whose `run` contains `needle`; -1 if there is none."""
    hits = [i for i, step in enumerate(steps) if needle in _run_text(step)]
    assert len(hits) <= 1, f"{needle!r} appears in {len(hits)} steps; expected at most 1"
    return hits[0] if hits else -1


# --- anti-vacuity: this module must be reading a real workflow ----------------------


def test_the_release_workflow_parses_and_declares_its_channels() -> None:
    """Without this, every assertion below could pass against an empty file."""
    assert _RELEASE_WORKFLOW.is_file(), _RELEASE_WORKFLOW
    jobs = _jobs()
    for channel in ("build", "pypi", "github-release", "ghcr"):
        assert channel in jobs, f"release.yml lost its {channel!r} job: {sorted(jobs)}"


def test_the_workflow_publishes_only_on_a_version_tag() -> None:
    """A push to a branch must never publish anything. `latest` depends on this.

    PyYAML parses the unquoted key `on:` as the boolean True (the "Norway problem"),
    so it is looked up both ways rather than assumed.
    """
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), f"unreadable trigger block: {triggers!r}"
    assert set(triggers) == {"push"}, triggers
    assert triggers["push"] == {"tags": ["v*"]}, triggers["push"]


# --- the rule: measured, then pushed ------------------------------------------------


def test_the_image_is_measured_before_it_is_pushed_in_the_same_job() -> None:
    """The whole point. Build → measure → push, one job, in that order.

    Same job, because a separate validating job would have to rebuild the image, and a
    rebuild is a different image: what was measured and what is pushed would be two
    artifacts with one name. Same order, because a push that precedes its measurement
    has already shipped by the time anything objects.
    """
    steps = _steps(_ghcr_job())

    build = _index_of(steps, "docker build")
    push = _index_of(steps, "docker push")
    assert build != -1, "the ghcr job never builds the image it publishes"
    assert push != -1, "the ghcr job never pushes — then it is not a publish job"

    measurements = [
        _index_of(steps, module) for module in _MEASUREMENT_MODULES
    ]
    assert all(i != -1 for i in measurements), (
        "the ghcr job does not run the in-image acceptance "
        f"({', '.join(_MEASUREMENT_MODULES)}) — it would push an image nothing "
        "measured, which is the one thing this job may never do"
    )
    measure = min(measurements)

    assert build < measure, "the image is measured before it is built"
    assert measure < push, (
        "the push step comes BEFORE the measurement, so a failing measurement cannot "
        "stop the publish — the artifact is already out"
    )


def test_the_measured_image_and_the_pushed_image_are_proved_identical() -> None:
    """Ordering alone would still allow measuring one tag and pushing another.

    The job asserts the two image IDs are equal at run time; this asserts that the job
    still does. `docker image inspect ... .Id` is the only thing that can tell two tags
    that point at different builds apart.
    """
    steps = _steps(_ghcr_job())
    inspects = [s for s in steps if "docker image inspect" in _run_text(s)]
    assert inspects, (
        "nothing in the ghcr job compares the measured image's ID with the pushed "
        "one, so the two tags could name different builds"
    )
    assert any(".Id" in _run_text(step) for step in inspects), inspects


def test_the_measurement_runs_against_the_image_that_will_be_pushed() -> None:
    """`BELAY_TEST_IMAGE` makes the suite ADOPT the built image instead of building
    its own copy — and it must name the tag the build produced, not some other one.

    Without it the fixture builds a second image and deletes it on the way out, so the
    job would be measuring an artifact that no longer exists by the time it pushes.
    With it, but pointed elsewhere, the job would measure the wrong image and never
    notice. Both are the same defect wearing different clothes.
    """
    job = _ghcr_job()
    steps = _steps(job)
    job_env = _env_of(job)

    measure = [
        step
        for step in steps
        if any(module in _run_text(step) for module in _MEASUREMENT_MODULES)
    ]
    assert measure, "no measurement step to check"

    built = _resolve(_run_text(steps[_index_of(steps, "docker build")]), job_env)
    for step in measure:
        adopted = _env_of(step).get("BELAY_TEST_IMAGE")
        assert adopted, (
            "the measurement step does not set BELAY_TEST_IMAGE, so the suite builds "
            "and then DELETES its own copy — the image the job pushes would be "
            "unmeasured"
        )
        assert adopted in built, (
            f"the measurement adopts {adopted!r}, which the build step never produced: "
            f"{built!r}"
        )


# --- scope and reference ------------------------------------------------------------


def test_the_ghcr_job_asks_for_package_scope_and_nothing_wider() -> None:
    """A publish job with `contents: write` could rewrite the repo it publishes from.

    The workflow's top-level default is read-only and each job requests exactly what it
    needs; this holds the newest job to that.
    """
    job = _ghcr_job()
    permissions = job.get("permissions")
    assert permissions == {"packages": "write"}, (
        f"the ghcr job's permissions are {permissions!r}; it needs `packages: write` "
        "and nothing else"
    )


@pytest.mark.parametrize("suffix", _PUBLISHED_SUFFIXES)
def test_both_published_references_are_pushed(suffix: str) -> None:
    """The version tag is the honest reference; `latest` is the one readers type.

    Both are asserted because a job that pushed only `latest` would leave no way to pin,
    and one that pushed only the version would leave the README's `docker pull` broken.
    The reference is resolved through the job's `env` first, so declaring the image once
    and reusing it — which is the better way to write it — reads the same here.
    """
    job = _ghcr_job()
    pushes = [
        _resolve(_run_text(step), _env_of(job))
        for step in _steps(job)
        if "docker push" in _run_text(step)
    ]
    assert pushes, "the ghcr job pushes nothing"
    assert any(f"{_IMAGE}:{suffix}" in push for push in pushes), (
        f"no `docker push` of {_IMAGE}:{suffix}; the job pushes: {pushes!r}"
    )


def test_the_version_reference_comes_from_the_tag_not_a_hand_written_string() -> None:
    """A hardcoded version would publish the wrong image the moment it went stale."""
    job = _ghcr_job()
    body = "\n".join(_run_text(step) for step in _steps(job))
    assert "${{ github.ref_name }}" in body + "\n".join(_env_of(job).values())


def test_the_channel_is_independent_of_the_other_channels() -> None:
    """`release.yml`'s jobs are parallel so one failing channel does not block the rest.

    A `needs:` on the wheel build would make a PyPI hiccup withhold the image, and vice
    versa. The image is built from the tagged checkout and needs no artifact from them.
    """
    assert "needs" not in _ghcr_job(), (
        "the ghcr job declares `needs`, coupling the container channel to another "
        "channel's success; release.yml's channels are deliberately independent"
    )
