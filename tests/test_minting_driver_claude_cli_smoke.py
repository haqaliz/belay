"""The manual-gated live smoke for the SUBSCRIPTION oracle — `--provider claude-cli`, once.

Twin of `tests/test_minting_driver_smoke.py` (the API-key providers' smoke), aimed at the
one question twelve green offline tests cannot answer: they all fake the subprocess, so
none of them shows whether the `claude` CLI, driven as a *prompted* tool-call oracle,
actually drives a **file edit across the MCP boundary** on a real repository. The 2026-07-28
spec's headline risk is that prompted tool-calls are more brittle than native tool-use, and
`docs/planning/phase0-mint-execution/mint-execution/STAGE2_FINDINGS.md:25-39` records what
that looks like when it goes wrong: a model that only reads produces *"a 0% violation rate
that means the agent did nothing"* — worse than `INSTRUMENT SUSPECT`, because it looks like
a result. Untested, that risk surfaces during an ~11 h batch, where it is expensive.

**NEVER runs in CI, and is never a merge gate.** Three independent guards, all required —
the same three as the sibling smoke: `sys.platform == "darwin"` (gated capture needs
Belay's Seatbelt sandbox), `BELAY_EVAL_LIVE=1` (the explicit human opt-in), and the
`manual` marker, which `pyproject.toml`'s `addopts = "-m 'not manual'"` excludes from the
default run. An explicit `-m manual` on the command line overrides that addopts value.

**This file was written and committed BEFORE it had ever been run** (the freeze protocol,
`plan_20260805.md` S-3): the tooling is frozen first so the output cannot have been fitted
to it. It therefore contains no result, no expected verdict, and no expected rate.

## The instance: `pytest-dev__pytest-7432`, and why

* **`pytest-dev/pytest`** — pytest's tests live under `testing/`, which the shipped A1
  scope covers (`no-assertion-weakening` on any `tests` or `testing` path segment), and
  pytest scored **6/7** on `exposure-forecast`'s text signal, the highest with a
  meaningful denominator. A clean run on a repo the detector cannot see into would prove
  nothing about editing.
* **Not one of the 15 already banked** — the banked pytest instances are `5221`, `5227`,
  `5692` and `6116` (read off the committed ledgers under
  `docs/planning/under-firing-measurable/miss-measurement/ledgers/`); the other banked
  repos are `flask-4045`/`4992`, `pylint-5859`, and the requests/sphinx/sympy set. Driving
  a banked instance would re-introduce the fitted-on confound the re-measurement exists to
  avoid.
* **Among the unbanked pytest candidates (`7432`, `8365`, `8906`), this one names its own
  file and hook** — *"the bug is in `src/_pytest/skipping.py`, the `pytest_runtest_makereport`
  hook"* — so a trajectory that never reaches a write is evidence about the *oracle*, not
  about a twelve-step budget spent searching a large repo. That is the whole point of a
  one-instance smoke: keep the failure attributable.
* Its record is byte-identical in `eval/instances/pool.json` and `selected.json`; the
  registry read here is the pool, because this instance was chosen by hand rather than
  drawn.

## `--no-ingest`, deliberately (S-2)

`belay phase0 run` otherwise banks every flagged turn as a corpus case. A single
**unadjudicated** turn from a one-off smoke must not enter the corpus: the corpus is the
regression suite and its cases are human-labeled, so an unlabeled case from a run nobody
adjudicated is noise at best — and `corpus score` would then be computed over it. The flag
suppresses WRITES, never detection: every verdict, count and rate in the report is exactly
what it would have been with ingestion on. A throwaway `--corpus-dir` under the mint root
is passed as well, so even a future regression in the flag cannot reach `corpus/local`.

## The criterion is the TRAJECTORY, not the first call (S-5)

Probed 2026-08-05: given an edit task the oracle **read the file first**. That is correct
agent behaviour — read, edit, read back is what `DEFAULT_SYSTEM_PROMPT` asks for — so the
assertion below is *"some recorded `tools/call` is a write"*, never *"the first one is"*.
A trajectory of reads with no write is a **real result** (Rule A row 2, the STAGE2 shape)
and it means: do not launch a batch.

Before concluding anything about the model, the write-tool NAMES are checked against the
`tools/list` reply recorded in the same trace (the spec's second open question): the tool
schemas travel to the oracle as prompt data, so a name mismatch would look like model
failure when it is a wiring bug. That check fires first, and says so.

## Where the capture lands, and why it is not `tmp_path`

The sibling smoke writes a stub workspace under `tmp_path`, which is right for a
self-contained fixture and wrong here: this run produces a **real mint capture** — the
evidence the write-up cites — and `tmp_path` is reclaimed after three runs. Snapshot
manifests also record absolute paths, so a capture cannot be moved afterwards. The root is
therefore the gitignored `eval/mint/live-smoke-claude-cli/` (override with
`$BELAY_EVAL_MINT_ROOT`), and the resume checkpoint that root carries is the **anti-re-roll
contract in action**: an instance that already produced an observation is refused here
rather than silently re-driven (S-4 — a red is a finding to fix, not a draw to repeat).
Re-minting is a fresh root, never a checkpoint edit.

## What this test does NOT assert, deliberately

* **No verdict.** PASS, FAIL and UNVERIFIED are all acceptable outcomes of this aspect
  (spec criterion 4); only an *unreported* one is a failure. The verdict is echoed, never
  asserted — asserting one would be predicting the result the freeze protocol exists to
  keep unpredicted. `INSTRUMENT SUSPECT` is the one outcome that IS refused, because it is
  a wiring report rather than a result.
* **Nothing about edit quality**, and nothing about whether any edit weakened an
  assertion. Execution evidence and human adjudication are separate evidence grades and
  are never merged.
* **No rate.** n=1 is not a base rate.
* **The child env's contents.** That the metered credential is scrubbed out of the
  subprocess environment is pinned offline, against the real `_build_env`, in
  `tests/test_minting_driver_claude_cli.py`; a live run records no env, so the assertion
  available here is over the recorded PROVENANCE — which is exactly what spec criterion 5
  asks for ("asserted from the run's own recorded provenance, not from intent").

## Reading `belay.*` here is fine

Same reason as the sibling smoke: the import guard walks `src/belay`'s own dependency
graph, not a test's imports, and `belay` has zero runtime dependencies. `belay.cli.main` is
imported because `[project.scripts] belay = "belay.cli:main"` — calling it with an argv
list IS the stock `belay phase0 run`, with no bespoke path or manifest handling, which is
what spec criterion 2 requires.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from eval.minting_driver.checkpoint import load_checkpoint
from eval.minting_driver.clients.claude_cli_client import (
    DEFAULT_CLAUDE_CLI_MODEL,
    PROVIDER_NAME,
    SCRUBBED_ENV_VARS,
)
from eval.minting_driver.entrypoint import MintConfig, mint_one, verify_server_command
from eval.minting_driver.servers import (
    SERVER_ROOT_ENV,
    MissingServerError,
    resolve_server_entrypoint,
)

from belay.cli import main as belay_main
from belay.frames import message_of
from belay.phase0.ledger import from_json
from belay.phase0.report import instrument_suspect
from belay.replay.reader import read_trace

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not (sys.platform == "darwin" and os.environ.get("BELAY_EVAL_LIVE") == "1"),
        reason=(
            "manual-gated live smoke: the real `claude` CLI on subscription "
            "credentials + a real git clone + a real MCP server + Seatbelt sandbox. "
            "Set BELAY_EVAL_LIVE=1 (and BELAY_EVAL_SERVER_ROOT to the pinned server "
            "install) and run on darwin to opt in -- see "
            "docs/planning/subscription-model-client/live-smoke-confirmation/."
        ),
    ),
]

#: The one instance this smoke drives. See the module docstring for the choice.
INSTANCE_ID = "pytest-dev__pytest-7432"

#: EXPLICIT, and a full model id rather than an alias (`opus` resolves to whatever is
#: newest at call time, so two runs reporting the same string would not have used the same
#: model). Overridable for a re-run under a different model; whatever is passed is what the
#: recorded provenance is asserted against, so the two cannot drift.
MODEL = os.environ.get("BELAY_EVAL_MODEL") or DEFAULT_CLAUDE_CLI_MODEL

#: The pinned filesystem server's write tools, as `eval/README.md:108` names them and as
#: the installed `@modelcontextprotocol/server-filesystem@2026.7.10` advertises them. Held
#: as data because the assertion below cross-checks it against the trace's own `tools/list`
#: reply: a name this set does not contain is a WIRING report, not a model verdict.
WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})

#: Repo root = one level up from `tests/`. Used so the mint root and the clone cache are
#: the same directories regardless of the CWD pytest was invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Override to mint into a fresh root — the documented way to retry after a *setup*
#: failure, and the only way to re-drive an instance that already produced an observation.
MINT_ROOT_ENV = "BELAY_EVAL_MINT_ROOT"

#: Gitignored (`/eval/mint/`), durable, and never `tmp_path` — see the module docstring.
DEFAULT_MINT_ROOT = _REPO_ROOT / "eval" / "mint" / "live-smoke-claude-cli"

#: Cached bare clones, shared with every other mint (`/eval/clones/`, gitignored). A
#: setup-failure retry then costs no second clone of pytest.
CLONES_DIR = _REPO_ROOT / "eval" / "clones"

#: The pool, not the draw: this instance was chosen by hand. Its record is byte-identical
#: in `selected.json`, so the choice of file changes nothing that is measured.
REGISTRY_PATH = _REPO_ROOT / "eval" / "instances" / "pool.json"

#: Any Anthropic API key, whatever this box happens to export — checked against the
#: recorded provenance so the assertion is not vacuous on a box with no key set.
_KEY_SHAPED = re.compile(r"sk-ant-[A-Za-z0-9_-]+")

#: The report's coverage-boundary heading (`belay.phase0.report._coverage_section`). A
#: status rendered without its coverage line is the failure mode `NOT_COVERED` creates, so
#: spec criterion 4's "with its coverage line" is checked rather than assumed.
_COVERAGE_HEADING = "coverage (NOT_COVERED"


def _server_root() -> Path:
    """`$BELAY_EVAL_SERVER_ROOT`, or a loud FAIL naming what to set.

    Read from the environment rather than hardcoded: the pinned servers are installed in
    another worktree (`eval/servers/` does not exist in this one), they are version-pinned
    so pointing at the existing install is equivalent, and baking that path into a
    committed test would make the file wrong on every other box.

    A `fail`, not a `skip`: an unset install root is an operator setup mistake, and the one
    thing this aspect must never do is let a setup mistake read as a quiet non-result.
    """
    root = (os.environ.get(SERVER_ROOT_ENV) or "").strip()
    if not root:
        pytest.fail(
            f"{SERVER_ROOT_ENV} is unset: this smoke launches the PINNED MCP filesystem "
            f"server by absolute `node` path (npx cannot work behind the gated proxy -- "
            f"see eval/minting_driver/servers.py). Point it at an existing install, e.g. "
            f"{SERVER_ROOT_ENV}=<repo>/eval/servers, and re-run."
        )
    return Path(root).resolve()


def _entrypoint(server_root: Path) -> Path:
    """The installed filesystem server's entrypoint, or a FAIL carrying `npm install`.

    `mint_one` preflights this itself; it is resolved here as well because the stock
    `belay phase0 run` invocation below needs the same absolute path for `--server`, and
    because failing before the clone keeps a missing install cheap.
    """
    try:
        return resolve_server_entrypoint("filesystem", root=server_root)
    except MissingServerError as exc:
        pytest.fail(f"pinned MCP filesystem server not installed -- {exc}")


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

    Reads the frames the proxy recorded, exactly as `belay.verify.effect._tool_name` does:
    the tool name is `params.name` off the client-to-server request frame. A frame that
    cannot be read, or whose `params` are positional (JSON-RPC 2.0 permits that), is
    skipped rather than turned into a fabricated call.
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
    """The tool names the SERVER advertised, off the `tools/list` reply in this trace.

    Matched structurally — a server-to-client response whose `result` carries a `tools`
    list — because only `tools/list` replies have that shape, and the reply's own request
    id is not needed to identify it. This exists so a missing write can be attributed:
    the schemas reach the oracle as prompt data, so a name mismatch is a wiring bug that
    would otherwise be read as the model refusing to edit (spec open question 2).
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


