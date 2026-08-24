# Runbook: time-to-first-verdict (aspect `stranger-timing`)

Part of `docs/planning/pypi-publish/prd.md` (launch checklist **L4**). This is the
runbook for L4's remaining DONE clause: **time-to-first-verdict < 15 minutes,
measured by a stranger following the quickstart** (`docs/planning/launch-readiness/CHECKLIST.md`
→ L4). It makes the measurement reproducible, so the post-merge operator step is a
20-minute task with a recordable result. See `plan_20260824.md` and `spec.md` in this
directory; the completion contract it writes into is the L4 entry the `quickstart-flip`
aspect already set up.

---

## 1 · What this measures

**Time-to-first-verdict** is the wall-clock time from the stranger starting the
runbook's timed command block to the moment `belay verify` prints its first verdict
line together with the coverage line that bounds it.

- **Stopwatch starts** at the first command of §3 (the `uv tool install` command).
- **Stopwatch stops** when `belay verify` prints the `turn 0` verdict line
  (`turn 0   write_note        PASS`) **and** the coverage line that travels with it
  (the aggregate `effect:network  NOT observed for 1/1 turn(s)` line — a `PASS` is a
  pass *on the dimensions Belay checks*, and the coverage line says which dimension
  was excluded). Stated this explicitly so two timers agree.

**n=1 is a measurement, not a guarantee.** A single clean-box run under 15 minutes
is evidence the quickstart is not an obstacle to a stranger; it is not a bound on
any other machine, network, or Python version. Record the number as exactly that —
one measurement, with its environment — never as "Belay installs in N minutes".

---

## 2 · Clean-box preconditions

A **fresh macOS or Linux box** (a VM is fine — say it is one in the record). The point
is a machine that has never had `belay-harness` on it: CI proves the *built artifact*
installs; this measures a stranger on a real box.

- **OS:** macOS (Apple Silicon or Intel) or Linux (measured on `ubuntu-24.04`,
  kernel ≥ 5.13 with Landlock enabled — see §4 for the named limits).
