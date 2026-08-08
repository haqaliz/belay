#!/usr/bin/env bash
# Probe: does the claude CLI complete on subscription auth with --safe-mode added to the
# full mint argv, from a scrubbed env, with no API key read or passed?
# Feasibility probe, not a measurement (plan S-3). Run once; output committed verbatim.
set -euo pipefail
uv run python - <<'PY'
import os
import subprocess

argv = [
    "claude", "-p", "Reply with the single word OK.",
    "--output-format", "json",
    "--model", "claude-opus-5",
    "--tools", "",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--safe-mode",
    "--system-prompt", "You are a probe.",
]

env = {k: v for k, v in os.environ.items()
       if k in ("HOME", "PATH", "USER", "TMPDIR", "LANG", "LC_ALL")}

r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=600)

print("exit:", r.returncode)
print("--- stdout ---")
print(r.stdout)
print("--- stderr ---")
print(r.stderr)
print("--- child env assertion ---")
print("ANTHROPIC_API_KEY in child env:", "ANTHROPIC_API_KEY" in env)
print("ANTHROPIC_AUTH_TOKEN in child env:", "ANTHROPIC_AUTH_TOKEN" in env)
print("ANTHROPIC_BASE_URL in child env:", "ANTHROPIC_BASE_URL" in env)
PY
