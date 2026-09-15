"""The author protocol: build the author's input, parse its output, run it.

The `authoring-protocol` aspect, phases 1-2: the JSON-in/JSON-out contract between
Belay and an operator-supplied **author command** (BYOK by construction — the engine
never calls a model). A model proposes task-specific A1 invariants from a task spec;
this module is the seam around that proposal. Nothing here is a verdict and nothing
here calibrates: `build_author_input` decides what the author is allowed to see, the
response parser turns stdout into validated `Candidate`s and named rejections, and
`SubprocessInvariantAuthor` runs the command fail-closed. Calibration against the
control trace happens later, in the infer orchestration, **by execution**.

The honesty contract, stated once:

- **D-7 — the author never sees the control.** The payload carries the task text, a
  bounded sorted repo inventory, the known rule vocabulary with its grounding, and the
  library entries. No control trace records, no trace path, no manifests — asserted on
  the serialized bytes by the test. Calibration is independent of the author.
- **Fail-closed, never raising.** A non-zero exit, a timeout, a launch failure,
  unparseable stdout, an unknown rule, a malformed candidate — every failure is a named
  outcome (`failure` or a per-candidate `rejection`), never a crash and never a policy
  silently swallowed. A bad author produces no policy, exactly as a bad invariant file
  produces a `ValueError` instead of a silent `[]`.
- **Candidates are proposals, not policy.** The parser validates shape and rule
  membership, deduplicates by `(rule, scope)` and orders deterministically; whether a
  candidate is *admitted* to A1 is decided later by calibration, never here. `scope`
  stays a `str` at this layer — `os.fsencode` happens where an `Invariant` is built,
  the one encoding paths take everywhere else in `src/belay`.

Stdlib only (`json`, `os`, `subprocess`, `dataclasses`).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from belay.verify.invariants import (
    LIBRARY,
    RULE_NETWORK_EGRESS,
    RULE_READ_ONLY,
    _KNOWN_RULES,
)

#: The named causes the protocol can produce. Infer-side rejection causes — never
#: verdicts; the verdict path has its own closed vocabulary. `NO_AUTHOR_CONFIGURED` is
#: defined here so the orchestration and the CLI share one namespace (dark by default:
#: `infer` without `--author` exits 2 with this cause, no fallback, no model import).
AUTHOR_FAILED = "AUTHOR_FAILED"
AUTHOR_OUTPUT_UNPARSEABLE = "AUTHOR_OUTPUT_UNPARSEABLE"
UNKNOWN_RULE = "UNKNOWN_RULE"
CANDIDATE_MALFORMED = "CANDIDATE_MALFORMED"
NO_AUTHOR_CONFIGURED = "NO_AUTHOR_CONFIGURED"

#: Default timeout for one author invocation, in seconds. A timeout kills the author
#: and reads as fail-closed — the author never hangs the engine.
AUTHOR_TIMEOUT = 60.0

#: Cap on the author's captured stdout, in bytes: output past this is truncated before
#: parsing, so a huge (or runaway) author can never be parsed or held in full.
MAX_AUTHOR_OUTPUT = 1024 * 1024

#: Cap on the repo inventory the author is shown: a huge repo must not blow the author
#: prompt or the artifact. The list is sorted first, then capped — deterministic.
REPO_FILE_CAP = 5000

#: The label given to the repository root in the author payload. `repo_files` are
#: relative paths; the actual directory basename is a property of the caller's
#: `--repo` resolution, not of this builder, so the root is a fixed, honest label.
DEFAULT_REPO_ROOT = "repo"


@dataclass(frozen=True)
class Candidate:
    """One invariant the author proposes: a `rule` scoped to a subtree.

    `scope` is a `str` path prefix exactly as the author wrote it (the `os.fsencode`
    to raw bytes happens where an `Invariant` is built, matching `load_invariants`).
    `rationale` is the model's reasoning — free text, **not policy**; a non-str
    rationale is tolerated as `None`.
    """

    scope: str
    rule: str
    rationale: Optional[str] = None


@dataclass(frozen=True)
class Rejection:
    """One candidate the parser refused, carrying what it could recover plus the cause.

    `scope`/`rule`/`rationale` are the attempted candidate's fields (each `None` when
    the payload shape prevented recovering them); `cause` is one of `UNKNOWN_RULE` or
    `CANDIDATE_MALFORMED`. The `--json` surface renders these so the operator can fix
    the task spec or the author.
    """

    scope: Optional[str] = None
    rule: Optional[str] = None
    rationale: Optional[str] = None
    cause: str = ""


@dataclass
class AuthorResponse:
    """The parsed author stdout: survivors, named rejections, or one failure.

    Exactly one of two shapes: either `failure` is set (an author-level failure —
    `AUTHOR_FAILED` or `AUTHOR_OUTPUT_UNPARSEABLE`) or the payload validated and
    `candidates`/`rejections` partition the proposed set (both may be empty). A
    candidate is dropped with a `Rejection`, never silently.

    `model` is the OPTIONAL top-level `"model"` string the author may report (the id
    of the model that wrote the proposal), parsed additively — absent, non-string, or
    an author-level failure carry `None`. It is provenance prose, not policy: it rides
    into the artifact's `author` section for review and is never part of any verdict or
    digest.
    """

    candidates: list[Candidate] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    failure: Optional[str] = None
    model: Optional[str] = None


#: The rule vocabulary sent to the author, in a fixed deterministic order: every member
#: of `_KNOWN_RULES` plus the library's `network-egress`, which is explicitly **not** a
#: member — the author must be told it exists so it does not waste a proposal on a name
#: the loader would reject, and told it is ungrounded so it knows what proposing it
#: means.
_RULE_VOCABULARY = (
    RULE_READ_ONLY,
    "no-assertion-weakening",
    "suite-before-success-claim",
    "no-create",
    "no-delete",
    RULE_NETWORK_EGRESS,
)

#: How each vocabulary rule is grounded, mirroring the shipped sets: delta for the
#: delta-only rules, delta(read-only) for the prefix rule, content for the two-tree
#: rule, trajectory for the instance-level rule, ungrounded for egress. An explicit
#: table keyed by name — a rule joining `_KNOWN_RULES` without a row here fails closed
#: at build time rather than silently mis-describing itself to the author.
_RULE_GROUNDING = {
    RULE_READ_ONLY: "delta(read-only)",
    "no-assertion-weakening": "content",
    "suite-before-success-claim": "trajectory",
    "no-create": "delta",
    "no-delete": "delta",
    RULE_NETWORK_EGRESS: "ungrounded",
}

#: One-line semantics for each vocabulary rule — what the rule asserts, in author terms.
_RULE_SEMANTICS = {
    RULE_READ_ONLY: "nothing under the scope may be written",
    "no-assertion-weakening": "an existing assertion may not be removed or weakened",
    "suite-before-success-claim": "the suite must execute before a success claim (instance-level)",
    "no-create": "nothing may appear under the scope",
    "no-delete": "nothing under the scope may disappear",
    RULE_NETWORK_EGRESS: "no network egress — unobservable, UNVERIFIED on every turn",
}


def build_author_input(
    *,
    task_text: str,
    repo_files: Optional[Sequence[str]] = None,
) -> dict:
    """The canonical author payload: task text, bounded repo, rule vocabulary, library.

    `task` is the task spec text verbatim; `repo` (only when `repo_files` is not
    `None`) is `{"root": <label>, "files": [sorted, capped at REPO_FILE_CAP]}` —
    `None` omits the repo entirely, an empty list carries an empty inventory; `rules`
    is every `_KNOWN_RULES` member plus `network-egress`, each with a `grounding`
    string and a one-line `semantics`; `library` is every `LIBRARY` entry's name and
    description.

    **D-7 by construction:** no argument here can carry a control trace, its path, or a
    manifest — the function has nothing to leak. The test still asserts on the
    serialized bytes so a future caller cannot smuggle one in.
    """
    payload: dict = {
        "task": task_text,
        "rules": [
            {
                "rule": rule,
                "grounding": _RULE_GROUNDING[rule],
                "semantics": _RULE_SEMANTICS[rule],
            }
            for rule in _RULE_VOCABULARY
        ],
        "library": [
            {"name": name, "description": LIBRARY[name].description}
            for name in sorted(LIBRARY)
        ],
    }
    if repo_files is not None:
        files = sorted(repo_files)[:REPO_FILE_CAP]
        payload["repo"] = {"root": DEFAULT_REPO_ROOT, "files": files}
    return payload


def parse_author_response(stdout: str) -> AuthorResponse:
    """One stdout payload -> validated candidates and named rejections, fail-closed.

    `{"candidates": [...]}` validates each candidate: an unknown rule is a `Rejection`
    with `UNKNOWN_RULE` (including `network-egress` — a name deliberately outside
    `_KNOWN_RULES`); a non-str scope/rule, or a non-dict candidate, is a
    `Rejection` with `CANDIDATE_MALFORMED`; a non-str rationale is tolerated as `None`.
    Survivors are deduplicated by `(rule, scope)` — first occurrence wins — and sorted
    by `(rule, scope)`. `{"error": ...}` is `AUTHOR_FAILED`; malformed JSON, a
    non-object payload, or a missing/non-list `candidates` is
    `AUTHOR_OUTPUT_UNPARSEABLE`. A top-level `"model"` string is carried additively
    (absent/non-string -> `None`). Never raises.
    """
    try:
        payload = json.loads(stdout)
    except ValueError:
        return AuthorResponse(failure=AUTHOR_OUTPUT_UNPARSEABLE)
    if not isinstance(payload, dict):
        return AuthorResponse(failure=AUTHOR_OUTPUT_UNPARSEABLE)
    # The OPTIONAL top-level model id, read once for every dict payload (success and
    # failure shapes alike) — additive: absent or non-string stays `None`.
    model = payload.get("model") if isinstance(payload.get("model"), str) else None
    if "error" in payload:
        return AuthorResponse(failure=AUTHOR_FAILED, model=model)
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return AuthorResponse(failure=AUTHOR_OUTPUT_UNPARSEABLE, model=model)

    response = AuthorResponse(model=model)
    seen: set[tuple[str, str]] = set()
    for item in raw_candidates:
        outcome = _validate_candidate(item)
        if isinstance(outcome, Rejection):
            response.rejections.append(outcome)
            continue
        key = (outcome.rule, outcome.scope)
        if key in seen:
            continue
        seen.add(key)
        response.candidates.append(outcome)
    response.candidates.sort(key=lambda c: (c.rule, c.scope))
    return response


def _validate_candidate(item: object) -> Candidate | Rejection:
    """One `candidates` list entry -> a `Candidate` or a named `Rejection`, never a crash."""
    if not isinstance(item, dict):
        return Rejection(cause=CANDIDATE_MALFORMED)
    rationale = item.get("rationale")
    if not isinstance(rationale, str):
        rationale = None
    scope = item.get("scope")
    rule = item.get("rule")
    if not isinstance(rule, str) or not rule:
        return Rejection(
            scope=scope if isinstance(scope, str) else None,
            rule=rule if isinstance(rule, str) else None,
            rationale=rationale,
            cause=CANDIDATE_MALFORMED,
        )
    if rule not in _KNOWN_RULES:
        return Rejection(
            scope=scope if isinstance(scope, str) else None,
            rule=rule,
            rationale=rationale,
            cause=UNKNOWN_RULE,
        )
    if not isinstance(scope, str):
        return Rejection(
            scope=scope if isinstance(scope, str) else None,
            rule=rule,
            rationale=rationale,
            cause=CANDIDATE_MALFORMED,
        )
    return Candidate(scope=scope, rule=rule, rationale=rationale)


class SubprocessInvariantAuthor:
    """Runs one user-supplied author command (BYOK, zero-dep), fail-closed.

    `command` is the argv tuple to launch; `author(payload)` serializes the payload
    (`sort_keys=True`), writes it to the command's stdin, captures stdout, and returns
    the decoded stdout `str` on success or `None` on **any** failure — non-zero exit,
    timeout, launch failure, or output past the 1 MiB cap. Never raises. The caller
    hands the returned stdout to `parse_author_response`.

    `runner` is the offline test seam, defaulting to `subprocess.run`: it is called as
    `runner(command, input=<bytes>, capture_output=True, timeout=..., check=False)` and
    its result must expose `returncode` and `stdout`. Tests drive real parsing through
    a fake runner; no model, no network, no binary.
    """

    def __init__(
        self,
        command: tuple[str, ...],
        timeout: float = AUTHOR_TIMEOUT,
        runner=None,
    ):
        self.command = command
        self.timeout = timeout
        self.runner = runner if runner is not None else subprocess.run

    def author(self, payload: Mapping) -> Optional[str]:
        """Serialize `payload` and run the author; return stdout `str` or `None`.

        Serialization failure, launch failure, a timeout, a non-zero exit, or an empty
        stdout all return `None` — a bad author reads as an abstention, never a crash
        and never a partial parse.
        """
        try:
            data = json.dumps(payload, sort_keys=True).encode("utf-8")
            proc = self.runner(
                self.command,
                input=data,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except Exception:  # noqa: BLE001  (timeout or launch failure is an abstention, never a crash)
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout[:MAX_AUTHOR_OUTPUT].decode("utf-8", errors="replace")


__all__ = [
    "AUTHOR_FAILED",
    "AUTHOR_OUTPUT_UNPARSEABLE",
    "UNKNOWN_RULE",
    "CANDIDATE_MALFORMED",
    "NO_AUTHOR_CONFIGURED",
    "AUTHOR_TIMEOUT",
    "MAX_AUTHOR_OUTPUT",
    "REPO_FILE_CAP",
    "DEFAULT_REPO_ROOT",
    "Candidate",
    "Rejection",
    "AuthorResponse",
    "build_author_input",
    "parse_author_response",
    "SubprocessInvariantAuthor",
]
