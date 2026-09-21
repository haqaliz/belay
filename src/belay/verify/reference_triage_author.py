"""The reference Jev triage author for the C10 calibrated-triage seam (BYOK, optional).

Runnable as `python -m belay.verify.reference_triage_author`, and wired by
`BELAY_TRIAGE_AUTHOR="python -m belay.verify.reference_triage_author"`: it reads the
whitelisted-features payload on stdin, validates it against `triage.WHITELISTED_KEYS`,
POSTs it to the operator's Jev REST endpoint with the operator's `BELAY_JEV_KEY`, and
prints the model's ONE score object `{"score": <float>, "confidence": <float>}` on
stdout — fail-closed at every step.

It lives beside the seam it implements — `triage.py` (the `SubprocessTriage` that runs
it) — for the same reason the A3 reference author lives beside `author.py`/`claims.py`
and not in `src/belay/authoring/`: the author is in the verification path (a triage
score orders and samples the replay queue), and shelving it in a package that declares
itself out of that path would falsify that package's own invariant.

THE DOCUMENTED CONTRACT, stated once here (the stub-verified shape; the live manual
test is the pin):

- **BYOK.** The operator's key (`BELAY_JEV_KEY`) is read by THIS author from ITS OWN
  env. The engine neither reads nor forwards it — `triage.py` never names the variable
  (asserted by the honest-line pair in the tests). Absent key ⇒ fail-closed error
  naming the variable, never a guessed key.
- **Endpoint.** `BELAY_JEV_ENDPOINT` names the Jev REST URL. Absent ⇒ the documented
  default `DEFAULT_ENDPOINT` (a `.example` placeholder pending the owner pinning the
  production endpoint — never a guessed endpoint; the owner sets the real URL for the
  live manual test).
- **Model.** `BELAY_JEV_MODEL` names the full model id; aliases are refused (the A3
  precedent, `reference_claim_author.py:81`) — an alias would pin the reply to
  whatever the vendor's alias table says, which is not reproducible policy.
- **Request.** One HTTP POST; the body carries exactly the whitelisted features read
  from stdin (validated BEFORE any egress); the key travels in
  `Authorization: Bearer <key>`; the model id in `X-Jev-Model`.
- **Response.** `{"score", "confidence"}` both numeric in `[0, 1]` ⇒ printed to stdout,
  nothing else. `{"error": ...}`, malformed JSON, missing/non-numeric/out-of-range
  values, a non-2xx status, an unreachable endpoint, or a timeout ⇒ fail-closed: exit
  ≠ 0 and `{"error": ...}` on stdout — a score is never guessed from a shape the
  contract does not name.

The seam reads a non-zero exit as an abstention (`SubprocessTriage.triage` returns
`None` → the turn goes to full replay): the reference author's fail-closed posture is
exactly the seam's fail-open contract in the other hat. Stdlib only (`urllib`) — the
zero-LLM guard (`tests/test_verify_zero_llm.py`) walks `src/belay/verify/`, and the
wheel stays zero-dependency. The call is bounded (`REQUEST_TIMEOUT`) so a slow endpoint
can never hang `belay verify`.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from belay.verify.triage import WHITELISTED_KEYS

#: The HTTP transport. Imported as a module-level name so tests can pin the constructed
#: request URL by monkeypatching it — the URL assertion is part of the contract.
urlopen = urllib.request.urlopen

#: The env var naming the operator's Jev API key. Read by the author from its OWN env;
#: the engine never reads or forwards it.
KEY_ENV = "BELAY_JEV_KEY"

#: The env var naming the full model id. Aliases are refused.
MODEL_ENV = "BELAY_JEV_MODEL"

#: The env var naming the Jev REST endpoint URL.
ENDPOINT_ENV = "BELAY_JEV_ENDPOINT"

#: The documented default endpoint. A `.example` placeholder (RFC 2606 — reserved, can
#: never resolve) until the owner pins the production endpoint; the owner sets
#: `BELAY_JEV_ENDPOINT` for the live manual test. Never a guessed endpoint.
DEFAULT_ENDPOINT = "https://api.jev.example/v1/triage"

#: The per-call wall-clock bound for the Jev POST, in seconds. A slow endpoint fails
#: closed here — it can never hang `belay verify`.
REQUEST_TIMEOUT = 10.0

#: The model id aliases. Full ids only — an alias would pin the reply to the vendor's
#: alias table on the operator's box, which is not reproducible policy
#: (`reference_claim_author.py:81`).
_MODEL_ALIASES = frozenset({"jev", "system-one"})


class ReferenceTriageAuthorError(Exception):
    """Base for every failure this module names."""


class PayloadError(ReferenceTriageAuthorError):
    """The stdin payload is not a JSON object, or carries a non-whitelisted key."""


class EnvError(ReferenceTriageAuthorError):
    """A required env var is absent — never a guessed key, model, or endpoint."""


class ModelIdError(ReferenceTriageAuthorError):
    """The model id is an alias or empty — full ids only."""


class EndpointError(ReferenceTriageAuthorError):
    """The endpoint did not answer: non-2xx status, unreachable, or timed out."""


class ResponseError(ReferenceTriageAuthorError):
    """The endpoint's reply is not the documented score shape — never guessed."""


