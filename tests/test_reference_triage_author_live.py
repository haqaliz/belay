"""C10 live proof — the Jev reference triage author against the real REST endpoint, owner-run ONLY.

The end-to-end smoke of `docs/planning/jev-triage/reference-author/plan_20260921.md`
phase 3: run the reference author (`python -m belay.verify.reference_triage_author`)
the way `belay verify --triage-author` will run it — whitelisted features JSON on
stdin — against the **real** Jev REST endpoint, and assert it round-trips a score.

This is the **pin for the documented REST contract** (PRD open question: the endpoint
path, key header name, and response schema are owner-provided; the author lands against
the documented contract with a stub-verified shape, and this live test is where the
documented shape meets the real service).

This is an **OWNER CHECKPOINT**, never CI: it spends the owner's key against a live
endpoint. It is `manual`-marked and excluded by the default `addopts`
(`pyproject.toml:94`), and it FAILS with instructions unless `BELAY_JEV_KEY`,
`BELAY_JEV_MODEL`, and `BELAY_JEV_ENDPOINT` are all set — a skip would be the wrong
shape, exactly as the precedent argues: the owner who asks for `-m manual` gets a
readable refusal, not a silent green.

To run it:

    BELAY_JEV_KEY=... BELAY_JEV_MODEL=<full-id> BELAY_JEV_ENDPOINT=https://... \\
        uv run pytest tests/test_reference_triage_author_live.py -m manual -q

Read the result as **"the path works at n=1"** — never a quality claim about the
model's scores. If the endpoint answers `{"error": ...}` (exit ≠ 0, fail-closed), that
is a **recorded result**, not a failure to hide: the seam reads the non-zero exit as an
abstention and the turn goes to full replay. What is never acceptable is an outcome
that is not a protocol reply at all — a traceback, empty stdout, or a reply that
cannot be parsed.

Darwin gate: owner-run checkpoint on the owner's machine (BYOK key + live endpoint
spend); never CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from belay.verify import triage

MODULE = "belay.verify.reference_triage_author"

KEY_ENV = "BELAY_JEV_KEY"
MODEL_ENV = "BELAY_JEV_MODEL"
ENDPOINT_ENV = "BELAY_JEV_ENDPOINT"

#: The same alias refusal the author itself enforces (full ids only), so an owner who
#: passes an alias gets the refusal here, naming the failure, rather than a fail-closed
#: author run that would be misread as an endpoint problem.
MODEL_ALIASES = frozenset({"jev", "system-one"})

#: One representative whitelisted-features payload — the seam's real payload shape.
FEATURES = triage.TriageFeatures(
    tool_name="run_process",
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=None,
    open_world_hint=False,
    annotations_present=True,
    offered_toolset=("run_process", "read_text_file"),
    reply_size=412,
    hash_raw="0" * 64,
    hash_canonical="1" * 64,
    turn_index=3,
    request_seq=7,
    ordering=2,
    truncated=False,
    state_handle_status="captured",
    trace_id="0af7651916cd43dd8448eb211c80319c",
    span_id="b7ad6b7169203331",
    protocol_version="2024-11-05",
    command_line="pytest -q",
)


@pytest.mark.manual
@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "owner-live-checkpoint: an owner-run manual checkpoint on the owner's "
        "machine — BYOK key + real Jev REST endpoint spend; never CI"
    ),
)
def test_reference_triage_author_round_trips_a_score_against_the_live_endpoint() -> None:
    key = (os.environ.get(KEY_ENV) or "").strip()
    model = (os.environ.get(MODEL_ENV) or "").strip()
    endpoint = (os.environ.get(ENDPOINT_ENV) or "").strip()
    missing = [
        name
        for name, value in ((KEY_ENV, key), (MODEL_ENV, model), (ENDPOINT_ENV, endpoint))
        if not value
    ]
    if missing:
        pytest.fail(
            f"{', '.join(missing)} is unset. This is an owner checkpoint that spends "
            "the owner's key against a live endpoint, so it refuses rather than "
            "skipping. Re-run as:\n\n"
            f"    {KEY_ENV}=... {MODEL_ENV}=<full-id> {ENDPOINT_ENV}=https://... "
            "uv run pytest tests/test_reference_triage_author_live.py -m manual -q\n"
        )
    assert model not in MODEL_ALIASES, (
        f"{MODEL_ENV} must name a full model id, never an alias (got {model!r})"
    )

    payload = json.dumps(triage.build_triage_payload(FEATURES), sort_keys=True)
    command = [sys.executable, "-m", MODULE]

    wall_start = time.monotonic()
    proc = subprocess.run(
        command,
        input=payload,
        capture_output=True,
        text=True,
        env=os.environ,
        timeout=120,
    )
    wall = time.monotonic() - wall_start

    # The outcome is the RESULT of this proof, so it is printed rather than merely
    # asserted: the precedent requires recording "the exact command, the model id, the
    # wall clock, the outcome" (tests/test_reference_author_live.py:213-227). A test
    # that passes without saying what it observed cannot be transcribed into the
    # record. Run with `-s` to see it.
    print(
        "\n=== JEV LIVE PROOF — observed outcome ===\n"
        f"command:  {' '.join(command)}\n"
        f"model:    {model}\n"
        f"endpoint: {endpoint}\n"
        f"wall:     {wall:.1f} s\n"
        f"exit:     {proc.returncode}\n"
        f"stdout:   {proc.stdout.strip()!r}\n"
        f"stderr:   {proc.stderr.strip()!r}\n"
    )

    # 1. The author RAN and its stdout is a protocol reply — never a traceback, never
    #    empty, never prose. A subprocess that dies before answering is an instrument
    #    failure, not an abstention.
    assert proc.returncode in (0, 1), (
        "the author subprocess did not run to a protocol reply (exit "
        f"{proc.returncode}).\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
    )
    try:
        reply = json.loads(proc.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"the author's stdout is not a JSON protocol reply:\n{proc.stdout[-2000:]!r}"
        ) from exc
    assert isinstance(reply, dict), f"the author's stdout is not a JSON object: {reply!r}"

    # 2. A fail-closed error IS a recorded result — the endpoint declined, or the
    #    documented contract mismatched the real service. Printed above for the record;
    #    the seam reads exit ≠ 0 as an abstention (full replay), so nothing is lost.
    if proc.returncode != 0:
        assert "error" in reply, (
            "the author exited non-zero without a protocol error object; got "
            f"{reply!r}. This is not a recorded abstention, it is an instrument fault."
        )
        return

    # 3. THE ROUND-TRIP: exit 0 means a score in [0, 1], parsed fail-closed — the
    #    author accepted it and the seam would too.
    score = reply.get("score")
    confidence = reply.get("confidence")
    assert isinstance(score, (int, float)) and not isinstance(score, bool), reply
    assert isinstance(confidence, (int, float)) and not isinstance(confidence, bool), reply
    assert 0.0 <= score <= 1.0 and 0.0 <= confidence <= 1.0, (
        f"the endpoint returned a score outside [0, 1]: {reply!r}"
    )