"""C10 reference-author tests: the Jev reference triage author contract.

`src/belay/verify/reference_triage_author.py` is the first BYOK triage command for the
provider-neutral seam (`src/belay/verify/triage.py`): it reads the whitelisted-features
payload on stdin, POSTs it to the operator's Jev REST endpoint with the operator's
`BELAY_JEV_KEY` (read by the author only, never the engine), and prints the model's ONE
score object `{"score", "confidence"}` on stdout — fail-closed at every step.

The Jev REST contract is the REAL protocol, verified live by the integrator 2026-09-22,
stub-verified here:

- Endpoint: `POST https://api.typesafe.ai/v1/systemone` — `BELAY_JEV_ENDPOINT` names
  an override; absent ⇒ the pinned default `DEFAULT_ENDPOINT` (asserted on the
  constructed request URL).
- The request body is the systemone envelope `{"model", "state", "questions"}`: the
  full model id in `model`; the whitelisted-features object in `state` (asserted
  against `triage.WHITELISTED_KEYS`); `questions` holds exactly one score question
  named `triage` with an ordered `criteria` array of exactly 2 level descriptions.
  The operator's key travels in `Authorization: Bearer <key>`.
- The response is `{"answers": {"triage": {"type": "score", "score", "confidence"}},
  ...}` — the author maps `answers.triage.{score,confidence}` to stdout; anything else
  is a fail-closed error (exit ≠ 0, `{"error": ...}` on stdout).

The HTTP side is stubbed deterministically — a threaded `http.server` on localhost for
the real-POST tests, a monkeypatched `urllib.request.urlopen` for the constructed-URL
assertion — no external network, no real key, nothing leaves the box.

The honest-line pairs live here too: test 7 proves the seam treats the Jev author and a
trivial stub command **identically** (the provider-neutrality pin — "laya later" is a
reference author, never an engine change), and test 8 proves the engine never passes the
key — `SubprocessTriage`'s child env carries no `BELAY_JEV_KEY` when the caller env has
none (by absence, never `""`).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from belay.verify import reference_triage_author, triage

MODULE = "belay.verify.reference_triage_author"

KEY = "test-operator-key"
MODEL = "jev-1.13.0"

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
FEATURES_PAYLOAD = triage.build_triage_payload(FEATURES)

#: The REAL reply shape: the score answer lives under `answers.triage`, not at the top
#: level (the placeholder shape this file's tests were written against).
SCORE_REPLY = {
    "model": MODEL,
    "answers": {
        "triage": {
            "type": "score",
            "score": 0.7,
            "confidence": 0.9,
            "probabilities": {"0": 0.3, "1": 0.7},
            "legend": {
                "0": "The turn appears clean.",
                "1": "The turn appears suspicious.",
            },
        }
    },
    "usage": {"input_tokens": 1, "output_tokens": 1},
}

#: What the author must print on stdout after mapping the real reply.
EXPECTED_SCORE = {"score": 0.7, "confidence": 0.9}


class _Handler(BaseHTTPRequestHandler):
    """One request recorder + responder; the stub instance is pinned per test."""

    stub: "_StubJev" = None  # type: ignore[assignment]

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        self.stub.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        status, payload = (
            self.stub.responses.pop(0)
            if self.stub.responses
            else (200, SCORE_REPLY)
        )
        data = payload if isinstance(payload, str) else json.dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def log_message(self, *args: Any) -> None:  # keep the test output clean
        pass


class _StubJev:
    """A threaded localhost Jev stub: records every request, answers from a queue."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[tuple[int, Any]] = []
        _Handler.stub = self
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/v1/systemone"

    def __enter__(self) -> "_StubJev":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


def _run_author(
    *,
    payload: dict[str, Any],
    env: dict[str, str],
    stdin: str | None = None,
) -> subprocess.CompletedProcess:
    """The author as `belay verify` would run it: one subprocess, JSON on stdin.

    The three Jev vars are removed from the inherited env first and only the test's own
    env is applied — no ambient key/model/endpoint can leak into a test from the
    developer's shell.
    """
    child_env = dict(os.environ)
    for name in ("BELAY_JEV_KEY", "BELAY_JEV_MODEL", "BELAY_JEV_ENDPOINT"):
        child_env.pop(name, None)
    child_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", MODULE],
        input=json.dumps(payload) if stdin is None else stdin,
        capture_output=True,
        text=True,
        env=child_env,
        timeout=60,
    )


def _env_with(stub: _StubJev, **extra: str) -> dict[str, str]:
    env = {
        "BELAY_JEV_KEY": KEY,
        "BELAY_JEV_MODEL": MODEL,
        "BELAY_JEV_ENDPOINT": stub.url,
    }
    env.update(extra)
    return env


def _answers(answer: Any) -> dict[str, Any]:
    """One real-shaped reply with a given `answers.triage` value (any shape)."""
    return {"model": MODEL, "answers": {"triage": answer}, "usage": {}}


