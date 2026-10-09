"""The claim-author live probe — owner-run ONLY, never CI, one trace per invocation.

The assertion layer on `docs/planning/claim-author-live-probe/` (spec.md,
plan_20261010.md). It drives the SAME seam the frozen run uses (`probe/run-probe.sh`,
the owner's one-shot) but as a test: given ONE cm6 trace via `BELAY_PROBE_TRACE`, it
runs `belay verify <trace> --manifest-dir <stem>.manifests --claim-author <wrapper>
--json --server node <fs-server> '{workspace}'` as a subprocess, and asserts the two
load-bearing facts the probe exists to record:

1. **The A3 axis ENGAGED.** `--claim-author` points at the recording wrapper
   (`probe/claim_author_wrapper.sh`), which appends one byte to
   `probe/probe-marker` per invocation and then runs the shipped
   `belay.verify.reference_claim_author` module. "The author ran" is therefore an
   OBSERVED fact on disk — never an inference from an absent JSON key (which is
   ambiguous between "the axis never ran" and "the check exited 0", D3 silence;
   `a3-author/live-run.md:60-89`). A document whose author never engaged is a
   FAILED probe, asserted with the reasons below.
2. **The document's author record is one of the three allowed shapes** (spec.md
   AC 3): an abstention `NO_CHECK_AUTHOR` with a `sub_cause` from the closed
   vocabulary and a bounded one-line detail; D3 `claim_silence` with
   `check.exit_code == 0`; or an A3 WARN/FAIL verdict. A document with a
   configured author and NO author record is the defect this probe exists to
   catch — asserted with its name.

R-D context: run 3's two `NO_CHECK_AUTHOR` abstentions never recorded why, and
the candidate cause is structural — the engine's 60 s subprocess bound against
the reference author's own 600 s bound (`claim-axis-legibility/prd.md:193-200`).
Whatever this probe observes is a result: the sub-cause, the silence, or a
verdict — committed verbatim next, whatever it says.

This is an OWNER CHECKPOINT, never CI: it spends the owner's subscription via the
BYOK reference author. It is `manual`-marked and excluded by the default addopts
(`pyproject.toml:94`), and it FAILS with instructions unless
`BELAY_REFERENCE_AUTHOR_MODEL` names a full model id and `BELAY_PROBE_TRACE`
names a real trace — a skip would be the wrong shape, exactly as the precedent
argues: the owner who asks for `-m manual` gets a readable refusal, not a silent
green.

To run it (one trace per invocation; the frozen run script drives both):

    BELAY_PROBE_TRACE=~/dev/at/holder/belay/mint/cm6/batch/trace-django__django-11422.jsonl \
    BELAY_REFERENCE_AUTHOR_MODEL=claude-opus-5 \
      uv run pytest tests/test_claim_author_live_probe.py -m manual -q -s

Darwin gate: A3 materializes the final state by replaying the final turn
(`claims.py`), and replay re-invokes inside the macOS Seatbelt sandbox — the same
cause the live reference-author proof and the demo capture's gate carry
(`tests/test_reference_claim_author_live.py:42-45`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from belay.verify.claims import SUB_CAUSES_BY_CAUSE

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = (
    REPO_ROOT / "docs" / "planning" / "claim-author-live-probe" / "probe"
)

#: The owner names the model in the environment — full ids only (the reference
#: author rejects `opus`/`sonnet`/`haiku`).
MODEL_ENV = "BELAY_REFERENCE_AUTHOR_MODEL"
#: The ONE trace this invocation verifies — the frozen run script drives both.
TRACE_ENV = "BELAY_PROBE_TRACE"

#: The recording wrapper: appends one marker byte per engine invocation, then
#: runs the shipped reference author. Committed with this test.
WRAPPER = PROBE_DIR / "claim_author_wrapper.sh"
#: The wrapper's marker file — "the author ran" as an observed byte count.
MARKER = PROBE_DIR / "probe-marker"

#: The pinned npm filesystem server, absolute — the run-3 script's own path
#: (`mint-run/acceptance-cm-run3-stage2.sh:40`).
FS_SERVER = (
    Path.home()
    / "dev"
    / "at"
    / "holder"
    / "belay"
    / "servers"
    / "node_modules"
    / "@modelcontextprotocol"
    / "server-filesystem"
    / "dist"
    / "index.js"
)

#: Each process's wall budget — the e2e precedent's 600 s-per-process detector
#: (spec.md:66; `test_claim_axis_e2e._WALL`). A hang detector, never an
#: assertion about timing: no timing assertions exist anywhere in this module.
_WALL = 600.0

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        sys.platform != "darwin",
        reason=(
            "replay-reinvokes-seatbelt: A3 materializes the final state by "
            "replaying the final turn inside the macOS Seatbelt sandbox"
        ),
    ),
]


def _require(env_name: str, what: str, example: str) -> str:
    """One owner-supplied variable, fail-closed: a missing value is a readable
    refusal with re-run instructions, never a skip and never a bare AssertionError."""
    value = (os.environ.get(env_name) or "").strip()
    if not value:
        pytest.fail(
            f"{env_name} is unset or blank — this probe needs {what}. It refuses "
            f"rather than skipping (an owner checkpoint that spends the "
            f"subscription). Re-run as, e.g.:\n\n"
            f"    {env_name}={example} uv run pytest "
            f"tests/test_claim_author_live_probe.py -m manual -q -s\n"
        )
    return value


def test_live_claim_author_probe_on_one_trace() -> None:
    model = _require(MODEL_ENV, "the full model id", "claude-opus-5")
    trace = _require(
        TRACE_ENV,
        "an absolute path to one cm6 trace",
        "~/dev/at/holder/belay/mint/cm6/batch/trace-django__django-11422.jsonl",
    )

    trace_path = Path(trace).expanduser()
    if not trace_path.is_file():
        pytest.fail(
            f"{TRACE_ENV}={trace!r} is not a file. The cm6 traces live at "
            "~/dev/at/holder/belay/mint/cm6/batch/ and are referenced by absolute "
            "path, never copied into the worktree."
        )
    if not WRAPPER.is_file():
        pytest.fail(f"the recording wrapper is missing: {WRAPPER}")

    # Hazard 1 (a3-author/live-run.md:98): `--manifest-dir` is required with no
    # default, and it is the trace's STEM + ".manifests" — the directory that
    # exists beside the trace (the .jsonl suffix is not part of its name).
    manifests = Path(f"{trace_path.with_suffix('')}.manifests")
    if not manifests.is_dir():
        pytest.fail(
            f"the manifest dir {manifests} does not exist. `--manifest-dir` is "
            "required on this surface (no default); omitting it is exit 2 with "
            "empty stdout, and an absent dir means the replay cannot restore."
        )
    if not FS_SERVER.is_file():
        pytest.fail(
            f"the pinned filesystem server does not exist: {FS_SERVER}. It is the "
            "run-3 script's absolute path; replay re-invokes it per turn."
        )

    # A stray BELAY_CLAIM_AUTHOR in the surroundings must not double-configure
    # the axis: the flag below wins over the env, but an inherited env value
    # that is un-lexable fails the surface — so strip it, as the e2e precedent
    # does (test_claim_axis_e2e.py:118-119).
    env = {k: v for k, v in os.environ.items() if k != "BELAY_CLAIM_AUTHOR"}

    # The `--json` flag sits BEFORE `--server`: `--server` is nargs=REMAINDER
    # and swallows everything after it, so a trailing `--json` would land inside
    # the server argv and stdout would be the human report (the same rule the
    # run script comments, and the e2e/live precedents obey).
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "belay.cli",
            "verify",
            str(trace_path),
            "--manifest-dir",
            str(manifests),
            "--claim-author",
            str(WRAPPER),
            "--json",
            "--server",
            "node",
            str(FS_SERVER),
            # Hazard 2 (a3-author/live-run.md:99): the `{workspace}` argv token.
            # The replay substitutes the scratch root it restored into; omitting
            # it leaves the server unable to answer the target frame and every
            # turn degrades to a named abstention before the author engages.
            "{workspace}",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=_WALL,
    )

    assert proc.returncode in (0, 1), (
        "belay verify did not run to a document.\n"
        f"exit={proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\n"
        f"stderr:\n{proc.stderr[-4000:]}"
    )

    payload = json.loads(proc.stdout)
    # The record is read from the document's top-level A3 key (hazard 3,
    # a3-author/live-run.md:100): reading the wrong key made an earlier probe
    # report an empty column against a payload that carried a good record.
    claim = payload.get("claim")
    silence = payload.get("claim_silence")

    # 1. THE AUTHOR ACTUALLY RAN — observed from the marker, never inferred
    #    from the payload: an absent record is ambiguous between "no author"
    #    and "the check exited 0" (D3 silence). A document with the axis never
    #    engaged is a FAILED probe, and this is the assertion that names it.
    invocations = len(MARKER.read_bytes()) if MARKER.exists() else 0
    assert invocations >= 1, (
        "the A3 author was NEVER INVOKED — the axis did not engage at all "
        f"(marker {MARKER} has {invocations} byte(s)). A document with an author "
        "configured and no engagement is the defect this probe exists to close, "
        "and an absent record alone could not have told us.\n"
        f"stdout:\n{proc.stdout[-4000:]}"
    )

    print(
        "\n=== CLAIM-AUTHOR LIVE PROBE — observed outcome ===\n"
        f"model:             {model}\n"
        f"author invoked:    {invocations} time(s)  (observed on disk, not inferred)\n"
        f"trace:             {trace_path}\n"
        f"result status:     {claim.get('status') if claim is not None else '<no claim record>'}\n"
        f"claim record:      {json.dumps(claim, indent=2) if claim else '<absent: D3 silence>'}\n"
        f"silence record:    {json.dumps(silence, indent=2) if silence else '<absent>'}\n"
    )

    # 2. THE THREE ALLOWED RECORD SHAPES (spec.md AC 3).
    if claim is not None:
        status = claim.get("status")
        # A3 NEVER emits PASS — a property pinned at
        # tests/test_verify_claims.py, asserted here against the real binary too.
        assert status != "PASS", f"A3 emitted PASS, which it may never do: {claim!r}"

        if claim.get("cause") == "NO_CHECK_AUTHOR":
            # Shape 1: an abstention naming WHY, from the closed vocabulary that
            # owns the cause — and a bounded one-line detail (`claims._one_line`,
            # ≤200 chars, no line breaks).
            sub_cause = claim.get("sub_cause")
            assert sub_cause in SUB_CAUSES_BY_CAUSE["NO_CHECK_AUTHOR"], (
                f"sub_cause {sub_cause!r} is not in the closed vocabulary "
                f"{sorted(SUB_CAUSES_BY_CAUSE['NO_CHECK_AUTHOR'])} for the "
                f"NO_CHECK_AUTHOR record. An unnamed or out-of-vocabulary cause "
                "is exactly what run 3's ledger could not say.\n"
                f"claim record: {json.dumps(claim, indent=2)}"
            )
            detail = claim.get("sub_cause_detail")
            assert isinstance(detail, str) and len(detail) <= 200 and "\n" not in detail, (
                f"sub_cause_detail must be one line of at most 200 chars, got "
                f"{detail!r}.\nclaim record: {json.dumps(claim, indent=2)}"
            )
        else:
            # Shape 3: a real A3 verdict.
            assert status in {"WARN", "FAIL"}, (
                f"A claim record with cause {claim.get('cause')!r} and status "
                f"{status!r} is neither a named abstention nor a verdict.\n"
                f"claim record: {json.dumps(claim, indent=2)}"
            )
    elif silence is not None:
        # Shape 2: D3 silence — the authored check re-derived the claim and
        # exited 0. Never PASS, and a valid observation on an honest run.
        assert silence.get("check", {}).get("exit_code") == 0, (
            f"the silence record must carry check.exit_code == 0, got "
            f"{json.dumps(silence, indent=2)}"
        )
    else:
        pytest.fail(
            "the document carries NEITHER an author record NOR a silence record — "
            "with an author configured, this is the ambiguous-empty-column "
            "defect the marker was built to disambiguate, and the marker says "
            f"the author WAS invoked ({invocations} time(s)). A payload that "
            "engaged the author and then dropped the record is a surface bug.\n"
            f"stdout:\n{proc.stdout[-4000:]}"
        )