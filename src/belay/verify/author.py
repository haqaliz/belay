"""A3 — the out-of-process BYOK check author: the user's command writes the check.

A3's model-backed author, behind the `CheckAuthor` seam: the agent claimed something;
this adapter turns the claim plus the observed facts into an executable `Check` by
**shelling out to a user-supplied command** — BYOK by construction. `BELAY_CLAIM_AUTHOR`
names a command line (shlex-split); Belay writes one JSON object to its stdin —
`{"claim", "classification", "turns": [{"tool", "seq"}...], "final_state_files"}` — and
the command answers on stdout with `{"source": <the check, verbatim>, "argv": [...]}` or
`{"error": <reason>}`.

The honesty contract, stated once here (spec acceptance 1-4):

- **Nothing leaves the box.** The command is whatever the user points at — a local model
  CLI, their own script — with no vendor key, no proxying, no network, and no model SDK
  import anywhere (the wheel stays zero-dependency, and the zero-LLM guard stays trivially
  satisfied). The reference implementation ships no model client by design.
- **Fail-closed, never raising.** Any failure — `{"error": ...}`, a non-zero exit,
  malformed stdout, a timeout, output past the 1 MiB cap — returns `None`, which the
  evaluator reads as `NO_CHECK_AUTHOR` (UNVERIFIED). A check is only ever produced from a
  stdout JSON object that carried `{"source": str, "argv": [str, ...]}`.
- **Unset is ABSENT, not a failure.** `author_from_env` returns `None` for an
  unset/blank/un-lexable `BELAY_CLAIM_AUTHOR` — the axis is simply not configured, so the
  evaluator returns `None` and surfaces render the coverage note; never UNVERIFIED, never
  PASS, never a crash.
- **The check travels verbatim.** `source` and `argv` are passed through untouched — the
  check a reader sees is exactly what the author command wrote.

Nothing here is a verdict: the authored check is executed later, by the runner seam, and
the exit code decides. This module is stdlib only (subprocess, json, shlex, os).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Mapping, Optional, Sequence

from belay.verify.claims import Check
from belay.verify.trajectory import TurnFact

#: The env var naming the author command line, shlex-split: e.g. "claude -p ..." or
#: "/usr/local/bin/my-author". Unset/blank/un-lexable -> the axis is ABSENT (None).
AUTHOR_ENV = "BELAY_CLAIM_AUTHOR"

#: The default timeout for one author invocation, in seconds. A timeout kills the author
#: and returns None (NO_CHECK_AUTHOR); the author never hangs the evaluator.
AUTHOR_TIMEOUT = 60.0

#: Cap on the author's captured stdout, in bytes: output past this is truncated before
#: parsing, so a huge (or runaway) author can never be parsed or held in full.
_MAX_OUTPUT = 1024 * 1024


def author_from_env(env: Mapping[str, str] | None = None) -> Optional[SubprocessAuthor]:
    """The configured author, or `None` when the axis is ABSENT — never a crash.

    Reads `BELAY_CLAIM_AUTHOR` from `os.environ` (when `env` is `None`) or from the given
    mapping, shlex-splits it into the command line, and returns a `SubprocessAuthor`.
    Unset, blank, or un-lexable (unbalanced quotes) -> `None`: absent, never UNVERIFIED,
    never PASS — the evaluator treats `None` as "claim axis not configured".
    """
    source = os.environ if env is None else env
    raw = (source.get(AUTHOR_ENV) or "").strip()
    if not raw:
        return None
    try:
        command = tuple(shlex.split(raw))
    except ValueError:
        return None
    if not command:
        return None
    return SubprocessAuthor(command)


class SubprocessAuthor:
    """A `CheckAuthor` that shells out to one user-supplied command (BYOK, zero-dep).

    The command runs with the JSON prompt on stdin and its stdout parsed fail-closed:
    `{"source", "argv"}` becomes the `Check` verbatim; `{"error"}` and every other
    failure shape return `None`. Never raises — every failure path is an abstention.
    """

    def __init__(self, command: tuple[str, ...], timeout: float = AUTHOR_TIMEOUT):
        self.command = command
        self.timeout = timeout

    def author_check(
        self,
        claim_text: str,
        *,
        classification: str,
        turns: Sequence[TurnFact],
        final_state_files: Sequence[str],
    ) -> Optional[Check]:
        prompt = json.dumps(
            {
                "claim": claim_text,
                "classification": classification,
                "turns": [{"tool": turn.tool_name, "seq": turn.turn_index} for turn in turns],
                "final_state_files": list(final_state_files),
            },
            sort_keys=True,
        )
        try:
            proc = subprocess.run(
                self.command,
                input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except Exception:  # noqa: BLE001  (timeout or launch failure is an abstention, never a crash)
            return None
        if proc.returncode != 0:
            return None
        stdout = proc.stdout[:_MAX_OUTPUT].decode("utf-8", errors="replace")
        return _parse_check(stdout)


def _parse_check(stdout: str) -> Optional[Check]:
    """One stdout payload, fail-closed: `{"source", "argv"}` -> Check, anything else -> None.

    `{"error": ...}` is an abstention; malformed JSON, a non-object payload, a non-str
    `source`, or a non-`[str, ...]` `argv` are all failures — a check is never guessed
    from a shape the contract does not name.
    """
    try:
        payload = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if "error" in payload:
        return None
    source = payload.get("source")
    argv = payload.get("argv")
    if not isinstance(source, str) or not isinstance(argv, list):
        return None
    if not all(isinstance(token, str) for token in argv):
        return None
    return Check(source=source, argv=tuple(argv))


__all__ = [
    "AUTHOR_ENV",
    "AUTHOR_TIMEOUT",
    "SubprocessAuthor",
    "author_from_env",
]