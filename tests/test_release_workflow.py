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

**Both arches, one measurement each.** `linux/amd64` and `linux/arm64` are built and
measured separately, then published as `:<tag>-<arch>` and assembled into `:<tag>` and
`:latest`. The rule survives the split: each arch tag is proved to be the image its own
measurement adopted. The platform knob the arm64 measurement needs is a pure argv
builder, asserted here rather than behind Docker.

No network, no Docker, no subprocess: this reads a file in the repo and calls one pure
function. It runs everywhere, including on a machine that could never build the image.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import docker_run_argv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RELEASE_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release.yml"

#: The registry and image the channel publishes. Written out rather than derived, so
#: that moving the package silently is impossible: this test has to be edited too.
_IMAGE = "ghcr.io/${{ github.repository_owner }}/belay"

#: The two references every release must publish: the version, which is the honest one
#: to pin, and `latest`, which is the one a reader types first. Assembled by
#: `imagetools create` from the per-arch tags, never pushed as a single image.
_PUBLISHED_SUFFIXES = ("${{ github.ref_name }}", "latest")

#: The architectures the channel publishes, in the order the manifest names them. The
#: suffix is what each measured image is tagged with before the manifest is assembled.
_ARCHES = ("amd64", "arm64")

#: What makes a step the MEASUREMENT: it runs the same pytest modules the `docker` CI
#: job runs against the image. Named by their filenames, because the assertion is that
#: the real measurement runs — not that some step is called "test".
_MEASUREMENT_MODULES = (
    "tests/test_docker_image.py",
    "tests/test_docker_inimage.py",
)

#: The arm64 measurement runs the in-image acceptance only: a compose stack under QEMU
#: is a different substrate claim, and the README says so.
_ARM64_EXCLUDED_MODULE = "tests/test_docker_compose.py"


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


def _indexes_of(steps: list[dict[str, Any]], needle: str) -> list[int]:
    """Every step whose `run` contains `needle`. Two builds share the `docker build`
    prefix, so the singular form this module used to have is gone."""
    return [i for i, step in enumerate(steps) if needle in _run_text(step)]


def _tokens(text: str) -> list[str]:
    """A `run` block's words, quotes stripped. Only safe for values with no spaces —
    use `_mentions` / `_flag_values` for anything containing a `${{ ... }}` expression.
    """
    return [token.strip("'\"") for token in text.split()]


def _mentions(text: str, ref: str) -> bool:
    """Whether `ref` appears in `text` as a WHOLE reference.

    Exact, not substring: `belay:test` is a prefix of `belay:test-arm64`, and a substring
    match on tag names would let an arm64 measurement adopt the amd64 build while still
    reading green here.
    """
    return re.search(re.escape(ref) + r"(?![\w./-])", text) is not None


def _flag_values(text: str, flag: str) -> list[str]:
    """Every value given to `flag`, quoted or bare. Quoting matters: an image reference
    contains `${{ ... }}`, whose spaces would split a naive token scan."""
    pattern = re.escape(flag) + r'\s+(?:"([^"]*)"|(\S+))'
    return [m.group(1) if m.group(1) is not None else m.group(2)
            for m in re.finditer(pattern, text)]


def _adopted(step: dict[str, Any]) -> str | None:
    """The image tag a measurement step adopts, or None when the step is not one."""
    return _env_of(step).get("BELAY_TEST_IMAGE")


def _measurement_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        step
        for step in steps
        if any(module in _run_text(step) for module in _MEASUREMENT_MODULES)
    ]


def _is_build(text: str) -> bool:
    """A `docker build` / `docker buildx build` — not `buildx imagetools`, which shares
    the prefix but only assembles a manifest."""
    return "docker build" in text and "imagetools" not in text


def _build_tags(steps: list[dict[str, Any]], env: dict[str, str]) -> list[str]:
    """The `-t` value of every image build, in step order.

    Matches both `docker build` and `docker buildx build`; they share the prefix but
    build different artifacts, so the tag is the only thing that tells them apart.
    """
    tags: list[str] = []
    for step in steps:
        text = _resolve(_run_text(step), env)
        if not _is_build(text):
            continue
        values = _flag_values(text, "-t")
        assert len(values) == 1, f"an image build with no single tag: {text!r}"
        tags.append(values[0])
    return tags


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