def _score_answer(score: Any = 0.7, confidence: Any = 0.9) -> dict[str, Any]:
    """One real-shaped `answers.triage` score answer with the given values."""
    return {"type": "score", "score": score, "confidence": confidence}


# --- 1. the systemone envelope: model + whitelisted state + one score question ------------


def test_posts_the_systemone_envelope_with_only_whitelisted_features_in_state() -> None:
    with _StubJev() as stub:
        proc = _run_author(payload=FEATURES_PAYLOAD, env=_env_with(stub))

    assert proc.returncode == 0, proc.stderr
    assert len(stub.requests) == 1
    request = stub.requests[0]

    body = json.loads(request["body"])
    assert set(body) == {"model", "state", "questions"}, (
        "the request body must be exactly the real Jev systemone envelope — "
        "{model, state, questions}; nothing else"
    )
    assert body["model"] == MODEL, (
        "the full model id travels in the body, never in a header"
    )

    state = body["state"]
    assert isinstance(state, dict), f"state must be the features object, got {type(state).__name__}"
    assert set(state) <= triage.WHITELISTED_KEYS, (
        "the request's state carries a key the PRD never named — only whitelisted "
        "derived features may ever leave the box"
    )
    assert state == FEATURES_PAYLOAD, (
        "the author must forward the features it read, unchanged"
    )

    questions = body["questions"]
    assert isinstance(questions, dict)
    assert set(questions) == {"triage"}, (
        "questions must hold exactly one question named 'triage'"
    )
    question = questions["triage"]
    assert question["type"] == "score", (
        "the one question must be a score question"
    )
    assert isinstance(question["instructions"], str) and question["instructions"].strip(), (
        "the question must carry non-empty instructions naming the triage semantics"
    )
    criteria = question["criteria"]
    assert isinstance(criteria, list) and len(criteria) == 2, (
        "the criteria array must hold exactly 2 ordered level descriptions (the score "
        "lands in [0, 1] with two levels)"
    )
    assert all(isinstance(level, str) and level.strip() for level in criteria), (
        "each level description must be a non-empty string"
    )
    assert criteria[0] != criteria[1], (
        "the two levels must be distinct descriptions (clean vs suspicious)"
    )

    assert request["headers"].get("Authorization") == f"Bearer {KEY}", (
        "the operator's BELAY_JEV_KEY must travel in the Authorization header"
    )
    assert request["headers"].get("Content-Type", "").startswith("application/json")
    assert request["path"] == "/v1/systemone"


# --- 2. a non-whitelisted stdin key is fail-closed, and NOTHING is sent -------------------


def test_non_whitelisted_key_is_fail_closed_and_nothing_is_sent() -> None:
    payload = dict(FEATURES_PAYLOAD)
    payload["raw_trace_bytes"] = "this is raw state and must never leave"

    with _StubJev() as stub:
        proc = _run_author(payload=payload, env=_env_with(stub))

    assert proc.returncode != 0
    error = json.loads(proc.stdout)
    assert "error" in error, error
    assert len(stub.requests) == 0, (
        "a non-whitelisted key must fail BEFORE any egress — the stub saw a request"
    )


# --- 3. answers.triage maps to the stdout score object ------------------------------------


def test_score_and_confidence_round_trip_to_stdout() -> None:
    with _StubJev() as stub:
        proc = _run_author(payload=FEATURES_PAYLOAD, env=_env_with(stub))

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == EXPECTED_SCORE
    assert proc.stdout.strip() == json.dumps(EXPECTED_SCORE), (
        "stdout must be exactly the ONE score object — a stray diagnostic would break "
        "the seam's parse"
    )


# --- 4. malformed / unexpected responses are fail-closed ----------------------------------


@pytest.mark.parametrize(
    "status,payload",
    [
        (200, "this is not json"),
        (200, "[1, 2]"),
        (200, {}),
        (200, {"answers": {}}),
        (200, {"answers": "not an object"}),
        (200, _answers("not an object")),
        (200, _answers({})),
        (200, _answers({"type": "score", "confidence": 0.9})),
        (200, _answers({"type": "score", "score": 0.7})),
        (200, _answers(_score_answer(score=None))),
        (200, _answers(_score_answer(confidence=None))),
        (200, _answers(_score_answer(score="high"))),
        (200, _answers(_score_answer(score=True))),
        (200, _answers(_score_answer(score=1.5))),
        (200, _answers(_score_answer(score=-0.1))),
        (200, _answers(_score_answer(confidence=1.5))),
        (200, _answers(_score_answer(confidence=-0.1))),
        (200, {"error": "jev declined to score this turn"}),
        (500, SCORE_REPLY),
    ],
)
def test_malformed_or_unexpected_response_is_fail_closed(
    status: int, payload: Any
) -> None:
    with _StubJev() as stub:
        stub.responses.append((status, payload))
        proc = _run_author(payload=FEATURES_PAYLOAD, env=_env_with(stub))

    assert proc.returncode != 0
    error = json.loads(proc.stdout)
    assert "error" in error, f"expected a fail-closed error, got {error!r}"