- **Python:** 3.10–3.12 (`requires-python = ">=3.10"`). Record the version used.
- **Installer:** [uv](https://github.com/astral-sh/uv) recommended
  (`uv tool install`). `pipx`/`pip` are alternates — see the note at the end of §3.
- **Record before you start:** the OS + version, whether it is a VM, the Python
  version, and the install path (for uv: `$(uv tool dir)/belay-harness`, default
  `~/.local/share/uv/tools/belay-harness`).

---

## 3 · The timed path

Mirrors the flipped README quickstart exactly: install the live PyPI package
(`belay-harness`, the `belay` command) → `belay --help` → the minimal capture →
verify example → the first verdict.

**Reference shape:** `tests/fixtures/docker_roundtrip_server.py` (with its
`docker_roundtrip_client.py` / `docker_roundtrip_trace.py` helpers) is the exact
shape this reproduces — a tiny deterministic stdio MCP server with one mutating
tool, driven through `python -m belay.proxy`, one `tools/call` that writes a file,
then `belay verify`. The inline scripts below are **self-contained** versions of
that shape (no fixture imports), so a stranger who only has the installed package
can paste them.

The two inline `await_recorded` waits are load-bearing, not decoration: the proxy
forwards ahead of recording by design, so a fast client+server can have the
`tools/list` REPLY recorded *after* the `tools/call` request. The annotation
snapshot then has nothing to read, and the effect verdict abstains — a green-looking
run that verified strictly less. The waits close that window by polling the trace
file itself (no sleeps tuned to one machine). Both are the reference fixture's waits,
inlined.

> **Start the stopwatch on the first command below. Paste the whole block.**

```bash
# ────────────────────────────────────────────────────────────────
# §3 · THE TIMED PATH — paste from here down
# ────────────────────────────────────────────────────────────────

# 3.1  Install — the README's headline command, verbatim.
uv tool install belay-harness

# 3.2  Sanity: the `belay` command exists.
belay --help

# 3.3  Enter the environment uv just installed, so `python`, `belay` and
#      `python -m belay.proxy` all resolve to the installed package.
source "$(uv tool dir)/belay-harness/bin/activate"

# 3.4  A fresh workspace. `$HOME` keeps paths canonical on macOS, where
#      `/var` is a symlink to `/private/var` and relocation compares strings —
#      `WS="$(pwd -P)"` makes every path below the resolved form.
mkdir -p ~/belay-demo/workspace && cd ~/belay-demo/workspace
WS="$(pwd -P)"

# 3.5  server.py — one deterministic MCP tool, `write_note`.
cat > server.py <<'PY'
"""A deterministic stdio MCP server with one mutating tool: write_note."""

import base64
import glob
import json
import os
import sys
import time

TOOL = {
    "name": "write_note",
    "description": "Write one fixed note to the given path.",
    "inputSchema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "annotations": {"readOnlyHint": False, "openWorldHint": False},
}


def _reply(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message).encode() + b"\n")
    sys.stdout.buffer.flush()


def await_recorded(direction: str, **fields) -> None:
    """Block until the trace holds a `direction` frame matching `fields`."""
    trace_dir = os.environ.get("BELAY_TRACE_DIR")
    if not trace_dir:
        return  # nothing is being captured (replay, or a bare run)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        for path in glob.glob(os.path.join(trace_dir, "*.jsonl")):
            for line in open(path, "rb"):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a partially written final line; the next poll gets it
                if record.get("kind") != "frame":
                    continue
                try:
                    message = json.loads(base64.b64decode(record["raw"]))
                except (KeyError, ValueError):
                    continue
                if (
                    isinstance(message, dict)
                    and record.get("dir") == direction
                    and all(message.get(k) == v for k, v in fields.items())
                ):
                    return
        time.sleep(0.005)
    raise AssertionError("the trace never recorded the awaited frame")


def main() -> None:
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method, msg_id = message.get("method"), message.get("id")

        if method == "initialize":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "timed-demo", "version": "1"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue  # a notification: no reply, ever
        elif method == "tools/list":
            await_recorded("c2s", method="tools/list")
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [TOOL]}})
        elif method == "tools/call":
            target = message["params"]["arguments"]["path"]
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("note\n")
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": "wrote note"}],
                        "isError": False,
                    },
                }
            )


if __name__ == "__main__":
    main()
PY

# 3.6  client.py — a sequenced stdio client that drives the gated proxy.
cat > client.py <<'PY'
"""A sequenced stdio client: drives the gated proxy and leaves a captured trace."""

import base64
import glob
import json
import os
import subprocess
import sys
import time


def await_recorded(direction: str, **fields) -> None:
    trace_dir = os.environ["BELAY_TRACE_DIR"]
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        for path in glob.glob(os.path.join(trace_dir, "*.jsonl")):
            for line in open(path, "rb"):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("kind") != "frame":
                    continue
                try:
                    message = json.loads(base64.b64decode(record["raw"]))
                except (KeyError, ValueError):
                    continue
                if (
                    isinstance(message, dict)
                    and record.get("dir") == direction
                    and all(message.get(k) == v for k, v in fields.items())
                ):
                    return
        time.sleep(0.005)
    raise AssertionError("the trace never recorded the awaited frame")


def main() -> int:
    server, target = sys.argv[1], sys.argv[2]
    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", sys.executable, server],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    def send(message: dict, expect_reply: bool = True) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(message).encode() + b"\n")
        proc.stdin.flush()
        if not expect_reply:
            return
        line = proc.stdout.readline()
        assert line, f"the proxy closed without answering {message.get('method')!r}"

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "timed-demo", "version": "1"},
            },
        }
    )
    send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    # The reply is in hand; the point is that it is also in the TRACE.
    await_recorded("s2c", id=2)
    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "write_note", "arguments": {"path": target}},
        }
    )

    assert proc.stdin is not None
    proc.stdin.close()
    return proc.wait(timeout=60)


if __name__ == "__main__":
    sys.exit(main())
PY

# 3.7  Capture one turn: gated proxy -> snapshot -> trace.
BELAY_SANDBOX_SCOPE="$WS" \
BELAY_SNAPSHOT_DIR="$WS/../snapshots" \
BELAY_TRACE_DIR="$WS/../traces" \
  python client.py server.py "$WS/note.txt"

# 3.8  First verdict: restore pre-state -> re-execute -> diff -> PASS.
belay verify "$WS/../traces"/trace-*.jsonl \
  --manifest-dir "$WS/../snapshots.manifests" \
  --server python "$WS/server.py"
```

**What "first verdict" looks like** (abridged; the important lines):

```
turns
  turn 0   write_note        PASS
      A2 replay    PASS        replayed reply reproduced the recorded reply
      A2 effect    PASS        effect-conformance PASS: tool 'write_note' declared readOnlyHint: false ...
      A2 effect:networkNOT_COVERED openWorldHint conformance NOT_COVERED: ... Belay does not observe network egress ...

aggregate
  turns verified        1
  PASS                  1
  WARN                  0
  FAIL                  0
  UNVERIFIED            0

  coverage (NOT_COVERED — outside what Belay observes; never a PASS)
    effect:network      NOT observed for 1/1 turn(s)
```

**Stop the stopwatch** the moment the `turn 0  write_note  PASS` line **and** the
`effect:network  NOT observed for 1/1 turn(s)` coverage line have both printed. If the
turn comes back anything but `PASS` with `UNVERIFIED 0`, the run did not complete —
do not record a time; investigate (most often a path detail below) and re-run.

**Why `$(pwd -P)` appears everywhere (the one easy trap).** On macOS `/var` is a
symlink to `/private/var`, and replay relocates whole-value in-root paths by **string
comparison** against the recorded `source_root` (which is realpath'd at capture). A
`$PWD` that still reads `/var/folders/...` therefore fails to relocate — the replayed
server then tries to write into the live workspace, the sandbox refuses it, and the
turn comes back `UNVERIFIED` with `server-exited`. Using `WS="$(pwd -P)"` for the
scope, the write target, and the `--server` command keeps every path resolved, and is
the difference between the `PASS` above and an honest `UNVERIFIED` that looks like a
flaky replay.

**Alternates (pipx / pip), same shape.** `pipx install belay-harness` or
`pip install belay-harness` install the same package; the only change is where
`python -m belay.proxy` and the `--server` interpreter resolve from. With pipx,
replace the activation with the pipx venv's python:
`"$HOME/.local/share/pipx/venvs/belay-harness/bin/python"` for both the client run
and `--server`. With `pip install --user`, the `python` you installed with *is* the
one that has the package. Record which alternate was used.

---

## 4 · The live-install check (not timed, network-dependent)

The §3 install was the point of this whole aspect: `uv tool install belay-harness`
grabs the **live PyPI package**, not a local build — CI proves the built artifact,
only a real network install proves the published one. So on this same clean box,
confirm the artifact is real and the substrate is enforced:

```bash
belay --help
mkdir -p ~/belay-demo/scope
belay sandbox check --scope ~/belay-demo/scope
```

`belay sandbox check` decides the boundary **by using it** — it writes outside the
scope and (on Linux) opens an `AF_INET` socket, and reports what the kernel did.
Expected output:

- **macOS:** `platform darwin (ok)`, `sandbox-exec ... (ok)`, `containment ok (a write
  outside the scope was refused)`, `snapshot backend clonefile-apfs (ok)`,
  `belay: substrate ok`. macOS uses **Seatbelt** (`/usr/bin/sandbox-exec`).
- **Linux:** `platform linux (ok)`, `landlock kernel ABI N (ok)`,
  `containment ok (a write outside the scope was refused)`, `seccomp ok (an AF_INET
  socket was refused)`, `substrate ok`. Linux needs **kernel ≥ 5.13 with Landlock
  enabled**.

**Named limits, stated so the refusal is not a failure:** on a Linux host below
kernel 5.13, or with the LSM disabled, `sandbox check` **refuses** (exit 2) with the
named cause `landlock-unavailable` — expected output, never a fabricated pass; Belay
will not run unsandboxed. This is the honest-coverage posture the README documents:
a boundary that cannot be enforced is refused loudly, not claimed.

If the install resolved a version that does not match the release being launched,
**stop and flag it** — this check exists to catch exactly that mismatch.

---

## 5 · Record

The measurement is not real until it is written into the completion contract:

1. Open `docs/planning/launch-readiness/CHECKLIST.md`.
2. In the **L4** entry (→ *"PyPI publish + quickstart flip"*), record:
   - the **number** (time-to-first-verdict, in minutes/seconds);
   - the **environment** (OS + version, VM or bare metal, Python version);
   - the **install path** (e.g. `~/.local/share/uv/tools/belay-harness`) and installer;
   - the **timer identity**: the checklist gate wants "one person" — name **who**
     timed it (**stranger** vs **owner**). If no stranger is available, the degraded
     case is **owner-measured n=1 following the exact runbook** — supported, but the
     record must say it was the owner (the gate stays honest either way);
   - the **date**.
3. Append a matching row to the checklist's **progress log** table.
4. **Then** mark L4 **✅** — marking the box is the operator's act, and the only act
   that checks it. Nothing in this repo marks it for you.

An n=1 under the limit is recorded as *"1 measurement, clean box, < 15 min"* — a
measurement, not a guarantee — exactly as §1 says.
