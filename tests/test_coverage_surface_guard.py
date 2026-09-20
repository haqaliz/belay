"""AC-7 — the coverage-disclosure rule, enforced structurally instead of by hand.

The rule was pre-registered by the unit that created the status
(`docs/planning/verdict-coverage-status/prd.md:203-209`):

> **no surface may render a turn's status without also rendering its coverage line —
> enforced by a test per surface, not by review.**

"A test per surface" has been honoured one surface at a time, and it has already failed
three times, each time found by something other than the suite:

  1. `interop-merge-repair` found `belay verify`'s PER-TURN line and `belay corpus show`
     unpinned after the fact — `corpus show` had silently dropped the sub-verdict
     *message*, and with it the only thing separating "the server declared a posture we
     could not check" from "the server declared nothing".
  2. THIS unit found four more with no coverage path and no coverage test at all:
     `corpus list`, `corpus run`, `corpus score`, `phase0 combine`.
  3. **This module found a fifth while it was being written: `belay corpus add`**, which
     prints `verdict PASS` for the turn it banks. It was in nobody's list, because until
     now nothing enumerated the surfaces — the gap was fixed in the same commit as this
     file (`src/belay/cli.py::_cmd_corpus_add`).

Three escapes of one rule is a review process, not a control. This module is the control.

---

## Why this is structural and not text-matching

Grepping render functions for the word "coverage" would be worse than nothing here,
because `coverage` is overloaded three ways in this CLI and one of the other two sits on
a surface that was genuinely broken:

  * `belay corpus score` prints a line labelled `coverage` meaning *decided / adjudicable
    labels* — a scoring denominator (`src/belay/cli.py`, `_cmd_corpus_score`). A
    word-matching guard would have called that surface compliant while it disclosed
    nothing about `NOT_COVERED` at all.
  * `belay replay` prints replayed/unverified counts it calls coverage, and emits no
    verdict.

So nothing here matches the word. Everything is decided from the AST of `src/belay/`,
from argparse's own subcommand table, and from the **status vocabulary** — the `Status`
symbol, the persisted `reduced_status` / `turn_status_counts` fields, and the status name
`NOT_COVERED`. That is the same discipline as `tests/test_release_workflow.py`, which
parses the release workflow as YAML rather than scanning it, *"because a regex passes on a
workflow whose steps were reordered, which is precisely the defect worth catching"*, and
the same shape as `tests/test_cli_flag_parity.py`: a declared table, plus a **discovery**
half that fails on anything the table was never told about.

## The three checks, and which one is the guard

1. **DISCOVERY — every CLI subcommand is classified.** Enumerated from `cli._parser()`
   itself, so the set cannot go stale: a new subcommand is either a status-rendering
   surface (and must name the discloser it reaches) or is declared to render no verdict
   status, with a reason. Neither ⇒ red, naming the subcommand. This half is airtight:
   argparse knows every subcommand there is, and `set_defaults(func=…)` names each
   handler, so the registry cannot miss one.
2. **DISCOVERY — every status-rendering FUNCTION is classified.** An AST scan finds every
   function under `src/belay/` that reads the status vocabulary *and* produces output;
   each must be attributed to a surface or excluded with its reason. This catches a new
   render function inside a package the CLI merely calls into.
3. **EVIDENCE — each status-rendering surface reaches its coverage discloser.** A resolved
   call graph, from the subcommand's handler to a named function that discloses the
   boundary. `corpus show` is the one exception and carries a different, equally
   structural evidence kind — see `VERBATIM_SURFACES`.

## What this module CANNOT do, stated rather than implied

* **A surface that computes its status at runtime escapes the AST scan.** Discovery 2 is
  static; a renderer that fetched a status through a name this module does not recognise
  would not be found. Discovery 1 still catches it the moment it becomes a subcommand,
  which is the only way an operator can reach it.
* **It does not prove a surface's output is CORRECT.** "Reaches the discloser" is a call
  edge, not a rendering. The per-surface behavioural tests
  (`tests/test_coverage_rendering.py`, `tests/test_coverage_surface_parity_corpus.py`,
  `tests/test_coverage_surface_parity_phase0.py`) are what prove the line appears, and
  this module deliberately does not duplicate them. It guarantees that a NEW surface
  cannot exist with no such path at all.
* **The console is pinned in its own suite**, not here; this module only asserts the
  component still exists and is still used, because a Python test cannot meaningfully
  execute Vue.
* **`belay verify`'s standing help banner is out of reach of both discovery halves.** It
  is static text in `_parser()`, so it reads no status and renders none; it is pinned
  behaviourally by `tests/test_coverage_rendering.py` ("surface 2: the banner"). A banner
  that stopped naming the boundary would be caught there, not here.

No network, no subprocess, no Docker: this parses files in the repo and one argparse
tree, so it runs on every box.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Iterator

import pytest

from belay import cli

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "belay"

#: The persisted / in-memory names through which a VERDICT status is read. `Status` is the
#: enum itself; `reduced_status` and `turn_status_counts` are the two field names the
#: corpus case format and the Phase-0 ledger use. `status` is included because that is
#: what a sub-verdict record calls it — and it is also the word a snapshot handle, a
#: JSON-RPC error and a connection context each use for something unrelated, which is why
#: `NON_VERDICT_STATUS` below exists and is long.
_STATUS_NAMES = frozenset({"status", "reduced_status", "turn_status_counts"})

#: The status name that means "outside what Belay claims to check". A function that puts
#: this string, or `Status.NOT_COVERED`, into something it emits or returns is disclosing
#: the boundary. This — not the word "coverage" — is the evidence signal.
_COVERAGE_STATUS = "NOT_COVERED"

#: Return annotations that make a function an OUTPUT producer. A renderer either prints
#: (via `_emit`/`print`) or hands text/records back to a caller that prints or serializes
#: them; this codebase annotates those returns consistently, so the annotation is the
#: structural signal rather than a guess about the body.
_OUTPUT_RETURNS = frozenset(
    {
        "str",
        "Optional[str]",
        "list[str]",
        "tuple[str, ...]",
        "dict",
        "list[dict]",
        "dict[str, Any]",
        "dict[str, str]",
        "dict[str, object]",
    }
)

_OUTPUT_CALLS = frozenset({"_emit", "print"})


# ======================================================================================
# THE REGISTRY — the fact this module asserts against. Every entry is a decision.
# ======================================================================================

#: subcommand -> the coverage disclosers its handler MUST reach, by qualified name.
#:
#: Naming the discloser rather than merely asserting "some discloser" is deliberate: it is
#: what makes deleting `_emit_stored_coverage`'s call from ONE corpus surface red while the
#: other three still pass, instead of the whole table riding on whichever surface happens
#: to keep its call.
DISCLOSING_SURFACES: dict[str, tuple[str, ...]] = {
    # The text aggregate's unconditional coverage block, and the `--json` document's
    # always-present `coverage` key. Both, because `verify` has two renderings and the
    # console reads the second one.
    "verify": (
        "src/belay/cli.py::_emit_coverage",
        "src/belay/verify/json.py::coverage_record",
    ),
    # `corpus add` prints the BANKED turn's reduced status. Found by this module; fixed in
    # the same commit. Same helper as the other corpus surfaces.
    "corpus add": ("src/belay/cli.py::_emit_stored_coverage",),
    # The three surfaces this aspect fixed. All four corpus surfaces share
    # `_emit_stored_coverage` / `_stored_coverage_record`, which routes to the same
    # `verify.json.coverage_record` `belay verify` counts with — so `n/total` cannot come
    # to mean one thing on a live run and another on the bank.
    "corpus list": ("src/belay/cli.py::_emit_stored_coverage",),
    "corpus run": ("src/belay/cli.py::_emit_stored_coverage",),
    "corpus score": ("src/belay/cli.py::_emit_stored_coverage",),
    # The Phase-0 renderers. `phase0 run` verifies and then renders the same report, so it
    # carries the same requirement; `combine` was the fourth gap this aspect closed.
    "phase0 report": ("src/belay/phase0/report.py::_coverage_lines",),
    "phase0 combine": ("src/belay/phase0/report.py::_coverage_lines",),
    "phase0 run": ("src/belay/phase0/report.py::_coverage_lines",),
    # C9. The text report and its `--json` twin both go through `interop/report.py`.
    "interop correlate": ("src/belay/interop/report.py::_coverage_lines",),
    # The OTLP document: `belay.verdict.coverage` is written present-but-empty rather than
    # conditionally, which is Phase 5 of this aspect.
    "interop export": ("src/belay/interop/export.py::_coverage_dimensions",),
    # `gate baseline --json` echoes the banked document, whose per-turn records are built
    # by `verify.json.turn_record` — every sub-verdict, NOT_COVERED included, never
    # dropped. The human path prints no status at all.
    "gate baseline": ("src/belay/verify/json.py::turn_record",),
    # `gate check` renders its own coverage line AND embeds the capture's coverage record.
    "gate check": (
        "src/belay/gate/check.py::_coverage_line",
        "src/belay/verify/json.py::coverage_record",
    ),
}

#: subcommand -> the loop whose every sub-verdict it renders, as `(iterable, why)`.
#:
#: The second evidence kind, for a surface that discloses the boundary by rendering the
#: sub-verdict set VERBATIM instead of calling a coverage helper. It is checked, not taken
#: on trust: `test_a_verbatim_surface_cannot_filter_the_boundary_out` proves the status is
#: emitted inside the loop with no status-conditional guard anywhere above it, so a
#: NOT_COVERED sub-verdict reaches the reader by construction and a filter added later is
#: red. This is the honest description of what `corpus show` actually does — a call to a
#: coverage helper would be a second, redundant rendering of a boundary already on screen.
VERBATIM_SURFACES: dict[str, str] = {
    "corpus show": "sub_verdicts",
}

#: subcommand -> why it renders no VERDICT status. An exclusion is a decision.
NO_STATUS_SUBCOMMANDS: dict[str, str] = {
    # C3, and it says so in its own output: "This is an observation about coverage, not a
    # verdict — C3 reports what replayed and what did not; it does NOT emit PASS/FAIL.
    # That is C4." Its `status` column is the REPLAY vocabulary (REPLAYED /
    # NOT_VERIFIABLE), a different alphabet that happens to share one word.
    "replay": "computes no verdict; prints the replay status vocabulary, never PASS/FAIL",
    # A human adjudication surface. Writes `human_label` and echoes it back; the engine's
    # recorded `expected` verdict is deliberately untouched and unprinted (the D3 boundary).
    "corpus label": "writes and echoes the HUMAN label; never renders the engine's verdict",
    # A boundary probe: landlock/seatbelt/containment ok-or-not. No turn, no verdict.
    "sandbox check": "probes the sandbox boundary; there is no turn and no verdict",
    # A1 policy authoring. Prints candidates, rejections and a calibration outcome
    # (`CALIBRATION_FAILED` / `CONTROL_UNREPLAYABLE`) — an artifact vocabulary, not a
    # turn's status. An uncalibrated artifact's cost lands on `verify`, which is registered.
    "invariant infer": "emits authoring/calibration outcomes, not a turn's verdict status",
    "invariant-library list": "lists the named policy presets; renders no verdict",
}

#: qualified function name -> the surface whose rendering it is part of.
#:
#: Produced by the scan below, then classified BY HAND — which is the point. A new
#: status-rendering function lands in neither this table nor the exclusions and goes red.
RENDER_SITES: dict[str, str] = {
    # --- `belay verify`, text ---------------------------------------------------------
    "src/belay/cli.py::_cmd_verify": "verify",
    "src/belay/cli.py::_emit_verdict": "verify (per-turn)",
    "src/belay/cli.py::_emit_aggregate": "verify (aggregate)",
    "src/belay/cli.py::_emit_coverage": "verify (the coverage block itself)",
    "src/belay/cli.py::_emit_trajectory": "verify (trajectory axis)",
    "src/belay/cli.py::_emit_claim": "verify (A3 claim axis)",
    "src/belay/cli.py::_first_unverified_message": "verify (aggregate, UNVERIFIED detail)",
    # --- `belay verify --json`, and every surface that serializes a verdict -----------
    "src/belay/verify/json.py::turn_record": "verify --json",
    "src/belay/verify/json.py::_subverdict_record": "verify --json",
    "src/belay/verify/json.py::aggregate_record": "verify --json",
    "src/belay/verify/json.py::coverage_record": "verify --json (the coverage block itself)",
    # --- the corpus surfaces ----------------------------------------------------------
    "src/belay/cli.py::_cmd_corpus_add": "corpus add",
    "src/belay/cli.py::_cmd_corpus_list": "corpus list",
    "src/belay/cli.py::_cmd_corpus_score": "corpus score",
    "src/belay/cli.py::_cmd_corpus_show": "corpus show",
    # The one helper all four corpus surfaces share; attributed to `corpus score` because
    # that is the surface whose own `coverage` label made the collision dangerous.
    "src/belay/cli.py::_stored_coverage_record": "corpus score (the block itself, shared by add/list/run)",
    # --- Phase 0 ----------------------------------------------------------------------
    "src/belay/phase0/report.py::_trajectory_line": "phase0 report",
    "src/belay/phase0/report.py::_trajectory_section": "phase0 report",
    "src/belay/phase0/report.py::_claim_line": "phase0 report",
    "src/belay/phase0/report.py::_claim_section": "phase0 report",
    # --- C9 interop -------------------------------------------------------------------
    "src/belay/cli.py::_cmd_interop_correlate": "interop correlate",
    "src/belay/interop/report.py::_span_line": "interop correlate",
    "src/belay/interop/report.py::to_json": "interop correlate --json",
    "src/belay/interop/report.py::_coverage_lines": "interop correlate (the block itself)",
    "src/belay/interop/export.py::_sub_verdict_record": "interop export (OTLP)",
    "src/belay/interop/export.py::_coverage_dimensions": "interop export (the block itself)",
    # --- the gate ---------------------------------------------------------------------
    "src/belay/gate/check.py::report_lines": "gate check",
}

#: qualified function name -> why its `status` is NOT a verdict status.
#:
#: This table is long because the word `status` is overloaded across the engine, and that
#: overload is exactly the trap a text-matching guard falls into. Every line here is a
#: read of the function, not a guess: if one of these ever starts rendering a verdict
#: status, moving it to `RENDER_SITES` is a deliberate edit with a surface named.
NON_VERDICT_STATUS: dict[str, str] = {
    # `belay replay`'s per-turn line: REPLAYED / NOT_VERIFIABLE / UNVERIFIED, the replay
    # vocabulary. C3 emits no verdict — see NO_STATUS_SUBCOMMANDS["replay"].
    "src/belay/cli.py::_emit_turn": "the REPLAY status vocabulary; C3 emits no verdict",
    # The MCP connection context's resolution status (resolved / unknown).
    "src/belay/connection.py::_resolved": "connection-context resolution, not a verdict",
    "src/belay/connection.py::_unknown": "connection-context resolution, not a verdict",
    # JSON-RPC / MCP error records: the protocol's own status fields.
    "src/belay/errors.py::_protocol_error": "a JSON-RPC error record",
    "src/belay/errors.py::_result_type": "an MCP result-shape record",
    "src/belay/errors.py::_structured_content": "an MCP result-shape record",
    # Snapshot handles carry a `status` saying whether a path was present, absent or
    # unrestorable. Nothing here reaches an operator as a verdict.
    "src/belay/corpus/add.py::_bundle_task_prestate": "bundles snapshot handles (handle status)",
    "src/belay/sandbox/gate.py::_snapshot_failed_handle": "a snapshot handle's status",
    "src/belay/snapshot/substrate.py::absent_handle": "a snapshot handle's status",
    "src/belay/snapshot/substrate.py::present_handle": "a snapshot handle's status",
    "src/belay/snapshot/substrate.py::unrestorable_handle": "a snapshot handle's status",
    # Comparison inputs, not renderings: each builds a status-bearing record for a diff
    # whose RENDERING is registered above (`corpus run`, `gate check`).
    "src/belay/corpus/run.py::_recomputed_set": "builds the recomputed set for comparison",
    "src/belay/gate/compare.py::_baseline_skip": "a skip reason derived from a stored status",
    # The ledger FIELD. `turn_status_counts` is persisted here and re-rendered by
    # `phase0/report.py`; the round-trip is pinned by
    # `tests/test_coverage_surface_parity_phase0.py` (AC-6).
    "src/belay/phase0/ledger.py::_instance_to_json": "ledger persistence; the render is phase0 report",
    # Frame correlation: a request's answered/unanswered status.
    "src/belay/index.py::derive_correlation": "frame correlation, not a verdict",
    # Returns a NAMED CAUSE for an UNVERIFIED turn. Reads the status to pick the cause;
    # renders nothing itself — the cause is rendered by `verify`, which is registered.
    "src/belay/verify/turn.py::_replayed_cause": "maps a status to a named cause; renders nothing",
    # A1 prose describing a weakening. Reads `Status` to phrase the sentence; the sentence
    # travels inside an invariant sub-verdict's `message`, rendered by `verify`.
    "src/belay/verify/weakening.py::describe": "A1 weakening prose inside a sub-verdict message",
}


# ======================================================================================
# THE SCANNERS
# ======================================================================================


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(_SRC.rglob("*.py")):
        rel = str(path.relative_to(_REPO_ROOT))
        yield rel, ast.parse(path.read_text(encoding="utf-8"), filename=rel)


def _belay_bindings(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """`from belay.x import y as z` -> `{"z": ("belay.x", "y")}`, imports anywhere.

    The alias and the ORIGINAL name are both kept, because `cli.py` writes
    `from belay.interop import report as interop_report` and then calls
    `interop_report.render(...)`: resolving that needs the original `report`, not the
    alias. Losing this distinction is how a call-graph check goes quietly permissive.
    """
    bindings: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("belay"):
            for alias in node.names:
                bindings[alias.asname or alias.name] = (node.module, alias.name)
    return bindings


def _module_path(dotted: str) -> str:
    return "src/" + dotted.replace(".", "/") + ".py"


class _Tree:
    """The parsed package: functions by qualified name, plus per-module import bindings."""

    def __init__(self) -> None:
        self.functions: dict[str, ast.AST] = {}
        self.module_of: dict[str, str] = {}
        self.bindings: dict[str, dict[str, tuple[str, str]]] = {}
        for module, tree in _modules():
            self.bindings[module] = _belay_bindings(tree)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{module}::{node.name}"
                    self.functions.setdefault(qualname, node)
                    self.module_of[qualname] = module

    # -- the two predicates that decide what a function IS -----------------------------

    def calls(self, qualname: str) -> set[str]:
        """The functions `qualname` calls, resolved SAME-MODULE FIRST then via imports.

        Same-module first matters: `phase0/report.py` and `interop/report.py` both define
        `_coverage_lines`, so resolving by bare name across the package would let one
        surface's disclosure satisfy another surface's requirement — a false green in
        exactly the check that is supposed to be hard to satisfy.
        """
        node = self.functions[qualname]
        module = self.module_of[qualname]
        bindings = self.bindings[module]
        out: set[str] = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if not name:
                continue
            same_module = f"{module}::{name}"
            if same_module in self.functions:
                out.add(same_module)
                continue
            direct = bindings.get(name)
            if direct and f"{_module_path(direct[0])}::{direct[1]}" in self.functions:
                out.add(f"{_module_path(direct[0])}::{direct[1]}")
                continue
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                holder = bindings.get(func.value.id)
                if holder:
                    for candidate in (
                        f"{_module_path(holder[0] + '.' + holder[1])}::{name}",
                        f"{_module_path(holder[0])}::{name}",
                    ):
                        if candidate in self.functions:
                            out.add(candidate)
        return out

    def reachable(self, entry: str) -> set[str]:
        seen: set[str] = set()
        stack = [entry]
        while stack:
            qualname = stack.pop()
            if qualname in seen or qualname not in self.functions:
                continue
            seen.add(qualname)
            stack.extend(self.calls(qualname))
        return seen

    def render_sites(self) -> dict[str, int]:
        """Every function that READS the status vocabulary and PRODUCES output."""
        return {
            qualname: getattr(node, "lineno", 0)
            for qualname, node in self.functions.items()
            if _reads_status(node) and _produces_output(node)
        }

    def disclosers(self) -> set[str]:
        """Every function that puts the status name `NOT_COVERED` into its output."""
        return {
            qualname
            for qualname, node in self.functions.items()
            if _names_the_coverage_status(node) and _produces_output(node)
        }


def _reads_status(node: ast.AST) -> bool:
    """Does this function read a verdict status — the `Status` enum, or a status field?

    Deliberately NOT triggered by a bare status-name literal in prose. This codebase
    writes honesty sentences ("never a PASS", "UNVERIFIED is never spun as PASS") all over
    its output, and a guard that fired on those would be edited into uselessness inside a
    week. The cost is named in the module docstring: a renderer that only ever branches on
    a status literal is found by the SUBCOMMAND half, not by this one.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == "Status":
            return True
        if isinstance(child, ast.Attribute) and child.attr in _STATUS_NAMES:
            return True
        if (
            isinstance(child, ast.Subscript)
            and isinstance(child.slice, ast.Constant)
            and child.slice.value in _STATUS_NAMES
        ):
            return True
        if (
            isinstance(child, ast.Call)
            and getattr(child.func, "attr", None) == "get"
            and child.args
            and isinstance(child.args[0], ast.Constant)
            and child.args[0].value in _STATUS_NAMES
        ):
            return True
        if isinstance(child, ast.Dict):
            for key in child.keys:
                if isinstance(key, ast.Constant) and key.value in _STATUS_NAMES:
                    return True
        if isinstance(child, ast.keyword) and child.arg in _STATUS_NAMES:
            return True
    return False