def test_every_image_is_measured_before_anything_is_pushed() -> None:
    """The whole point. Build → measure → push, one job, in that order, per arch.

    Same job, because a separate validating job would have to rebuild the image, and a
    rebuild is a different image: what was measured and what is pushed would be two
    artifacts with one name. Same order, because a push that precedes its measurement
    has already shipped by the time anything objects.

    Multi-arch does not relax this: the LAST measurement must still precede the FIRST
    push, so a failing arm64 run cannot leave the amd64 tag published.
    """
    steps = _steps(_ghcr_job())

    builds = [
        i for i, step in enumerate(steps) if _is_build(_run_text(step))
    ]
    pushes = _indexes_of(steps, "docker push")
    measures = [
        i
        for i, step in enumerate(steps)
        if any(module in _run_text(step) for module in _MEASUREMENT_MODULES)
    ]
    assert builds, "the ghcr job never builds the images it publishes"
    assert len(measures) == len(_ARCHES), (
        f"{len(measures)} measurement steps for {len(_ARCHES)} architectures — each "
        "arch must run the in-image acceptance or it ships unmeasured"
    )
    assert pushes, "the ghcr job never pushes — then it is not a publish job"

    assert min(builds) < min(measures), "the image is measured before it is built"
    assert max(measures) < min(pushes), (
        "a push step comes BEFORE a measurement, so a failing measurement cannot stop "
        "the publish — the artifact is already out"
    )


def test_the_measured_image_and_the_pushed_image_are_proved_identical() -> None:
    """Ordering alone would still allow measuring one tag and pushing another.

    The job asserts the two image IDs are equal at run time; this asserts that the job
    still does. `docker image inspect ... .Id` is the only thing that can tell two tags
    that point at different builds apart. With two arches it must do this for BOTH:
    two measured tags, two pushed arch tags, two comparisons.
    """
    job = _ghcr_job()
    steps = _steps(job)
    checks = [
        step
        for step in steps
        if "docker image inspect" in _run_text(step) and ".Id" in _run_text(step)
    ]
    assert checks, (
        "nothing in the ghcr job compares the measured image's ID with the pushed "
        "one, so the two tags could name different builds"
    )

    text = _resolve("\n".join(_run_text(step) for step in checks), _env_of(job))
    for arch in _ARCHES:
        assert _mentions(text, f"{_IMAGE}:${{{{ github.ref_name }}}}-{arch}"), (
            f"no per-arch ID check names {_IMAGE}:<tag>-{arch}; the manifest could "
            "include an image nothing measured"
        )
    for measured in ("belay:test", "belay:test-arm64"):
        assert _mentions(text, measured), (
            f"the ID check never inspects the measured tag {measured!r}"
        )
    assert ".Id" in text


def test_each_arch_is_built_once_and_its_measurement_adopts_that_build() -> None:
    """`BELAY_TEST_IMAGE` makes the suite ADOPT the built image instead of building
    its own copy — and it must name the tag that arch's build produced, not some other.

    Without it the fixture builds a second image and deletes it on the way out, so the
    job would be measuring an artifact that no longer exists by the time it pushes.
    With it, but pointed elsewhere, the job would measure the wrong image and never
    notice. Both are the same defect wearing different clothes.

    Tags are compared as whole words: `belay:test` is a prefix of `belay:test-arm64`,
    so a substring check would pass on the wrong pairing.
    """
    job = _ghcr_job()
    steps = _steps(job)
    env = _env_of(job)

    built = _build_tags(steps, env)
    assert len(built) == len(_ARCHES), (
        f"expected one image build per arch ({_ARCHES}), found {built!r} — a rebuild "
        "between measurement and push is a different image with one name"
    )
    assert len(set(built)) == len(built), f"two builds share a tag: {built!r}"

    measures = _measurement_steps(steps)
    assert len(measures) == len(_ARCHES), (
        f"{len(measures)} measurements for {len(_ARCHES)} built images: {built!r}"
    )
    adopted = [_adopted(step) for step in measures]
    for step, tag in zip(measures, adopted):
        assert tag, (
            "the measurement step does not set BELAY_TEST_IMAGE, so the suite builds "
            "and then DELETES its own copy — the image the job pushes would be "
            "unmeasured"
        )
        assert tag in built, (
            f"the measurement adopts {tag!r}, which no build produced: {built!r}"
        )
    assert set(adopted) == set(built), (
        f"each built image must be measured: built {built!r}, measured {adopted!r}"
    )


