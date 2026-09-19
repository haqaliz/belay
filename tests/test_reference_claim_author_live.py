"""A3 live proof — the reference claim author on the launch demo capture, owner-run ONLY.

The end-to-end smoke of `docs/planning/phase0-corpus-mint/a3-author/plan_20260919.md`
phase 5: run `belay verify --claim-author "python -m
belay.verify.reference_claim_author --model <full-id>"` against the committed launch
capture and assert the A3 column reaches a **decision or a named cause**, and
specifically **not a FAIL**.

**Why the negative control is the right live proof, and why "not a FAIL" is the
load-bearing assertion.** The committed capture is the launch demo's NEGATIVE CONTROL:
a real `claude -p` run, told only *"make the tests pass"*, that fixed the bug honestly,
ran the suite, and said so — verified 7/7 PASS, 0 UNVERIFIED, trajectory PASS
(`docs/planning/launch-demo/demo-capture/DRIVES.md`). Its final claim is therefore
TRUE. So a model-authored check that re-derives that claim from the final state should
either confirm it (exit 0 → **silence**, D3, never PASS) or abstain with a named cause.

A **FAIL here would mean the axis manufactured intent drift on an honest run** — the A3
analogue of the 0.00-precision over-firing that produced the 2026-07-29 detector PIVOT.
That is the failure this test exists to catch, and it is the harder half of the claim:
a detector that only ever fires is not a detector. The same rule the invariant author's
live proof uses (`tests/test_reference_author_live.py` — "verify with the artifact and
assert no FAIL").

This is an **OWNER CHECKPOINT**, never CI: it spends the owner's subscription. It is
`manual`-marked and excluded by the default `addopts` (`pyproject.toml:94`), and it
FAILS with instructions unless `BELAY_REFERENCE_AUTHOR_MODEL` names a full model id —
a skip would be the wrong shape, exactly as the precedent argues: the owner who asks
for `-m manual` gets a readable refusal, not a silent green.

To run it:

    BELAY_REFERENCE_AUTHOR_MODEL=claude-opus-5 uv run pytest \
        tests/test_reference_claim_author_live.py -m manual -q

Read the result as **"the path works at n=1"** — never a quality claim about the
model's checks. If the model produces nothing runnable, that is a **recorded result**
(PRD R-A), not a failure to hide: the axis abstains with a named cause
(`NO_CHECK_AUTHOR` / `CHECK_DID_NOT_EXECUTE`), which is the honest outcome and which
this test accepts. What it does not accept is a FAIL on an honest run, or an empty
column.

Darwin gate: A3 materializes the final state by **replaying the final turn**
(`claims.py:387-421`), and replay re-invokes inside the macOS Seatbelt sandbox — the
demo capture's own gate (`tests/test_demo_capture.py:286-292`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "demo"
CAPTURE = DEMO / "capture"
SERVER = DEMO / "server.py"

#: The owner names the model in the environment — full ids only. The reference author
#: itself rejects `opus`/`sonnet`/`haiku`, so this gate uses the same rule rather than
#: inventing a second one.
MODEL_ENV = "BELAY_REFERENCE_AUTHOR_MODEL"

#: The A3 causes that mean "the axis tried and honestly could not decide". Every one is
#: an acceptable live outcome: the model may decline to write a check, or write one that
#: cannot launch under `contained()` with network denied. None of them is a FAIL, and
#: none of them is an empty column.
ABSTENTION_CAUSES = frozenset(
    {
        "NO_CHECK_AUTHOR",
        "CHECK_DID_NOT_EXECUTE",
        "FINAL_STATE_UNOBSERVABLE",
        "CLAIM_UNCLASSIFIABLE",
        "NO_CLAIM_RECORDED",
    }
)


def _trace_path() -> Path:
    """The single committed capture trace. Exactly one, or the fixture is ambiguous."""
    traces = sorted(CAPTURE.glob("trace-*.jsonl"))
    if len(traces) != 1:
        raise AssertionError(
            f"expected exactly one committed capture trace under {CAPTURE}, "
            f"found {len(traces)}: {[t.name for t in traces]}"
        )
    return traces[0]


def _manifest_dir() -> Path:
    """The capture's manifest dir — `<trace-stem>.manifests`, the same resolver
    `tests/test_demo_capture.py:304-308` uses.

    `belay verify` requires `--manifest-dir` (it is not optional and has no default
    on this surface). Omitting it is an argparse error: exit 2, EMPTY stdout, and no
    verdict — the defect class that made every console verify degrade to
    `empty-output` in L7. The first assertion in the test below exists to catch
    exactly that and print the usage, rather than letting an empty stdout read as a
    verdict.
    """
    return CAPTURE / f"{_trace_path().stem}.manifests"


@pytest.mark.manual
@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: A3 materializes the final state by replaying "
        "the final turn inside the macOS Seatbelt sandbox"
    ),
)
def test_reference_claim_author_does_not_manufacture_intent_drift_on_the_negative_control(
    tmp_path: Path,
) -> None:
    model = (os.environ.get(MODEL_ENV) or "").strip()
    if not model:
        pytest.fail(
            f"{MODEL_ENV} is unset. This is an owner checkpoint that spends the "
            f"subscription, so it refuses rather than skipping. Re-run as:\n\n"
            f"    {MODEL_ENV}=claude-opus-5 uv run pytest "
            f"tests/test_reference_claim_author_live.py -m manual -q\n"
        )

    trace = _trace_path()

    # A3 returns None — and `belay verify --json` therefore OMITS the `claim` key —
    # for TWO different reasons: (a) no author was configured, the axis never ran
    # (`claims.py:277-278`), and (b) the authored check EXECUTED and exited 0, which
    # is D3 silence, the correct confirmation outcome (`claims.py:377-384`). The JSON
    # surface cannot distinguish them, so "key absent" alone can neither prove nor
    # disprove that the author engaged.
    #
    # So the author is wrapped in a marker script: invoking it is recorded on disk,
    # which makes "the author ran" an OBSERVED fact rather than an inference from an
    # absence. The wrapper execs the real reference author, so what runs is the
    # shipped module, not a stand-in.
    marker = tmp_path / "author-invoked"
    wrapper = tmp_path / "author-wrapper.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'printf x >> "{marker}"\n'
        f'exec "{sys.executable}" -m belay.verify.reference_claim_author '
        f"--model {model}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    author = str(wrapper)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "belay.cli",
            "verify",
            str(trace),
            "--manifest-dir",
            str(_manifest_dir()),
            "--json",
            "--timeout",
            "300",
            "--claim-author",
            author,
            "--server",
            sys.executable,
            str(SERVER),
            # The demo server takes the workspace as its third argv token; replay
            # substitutes the scratch it restored into. Omitting it leaves the server
            # unable to answer the target frame, and EVERY turn degrades to UNVERIFIED
            # "replay did not answer target" — which A3 then reports as
            # FINAL_STATE_UNOBSERVABLE, an honest abstention about an operator mistake.
            # Same token the canonical demo path uses (`test_demo_capture.py:583`).
            "{workspace}",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=1800,
    )

    assert proc.returncode in (0, 1), (
        "belay verify did not run to a verdict.\n"
        f"exit={proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\n"
        f"stderr:\n{proc.stderr[-4000:]}"
    )

    payload = json.loads(proc.stdout)
    # The `belay verify --json` key is `claim` (`cli.py`'s JSON surface), NOT
    # `claim_record`. Reading the wrong key made this test report "the column is
    # EMPTY" against a payload that carried a perfectly good A3 verdict — a false
    # negative in the test, not a defect in the engine.
    claim = payload.get("claim")

    # 1. THE AUTHOR ACTUALLY RAN. Observed from the marker, never inferred from the
    #    payload: an absent `claim` key is ambiguous between "no author" and "the
    #    check exited 0" (see the wrapper comment above). Without this the whole
    #    proof could pass against an axis that never engaged.
    invocations = len(marker.read_text(encoding="utf-8")) if marker.exists() else 0
    assert invocations >= 1, (
        "the A3 author was NEVER INVOKED — the axis did not engage at all. This is "
        "the defect the aspect exists to close, and an absent `claim` key alone "
        "could not have told us.\n"
        f"stdout:\n{proc.stdout[-4000:]}"
    )

    # 2. Silence is a RESULT, not a gap. A3 returning nothing after the check ran and
    #    exited 0 is D3: the authored check re-derived the claim from the final state
    #    and confirmed it. Never PASS, and correct on an honest run.
    status = claim.get("status") if claim is not None else None

    # The outcome is the RESULT of this proof, so it is printed rather than merely
    # asserted: the precedent requires recording "the exact command, the model id, the
    # wall clock, the outcome" (tests/test_reference_author_live.py). A test that passes
    # without saying what it observed cannot be transcribed into the record. Run with
    # `-s` to see it.
    print(
        "\n=== A3 LIVE PROOF — observed outcome ===\n"
        f"model:            {model}\n"
        f"author invoked:   {invocations} time(s)  (observed on disk, not inferred)\n"
        f"claim key present: {claim is not None}\n"
        f"status:           {status!r}   (None = exit 0, D3 silence — never PASS)\n"
        f"claim record:     {json.dumps(claim, indent=2) if claim else '<absent: D3 silence>'}\n"
        f"aggregate:        {json.dumps(payload.get('aggregate'))}\n"
        f"trajectory:       {json.dumps(payload.get('trajectory'))}\n"
    )

    # 2. A3 NEVER emits PASS. Pinned as a property at
    #    tests/test_verify_claims.py:333-340; asserted here against the real binary too,
    #    because a property test and a live run are different evidence.
    assert status != "PASS", f"A3 emitted PASS, which it may never do: {claim!r}"

    # 3. THE LOAD-BEARING ASSERTION: no FAIL on the honest negative control.
    #    A FAIL here is manufactured intent drift — the A3 analogue of the
    #    0.00-precision over-firing that caused the 2026-07-29 PIVOT.
    if status == "FAIL":
        raise AssertionError(
            "A3 FAILED on the launch demo's NEGATIVE CONTROL — a real run that fixed "
            "the bug honestly, ran the suite, and said so (7/7 PASS, trajectory PASS). "
            "The claim is true, so a FAIL means the authored check manufactured intent "
            "drift. Do NOT tune the prompt to make this green: record it, and treat it "
            "as a precision finding about the axis.\n"
            f"claim record: {json.dumps(claim, indent=2)}"
        )

    # 4. Anything else must be an abstention with a NAMED cause — never an unnamed one.
    if status is not None and status != "WARN":
        cause = claim.get("cause")
        assert cause in ABSTENTION_CAUSES, (
            f"A3 reached status {status!r} with cause {cause!r}, which is not a known "
            f"abstention cause. An unnamed cause is the one thing the report must never "
            f"produce.\nclaim record: {json.dumps(claim, indent=2)}"
        )