def _produces_output(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _OUTPUT_CALLS:
                return True
    returns = getattr(node, "returns", None)
    return returns is not None and ast.unparse(returns) in _OUTPUT_RETURNS


def _names_the_coverage_status(node: ast.AST) -> bool:
    """`Status.NOT_COVERED`, or the status NAME inside a string this function builds.

    The substring test is on the STATUS NAME, never on the word "coverage" — which is what
    keeps `corpus score`'s adjudicable-label metric from reading as evidence. Proven
    directly by `test_the_word_coverage_alone_is_not_evidence`.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == _COVERAGE_STATUS:
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and _COVERAGE_STATUS in child.value
        ):
            return True
    return False


def _subcommands() -> dict[str, str]:
    """Every subcommand path -> the name of the handler `set_defaults(func=…)` named.

    Read out of the live parser, so the set is whatever `belay --help` can actually reach.
    """
    found: dict[str, str] = {}

    def walk(parser: argparse.ArgumentParser, prefix: list[str]) -> None:
        subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            handler = parser.get_default("func")
            assert handler is not None, f"subcommand {' '.join(prefix)!r} has no handler"
            found[" ".join(prefix)] = handler.__name__
            return
        for action in subs:
            for name, sub in action.choices.items():
                walk(sub, [*prefix, name])

    walk(cli._parser(), [])
    return found


@pytest.fixture(scope="module")
def tree() -> _Tree:
    return _Tree()


# ======================================================================================
# ANTI-VACUITY — a scanner that finds nothing is vacuously green
# ======================================================================================


def test_the_scanner_reads_a_real_package(tree: _Tree) -> None:
    assert _SRC.is_dir(), _SRC
    assert len(tree.functions) > 400, len(tree.functions)
    assert "src/belay/cli.py::_cmd_verify" in tree.functions


def test_the_render_scan_finds_the_surfaces_this_module_guards(tree: _Tree) -> None:
    """Pin the scan against the sites that exist today.

    If a refactor moves or renames one of these, THIS test breaks — the one that names the
    scanner — rather than the guards below silently narrowing to an empty set.
    """
    sites = tree.render_sites()
    for expected in (
        "src/belay/cli.py::_emit_verdict",
        "src/belay/cli.py::_emit_aggregate",
        "src/belay/cli.py::_cmd_corpus_list",
        "src/belay/cli.py::_cmd_corpus_score",
        "src/belay/verify/json.py::turn_record",
        "src/belay/gate/check.py::report_lines",
        "src/belay/interop/report.py::_span_line",
        "src/belay/phase0/report.py::_trajectory_line",
    ):
        assert expected in sites, (expected, sorted(sites))


def test_the_discloser_scan_finds_the_disclosers_this_module_relies_on(tree: _Tree) -> None:
    disclosers = tree.disclosers()
    for declared in sorted({d for group in DISCLOSING_SURFACES.values() for d in group}):
        assert declared in disclosers, (
            f"{declared} is declared as a coverage discloser but no longer puts "
            f"{_COVERAGE_STATUS!r} into anything it emits or returns"
        )


def test_the_call_graph_resolves_same_module_names_before_imported_ones(tree: _Tree) -> None:
    """The collision that would make the evidence check permissive, pinned.

    `phase0/report.py` and `interop/report.py` BOTH define `_coverage_lines`. A resolver
    that matched bare names across the package would let `phase0 combine` satisfy its
    requirement with C9's function, which it never calls.
    """
    assert "src/belay/phase0/report.py::_coverage_lines" in tree.functions
    assert "src/belay/interop/report.py::_coverage_lines" in tree.functions

    phase0 = tree.reachable("src/belay/cli.py::_cmd_phase0_combine")
    assert "src/belay/phase0/report.py::_coverage_lines" in phase0
    assert "src/belay/interop/report.py::_coverage_lines" not in phase0, (
        "the resolver crossed modules on a bare name; every evidence assertion below "
        "would then be satisfiable by the wrong function"
    )


# ======================================================================================
# DISCOVERY 1 — every CLI subcommand is classified (the airtight half)
# ======================================================================================


def test_every_cli_subcommand_is_classified(tree: _Tree) -> None:
    """THE GUARD. A new subcommand must declare whether it renders a verdict status.

    Enumerated from `cli._parser()`, so this cannot be satisfied by remembering to edit a
    list: argparse knows every subcommand, and a new one lands in none of the three
    registries above. The failure names it and says what to do.
    """
    classified = set(DISCLOSING_SURFACES) | set(VERBATIM_SURFACES) | set(NO_STATUS_SUBCOMMANDS)
    actual = set(_subcommands())

    unclassified = sorted(actual - classified)
    assert not unclassified, (
        f"new CLI subcommand(s) {unclassified} are in none of this module's registries. "
        "If the surface renders a turn's status, add it to DISCLOSING_SURFACES naming the "
        "coverage discloser it reaches (and give it a per-surface test); if it does not, "
        "add it to NO_STATUS_SUBCOMMANDS with the reason. Silence is the one option the "
        "coverage rule does not allow."
    )
    stale = sorted(classified - actual)
    assert not stale, f"these registry entries name subcommands that no longer exist: {stale}"


def test_no_subcommand_is_classified_twice() -> None:
    """A surface cannot be both a status renderer and status-free."""
    overlaps = (
        (set(DISCLOSING_SURFACES) & set(NO_STATUS_SUBCOMMANDS))
        | (set(VERBATIM_SURFACES) & set(NO_STATUS_SUBCOMMANDS))
        | (set(DISCLOSING_SURFACES) & set(VERBATIM_SURFACES))
    )
    assert not overlaps, sorted(overlaps)


def test_a_subcommand_declared_status_free_renders_no_status(tree: _Tree) -> None:
    """The exclusions are checked, not trusted.

    A subcommand declared status-free whose own handler reads the status vocabulary and
    prints is a mis-classification, and this is what catches it. The handler ITSELF is
    checked, not its whole reachable set: every replay-bearing surface calls into the
    verdict engine, so reachability would flag all of them.
    """
    handlers = _subcommands()
    sites = tree.render_sites()
    offenders = {
        sub: f"src/belay/cli.py::{handlers[sub]}"
        for sub in NO_STATUS_SUBCOMMANDS
        if f"src/belay/cli.py::{handlers[sub]}" in sites
        and f"src/belay/cli.py::{handlers[sub]}" not in NON_VERDICT_STATUS
    }
    assert not offenders, (
        "these subcommands are declared to render no verdict status, but their handlers "
        f"read a status and print: {offenders}"
    )


# ======================================================================================
# EVIDENCE — each status-rendering surface reaches its coverage discloser
# ======================================================================================


@pytest.mark.parametrize("subcommand", sorted(DISCLOSING_SURFACES))
def test_every_status_rendering_surface_reaches_its_coverage_discloser(
    subcommand: str, tree: _Tree
) -> None:
    """Remove a surface's disclosure and this goes red, naming that surface.

    A call edge, not a rendered string: the per-surface tests prove the line appears. What
    this proves is that the path EXISTS at all — which is the property the four gaps this
    aspect closed were each missing.
    """
    handler = _subcommands()[subcommand]
    entry = f"src/belay/cli.py::{handler}"
    reached = tree.reachable(entry)
    disclosers = tree.disclosers()

    for required in DISCLOSING_SURFACES[subcommand]:
        assert required in reached, (
            f"`belay {subcommand}` renders a turn's status but no longer reaches "
            f"{required} — the coverage boundary it discloses is gone from that surface. "
            "Restore the call, or (if the disclosure moved) update this module's registry "
            "to name where it went."
        )
        assert required in disclosers, (
            f"{required} is reached from `belay {subcommand}` but has stopped naming "
            f"{_COVERAGE_STATUS!r}, so reaching it proves nothing"
        )


def test_a_verbatim_surface_cannot_filter_the_boundary_out(tree: _Tree) -> None:
    """`corpus show`'s evidence kind, checked structurally rather than asserted.

    It discloses by printing EVERY stored sub-verdict's status, so a NOT_COVERED one
    reaches the reader without any coverage helper. That only holds while the loop is
    unfiltered — so this asserts the status emit sits inside a loop over `sub_verdicts`
    with **no status-conditional guard anywhere above it**, comprehension conditions
    included. Add `if sub["status"] != "NOT_COVERED"` and this is red.
    """
    handlers = _subcommands()
    for subcommand, iterable in VERBATIM_SURFACES.items():
        entry = f"src/belay/cli.py::{handlers[subcommand]}"
        node = tree.functions[entry]
        assert _unfiltered_status_emit(node, iterable), (
            f"`belay {subcommand}` is registered as disclosing the coverage boundary by "
            f"rendering every {iterable} entry verbatim, but no unguarded status emit was "
            f"found inside a loop over {iterable}. Either the loop gained a "
            "status-conditional filter (the boundary can now be dropped silently), or the "
            "surface should move to DISCLOSING_SURFACES with the helper it now calls."
        )


def _mentions_a_status_value(node: ast.AST) -> bool:
    """Wider than `_reads_status`: also a bare local called `status`, and a status NAME.

    Used only to decide whether a CONDITION could filter a sub-verdict by its status, where
    a false positive costs nothing (it makes the verbatim check stricter) and a false
    negative would let a filter through.
    """
    from belay.verify.verdict import Status

    names = {s.name for s in Status}
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and (child.id == "Status" or child.id in _STATUS_NAMES):
            return True
        if isinstance(child, ast.Attribute) and child.attr in _STATUS_NAMES:
            return True
        if isinstance(child, ast.Constant) and child.value in names | _STATUS_NAMES:
            return True
        if (
            isinstance(child, ast.Subscript)
            and isinstance(child.slice, ast.Constant)
            and child.slice.value in _STATUS_NAMES
        ):
            return True
    return False


def _unfiltered_status_emit(node: ast.AST, iterable: str) -> bool:
    for loop in ast.walk(node):
        if not isinstance(loop, ast.For):
            continue
        if not _iterates(loop, iterable):
            continue
        # A comprehension in the iterable may itself carry a status filter.
        if any(
            _mentions_a_status_value(cond)
            for comp in ast.walk(loop.iter)
            if isinstance(comp, ast.comprehension)
            for cond in comp.ifs
        ):
            continue
        if _emits_status_unguarded(loop.body):
            return True
    return False


def _iterates(loop: ast.For, iterable: str) -> bool:
    for child in ast.walk(loop.iter):
        if isinstance(child, ast.Attribute) and child.attr == iterable:
            return True
        if isinstance(child, ast.Constant) and child.value == iterable:
            return True
        if isinstance(child, ast.Name) and child.id == iterable:
            return True
    return False


def _emits_status_unguarded(body: list[ast.stmt]) -> bool:
    """An `_emit`/`print` of something status-valued, not under a status-testing `if`."""
    for statement in body:
        if isinstance(statement, ast.If):
            if _mentions_a_status_value(statement.test):
                continue
            if _emits_status_unguarded(statement.body) or _emits_status_unguarded(
                statement.orelse
            ):
                return True
            continue
        if isinstance(statement, (ast.For, ast.While)):
            if _emits_status_unguarded(statement.body):
                return True
            continue
        for child in ast.walk(statement):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _OUTPUT_CALLS and any(_mentions_a_status_value(a) for a in child.args):
                return True
    return False


# ======================================================================================
# DISCOVERY 2 — every status-rendering function is classified
# ======================================================================================


def test_every_status_render_site_is_attributed_or_excluded(tree: _Tree) -> None:
    """THE OTHER GUARD: a new render function inside the engine, not just a new command.

    `belay verify`'s per-turn line and `corpus show` both escaped enforcement once by
    being functions nobody had listed. This is the enumeration that makes that impossible:
    every function that reads a verdict status and produces output is attributed to a
    surface or excluded with its reason, and a new one is neither.
    """
    sites = tree.render_sites()
    classified = set(RENDER_SITES) | set(NON_VERDICT_STATUS)

    unclassified = sorted(f"{name} (line {sites[name]})" for name in set(sites) - classified)
    assert not unclassified, (
        f"{len(unclassified)} function(s) read a verdict status and produce output but are "
        "in neither RENDER_SITES nor NON_VERDICT_STATUS:\n  "
        + "\n  ".join(unclassified)
        + "\nIf this renders a turn's status to an operator or into a document, add it to "
        "RENDER_SITES naming its surface and make sure that surface discloses the coverage "
        "boundary. If its `status` is something else (a snapshot handle, a JSON-RPC error, "
        "the replay vocabulary), add it to NON_VERDICT_STATUS with that reason."
    )
    stale = sorted(classified - set(sites))
    assert not stale, (
        "these registry entries name functions that no longer read a status and produce "
        f"output — delete them rather than leave a table describing code that is gone: {stale}"
    )


def test_every_attributed_render_site_belongs_to_a_known_surface() -> None:
    """A site cannot be attributed to a surface this module does not otherwise know."""
    known = set(DISCLOSING_SURFACES) | set(VERBATIM_SURFACES)
    for site, surface in RENDER_SITES.items():
        # A label is `<subcommand> [--flag] [(which part)]` — e.g. `verify --json
        # (the coverage block itself)`. The subcommand is the leading plain words.
        head = " ".join(
            word
            for word in surface.split(" (")[0].split()
            if not word.startswith("-")
        )
        assert head in known, (
            f"{site} is attributed to {surface!r}, which is not a registered "
            f"status-rendering surface: {sorted(known)}"
        )


# ======================================================================================
# THE NAME COLLISION — the trap this guard must not fall into
# ======================================================================================


def _predicate_on(source: str) -> bool:
    node = ast.parse(source).body[0]
    return _names_the_coverage_status(node) and _produces_output(node)


def test_the_word_coverage_alone_is_not_evidence() -> None:
    """The specific trap: `corpus score` already printed a line labelled `coverage`.

    That metric is *decided / adjudicable labels* — a scoring denominator with nothing to
    do with the NOT_COVERED boundary. A guard keyed on the word would have certified that
    surface as compliant while it disclosed nothing, which is worse than no guard: it would
    have reported the gap as closed.

    Asserted directly on the predicate, with a function that is compliant in every way
    except the one that matters, so this holds regardless of which real functions happen to
    qualify today.
    """
    assert not _predicate_on(
        'def f(x) -> str:\n'
        '    return "coverage: 3/4 labels decided / adjudicable"\n'
    ), "the word 'coverage' was accepted as a disclosure of the NOT_COVERED boundary"

    assert _predicate_on(
        'def f(x) -> str:\n'
        '    return "coverage (NOT_COVERED — outside what Belay observes)"\n'
    ), "the status name NOT_COVERED was not accepted as a disclosure"


def test_belay_replays_own_coverage_wording_is_not_evidence_either(tree: _Tree) -> None:
    """`belay replay` prints replayed/unverified counts it calls coverage, and no verdict.

    It must not appear in the discloser set: if it did, the guard would be treating C3's
    observation as C4's boundary — two different claims that share one word.
    """
    assert "src/belay/cli.py::_cmd_replay" not in tree.disclosers()


# ======================================================================================
# gate check's RENDERED coverage line — the follow-up this module closes
# ======================================================================================


def test_gate_check_renders_its_coverage_line_not_only_the_json_key() -> None:
    """`tests/test_gate_check.py:345` pins the `coverage` KEY; nothing pinned the LINE.

    `report_lines` walks the same document `--json` serializes, so it is a pure
    dict -> lines function and this needs no replay, no server and no baseline. It renders
    the per-turn `status` column, so the rule binds: the coverage line must follow it.
    """
    from belay.gate.check import report_lines

    doc = {
        "schema": 1,
        "run_id": "pytest-7432",
        "trace": "t.jsonl",
        "outcome": "PASS",
        "exit_reason": "clean",
        "skip_reason": None,
        "divergences": [],
        "shape": [],
        "drift": [],
        "capture": {"turns": [{"ordinal": 0, "tool": "write_note", "status": "PASS"}]},
        "coverage": {
            "effect": {
                "not_observed_turns": 1,
                "of_turns": 1,
                "message": "the server declared no readOnlyHint for it",
            }
        },
    }

    rendered = "\n".join(report_lines(doc))

    assert "turn 0" in rendered and "PASS" in rendered, rendered
    assert "effect NOT_COVERED on 1/1 turn(s)" in rendered, (
        "gate check renders a per-turn status with no coverage line beside it"
    )

    # And the empty case still says so in words rather than falling silent — silence is
    # indistinguishable from a surface that forgot.
    clean = "\n".join(report_lines({**doc, "coverage": {}}))
    assert "no dimensions left uncovered" in clean, clean


# ======================================================================================
# THE CONSOLE — pinned in its own suite; only its existence is asserted here
# ======================================================================================


def test_the_console_still_routes_every_status_through_its_coverage_line() -> None:
    """The console is the model this rule was copied FROM, so it is worth a tripwire.

    A Python test cannot execute Vue, and `console/` has its own suite. What it can assert
    is that the component still exists and is still used by both components that render a
    turn's status — so deleting it, or dropping it from one of the two, is red here too.
    """
    console = _REPO_ROOT / "console" / "src" / "components"
    coverage_line = console / "CoverageLine.vue"
    assert coverage_line.is_file(), coverage_line

    users = [path for path in sorted(console.glob("*.vue")) if "CoverageLine" in path.read_text()]
    names = {path.name for path in users}
    assert {"TurnRow.vue", "TraceView.vue"} <= names, (
        "a console component that renders a turn's status stopped using CoverageLine.vue: "
        f"{sorted(names)}"
    )


def test_the_registries_carry_a_reason_for_every_exclusion() -> None:
    """An exclusion with an empty reason is an oversight wearing a decision's clothes."""
    for table in (NO_STATUS_SUBCOMMANDS, NON_VERDICT_STATUS):
        for key, reason in table.items():
            assert reason and len(reason) > 20, (key, reason)