# --- 5. BELAY_JEV_ENDPOINT absent ⇒ the real default, asserted on the URL -----------------


def test_default_endpoint_is_the_real_systemone_url_when_belay_jev_endpoint_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> Any:
        seen.append(request)

        class _FakeResponse:
            status = 200

            def read(self) -> bytes:
                return json.dumps(SCORE_REPLY).encode("utf-8")

            def __enter__(self) -> "_FakeResponse":
                return self

            def __exit__(self, *exc: Any) -> None:
                pass

        return _FakeResponse()

    monkeypatch.setattr(reference_triage_author, "urlopen", fake_urlopen)
    monkeypatch.setattr(reference_triage_author.sys, "stdin", io.StringIO(json.dumps(FEATURES_PAYLOAD)))
    monkeypatch.delenv("BELAY_JEV_ENDPOINT", raising=False)
    monkeypatch.setenv("BELAY_JEV_KEY", KEY)
    monkeypatch.setenv("BELAY_JEV_MODEL", MODEL)

    exit_code = reference_triage_author.main()

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert len(seen) == 1
    assert reference_triage_author.DEFAULT_ENDPOINT == "https://api.typesafe.ai/v1/systemone", (
        "the pinned default is the real Jev systemone URL, never a placeholder"
    )
    assert seen[0].full_url == reference_triage_author.DEFAULT_ENDPOINT, (
        "an unset BELAY_JEV_ENDPOINT must resolve to the documented default, never a "
        "guessed endpoint"
    )
    assert json.loads(captured.out) == EXPECTED_SCORE


# --- 6. BELAY_JEV_MODEL: full ids only, aliases refused ------------------------------------


@pytest.mark.parametrize("model", ["jev", "system-one", "", "  "])
def test_model_alias_or_blank_is_refused_fail_closed(model: str) -> None:
    with _StubJev() as stub:
        proc = _run_author(payload=FEATURES_PAYLOAD, env=_env_with(stub, BELAY_JEV_MODEL=model))

    assert proc.returncode != 0
    error = json.loads(proc.stdout)
    assert "error" in error, error
    assert len(stub.requests) == 0, (
        "an alias/blank model must be refused before any egress"
    )


def test_full_model_id_is_accepted_and_carried_in_the_body() -> None:
    with _StubJev() as stub:
        proc = _run_author(payload=FEATURES_PAYLOAD, env=_env_with(stub))

    assert proc.returncode == 0, proc.stderr
    assert json.loads(stub.requests[0]["body"])["model"] == MODEL


# --- 7. provider-neutrality: the seam treats Jev and a trivial stub identically -----------


def test_the_seam_treats_the_jev_author_and_a_trivial_stub_command_identically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = triage.TriageScore(score=0.7, confidence=0.9)
    stub_command = (
        sys.executable,
        "-c",
        "import sys, json; "
        "json.load(sys.stdin); "
        'sys.stdout.write(json.dumps({"score": 0.7, "confidence": 0.9}))',
    )
    assert triage.SubprocessTriage(stub_command).triage(FEATURES) == expected

    with _StubJev() as stub:
        monkeypatch.setenv("BELAY_JEV_KEY", KEY)
        monkeypatch.setenv("BELAY_JEV_MODEL", MODEL)
        monkeypatch.setenv("BELAY_JEV_ENDPOINT", stub.url)
        jev_score = triage.SubprocessTriage(
            (sys.executable, "-m", MODULE), timeout=30
        ).triage(FEATURES)

    assert jev_score == expected, (
        "the seam must treat the Jev reference author and a trivial stub command "
        "identically — the provider-neutrality pin: any model is one command, never "
        "an engine change"
    )


# --- 8. the engine never passes the key (by absence, never "") -----------------------------


def test_subprocess_triage_never_passes_or_names_a_jev_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import belay.verify.triage as triage_mod

    calls: list[dict[str, Any]] = []

    def spy_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(EXPECTED_SCORE).encode("utf-8"), stderr=b""
        )

    monkeypatch.setattr(triage_mod.subprocess, "run", spy_run)
    monkeypatch.delenv("BELAY_JEV_KEY", raising=False)

    score = triage.SubprocessTriage(("true",)).triage(FEATURES)
    assert score == triage.TriageScore(score=0.7, confidence=0.9)
    assert calls, "the spy saw no subprocess call — the seam did not engage"

    assert all("env" not in kwargs for kwargs in calls), (
        "SubprocessTriage must not pass env= — the child inherits the caller env, so "
        "a key can only reach it from the operator's own environment, never the engine"
    )

    source = Path(triage_mod.__file__).read_text(encoding="utf-8")
    assert "BELAY_JEV_KEY" not in source, (
        "the engine module must not name the key at all — by absence, never ''; a "
        "module that never mentions BELAY_JEV_KEY cannot forward it"
    )