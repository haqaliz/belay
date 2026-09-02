"""The deterministic CI fake author: reads the stdin JSON prompt, validates the contract keys.

The author contract (`src/belay/verify/author.py`): Belay writes one JSON object to the
command's stdin — `{"claim", "classification", "turns", "final_state_files"}` — and the
command answers on stdout with `{"source": ..., "argv": [...]}` or `{"error": ...}`.

This fixture answers with a FIXED check, and answers with `{"error": ...}` when the
prompt violates the contract — so a round-trip through it proves the adapter really sent
the four required keys, and it never manufactures a passing shape. Deterministic, no
network, no model: the CI fake.
"""

import json
import sys

REQUIRED_KEYS = ("claim", "classification", "turns", "final_state_files")

CHECK = {"source": "echo ok", "argv": ["sh", "-c", "exit 0"]}


def main() -> int:
    try:
        prompt = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"error": "stdin was not JSON"}))
        return 0
    if not isinstance(prompt, dict):
        print(json.dumps({"error": "stdin was not a JSON object"}))
        return 0
    missing = [key for key in REQUIRED_KEYS if key not in prompt]
    if missing:
        print(json.dumps({"error": "missing required key(s): " + ", ".join(missing)}))
        return 0
    print(json.dumps(CHECK))
    return 0


if __name__ == "__main__":
    sys.exit(main())