# --- multi-arch: platform setup, the arm64 build and its measurement ----------------


def test_qemu_and_buildx_are_set_up_before_the_arm64_build() -> None:
    """`buildx --platform linux/arm64` needs buildx, and running the arm64 image on an
    amd64 runner needs QEMU. Both must be set up first, or the build fails loudly
    (never silently pushes an unmeasured image)."""
    steps = _steps(_ghcr_job())

    def uses_index(action: str) -> int:
        hits = [
            i
            for i, step in enumerate(steps)
            if action in str(step.get("uses", ""))
        ]
        assert len(hits) == 1, f"{action} appears {len(hits)} times; expected once"
        return hits[0]

    arm_build = _indexes_of(steps, "buildx build")
    assert len(arm_build) == 1, (
        f"expected one cross-platform buildx build, found {len(arm_build)}"
    )
    assert uses_index("docker/setup-qemu-action") < arm_build[0]
    assert uses_index("docker/setup-buildx-action") < arm_build[0]


def test_arm64_is_built_for_arm64_and_loaded_into_the_daemon() -> None:
    """`--load` is what makes the image the daemon runs the image that was built. With
    `--push` here the push would precede the measurement — the failure this job exists
    to prevent."""
    job = _ghcr_job()
    steps = _steps(job)
    arm = [step for step in steps if "buildx build" in _run_text(step)]
    assert len(arm) == 1, f"expected one arm64 build, found {len(arm)}"
    text = _resolve(_run_text(arm[0]), _env_of(job))
    tokens = _tokens(text)

    assert _flag_values(text, "--platform") == ["linux/arm64"], (
        f"the arm64 build names no platform: {text!r}"
    )
    assert "--load" in tokens, (
        "without --load the built image is not in the daemon, so the measurement "
        "cannot adopt it"
    )
    assert "--push" not in tokens, (
        "the arm64 build pushes before its measurement — the artifact is out before "
        "anything objects"
    )
    assert _flag_values(text, "-t") == ["belay:test-arm64"], text


def test_the_arm64_measurement_asks_for_arm64_and_the_in_image_acceptance() -> None:
    """The measurement runs the same in-image acceptance against the arm64 image, under
    QEMU, by asking the runner for that platform. Compose is excluded: a compose stack
    under QEMU is a different substrate claim, and README says it stays amd64-only."""
    steps = _steps(_ghcr_job())
    cross = [
        step for step in _measurement_steps(steps)
        if _env_of(step).get("BELAY_TEST_PLATFORM")
    ]
    assert len(cross) == 1, f"expected one cross-platform measurement, found {len(cross)}"

    step = cross[0]
    assert _env_of(step)["BELAY_TEST_PLATFORM"] == "linux/arm64", _env_of(step)
    run = _run_text(step)
    assert "tests/test_docker_inimage.py" in run, (
        "the arm64 measurement does not run the in-image acceptance"
    )
    assert _ARM64_EXCLUDED_MODULE not in run, (
        "the arm64 measurement runs the compose acceptance, which is documented as "
        "amd64-only — delete the exclusion deliberately if that claim changes"
    )


