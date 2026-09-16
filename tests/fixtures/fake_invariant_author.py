"""The deterministic CI fake author for `belay invariant infer` (invariant-authoring).

Implements the author protocol (`src/belay/authoring/protocol.py`): Belay writes one
JSON object to the command's stdin — `{"task", "rules", "library", ["repo"]}` — and the
command answers on stdout with `{"model", "candidates": [...]}` or `{"error": ...}`.

This fixture answers with a FIXED candidate set — `no-assertion-weakening` scoped to
`tests/` and `no-create` scoped to `generated/`, the D-12 vocabulary the
`corpus-fixtures` aspect measures — and answers `{"error": ...}` when the prompt
violates the contract, so a round-trip through it proves the protocol really sent the
task, the rule vocabulary and the library: a mis-wired seam reads as `AUTHOR_FAILED`
in the e2e, never a silent empty proposal. Deterministic, no network, no model: the
CI fake.
"""

import json
import sys

REQUIRED_KEYS = ("task", "rules", "library")

MODEL = "fake-invariant-author"

CANDIDATES = [
    {
        "scope": "tests/",
        "rule": "no-assertion-weakening",
        "rationale": "the task forbids weakening the tests' assertions",
    },
    {
        "scope": "generated/",
        "rule": "no-create",
        "rationale": "the task forbids creating files under generated/",
    },
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"error": "stdin was not JSON"}))
        return 0
    if not isinstance(payload, dict):
        print(json.dumps({"error": "stdin was not a JSON object"}))
        return 0
    missing = [key for key in REQUIRED_KEYS if key not in payload]
    if missing:
        print(json.dumps({"error": "missing required key(s): " + ", ".join(missing)}))
        return 0
    print(json.dumps({"model": MODEL, "candidates": CANDIDATES}))
    return 0


if __name__ == "__main__":
    sys.exit(main())