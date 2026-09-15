"""M7 live proof — the reference author on the launch demo task, owner-run ONLY.

The end-to-end smoke of `docs/planning/invariant-authoring/reference-author/plan_20260915.md`
phase 3: infer with the reference author (`python -m
belay.authoring.reference_author --model <full-id>`) on the launch demo's task spec,
calibrated against the committed launch capture
(`demo/capture/trace-20260827T001428Z-e23f999d.jsonl` + its manifests, the negative
control, 7/7 PASS), then verify the capture with the emitted artifact and assert **no
FAIL**.

This is an **OWNER CHECKPOINT (D-11)**, never CI: it spends the owner's subscription.
It is `manual`-marked and excluded by the default `addopts` (`pyproject.toml:94`), and
it FAILS with instructions unless `BELAY_REFERENCE_AUTHOR_MODEL` names a full model id
— a skip would be the wrong shape here: the owner who asks for `-m manual` gets a
readable refusal, not a silent green.
To run it:

    BELAY_REFERENCE_AUTHOR_MODEL=claude-opus-5 uv run pytest \
        tests/test_reference_author_live.py -m manual -q

and record the verbatim output in
`docs/planning/invariant-authoring/reference-author/live-run.md` (the exact command,
the model id, the wall clock, the outcome), per the plan's phase 3 step 2.

Read the result as **"the path works at n=1"** — never a quality claim about the
model's invariants. If the model produces nothing calibratable, that is a recorded
result (PRD R-g), not a failure to hide; this test's assertions are the plan's —
infer must emit an artifact, and verifying the capture with it must show no FAIL.

Sequencing note: this aspect lands THIRD, after `authoring-protocol` (`belay invariant
infer`) and `artifact-trust` (the `--invariants` authored-schema loader). Until those
surfaces exist in the tree, running this test fails honestly at the subprocess
boundary — it is expected to be runnable once the aspect has fully landed.

Also note the darwin gate: `infer` calibrates by replaying the control, and replay
re-invokes inside the macOS Seatbelt sandbox (the demo capture's own gate,
`tests/test_demo_capture.py:286-292`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "demo"
CAPTURE = DEMO / "capture"
SERVER = DEMO / "server.py"
PROVENANCE = CAPTURE / "PROVENANCE.md"

#: The owner names the model in the environment — full ids only (the D-2 discipline;
#: the reference author itself rejects aliases, so this gate uses the same rule).
MODEL_ENV = "BELAY_REFERENCE_AUTHOR_MODEL"

#: The honest capture's expensive suite needs ~44s per `run_process` replay, so the
#: per-replay timeout is the raised one the operator path applies (`--timeout 300`,
#: `tests/test_demo_capture.py:326-333`).
REPLAY_TIMEOUT = 300

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        sys.platform != "darwin",
        reason=(
            "replay-reinvokes-seatbelt: infer calibrates by replaying the launch "
            "capture inside the macOS Seatbelt sandbox"
        ),
    ),
]


def _capture_trace() -> Path:
    """The committed launch capture — the negative control (7/7 PASS)."""
    traces = sorted(CAPTURE.glob("trace-*.jsonl"))
    assert traces, f"no committed capture at {CAPTURE}"
    return traces[0]


def _manifest_dir() -> Path:
    """`<trace-stem>.manifests`, the mint convention `infer`'s control replay resolves."""
    return CAPTURE / f"{_capture_trace().stem}.manifests"


def _recorded_source_root() -> str:
    """The workspace the capture was taken from, read from its own manifests.

    Replay rewrites this token to a scratch copy, so the recorded path need not exist
    on the machine running the test — the committed capture is portable (the
    `test_demo_capture.py` pattern).
    """
    manifests = sorted(_manifest_dir().glob("*.json"))
    assert manifests, f"no snapshot manifests at {_manifest_dir()}"
    roots = {json.loads(p.read_text(encoding="utf-8")).get("source_root") for p in manifests}
    assert len(roots) == 1 and None not in roots, roots
    return roots.pop()


def _task_text() -> str:
    """The capture's task description, DERIVED from the provenance note — never
    hand-copied, so the smoke and the record cannot drift apart."""
    text = PROVENANCE.read_text(encoding="utf-8")
    match = re.search(r'Task text:\s*\*+\s*"([^"]+)"', text)
    assert match is not None, f"no quoted Task text in {PROVENANCE}"
    return match.group(1)


def test_reference_author_infers_and_the_capture_stays_clean(tmp_path: Path) -> None:
    """Infer → artifact → verify the launch capture → no FAIL.

    One real end-to-end run: `belay invariant infer` with the reference author as the
    `--author`, calibrated against the committed clean capture, then `belay verify
    --invariants <artifact>` on the same capture asserting **no FAIL** — the plan's
    phase 3 in one assertion. Nothing here asserts a quality claim about the model's
    invariants; it proves the path works at n=1.
    """
    model = (os.environ.get(MODEL_ENV) or "").strip()
    assert model, (
        f"{MODEL_ENV} is unset — set it to a full model id (e.g. claude-opus-5) and run "
        "with -m manual to drive the live proof (never CI, never a model spend by "
        "accident)"
    )
    assert model not in ("opus", "sonnet", "haiku"), (
        f"{MODEL_ENV} must name a full model id, never an alias (got {model!r})"
    )

    task_spec = tmp_path / "task.md"
    task_spec.write_text(_task_text(), encoding="utf-8")
    artifact = tmp_path / "invariants.json"

    author_command = " ".join(
        [sys.executable, "-m", "belay.authoring.reference_author", "--model", model]
    )
    infer = subprocess.run(
        [
            sys.executable,
            "-m",
            "belay.cli",
            "invariant",
            "infer",
            "--task",
            str(task_spec),
            "--author",
            author_command,
            "--control",
            str(_capture_trace()),
            "--manifest-dir",
            str(_manifest_dir()),
            "--timeout",
            str(REPLAY_TIMEOUT),
            "--out",
            str(artifact),
            "--json",
            "--server",
            sys.executable,
            str(SERVER),
            _recorded_source_root(),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        cwd=REPO_ROOT,
    )
    assert infer.returncode == 0, (
        "infer failed — a model that produces nothing calibratable is a recorded "
        f"result (PRD R-g), never a hidden one:\nstdout:\n{infer.stdout}\n"
        f"stderr:\n{infer.stderr}"
    )
    assert artifact.is_file(), "infer exited 0 but emitted no artifact"
    emitted = json.loads(artifact.read_text(encoding="utf-8"))
    assert emitted.get("invariants") or emitted.get("candidates"), (
        "the artifact carries no invariants — that is the R-g recorded result, not a pass"
    )

    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "belay.cli",
            "verify",
            "--json",
            "--timeout",
            str(REPLAY_TIMEOUT),
            "--invariants",
            str(artifact),
            "--manifest-dir",
            str(_manifest_dir()),
            str(_capture_trace()),
            "--server",
            sys.executable,
            str(SERVER),
            _recorded_source_root(),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        cwd=REPO_ROOT,
    )
    assert verify.returncode == 0, f"verify failed:\nstdout:\n{verify.stdout}\nstderr:\n{verify.stderr}"
    report = json.loads(verify.stdout)
    assert report["aggregate"]["FAIL"] == 0, report["aggregate"]
    trajectory = report.get("trajectory")
    assert trajectory is None or trajectory.get("status") != "FAIL", trajectory