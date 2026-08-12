"""The manual-gated live smoke for the DUAL-server mint — `--toolset filesystem+shell`, once.

Twin of `tests/test_minting_driver_claude_cli_smoke.py` (the single-server subscription
smoke), aimed at the one question the green offline tests cannot answer: they all fake
the shell session, so none of them shows whether the composite boundary — the pinned
filesystem server AND the pinned shell server (`mcp-server-commands`, offering
`run_process`) behind one gated proxy — actually drives a real session on a real
repository with the shell rooted at the instance workspace. The composite's routing map,
the merged tool list, `--toolset` parsing and the `cwd` Popen argument are pinned by
deterministic tests (`tests/test_minting_driver_composite.py`,
`tests/test_minting_driver_transport.py`); this smoke is the first evidence that the
composition works end to end on live servers, exactly as `mint-dual-server`'s plan
Phase 4 requires ("First evidence that a real dual-server mint session works
end-to-end").

**NEVER runs in CI, and is never a merge gate.** Three independent guards, all required —
the same three as the sibling smokes: `sys.platform == "darwin"` (gated capture needs
Belay's Seatbelt sandbox), `BELAY_EVAL_LIVE=1` (the explicit human opt-in), and the
`manual` marker, which `pyproject.toml`'s `addopts = "-m 'not manual'"` excludes from the
default run. An explicit `-m manual` on the command line overrides that addopts value.

**This file was written and committed BEFORE it had ever been run** (the freeze
protocol): the tooling is frozen first so the output cannot have been fitted to it. It
therefore contains no result, no expected verdict, and no expected rate. The run itself
is an operator step once `eval/servers/` is installed — see
`docs/planning/trajectory-toolset-rescope/mint-dual-server/smoke.md`, which states
explicitly that it was NOT run in the unit that shipped this test.

## What this smoke proves, and how

1. **Both pinned servers resolve and launch.** `resolve_server_entrypoint` for
   `filesystem` AND `shell`; a missing install is a FAIL (never a skip, never a quiet
   non-result) carrying the exact `npm install --prefix eval/servers ...` command from
   `MissingServerError` — the fail-fast path this module's `servers.py` exists for.
2. **One mint instance drives the composite boundary.** `mint_one` with
   `cfg.toolset="filesystem+shell"` and the subscription oracle (`--provider
   claude-cli`), exactly the composition the successor mint freezes — the smoke
   rehearses the batch path on one instance.
3. **The merged tool list reached the trace.** The capture's `tools/list` replies name
   BOTH servers' tools — `run_process` from the shell session AND the filesystem
   server's write tools — un-prefixed, verbatim. The schemas travel to the oracle as
   prompt data, so a missing name here is a WIRING report, never a model verdict.
4. **A `run_process` turn crossed the boundary.** At least one recorded `tools/call`
   names `run_process`.
5. **Per-instance shell cwd, asserted on live evidence.** The system prompt steers
   exactly one command first: `touch BELAY_PROBE.txt` with no path prefix. If the
   shell's cwd were not the instance workspace, the file would land somewhere else and
   the assertion `work_dir/BELAY_PROBE.txt exists` would fail. (The cwd is pinned
   structurally by `parse_toolset`/`Popen` tests; this is the live counterpart, and its
   absence — the oracle never running the probe — is a MODEL finding, never a harness
   pass.)
6. **The `run_process` turn replays verifiably.** The captured turn is re-invoked
   against the ROOTLESS pinned shell server command (the honest replay path for a shell
   turn, exactly as `tests/test_replay_relocation_shell_e2e.py` does it) and its
   verdict must be PASS or UNVERIFIED **with a named cause** — never the
   no-snapshot `NOT_VERIFIABLE` shape (a silent miss), and never FAIL (a finding to
   record and stop, per the plan: "if the shell server misbehaves on the smoke
   instance, record the finding ... and stop").

## What this test does NOT assert, deliberately

* **No verdict on the stock `belay phase0 run`'s shell-turn rows.** The stock run
  re-invokes every turn against the single `--server` filesystem command the mint
  prints, so its shell-turn rows may legitimately read FAIL or UNVERIFIED there; the
  smoke asserts only that the stock path resolves the capture (exit 0, no
  `INSTRUMENT SUSPECT`) and echoes every row it produced, FAILs included — a shell turn
  failing on the stock path is a real finding for the successor mint's verify
  composition, recorded in the aspect dir, not asserted away.
* **Nothing about edit quality or the trajectory verdict.** Execution evidence and
  human adjudication are separate evidence grades and are never merged; n=1 is not a
  base rate.
* **No per-turn `belay phase0 run` verdict.** The ledger's dispositions are echoed,
  never interpreted.

## Reading `belay.*` here is fine

Same reason as the sibling smoke: the import guard walks `src/belay`'s own dependency
graph, not a test's imports, and `belay` has zero runtime dependencies. `belay.cli.main`
is imported because `[project.scripts] belay = "belay.cli:main"` — calling it with an
argv list IS the stock `belay phase0 run`, with no bespoke path or manifest handling.
`verify_turn` is the same per-turn API the shell relocation e2e tests drive.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from eval.minting_driver.checkpoint import load_checkpoint
from eval.minting_driver.clients.claude_cli_client import (
    DEFAULT_CLAUDE_CLI_MODEL,
    PROVIDER_NAME,
)
from eval.minting_driver.entrypoint import MintConfig, mint_one, verify_server_command
from eval.minting_driver.servers import (
    MissingServerError,
    resolve_server_entrypoint,
    server_root,
)
from eval.minting_driver.workspace import layout_for

from belay.cli import main as belay_main
from belay.frames import message_of
from belay.phase0.ledger import from_json
from belay.phase0.report import instrument_suspect
from belay.phase0.runner import default_manifest_dir_for
from belay.replay.reader import read_trace
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not (sys.platform == "darwin" and os.environ.get("BELAY_EVAL_LIVE") == "1"),
        reason=(
            "manual-gated live smoke: the real `claude` CLI on subscription "
            "credentials + a real git clone + BOTH pinned MCP servers (filesystem + "
            "shell) + Seatbelt sandbox. Set BELAY_EVAL_LIVE=1 (and point "
            "BELAY_EVAL_SERVER_ROOT at an existing install if eval/servers is absent) "
            "and run on darwin to opt in -- see "
            "docs/planning/trajectory-toolset-rescope/mint-dual-server/smoke.md."
        ),
    ),
]

#: The one instance this smoke drives. Same choice as the single-server subscription
#: smoke (`tests/test_minting_driver_claude_cli_smoke.py`): not one of the 15 banked
#: instances, it names its own file and hook, and its record is byte-identical in
#: `pool.json` and `selected.json`. Reusing it keeps the two smokes comparable — same
#: repo, same task, same oracle — so the toolset is the only variable changed.
INSTANCE_ID = "pytest-dev__pytest-7432"

#: EXPLICIT, and a full model id rather than an alias. Overridable for a re-run under a
#: different model; whatever is passed is what the recorded provenance is asserted
#: against, so the two cannot drift.
MODEL = os.environ.get("BELAY_EVAL_MODEL") or DEFAULT_CLAUDE_CLI_MODEL

#: The shell server's tool, as `servers.py` pins it and the trace must advertise it.
#: Verbatim and un-prefixed — the composite merges tool names as-is, because the
#: trajectory evidence gate matches this exact name (`trajectory.py:155`).
SHELL_TOOL_NAME = "run_process"

#: The filesystem server's write tools, as `eval/README.md` names them and as the
#: installed `@modelcontextprotocol/server-filesystem@2026.7.10` advertises them. A
#: merged-list assertion must find BOTH servers' tools or the composite's merge (or the
#: trace's tools/list capture) is broken.
WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})

#: Repo root = one level up from `tests/`.
_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Override to mint into a fresh root — the documented way to retry after a *setup*
#: failure, and the only way to re-drive an instance that already produced an observation.
MINT_ROOT_ENV = "BELAY_EVAL_MINT_ROOT"

#: Gitignored (`/eval/mint/`), durable, and never `tmp_path` — same rationale as the
#: sibling smoke: this run produces a REAL mint capture, the evidence the write-up
#: cites, and snapshot manifests record absolute paths so a capture cannot be moved.
DEFAULT_MINT_ROOT = _REPO_ROOT / "eval" / "mint" / "live-smoke-dual-server"

#: Cached bare clones, shared with every other mint (`/eval/clones/`, gitignored).
CLONES_DIR = _REPO_ROOT / "eval" / "clones"

#: The pool, not the draw: this instance was chosen by hand.
REGISTRY_PATH = _REPO_ROOT / "eval" / "instances" / "pool.json"

#: The system prompt. The mint's own DEFAULT_SYSTEM_PROMPT knows nothing about shell
#: tools, so the smoke adds the cwd probe: exactly one `touch BELAY_PROBE.txt` with no
#: path prefix, run FIRST. The probe is what makes "per-instance shell cwd" a live,
#: assertable fact rather than a construction claim.
SYSTEM_PROMPT = (
    "You are a coding agent. You have filesystem tools (read_file, write_file, "
    "edit_file, and related tools) AND the run_process shell tool, which executes "
    "commands with the repository workspace as its working directory.\n\n"
    "First, run exactly this command via run_process (no path prefix -- it must land "
    "in the repository root, which IS your working directory):\n"
    "    touch BELAY_PROBE.txt\n\n"
    "Then use the file tools to make the requested edit, and confirm the change is "
    "present by reading the file back. When the edit is made and confirmed, reply "
    "with a short summary and do not call any more tools."
)

#: The engine's exact NOT_VERIFIABLE cause (`replay/engine.py`): "no snapshot was
#: attempted for this turn; there is no pre-state to restore". A run_process turn whose
#: verdict carries THIS cause never replayed — nothing was even attempted — which is
#: the silent-miss shape the smoke must refuse: the whole point of gating is that every
#: turn carries a snapshot.
_NO_SNAPSHOT_CAUSE = (
    "no snapshot was attempted for this turn; there is no pre-state to restore"
)

#: The report's coverage-boundary heading (`belay.phase0.report._coverage_section`).
_COVERAGE_HEADING = "coverage (NOT_COVERED"


def _resolve_servers() -> tuple[Path, Path, Path]:
    """Both pinned servers' entrypoints (and the install root), or a loud FAIL.

    Resolved through `servers.server_root` (so `$BELAY_EVAL_SERVER_ROOT` overrides the
    default in-repo `eval/servers/`), then `resolve_server_entrypoint` per server. A
    missing install is a `pytest.fail`, never a skip and never a silent non-result: the
    `MissingServerError` message carries the exact `npm install --prefix ...` command,
    and this check runs BEFORE the clone and before any spend. The install root is
    returned too, because `MintConfig.server_root` must be told it explicitly.
    """
    root = server_root()
    try:
        fs_entrypoint = resolve_server_entrypoint("filesystem", root=root)
        shell_entrypoint = resolve_server_entrypoint("shell", root=root)
    except MissingServerError as exc:
        pytest.fail(f"pinned MCP server not installed -- {exc}")
    return fs_entrypoint, shell_entrypoint, root


def _records(trace_path: Path) -> list[dict]:
    """The trace's records, read with Belay's own reader (skips surfaced, never silent)."""
    result = read_trace(trace_path)
    assert not result.skips, (
        "the reader could not accept every record in the capture, so this trace is not "
        f"fully readable: {result.skips}"
    )
    return result.records


def _tool_call_params(records: list[dict]) -> list[dict[str, Any]]:
    """Every recorded `tools/call` request's `params`, in capture order.

    Reads the frames the proxy recorded, exactly as `belay.verify.effect._tool_name`
    does: the tool name is `params.name` off the client-to-server request frame. The
    order is the order `replay.engine.tool_calls` indexes by (both walk the records in
    order), so the positional index of a call here is the `n` `verify_turn` expects.
    A frame that cannot be read is skipped rather than turned into a fabricated call.
    """
    calls: list[dict[str, Any]] = []
    for record in records:
        if record.get("kind") != "frame" or record.get("dir") != "c2s":
            continue
        message, cause = message_of(record)
        if cause is not None or not isinstance(message, dict):
            continue
        if message.get("method") != "tools/call":
            continue
        params = message.get("params")
        if isinstance(params, dict):
            calls.append(params)
    return calls


def _advertised_tool_names(records: list[dict]) -> set[str]:
    """The tool names the SERVERS advertised, off the `tools/list` replies in this trace.

    Matched structurally — a server-to-client response whose `result` carries a `tools`
    list — because only `tools/list` replies have that shape. Both sessions' replies
    land in the same trace, so this set is exactly the merged list the oracle was
    offered (verbatim, un-prefixed).
    """
    names: set[str] = set()
    for record in records:
        if record.get("kind") != "frame" or record.get("dir") != "s2c":
            continue
        message, cause = message_of(record)
        if cause is not None or not isinstance(message, dict):
            continue
        result = message.get("result")
        if not isinstance(result, dict):
            continue
        tools = result.get("tools")
        if not isinstance(tools, list):
            continue
        for tool in tools:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                names.add(tool["name"])
    return names


def test_dual_server_mint_drives_run_process_end_to_end(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One instance under `--toolset filesystem+shell`, end to end, on the subscription
    oracle.

    `mint_one` (composite boundary: both servers proxied, merged tool list into the
    prompt) -> real `git clone` at `base_commit` -> gated capture through
    `python -m belay.proxy` -> `bridge_capture` -> the **stock** `belay phase0 run`
    -> replay of the captured `run_process` turn against the pinned shell server. Then
    the assertions the plan Phase 4 lists, and an echo of everything the run showed.
    """
    fs_entrypoint, shell_entrypoint, server_install_root = _resolve_servers()

    mint_root = Path(os.environ.get(MINT_ROOT_ENV) or DEFAULT_MINT_ROOT).resolve()
    cfg = MintConfig(
        root=mint_root,
        model=MODEL,
        provider=PROVIDER_NAME,
        clones_dir=CLONES_DIR,
        registry_path=REGISTRY_PATH,
        server_root=server_install_root,
        system=SYSTEM_PROMPT,
        # The toolset under test: both pinned servers on one boundary. The default
        # `filesystem` is exactly the single-server path and is NOT what this smoke
        # exists to prove.
        toolset="filesystem+shell",
        # `request_timeout` and `max_steps` are left at the entry point's own defaults
        # on purpose: this smoke has to rehearse what a batch would do.
    )

    # Refused BEFORE the clone and before any spend. `mint_one` would silently skip an
    # instance the checkpoint already records, and this run would then report
    # "0 captured" for a reason that has nothing to do with the boundary. Re-driving an
    # instance that already produced an observation is exactly what the anti-re-roll
    # contract forbids: mint into a fresh root instead.
    if load_checkpoint(cfg.checkpoint_path).is_done(INSTANCE_ID):
        pytest.fail(
            f"{INSTANCE_ID} already has a recorded disposition in "
            f"{cfg.checkpoint_path} "
            f"({load_checkpoint(cfg.checkpoint_path).status(INSTANCE_ID)!r}): this "
            f"instance has already been driven under this root. Re-running it would be "
            f"a re-roll after seeing a result. Set {MINT_ROOT_ENV} to a fresh "
            f"directory if the previous attempt was a SETUP failure that produced no "
            f"observation."
        )

    report = mint_one(INSTANCE_ID, cfg)

    assert report.captured == 1, (
        "the mint captured nothing for this instance, so there is no dual-server "
        f"capture to read: status={report.checkpoint.status(INSTANCE_ID)!r} "
        f"reason={report.checkpoint.reason(INSTANCE_ID)!r}\n{report.render()}"
    )

    # ---- the capture exists, in the layout the stock runner resolves ----
    trace_path = report.batch_dir / f"trace-{INSTANCE_ID}.jsonl"
    manifests_dir = report.batch_dir / f"trace-{INSTANCE_ID}.manifests"
    assert trace_path.is_file(), (
        f"no bridged capture at {trace_path}: `bridge_capture` is the load-bearing "
        f"wiring test, and a mis-wire here reads as INSTRUMENT SUSPECT -- a fake PIVOT"
    )
    assert manifests_dir.is_dir(), (
        f"no manifests sibling at {manifests_dir}: without it every turn resolves "
        f"UNVERIFIED and the run reads as INSTRUMENT SUSPECT rather than as a result"
    )

    # ---- the STOCK `belay phase0 run` resolves the capture ----
    # `belay.cli.main` is the console script's own entry point, called with an argv
    # list; `--server` is REMAINDER and therefore last, and `{workspace}` is ONE
    # argument replaced per trace with that trace's own recorded `source_root` -- the
    # exact command the mint prints. `--no-ingest`: a single unadjudicated turn from a
    # one-off smoke must not enter the corpus.
    ledger_path = mint_root / "phase0-dual-server-smoke.json"
    exit_code = belay_main(
        [
            "phase0",
            "run",
            str(report.batch_dir),
            "--ledger",
            str(ledger_path),
            "--corpus-dir",
            str(mint_root / "corpus-never-written"),
            "--no-ingest",
            "--server",
            *verify_server_command(fs_entrypoint),
        ]
    )
    phase0_output = capsys.readouterr().out
    assert exit_code == 0, (
        f"stock `belay phase0 run` exited {exit_code} (a HARD error -- it exits 0 even "
        f"with violations present):\n{phase0_output}"
    )

    ledger = from_json(json.loads(ledger_path.read_text(encoding="utf-8")))
    assert [inst.trace_id for inst in ledger.instances] == [f"trace-{INSTANCE_ID}"], (
        "the stock runner did not resolve exactly this instance's capture: "
        f"{[inst.trace_id for inst in ledger.instances]}"
    )
    instance = ledger.instances[0]

    # INSTRUMENT SUSPECT is the one outcome that IS refused: it is a wiring report,
    # never a result. Asserted on BOTH the mechanism and the surface.
    assert not instrument_suspect(ledger), (
        "INSTRUMENT SUSPECT fired: the capture yielded no verifiable turn, so this run "
        f"is a wiring report and NOT a result. disposition={instance.disposition.value} "
        f"turns={instance.turn_status_counts} unverified={instance.unverified_causes} "
        f"error={instance.error!r}\n{phase0_output}"
    )
    assert "INSTRUMENT SUSPECT" not in phase0_output, (
        f"the report printed an INSTRUMENT SUSPECT block:\n{phase0_output}"
    )
    assert _COVERAGE_HEADING in phase0_output, (
        "the report carries no coverage boundary, so its statuses are rendered without "
        f"the limits of what Belay observed:\n{phase0_output}"
    )

    # ---- the trace's tools/list names BOTH servers' tools, verbatim ----
    records = _records(trace_path)
    advertised = _advertised_tool_names(records)
    # FIRST, so a missing tool can be attributed. The schemas reach the oracle as
    # prompt DATA, so if the trace's tools/list never advertised a tool the oracle
    # could not have proposed it: that is a WIRING report, never a model verdict.
    assert SHELL_TOOL_NAME in advertised, (
        f"the trace's tools/list never advertised {SHELL_TOOL_NAME!r} -- the merged "
        f"composite list (or its capture) is broken. Advertised: {sorted(advertised)}"
    )
    assert WRITE_TOOL_NAMES & advertised, (
        "the trace's tools/list never advertised the filesystem server's write tools "
        f"({sorted(WRITE_TOOL_NAMES)}); advertised: {sorted(advertised)}. The composite "
        "merge must carry BOTH servers' tools -- this is a WIRING report."
    )

    # ---- a run_process turn crossed the boundary ----
    calls = _tool_call_params(records)
    shell_indices = [
        index
        for index, params in enumerate(calls)
        if params.get("name") == SHELL_TOOL_NAME
    ]
    assert shell_indices, (
        "no recorded tools/call named run_process: the boundary offered the tool (the "
        f"tools/list assertion passed) but the oracle never used it. Calls in order: "
        f"{[params.get('name') for params in calls]}"
    )

    # ---- per-instance shell cwd, asserted on live evidence ----
    # The probe (`touch BELAY_PROBE.txt`, no path prefix) lands in the shell's cwd. It
    # must be at the instance workspace root, or the shell session was not rooted at
    # the workspace (the construction claim `parse_toolset` pins structurally, asserted
    # here on the real run).
    work_dir = layout_for(INSTANCE_ID, mint_root).work_dir
    probe = work_dir / "BELAY_PROBE.txt"
    assert probe.is_file(), (
        f"the cwd probe {probe} does not exist after the mint: the oracle never ran "
        f"`touch BELAY_PROBE.txt` in the workspace, or the shell's cwd was not the "
        f"instance workspace. This is a MODEL finding if the command was never issued "
        f"-- read the run_process calls ({shell_indices}) in the trace -- and a WIRING "
        f"finding if it was issued and landed elsewhere."
    )

    # ---- the run_process turn replays verifiably ----
    # The FIRST run_process turn is the mandated probe. Replay it against the ROOTLESS
    # pinned shell server command (the honest replay path for a shell turn, as the
    # shell relocation e2e tests do) and require PASS or UNVERIFIED-with-cause -- never
    # the no-snapshot NOT_VERIFIABLE shape (a silent miss: nothing was even attempted)
    # and never FAIL (a finding to record and stop, per the plan).
    n_shell = shell_indices[0]
    verdict = verify_turn(
        records,
        n_shell,
        server_command=["node", str(shell_entrypoint)],
        manifest_dir=default_manifest_dir_for(trace_path),
        timeout=120.0,
    )
    assert verdict.tool_name == SHELL_TOOL_NAME, (
        f"verify_turn replayed a {verdict.tool_name!r} turn at index {n_shell}, not "
        f"{SHELL_TOOL_NAME!r}: the index derivation drifted from the replay engine's"
    )
    assert verdict.status is Status.PASS or verdict.status is Status.UNVERIFIED, (
        f"the run_process turn did not replay verifiably: status={verdict.status.value} "
        f"cause={verdict.cause!r}. A FAIL or silent non-replay on the shell turn is a "
        "FINDING to record in the aspect dir and stop -- see the plan's Phase 4 "
        "validation."
    )
    if verdict.status is Status.UNVERIFIED:
        assert verdict.cause, (
            "the run_process turn reduced to UNVERIFIED with no cause: UNVERIFIED "
            "always names its cause, and an unnamed one is the report's causeless "
            f"catch-all. verdict={verdict}"
        )
        assert verdict.cause != _NO_SNAPSHOT_CAUSE, (
            "the run_process turn never replayed: its verdict is the no-snapshot "
            "NOT_VERIFIABLE shape, meaning the gated capture attempted no pre-state for "
            "a turn that must carry one. That is a silent miss -- the gating did not "
            "happen -- and this smoke refuses it."
        )

    # ---- what this run showed, echoed to the REAL stdout ----
    # Facts only: no verdict is interpreted here, no rate is computed, and n=1 is not a
    # base rate. The stock-run rows are echoed verbatim -- including any FAIL on the
    # shell turns under the single `--server` filesystem command, which is a real
    # finding for the successor mint's verify composition, recorded not asserted away.
    with capsys.disabled():
        print(f"\ninstance:    {INSTANCE_ID}")
        print(f"provider:    {PROVIDER_NAME}")
        print(f"model:       {MODEL}")
        print("toolset:     filesystem+shell")
        print(f"root:        {mint_root}")
        print(f"work_dir:    {work_dir}")
        print(f"trace:       {trace_path}")
        print(f"ledger:      {ledger_path}")
        print(f"advertised:  {sorted(advertised)}")
        print(f"calls:       {[params.get('name') for params in calls]}")
        print(f"shell turns: {shell_indices}")
        print(f"cwd probe:   {probe} exists={probe.is_file()}")
        print(f"shell-turn replay: status={verdict.status.value} cause={verdict.cause!r}")
        print(f"disposition: {instance.disposition.value}")
        print(f"turns:       {instance.turn_status_counts}")
        print(f"flagged:     {instance.flagged_turns}")
        print(f"unverified:  {instance.unverified_causes}")
        print(f"not covered: {instance.not_covered_turns}")
        print(f"exposure:    {instance.exposure}")
        print()
        print(report.render())
        print()
        print(phase0_output)
