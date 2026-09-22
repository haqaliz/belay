"""C10 triage-seam tests: the provider-neutral calibrated-suspicion seam contract.

`src/belay/verify/triage.py` is the injection point a cheap calibrated decision model
orders and samples the replay queue behind: the engine writes one JSON object of
**whitelisted derived features** to the command's stdin (`BELAY_TRIAGE_AUTHOR`,
shlex-split) and the command answers on stdout with `{"score", "confidence"}` — or
`{"error": ...}` (an abstention). Nothing leaves the box; no model SDK, no network, no
vendor key — the wheel stays zero-dependency, exactly like the A3 author it mirrors.

The failure posture is fail-open (the PRD's accepted contract) and never-raising: the
*seam* abstains — `{"error": ...}`, a non-zero exit, malformed stdout, a timeout, or
output past the 1 MiB cap all yield `None`, and the *caller* decides what `None` means
(the turn goes to full replay; a broken triage command never shrinks the replay
budget). `triage_from_env` returns `None` (triage is ABSENT) for an unset/blank/
un-lexable variable — never a crash.

The payload is whitelisted by construction: `TriageFeatures` carries only derived
scalars (tool name, tri-state annotation hints, hashes, indices, ids — never raw state
or trace bytes), and `build_triage_payload` emits exactly the module-level
`WHITELISTED_KEYS` set. Raw trace/state content is structurally unrepresentable.
"""

from __future__ import annotations

import shlex
import sys

import pytest

from belay.verify import triage

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

SCORE = triage.TriageScore(score=0.7, confidence=0.9)


def _py_triage(code: str, *, timeout: float = 5.0) -> triage.SubprocessTriage:
    """One inline triage command, no shell: `python -c <code>` straight through argv."""
    return triage.SubprocessTriage((sys.executable, "-c", code), timeout=timeout)


# --- the default: NullTriage abstains, and can spawn nothing -----------------------------


def test_null_triage_returns_none() -> None:
    assert triage.NullTriage().triage(FEATURES) is None  # no command exists to spawn


# --- the stdin/stdout contract, driven through inline stubs -------------------------------


def test_subprocess_triage_round_trips_the_score() -> None:
    echo = (
        "import sys, json; "
        "payload = json.load(sys.stdin); "
        "assert isinstance(payload, dict) and 'tool_name' in payload; "
        'sys.stdout.write(json.dumps({"score": 0.7, "confidence": 0.9}))'
    )
    assert _py_triage(echo).triage(FEATURES) == SCORE  # the stub validated stdin, then the score


@pytest.mark.parametrize(
    "code",
    [
        'import sys; sys.stdout.write("this is not json")',
        'import sys, json; sys.stdout.write(json.dumps({"error": "no score"}))',
        'import sys; sys.stdout.write("[1, 2]")',
        'import sys, json; sys.stdout.write(json.dumps({"confidence": 0.9}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": 0.7}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": "high", "confidence": 0.9}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": 0.7, "confidence": [0.9]}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": True, "confidence": 0.9}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": 1.5, "confidence": 0.9}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": 0.7, "confidence": 1.5}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": -0.1, "confidence": 0.9}))',
        'import sys, json; sys.stdout.write(json.dumps({"score": 0.7, "confidence": -0.1}))',
    ],
)
def test_malformed_or_out_of_range_stdout_is_none(code: str) -> None:
    assert _py_triage(code).triage(FEATURES) is None  # a score is never fabricated or guessed


def test_triage_timeout_is_none() -> None:
    sleeper = _py_triage("import time; time.sleep(30)", timeout=0.1)
    assert sleeper.triage(FEATURES) is None  # the 30s sleep is the bound: far past the 0.1s timeout


def test_triage_nonzero_exit_is_none() -> None:
    assert _py_triage("import sys; sys.exit(3)").triage(FEATURES) is None


def test_triage_output_past_the_cap_is_none() -> None:
    huge = (
        "import sys; "
        'sys.stdout.write(\'{"score": 0.7, "confidence": 0.9, "pad": "\' + "x" * 2_000_000 + "\'}\')'
    )
    assert _py_triage(huge).triage(FEATURES) is None  # 2 MiB of valid JSON: capped at 1 MiB


# --- configuration: BELAY_TRIAGE_AUTHOR, absent never a crash -----------------------------


def test_triage_from_env_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(triage.TRIAGE_ENV, raising=False)
    assert triage.triage_from_env() is None  # triage is ABSENT, never a crash


def test_triage_from_env_blank_is_none() -> None:
    assert triage.triage_from_env({triage.TRIAGE_ENV: "   "}) is None


def test_triage_from_env_lexes_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote('print(1)')}"
    monkeypatch.setenv(triage.TRIAGE_ENV, command)
    configured = triage.triage_from_env()
    assert isinstance(configured, triage.SubprocessTriage)
    assert configured.command == (sys.executable, "-c", "print(1)")
    assert configured.timeout == triage.TRIAGE_TIMEOUT


def test_triage_from_env_unlexable_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(triage.TRIAGE_ENV, 'python "unbalanced')
    assert triage.triage_from_env() is None  # absent, never a crash


# --- the whitelist: derived features only, asserted on the constructed payload ------------


def test_build_triage_payload_emits_exactly_the_whitelist() -> None:
    payload = triage.build_triage_payload(FEATURES)
    assert set(payload) == triage.WHITELISTED_KEYS  # nothing derived from raw state or trace bytes
    for key, value in payload.items():
        assert not isinstance(value, bytes), key  # raw bytes are structurally unrepresentable
        assert isinstance(value, (str, int, bool, float, list, type(None))), (key, type(value))
    assert payload["tool_name"] == "run_process"
    assert payload["idempotent_hint"] is None  # the tri-state survives: absent is not declared-false
    assert payload["offered_toolset"] == ["run_process", "read_text_file"]
    assert payload["hash_raw"] == "0" * 64
    assert payload["command_line"] == "pytest -q"