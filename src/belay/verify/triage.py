"""C10 — the calibrated-triage seam: a provider-neutral suspicion score per turn.

The engine asks *some* triage command for a calibrated suspicion score per turn without
ever knowing the model: `BELAY_TRIAGE_AUTHOR` names a command line (shlex-split); Belay
writes one JSON object of **whitelisted derived features** to its stdin and the command
answers on stdout with `{"score": <float>, "confidence": <float>}` or
`{"error": <reason>}`.

The honesty contract, stated once here (spec acceptance 1-4):

- **Nothing leaves the box.** The command is whatever the user points at — a local model
  CLI, their own script — with no vendor key, no proxying, no network, and no model SDK
  import anywhere (the wheel stays zero-dependency, and the zero-LLM guard stays trivially
  satisfied). The reference implementation ships no model client by design.
- **Fail-open, never raising.** Any failure — `{"error": ...}`, a non-zero exit, malformed
  stdout, a timeout, output past the 1 MiB cap — returns `None`: the seam abstains, and
  the *caller* decides what `None` means (the PRD's accepted contract: a broken triage
  command never shrinks the replay budget — the turn goes to full replay). A score is
  only ever produced from a stdout JSON object that carried `{"score": float,
  "confidence": float}` within `[0, 1]`.
- **Unset is ABSENT, not a failure.** `triage_from_env` returns `None` for an
  unset/blank/un-lexable `BELAY_TRIAGE_AUTHOR` — triage is simply not configured, so the
  caller replays everything, and every verdict and exit code is unchanged.
- **Only derived features leave.** The payload carries exactly the whitelisted keys —
  tool name, tri-state annotation hints, annotation-object presence, offered toolset,
  reply size, hashes, turn index/seq, ordering, truncated flag, state-handle status,
  trace-context ids, protocol version, `run_process` command_line. Never raw state or
  trace bytes: `TriageFeatures` makes them structurally unrepresentable, and
  `build_triage_payload` asserts the emitted key set against `WHITELISTED_KEYS`.

Nothing here is a verdict: the score only orders and samples the replay queue; replay and
execution still decide. This module is stdlib only (dataclasses, json, os, shlex,
subprocess, typing).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

#: The env var naming the triage command line, shlex-split: e.g. "jev triage" or
#: "/usr/local/bin/my-triage". Unset/blank/un-lexable -> triage is ABSENT (None).
TRIAGE_ENV = "BELAY_TRIAGE_AUTHOR"

#: The default timeout for one triage invocation, in seconds. A timeout kills the triage
#: command and returns None (the turn goes to full replay); a hanging command never hangs
#: `belay verify`.
TRIAGE_TIMEOUT = 60.0

#: Cap on the triage command's captured stdout, in bytes: output past this is truncated
#: before parsing, so a huge (or runaway) command can never be parsed or held in full.
_MAX_OUTPUT = 1024 * 1024

#: The exact key set `build_triage_payload` may emit. Derived features only — never raw
#: state or trace bytes; a turn whose only useful signal would require raw egress is not
#: triaged (it goes to full replay).
WHITELISTED_KEYS = frozenset(
    {
        "tool_name",
        "read_only_hint",
        "destructive_hint",
        "idempotent_hint",
        "open_world_hint",
        "annotations_present",
        "offered_toolset",
        "reply_size",
        "hash_raw",
        "hash_canonical",
        "turn_index",
        "request_seq",
        "ordering",
        "truncated",
        "state_handle_status",
        "trace_id",
        "span_id",
        "protocol_version",
        "command_line",
    }
)


@dataclass(frozen=True)
class TriageFeatures:
    """Whitelisted derived features for one turn; raw state or trace bytes are unrepresentable.

    Every field is a derived scalar — the tool name, the tri-state annotation hints
    (`None` = the server declared nothing; a default is never a declaration), the
    hashes rather than the content they digest, indices and ids rather than the frames
    they point at. There is deliberately no field that could hold raw content: what is
    sent is named in the PRD and asserted on the constructed payload in a test.
    """

    tool_name: str
    read_only_hint: Optional[bool] = None
    destructive_hint: Optional[bool] = None
    idempotent_hint: Optional[bool] = None
    open_world_hint: Optional[bool] = None
    annotations_present: bool = False
    offered_toolset: tuple[str, ...] = ()
    reply_size: int = 0
    hash_raw: str = ""
    hash_canonical: str = ""
    turn_index: int = 0
    request_seq: int = 0
    ordering: int = 0
    truncated: bool = False
    state_handle_status: str = ""
    trace_id: str = ""
    span_id: str = ""
    protocol_version: str = ""
    command_line: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        """One JSON-serializable dict, keys sorted, exactly `WHITELISTED_KEYS`.

        A field added to this dataclass without being whitelisted is a contract break —
        the payload would carry something the PRD never named — so the emitted key set
        is asserted against `WHITELISTED_KEYS` rather than silently filtered.
        """
        payload = dict(
            sorted(
                {
                    "tool_name": self.tool_name,
                    "read_only_hint": self.read_only_hint,
                    "destructive_hint": self.destructive_hint,
                    "idempotent_hint": self.idempotent_hint,
                    "open_world_hint": self.open_world_hint,
                    "annotations_present": self.annotations_present,
                    "offered_toolset": list(self.offered_toolset),
                    "reply_size": self.reply_size,
                    "hash_raw": self.hash_raw,
                    "hash_canonical": self.hash_canonical,
                    "turn_index": self.turn_index,
                    "request_seq": self.request_seq,
                    "ordering": self.ordering,
                    "truncated": self.truncated,
                    "state_handle_status": self.state_handle_status,
                    "trace_id": self.trace_id,
                    "span_id": self.span_id,
                    "protocol_version": self.protocol_version,
                    "command_line": self.command_line,
                }.items()
            )
        )
        if set(payload) != WHITELISTED_KEYS:
            raise ValueError(
                "TriageFeatures drifted from WHITELISTED_KEYS: "
                f"{sorted(set(payload) ^ WHITELISTED_KEYS)}"
            )
        return payload


def build_triage_payload(features: TriageFeatures) -> dict[str, Any]:
    """The JSON-serializable payload for one turn: exactly `WHITELISTED_KEYS`.

    The whitelist guard lives in `TriageFeatures.to_payload` — this is the seam's one
    entry point so a caller can never construct an off-whitelist payload by hand.
    """
    return features.to_payload()


@dataclass(frozen=True)
class TriageScore:
    """A calibrated suspicion score for one turn, with the model's stated confidence.

    Both values are floats in `[0, 1]` — enforced at parse, never at use. A score only
    orders and samples the replay queue; it is never a verdict.
    """

    score: float
    confidence: float


class Triage(Protocol):
    """The seam: `triage(features) -> TriageScore | None`, `None` = abstain, fail-closed.

    The engine depends on this protocol, never on a model — Jev, laya, a local model or
    a shell script are all one command behind `SubprocessTriage`.
    """

    def triage(self, features: TriageFeatures) -> Optional[TriageScore]: ...


class NullTriage:
    """The default: no triage command configured — every turn goes to full replay.

    Always abstains; there is no command to spawn and no I/O of any kind. Unset is
    ABSENT, never a failure.
    """

    def triage(self, features: TriageFeatures) -> Optional[TriageScore]:
        return None


class SubprocessTriage:
    """A `Triage` that shells out to one user-supplied command (BYOK, zero-dep).

    The command runs with the whitelisted-features payload on stdin and its stdout
    parsed fail-closed: `{"score", "confidence"}` in `[0, 1]` becomes the `TriageScore`;
    `{"error"}` and every other failure shape return `None`. Never raises — every
    failure path is an abstention, and the caller decides what `None` means (full
    replay: a broken triage command never shrinks the replay budget).
    """

    def __init__(self, command: tuple[str, ...], timeout: float = TRIAGE_TIMEOUT):
        self.command = command
        self.timeout = timeout

    def triage(self, features: TriageFeatures) -> Optional[TriageScore]:
        payload = json.dumps(build_triage_payload(features), sort_keys=True)
        try:
            proc = subprocess.run(
                self.command,
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except Exception:  # noqa: BLE001  (timeout or launch failure is an abstention, never a crash)
            return None
        if proc.returncode != 0:
            return None
        stdout = proc.stdout[:_MAX_OUTPUT].decode("utf-8", errors="replace")
        return _parse_score(stdout)


def _parse_score(stdout: str) -> Optional[TriageScore]:
    """One stdout payload, fail-closed: `{"score", "confidence"}` in `[0, 1]` -> TriageScore.

    `{"error": ...}` is an abstention; malformed JSON, a non-object payload, a missing,
    non-numeric or boolean `score`/`confidence`, or either value outside `[0, 1]` are all
    failures — a score is never guessed from a shape the contract does not name.
    """
    try:
        payload = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if "error" in payload:
        return None
    score = payload.get("score")
    confidence = payload.get("confidence")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    if not (0.0 <= score <= 1.0) or not (0.0 <= confidence <= 1.0):
        return None
    return TriageScore(score=float(score), confidence=float(confidence))


def triage_from_env(env: Mapping[str, str] | None = None) -> Optional[SubprocessTriage]:
    """The configured triage command, or `None` when triage is ABSENT — never a crash.

    Reads `BELAY_TRIAGE_AUTHOR` from `os.environ` (when `env` is `None`) or from the given
    mapping, shlex-splits it into the command line, and returns a `SubprocessTriage`.
    Unset, blank, or un-lexable (unbalanced quotes) -> `None`: absent, never a failure —
    the caller replays everything, and every verdict and exit code is unchanged.
    """
    source = os.environ if env is None else env
    raw = (source.get(TRIAGE_ENV) or "").strip()
    if not raw:
        return None
    try:
        command = tuple(shlex.split(raw))
    except ValueError:
        return None
    if not command:
        return None
    return SubprocessTriage(command)


__all__ = [
    "TRIAGE_ENV",
    "TRIAGE_TIMEOUT",
    "WHITELISTED_KEYS",
    "Triage",
    "TriageFeatures",
    "TriageScore",
    "NullTriage",
    "SubprocessTriage",
    "build_triage_payload",
    "triage_from_env",
]