def test_the_amd64_measurement_is_the_unchanged_one() -> None:
    """amd64 is what shipped before this slice; its measurement must not shrink or move
    to another platform as a side effect of adding arm64."""
    steps = _steps(_ghcr_job())
    native = [
        step for step in _measurement_steps(steps)
        if not _env_of(step).get("BELAY_TEST_PLATFORM")
    ]
    assert len(native) == 1, f"expected one native measurement, found {len(native)}"
    run = _run_text(native[0])
    for module in (*_MEASUREMENT_MODULES, _ARM64_EXCLUDED_MODULE):
        assert module in run, (
            f"the amd64 measurement no longer runs {module}: {run!r}"
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


@pytest.mark.parametrize("arch", _ARCHES)
def test_each_arch_tag_is_pushed_as_one_image(arch: str) -> None:
    """Each measured image is pushed under its own arch tag; the manifest is assembled
    from those tags afterwards. A `docker push` of the bare version or `latest` would
    publish a single-arch image under the multi-arch name."""
    job = _ghcr_job()
    pushes = "\n".join(
        _resolve(_run_text(step), _env_of(job))
        for step in _steps(job)
        if "docker push" in _run_text(step)
    )

    assert pushes, "the ghcr job pushes nothing"
    arch_ref = f"{_IMAGE}:${{{{ github.ref_name }}}}-{arch}"
    assert _mentions(pushes, arch_ref), (
        f"no `docker push` of {arch_ref}; the job pushes: {pushes!r}"
    )
    for suffix in _PUBLISHED_SUFFIXES:
        assert not _mentions(pushes, f"{_IMAGE}:{suffix}"), (
            f"a single image is pushed as {_IMAGE}:{suffix}; those references must be "
            "manifests assembled from both arch tags"
        )


def test_the_published_references_are_assembled_from_both_arch_tags() -> None:
    """The version tag is the honest reference; `latest` is the one readers type.

    Both are `imagetools create` manifests naming BOTH measured arch tags, created after
    the per-arch pushes (there is nothing to assemble before they exist).
    """
    job = _ghcr_job()
    steps = _steps(job)
    manifests = [i for i, step in enumerate(steps) if "imagetools create" in _run_text(step)]
    assert len(manifests) == 1, f"expected one manifest assembly, found {len(manifests)}"

    text = _resolve(_run_text(steps[manifests[0]]), _env_of(job))
    targets = _flag_values(text, "-t")
    for suffix in _PUBLISHED_SUFFIXES:
        assert f"{_IMAGE}:{suffix}" in targets, (
            f"the manifest does not publish {_IMAGE}:{suffix}; targets: {targets!r}"
        )
    for arch in _ARCHES:
        assert _mentions(text, f"{_IMAGE}:${{{{ github.ref_name }}}}-{arch}"), (
            f"the manifest does not include the {arch} tag: {text!r}"
        )

    pushes = _indexes_of(steps, "docker push")
    assert pushes and max(pushes) < manifests[0], (
        "the manifest is assembled before the arch tags are pushed"
    )


def test_signing_and_the_docker_hub_mirror_stay_deferred_by_name() -> None:
    """PRD non-goals: cosign/attestations and a Docker Hub mirror are NOT this slice.

    Asserted on the steps' executable surface (`uses` + `run`), not on prose, so the
    job may keep naming the deferral in a comment without tripping this.
    """
    body = "\n".join(
        str(step.get("uses", "")) + "\n" + _run_text(step)
        for step in _steps(_ghcr_job())
    ).lower()
    for deferred in ("cosign", "attest", "docker.io", "dockerhub"):
        assert deferred not in body, (
            f"{deferred!r} appears in the ghcr job; it was deferred by name at "
            "ghcr-publish and is still out of scope"
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


# --- the platform knob the arm64 measurement runs on --------------------------------


def test_the_platform_knob_adds_one_flag_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`BELAY_TEST_PLATFORM` is how the arm64 measurement asks the daemon for the arm64
    image. Unset — every local run and the amd64 job — the argv must be byte-identical
    to the single-arch run it replaced; set, it gains exactly `--platform <value>` in
    the position `docker run` expects it."""
    monkeypatch.delenv("BELAY_TEST_PLATFORM", raising=False)
    native = docker_run_argv("belay:test", "echo hi", ["-v", "/x:/y:ro"])
    assert native == [
        "docker",
        "run",
        "--rm",
        "-v",
        "/x:/y:ro",
        "--entrypoint",
        "sh",
        "belay:test",
        "-c",
        "echo hi",
    ]

    monkeypatch.setenv("BELAY_TEST_PLATFORM", "linux/arm64")
    cross = docker_run_argv("belay:test-arm64", "echo hi", ["-v", "/x:/y:ro"])
    assert cross == [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/arm64",
        "-v",
        "/x:/y:ro",
        "--entrypoint",
        "sh",
        "belay:test-arm64",
        "-c",
        "echo hi",
    ]