def _writes(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `tools/call`s that are a write TO A FILE: a write tool naming a `path`.

    Both `write_file` and `edit_file` take the target as `path` (verified against the
    installed pinned server). A write tool called with no string path is not a write to a
    file, so it does not count here.
    """
    return [
        params
        for params in calls
        if params.get("name") in WRITE_TOOL_NAMES
        and isinstance(params.get("arguments"), dict)
        and isinstance(params["arguments"].get("path"), str)
        and params["arguments"]["path"].strip()
    ]


def test_claude_cli_provider_drives_one_instance_end_to_end(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One instance, end to end, on the subscription oracle — the unit's exit criterion.

    `mint_one` -> real `git clone` at `base_commit` -> gated capture through
    `python -m belay.proxy` -> `bridge_capture` -> the **stock** `belay phase0 run`
    -> replay. Then five assertions (spec criteria 1-6), and an echo of everything this
    aspect has to record: the disposition, the per-turn statuses, the exposure line, the
    accounting, and the trajectory's tool calls in order.
    """
    server_root = _server_root()
    entrypoint = _entrypoint(server_root)

    mint_root = Path(os.environ.get(MINT_ROOT_ENV) or DEFAULT_MINT_ROOT).resolve()
    cfg = MintConfig(
        root=mint_root,
        model=MODEL,
        provider=PROVIDER_NAME,
        clones_dir=CLONES_DIR,
        registry_path=REGISTRY_PATH,
        server_root=server_root,
        # `request_timeout`, `max_steps` and `system` are left at the entry point's own
        # defaults on purpose: this smoke has to rehearse what a batch would do, and a
        # bespoke budget here would measure a configuration no mint will ever use.
    )

    # Refused BEFORE the clone and before any spend. `mint_one` would silently skip an
    # instance the checkpoint already records (`is_done` is true for `captured` and
    # `failed`), and this run would then report "0 captured" for a reason that has nothing
    # to do with the oracle. Re-driving an instance that already produced an observation is
    # exactly what the anti-re-roll contract forbids: mint into a fresh root instead.
    if load_checkpoint(cfg.checkpoint_path).is_done(INSTANCE_ID):
        pytest.fail(
            f"{INSTANCE_ID} already has a recorded disposition in "
            f"{cfg.checkpoint_path} "
            f"({load_checkpoint(cfg.checkpoint_path).status(INSTANCE_ID)!r}): this "
            f"instance has already been driven under this root. Re-running it would be a "
            f"re-roll after seeing a result. Set {MINT_ROOT_ENV} to a fresh directory if "
            f"the previous attempt was a SETUP failure that produced no observation."
        )

    report = mint_one(INSTANCE_ID, cfg)

    assert report.captured == 1, (
        "the mint captured nothing for this instance, so there is no trajectory to read: "
        f"status={report.checkpoint.status(INSTANCE_ID)!r} "
        f"reason={report.checkpoint.reason(INSTANCE_ID)!r}\n{report.render()}"
    )

    # ---- criterion 1a: the capture exists, in the layout the stock runner resolves ----
    trace_path = report.batch_dir / f"trace-{INSTANCE_ID}.jsonl"
    manifests_dir = report.batch_dir / f"trace-{INSTANCE_ID}.manifests"
    assert trace_path.is_file(), (
        f"no bridged capture at {trace_path}: `bridge_capture` is the load-bearing wiring "
        f"test, and a mis-wire here reads as INSTRUMENT SUSPECT -- a fake PIVOT"
    )
    assert manifests_dir.is_dir(), (
        f"no manifests sibling at {manifests_dir}: without it every turn resolves "
        f"UNVERIFIED and the run reads as INSTRUMENT SUSPECT rather than as a result"
    )

    # ---- criterion 1b: the STOCK `belay phase0 run` resolves it ----
    # `belay.cli.main` is the console script's own entry point, called with an argv list:
    # no bespoke path handling, no explicit `manifest_dir_for=` (which is what the sibling
    # smoke passes), so the default trace-stem manifest resolution is what is exercised.
    # `--server` is REMAINDER and therefore last; `{workspace}` is ONE argument, replaced
    # per trace with that trace's own recorded `source_root`.
    ledger_path = mint_root / "phase0-live-smoke.json"
    exit_code = belay_main(
        [
            "phase0",
            "run",
            str(report.batch_dir),
            "--ledger",
            str(ledger_path),
            "--corpus-dir",
            str(mint_root / "corpus-never-written"),
            # S-2: a single unadjudicated turn must not enter the corpus.
            "--no-ingest",
            "--server",
            *verify_server_command(entrypoint),
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

    # ---- criterion 2: INSTRUMENT SUSPECT did not fire ----
    # Asserted on BOTH the mechanism and the surface: `instrument_suspect` is what suppresses
    # the headline, and the printed block is what a reader sees. On an n=1 ledger this also
    # means the instance yielded a verifiable turn -- a NO_VERIFIABLE_TURNS or ERRORED
    # disposition here is a WIRING report, never a result, and the batch stays unfunded.
    assert not instrument_suspect(ledger), (
        "INSTRUMENT SUSPECT fired: the capture yielded no verifiable turn, so this run is "
        f"a wiring report and NOT a result. disposition={instance.disposition.value} "
        f"turns={instance.turn_status_counts} unverified={instance.unverified_causes} "
        f"error={instance.error!r}\n{phase0_output}"
    )
    assert "INSTRUMENT SUSPECT" not in phase0_output, (
        f"the report printed an INSTRUMENT SUSPECT block:\n{phase0_output}"
    )

    # ---- spec criterion 4: the verdict travels with its coverage line ----
    # The verdict itself is NOT asserted -- PASS, FAIL and UNVERIFIED are all acceptable
    # outcomes here. What must hold is that the report states the limits of what Belay
    # looked at, because a status rendered without them is the failure `NOT_COVERED` creates.
    assert _COVERAGE_HEADING in phase0_output, (
        "the report carries no coverage boundary, so its statuses are rendered without "
        f"the limits of what Belay observed:\n{phase0_output}"
    )

    # ---- criterion 3: the TRAJECTORY reaches a real write to a file ----
    records = _records(trace_path)
    calls = _tool_call_params(records)
    advertised = _advertised_tool_names(records)
    # FIRST, so a missing write can be attributed. The tool schemas travel to the oracle as
    # prompt DATA, so if the server never advertised a write tool under one of these names
    # the oracle could not have proposed one: that is a wiring bug, and reading it as "the
    # model would not edit" would blame the model for the harness.
    assert WRITE_TOOL_NAMES & advertised, (
        "the server advertised NO write tool under a name this test knows "
        f"({sorted(WRITE_TOOL_NAMES)}); it advertised {sorted(advertised)}. This is a "
        "WIRING report, not a model verdict -- the schemas reach the oracle as prompt "
        "data, so a name mismatch looks exactly like a model that refused to edit."
    )
    writes = _writes(calls)
    # NOT "the first call is a write": probed 2026-08-05, the oracle reads the file before
    # editing it, which is correct agent behaviour and what DEFAULT_SYSTEM_PROMPT asks for.
    # The criterion is that the trajectory REACHES a write (S-5). Reads with no write is a
    # real result -- the STAGE2 "the agent did nothing" shape -- and means: do not launch a
    # batch.
    assert writes, (
        "no recorded tools/call wrote to a file: the trajectory never reached an edit "
        "through the MCP boundary. This is a REAL RESULT (Rule A row 2, the STAGE2 shape), "
        "not a harness failure -- the batch stays unfunded. Calls in order: "
        f"{[params.get('name') for params in calls]}"
    )

    # ---- criteria 4 and 5: the recorded provenance names the provider and the model ----
    accounting = report.checkpoint.accounting(INSTANCE_ID)
    assert accounting, (
        "the checkpoint recorded no accounting for this instance, so the run cannot say "
        "which provider or model produced it"
    )
    assert accounting.get("provider") == PROVIDER_NAME, (
        f"recorded provider is {accounting.get('provider')!r}, not {PROVIDER_NAME!r}: the "
        f"published run must name the path that actually minted it"
    )
    assert accounting.get("model") == MODEL, (
        f"recorded model is {accounting.get('model')!r}, not the {MODEL!r} that was "
        f"passed: a run whose config and wiring disagree must not report the config's "
        f"answer"
    )

    # ---- criterion 5: no API key appears in the recorded provenance ----
    # Over the artifacts this run actually recorded -- the checkpoint, the ledger, the
    # report -- never over intent. The other half of the claim (that the metered
    # credential is absent from the CHILD environment) is pinned offline against the real
    # `_build_env` in tests/test_minting_driver_claude_cli.py; a live run records no env.
    provenance = "\n".join(
        (
            Path(cfg.checkpoint_path).read_text(encoding="utf-8"),
            ledger_path.read_text(encoding="utf-8"),
            phase0_output,
            report.render(),
        )
    )
    leaked = _KEY_SHAPED.search(provenance)
    assert leaked is None, (
        f"an API-key-shaped string appears in the recorded provenance: "
        f"{leaked.group(0)[:12]!r}..."
    )
    for name in SCRUBBED_ENV_VARS:
        exported = (os.environ.get(name) or "").strip()
        if exported:
            assert exported not in provenance, (
                f"the value of ${name} exported in this shell appears verbatim in the "
                f"recorded provenance"
            )

    # ---- what this run showed, echoed to the REAL stdout ----
    # `capsys.disabled()` so the facts land in the terminal (and so in the committed
    # verbatim output) rather than only in a failure report. Facts only: no verdict is
    # interpreted here, no rate is computed, and n=1 is not a base rate.
    with capsys.disabled():
        print(f"\ninstance:   {INSTANCE_ID}")
        print(f"provider:   {accounting.get('provider')}")
        print(f"model:      {accounting.get('model')}")
        print(f"root:       {mint_root}")
        print(f"trace:      {trace_path}")
        print(f"ledger:     {ledger_path}")
        print(f"advertised: {sorted(advertised)}")
        print(f"calls:      {[params.get('name') for params in calls]}")
        print(
            "writes:     "
            f"{[params['arguments']['path'] for params in writes]}"
        )
        print(f"disposition: {instance.disposition.value}")
        print(f"turns:       {instance.turn_status_counts}")
        print(f"flagged:     {instance.flagged_turns}")
        print(f"unverified:  {instance.unverified_causes}")
        print(f"not covered: {instance.not_covered_turns}")
        print(f"exposure:    {instance.exposure}")
        print(f"accounting:  {accounting}")
        print()
        print(report.render())
        print()
        print(phase0_output)
