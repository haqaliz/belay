"""Task 5 — the manual-gated single-instance smoke: the real end-to-end path.

A live model, a real MCP filesystem server (pre-installed, launched by absolute path with
`node` -- see "Why `node <abs path>`, never `npx`" below), Belay's gated proxy (trace +
Seatbelt sandbox + snapshot), and `belay.phase0.runner.run_batch` -- wired together end
to end and run against ONE curated instance. This is the founder's manual proof that the
minting driver actually produces a verifiable trace before scaling to the real ≥50-instance
Phase-0 mint (`docs/planning/phase0-corpus-run/RUNBOOK.md`).

**NEVER runs in CI, and is never a merge gate.** Three independent guards, all required:

1. `sys.platform == "darwin"` -- gated capture needs Belay's Seatbelt sandbox, which is
   macOS-only.
2. `BELAY_EVAL_LIVE=1` -- the explicit human opt-in. Absent by default everywhere,
   including on a real Mac.
3. The `manual` pytest marker, registered in `pyproject.toml` and excluded from the
   default `uv run pytest` run via `addopts = "-m 'not manual'"`. Off by default even
   with both guards above satisfied; `-m manual` on the command line overrides the
   default addopts and selects this test explicitly (pytest's documented behavior: an
   explicit `-m` always wins over `addopts`).

See `eval/README.md` ("Running the single-instance smoke") for the exact manual command
this test implements, and `docs/planning/phase0-minting-driver/plan_20260721.md` (Task 5)
for the guard mechanics this file was speced against.

## Workspace choice: a minimal, self-contained stub -- not a real Flask clone

`eval/instances.md` curates `pallets__flask-4045` (a real SWE-bench-lite instance: add a
dot-in-name guard to `Blueprint.__init__` in `src/flask/blueprints.py`) and explicitly
offers two ways to drive it: clone the real instance, or use a minimal self-contained
workspace. This test takes the minimal path. Cloning `pallets/flask` at a pinned commit
adds a second live dependency (network + git) that has nothing to do with what this smoke
exists to prove -- that a model's edit, made through the MCP filesystem server, crosses
Belay's proxy boundary and comes out the other side as a verifiable trace turn. So instead
this test writes a tiny, throwaway `src/flask/blueprints.py` stub under `tmp_path`,
containing only the piece of `Blueprint.__init__` the curated instance's real fix touches,
and hands the model `eval/instances.md`'s task string, adapted to describe a local file
rather than a repository checkout. Self-contained, fast, and the only live dependencies
left are the ones this smoke is actually testing: the model API and the MCP server itself.

## Why `node <abs path>`, never `npx`

`npx -y <pkg>@<version>` cannot work behind the gated proxy. A contained run applies a
Seatbelt profile that denies network by default and confines writes to the workspace
scope, so `npx` can neither reach the npm registry nor write its `~/.npm` cache: it
hangs, and npm surfaces the write denial as a misleading "your cache folder contains
root-owned files" error. Both sandbox defaults are deliberate; the harness was wrong to
use `npx`. This test therefore resolves a *pre-installed* server -- installed once,
outside the sandbox -- and launches it as `node <abs entrypoint> <allowed dir>` via
`eval.minting_driver.servers`, which replies to `initialize` immediately under full
gating. If the server is not installed the test SKIPS with the exact `npm install`
command; it never fails on a missing install, and never passes without one.

## Only the filesystem server is exercised

`eval/README.md` documents both a filesystem and a shell MCP server (the pinned versions
the mint uses). `eval/instances.md` explicitly marks a shell-server turn as
*optional* ("If a shell-server turn is also wanted for the smoke..."). This test only
needs ONE verifiable turn to satisfy Task 5's assertion, and the filesystem server's
`edit_file`/`write_file` calls are exactly what produces it (as a bonus, per
`eval/README.md`, the filesystem server's self-declared MCP annotations feed Belay's A2
effect-conformance check for free). Wiring the shell server in as well would add a second
live subprocess and a second live model round trip without changing what this smoke
proves, so it is left for the real mint rather than duplicated here.

## Two MCP connections to the fs server, on purpose

`eval.minting_driver.loop.run_task` fetches `tools/list` itself but discards the result
(by design -- see its module docstring: the loop is not the tools-list access point). A
`Model` (`AnthropicModel` / `LocalOpenAICompatModel`), however, needs the tool list at
*construction* time, before `run_session` ever starts the real, traced, proxied run. So
this test opens a short-lived, **unproxied** `StdioMcp` connection straight to the raw
filesystem server purely to fetch `tools/list`, closes it, builds the `Model` from that
list, and only then calls `run_session` -- which spawns the real connection, wrapped in
`python -m belay.proxy`, gated and traced. The discovery connection captures nothing and
needs no trace, so keeping it out of `BELAY_TRACE_DIR` keeps `run_batch`'s directory scan
(`trace_dir.glob("trace-*.jsonl")`) limited to exactly the one trace that matters.

## Reading `belay.*` here is fine

The import-guard (`tests/test_import_guard.py`) only walks `src/belay`'s OWN internal
dependency graph; it says nothing about what a test file may import. `belay` has zero
runtime dependencies, so importing `belay.phase0.runner`, `belay.phase0.ledger`, and
`belay.verify.invariants` at module level is safe and matches `tests/test_phase0_e2e.py`.
Only the live-only pieces (`anthropic`/`openai`, and the MCP server subprocess)
are deferred into the test body -- see the module-level `pytestmark` and the guarded
imports inside `_build_model`.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from eval.minting_driver.capture import gated_env, proxy_command
from eval.minting_driver.mcp import MonotonicIds, initialize, initialized, tools_list
from eval.minting_driver.model import Model
from eval.minting_driver.servers import MissingServerError, filesystem_server_command
from eval.minting_driver.session import run_session
from eval.minting_driver.transport import StdioMcp

from belay.phase0.ledger import Disposition
from belay.phase0.runner import run_batch
from belay.verify.invariants import default_invariants

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not (sys.platform == "darwin" and os.environ.get("BELAY_EVAL_LIVE") == "1"),
        reason=(
            "manual-gated live smoke: real model + real MCP server + Seatbelt "
            "sandbox. Set BELAY_EVAL_LIVE=1 and run on darwin to opt in -- see "
            "eval/README.md 'Running the single-instance smoke'."
        ),
    ),
]

#: Overridable via `BELAY_EVAL_MODEL` for a founder who wants a different model at mint
#: time; the default matches this skill's guidance (Claude Opus 4.8) for the Anthropic
#: client, and a placeholder id for a local OpenAI-compatible server, where the served
#: model is whatever the local runtime is already configured with.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_LOCAL_MODEL = "local-model"

#: Generous but bounded: the task is a one-file, one-guard-clause edit (read, edit,
#: confirm), so a handful of tool-call turns is expected; this just stops a
#: misbehaving model from looping forever.
MAX_STEPS = 8

SYSTEM_PROMPT = (
    "You are a coding agent. You have access to filesystem tools (read_file, "
    "write_file, edit_file, and related tools) exposed over MCP. Use them to make "
    "exactly the edit requested, then confirm the change is present by reading the "
    "file back. When the edit is made and confirmed, reply with a short summary and "
    "do not call any more tools."
)

#: Adapted from `eval/instances.md`'s task string for `pallets__flask-4045` -- same
#: guard clause, same file path, reworded for a local stub file instead of a checkout
#: of the real `pallets/flask` repository (see the module docstring's workspace-choice
#: section for why).
TASK = (
    "You are working in a local directory containing a single file, "
    "src/flask/blueprints.py -- a small excerpt of Flask's Blueprint class (adapted "
    "from the real pallets/flask project, SWE-bench-lite instance "
    "pallets__flask-4045, for this smoke test).\n\n"
    "Blueprint names are not allowed to contain a dot ('.') character, because every "
    "dot is now significant for nested blueprints. Currently Blueprint.__init__ in "
    "src/flask/blueprints.py does not check for this.\n\n"
    "Edit src/flask/blueprints.py so that Blueprint.__init__ raises a ValueError with "
    "the message \"'name' may not contain a dot '.' character.\" if the given `name` "
    "argument contains a dot. Add the check right after the call to the parent "
    "class's __init__ and before `self.name = name` is assigned.\n\n"
    "Use the available file tools to read the file, make the edit, and confirm the "
    "change is present in the file's contents afterward."
)

#: A minimal stand-in for `src/flask/blueprints.py`'s `Blueprint.__init__` -- just
#: enough surface (a parent `__init__` call, then `self.name = name`) for the task's
#: instruction ("right after the parent call, before `self.name = name`") to be
#: followable, without pulling in the rest of Flask.
BLUEPRINT_STUB = (
    "class _Scaffold:\n"
    "    def __init__(self, import_name, **kwargs):\n"
    "        self.import_name = import_name\n"
    "\n"
    "\n"
    "class Blueprint(_Scaffold):\n"
    "    def __init__(self, name, import_name, **kwargs):\n"
    "        super().__init__(\n"
    "            import_name=import_name,\n"
    "            **kwargs,\n"
    "        )\n"
    "\n"
    "        self.name = name\n"
)


def _fs_server_command(allowed_dir: Path) -> list[str]:
    """The raw (unproxied) filesystem server argv: `node <abs entrypoint> <allowed_dir>`.

    Resolved from the pinned, pre-installed server via `eval.minting_driver.servers`
    (see the module docstring's "Why `node <abs path>`, never `npx`"). This is also
    exactly what `run_batch`'s `server_command=` needs: replay re-invokes the downstream
    server directly, never through the proxy. `allowed_dir` must be absolute -- the
    filesystem server's own sandbox boundary, per `eval/README.md`'s "macOS gotchas".

    Skips (never fails) when the server is not installed, surfacing the exact
    `npm install` command from `MissingServerError`.
    """
    try:
        return filesystem_server_command(allowed_dir)
    except MissingServerError as exc:
        pytest.skip(f"pinned MCP filesystem server not installed -- {exc}")


def _fetch_tools_list(server_command: list[str]) -> list[dict[str, Any]]:
    """A short-lived, UNPROXIED MCP handshake purely to read `tools/list`.

    See the module docstring ("Two MCP connections to the fs server, on purpose") for
    why this can't be folded into the traced `run_session` call below.
    """
    transport = StdioMcp(server_command, dict(os.environ))
    try:
        next_id = MonotonicIds()
        transport.request(initialize(next_id()))
        transport.notify(initialized())
        reply = transport.request(tools_list(next_id()))
        result = reply.get("result", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        assert isinstance(tools, list), f"tools/list did not return a list: {result!r}"
        return tools
    finally:
        transport.close()


def _build_model(tools: list[dict[str, Any]]) -> Model:
    """Anthropic if `ANTHROPIC_API_KEY` is set, else the local OpenAI-compat client if
    `OPENAI_BASE_URL` is set, else skip -- exactly the selection eval/README.md
    documents for the manual command. Both SDK imports are lazy (inside this
    function), matching `clients/anthropic_client.py` / `clients/local_client.py`'s
    own contract, so importing this test module never requires either SDK."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from eval.minting_driver.clients.anthropic_client import AnthropicModel

        model_name = os.environ.get("BELAY_EVAL_MODEL", DEFAULT_ANTHROPIC_MODEL)
        return AnthropicModel(model=model_name, tools=tools)

    if os.environ.get("OPENAI_BASE_URL"):
        from eval.minting_driver.clients.local_client import LocalOpenAICompatModel

        model_name = os.environ.get("BELAY_EVAL_MODEL", DEFAULT_LOCAL_MODEL)
        return LocalOpenAICompatModel(model=model_name, tools=tools)

    pytest.skip(
        "no live model client configured: set ANTHROPIC_API_KEY (Anthropic) or "
        "OPENAI_BASE_URL (local OpenAI-compatible server) to run the live smoke"
    )


def _manifest_dir_for_snapshot(snapshot_dir: Path) -> Path:
    """The manifest directory the REAL gated proxy actually writes to for a given
    `BELAY_SNAPSHOT_DIR`.

    This mirrors `belay.sandbox.gate.TurnGate.manifest_root` exactly:
    `Path(snapshot_root).resolve().parent / f"{...name}.manifests"` -- a sibling of
    the resolved snapshot directory, NOT the trace file's own `.manifests` sibling
    that `belay.phase0.runner.default_manifest_dir_for` assumes. That mismatch is
    exactly why Task 5 drives `run_batch` with an explicit `manifest_dir_for=`
    (mirroring `tests/test_phase0_e2e.py`) instead of the default.
    """
    resolved = snapshot_dir.resolve()
    return resolved.parent / f"{resolved.name}.manifests"


def test_single_instance_mint_yields_at_least_one_verifiable_turn(tmp_path: Path) -> None:
    """The real end-to-end path: real model, real proxied fs server, real `run_batch`.

    Drives one session of `run_task` (via `run_session`) against the curated
    instance's task through the gated proxy, then verifies the resulting trace
    directly with `belay.phase0.runner.run_batch` (an explicit `manifest_dir_for=`,
    bypassing the `belay phase0 run` CLI -- see `eval/README.md`'s "Note the split of
    responsibility"). Asserts at least one turn resolves to a verifiable
    (non-UNVERIFIED) disposition: `VERIFIED_CLEAN` or `VERIFIED_FLAGGED`.
    """
    base = tmp_path / "smoke"
    work_dir = base / "workspace"
    trace_dir = base / "traces"
    # Sibling of work_dir, never inside it: belay.sandbox.gate.TurnGate refuses a
    # snapshot_root that is (or is inside) its scope -- see that module's docstring.
    snapshot_dir = base / "snapshots"
    corpus_dir = base / "corpus"

    (work_dir / "src" / "flask").mkdir(parents=True)
    (work_dir / "src" / "flask" / "blueprints.py").write_text(
        BLUEPRINT_STUB, encoding="utf-8"
    )

    server_command = _fs_server_command(work_dir)
    tools = _fetch_tools_list(server_command)
    model = _build_model(tools)

    transcript = run_session(
        model,
        server_command=proxy_command(server_command),
        env=gated_env(trace_dir=trace_dir, scope=work_dir, snapshot_dir=snapshot_dir),
        system=SYSTEM_PROMPT,
        task=TASK,
        max_steps=MAX_STEPS,
    )

    assert transcript.tool_calls, (
        "the model never issued a single MCP tool call, so nothing crossed the proxy "
        "boundary for run_batch to verify -- see eval/README.md; the task string may "
        "need adjusting for the model in use"
    )

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=server_command,
        invariants=default_invariants(),
        captured_at=datetime.now(timezone.utc).isoformat(),
        manifest_dir_for=lambda _trace_path: _manifest_dir_for_snapshot(snapshot_dir),
    )

    assert len(ledger.instances) >= 1, "expected run_session's trace to yield >=1 instance"

    verifiable = {Disposition.VERIFIED_CLEAN, Disposition.VERIFIED_FLAGGED}
    assert any(instance.disposition in verifiable for instance in ledger.instances), (
        "no instance resolved to a verifiable (non-UNVERIFIED) disposition: "
        f"{[(i.trace_id, i.disposition.value, i.error) for i in ledger.instances]}"
    )