def _fail(message: str) -> int:
    """Print the fail-closed error on stdout and exit non-zero.

    The seam reads a non-zero exit as an abstention, so the error JSON on stdout is the
    machine-readable record of WHY; a human line goes to stderr, mirroring the A3
    reference author's named-message convention.
    """
    json.dump({"error": message}, sys.stdout)
    sys.stdout.write("\n")
    print(f"reference-triage-author: {message}", file=sys.stderr)
    return 1


def _read_payload() -> dict[str, Any]:
    """The whitelisted-features payload from stdin, validated BEFORE any egress.

    The payload must be a JSON object whose keys are all in `WHITELISTED_KEYS`: a
    non-whitelisted key means the payload carries something the PRD never named, so the
    turn must NOT be triaged — fail-closed error, nothing sent.
    """
    try:
        payload = json.load(sys.stdin)
    except ValueError as exc:
        raise PayloadError(
            f"stdin is not a JSON document: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PayloadError(
            f"the payload on stdin must be a JSON object, got {type(payload).__name__}."
        )
    unknown = set(payload) - set(WHITELISTED_KEYS)
    if unknown:
        raise PayloadError(
            "the payload carries key(s) outside the whitelist: "
            f"{sorted(unknown)}. Only whitelisted derived features may ever leave "
            "the box — this turn is not triaged."
        )
    return payload


def _env(name: str) -> str:
    """One required env var, stripped; absent or blank is a named error, never a guess."""
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise EnvError(
            f"{name} is unset. The reference Jev author is BYOK: the operator's own "
            f"key, model, and endpoint come from the author's env, never the engine's."
        )
    return value


def _validate_model(model: str) -> None:
    """Full model ids only — an alias or an empty id is a named error (D-2 discipline)."""
    if model in _MODEL_ALIASES:
        raise ModelIdError(
            f"model id {model!r} is an alias, not a full model id. Full ids only "
            "(the A3 precedent) — pass e.g. a full id; aliases are not reproducible "
            "policy."
        )


def _post(
    endpoint: str,
    key: str,
    model: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """One POST to the Jev endpoint, fail-closed: the score object, or a named error.

    The body carries exactly the whitelisted features; the key travels in
    `Authorization: Bearer <key>`; the model id in `X-Jev-Model`. A non-2xx status,
    an unreachable endpoint, or a timeout is an `EndpointError`; the reply itself is
    parsed fail-closed by `_parse_reply`.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "X-Jev-Model": model,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise EndpointError(
            f"the Jev endpoint answered HTTP {exc.code} for {endpoint!r}."
        ) from exc
    except urllib.error.URLError as exc:
        raise EndpointError(
            f"the Jev endpoint {endpoint!r} is unreachable: {exc.reason}."
        ) from exc
    except TimeoutError as exc:
        raise EndpointError(
            f"the Jev endpoint {endpoint!r} did not answer within "
            f"{REQUEST_TIMEOUT} seconds."
        ) from exc
    return _parse_reply(text)


def _parse_reply(text: str) -> dict[str, Any]:
    """One endpoint reply, fail-closed: `{"score", "confidence"}` in `[0, 1]`.

    `{"error": ...}` from the endpoint is a fail-closed error, not a score; malformed
    JSON, a non-object reply, a missing, non-numeric or boolean `score`/`confidence`,
    or either value outside `[0, 1]` are all errors — a score is never guessed from a
    shape the contract does not name.
    """
    try:
        reply = json.loads(text)
    except ValueError as exc:
        raise ResponseError(
            f"the Jev endpoint's reply is not JSON: {text[:200]!r}."
        ) from exc
    if not isinstance(reply, dict):
        raise ResponseError(
            "the Jev endpoint's reply parsed as JSON but is not an object; got "
            f"{type(reply).__name__}."
        )
    if "error" in reply:
        raise ResponseError(
            f"the Jev endpoint declined: {str(reply['error'])[:200]!r}."
        )
    score = reply.get("score")
    confidence = reply.get("confidence")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ResponseError(
            "the Jev endpoint's `score` is not a number; got "
            f"{type(score).__name__}."
        )
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ResponseError(
            "the Jev endpoint's `confidence` is not a number; got "
            f"{type(confidence).__name__}."
        )
    if not (0.0 <= score <= 1.0) or not (0.0 <= confidence <= 1.0):
        raise ResponseError(
            "the Jev endpoint's score/confidence must lie in [0, 1]; got "
            f"score={score!r}, confidence={confidence!r}."
        )
    return {"score": float(score), "confidence": float(confidence)}


def main() -> int:
    """Run the reference Jev triage author: whitelisted features in on stdin, score out.

    Every failure path — unreadable/non-whitelisted stdin, missing key/model/endpoint,
    an alias model id, a non-2xx or unreachable or timed-out endpoint, an
    unparseable/out-of-range reply — exits non-zero with `{"error": ...}` on stdout,
    which the seam reads as an abstention (the turn goes to full replay). On success
    exactly ONE score object is written to stdout and nothing else.
    """
    try:
        payload = _read_payload()
        key = _env(KEY_ENV)
        model = _env(MODEL_ENV)
        _validate_model(model)
        endpoint = (os.environ.get(ENDPOINT_ENV) or "").strip() or DEFAULT_ENDPOINT
        reply = _post(endpoint, key, model, payload)
    except ReferenceTriageAuthorError as exc:
        return _fail(str(exc))

    json.dump(reply, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())