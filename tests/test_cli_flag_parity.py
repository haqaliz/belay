"""The replay-bearing CLI surfaces agree on the flags they share (AC-6).

**This guard exists because the same defect has now happened twice, and both times it was
found by running the product rather than by the suite.**

  1. `belay verify` had no `--timeout` while `corpus add`, `phase0 run` and `interop
     correlate` all did. The C7 console had already shipped *passing* it; argparse
     answered `unrecognized arguments: --timeout <trace>` with an EMPTY stdout and exit 2,
     so every console verify degraded to `empty-output` — strictly worse than the
     UNVERIFIED it was meant to fix (launch demo, L7).
  2. `belay verify` had no `--shell-server` while `belay phase0 run` had carried it since
     `9138cea` (2026-08-14). The engine has routed a `run_process` turn to a second server
     since that commit (`src/belay/verify/turn.py:210`); the documented surface simply
     could not ask for it, so a trace captured from an agent with more than one MCP server
     reported a confident FAIL on every turn belonging to the server the operator could
     not name (`docs/planning/verify-tool-not-offered/prd.md`).

A missing flag is invisible to every other test in this suite: nothing goes red when a
surface merely *cannot express* something, and the failure only shows up as a degraded
verdict on a real run. So the parity is asserted here, declaratively.

**What is pinned, and what deliberately is not.** Not a full cross-product of every
subcommand's options — that would fail on every unrelated flag and teach the next reader
to edit the table without thinking. The scope is the five **replay-bearing** surfaces
(the ones that restore a pre-state and re-invoke a server), and the rule is: every flag
carried by two or more of them is declared here with its exact surface set, so dropping
one, or adding a flag to only one of a pair, is a red test that names the surfaces. Each
row's exclusions are stated in a comment: an exclusion is a decision, not an oversight.
"""

from __future__ import annotations

import argparse

from belay import cli

#: The surfaces that restore a pre-state and re-invoke an MCP server. `sandbox check`,
#: `corpus label/list/score`, `phase0 report/combine` are excluded because they
#: replay nothing — a `--server` on them would be meaningless. `corpus run` is IN scope:
#: it re-verifies every stored case by re-execution (it was omitted from the original
#: list because it carried no flags at all; it carries the claim-axis flag now).
#: `corpus show` is IN scope: its recompute re-invokes the server too (a stored
#: trajectory case can be re-derived on demand), so the surface that carries the shell
#: flag must be declared with it; `corpus label/list/score` still replay nothing.
REPLAY_BEARING = (
    "replay",
    "verify",
    "corpus add",
    "corpus run",
    "corpus show",
    "phase0 run",
    "interop correlate",
    "interop export",
    "gate baseline",
    "gate check",
    "invariant infer",
)

_ALL = frozenset(REPLAY_BEARING)

#: flag -> the replay-bearing surfaces that MUST carry it.
EXPECTED: dict[str, frozenset[str]] = {
    # The replay boundary itself. Every surface that re-invokes needs one, EXCEPT
    # `corpus run` and `corpus show`: each stored case carries its own resolved server
    # command (`add_case` records it), so neither the batch nor the display takes one.
    "--server": _ALL - {"corpus run", "corpus show"},
    # The determinism gate's re-invoke count: shared by every surface that can reach a
    # DIVERGED reply, which is all of them — except `corpus run` and `corpus show`, whose
    # per-case replays count is recorded on the case at ingest, and `gate check`, which
    # re-verifies against the BASELINE's stored policy (the banked replays count) —
    # a deliberate narrowing: the gate's policy is the banked one by decision (M3).
    "--replays": _ALL - {"corpus run", "corpus show", "gate check"},
    # The per-replay wall. `replay` is excluded: it is the raw re-invoke surface with no
    # verdict of its own, and its timeout has never been operator-settable. If it ever
    # grows one, this row is the place that says so. `corpus run` and `corpus show` are
    # excluded the same way: a case's timeout is recorded on the case, never
    # operator-settable. `gate check` is excluded by the same decision as `--replays`:
    # the banked timeout is the policy (M3).
    "--timeout": _ALL - {"replay", "corpus run", "corpus show", "gate check"},
    # Per-tool routing: a recorded `run_process` turn replays against this instead.
    # `replay` re-invokes one named turn, so the operator already chooses the server;
    # `gate baseline` widens it by decision (M8): the bank composes the verdict set
    # exactly as verify does, so it must be able to ask for the same boundary. Widening
    # is a decision, and it belongs here. `gate check` widens it the same way:
    # `--shell-server` is an OVERRIDE of the stored boundary, so the surface that banks
    # the boundary must also be able to override it. `corpus add` resolves the stored
    # command for the target turn, `corpus run`/`corpus show` recompute whole traces
    # whose second boundary is caller-supplied — the old "deliberately out of scope"
    # rationale for `corpus add` is retired by this unit.
    "--shell-server": frozenset({"verify", "phase0 run", "gate baseline", "gate check", "corpus add", "corpus run", "corpus show"}),
    # Where the gate persisted the run's snapshot manifests. `phase0 run` is excluded: it
    # takes a whole trace DIRECTORY and resolves each trace's `.manifests` sibling itself.
    # `corpus run` and `corpus show` are excluded the same way, one level further: a case
    # is self-contained — its manifests are bundled IN the case dir, so neither the batch
    # nor the display points at a sibling.
    "--manifest-dir": _ALL - {"phase0 run", "corpus run", "corpus show"},
    # Single-turn narrowing. The batch surfaces (`phase0 run`) and the span-driven one
    # (`interop correlate`) have no single-turn meaning; `gate baseline` banks the WHOLE
    # trace (its expected set is the run's, and a partial bank would be a partial record).
    "--turn": frozenset({"replay", "verify", "corpus add"}),
    # The A1 policy. `replay` computes no verdict; `interop correlate` attaches an
    # existing one and computes none of its own. `gate baseline` STORES the resolved
    # policy, so it must be able to resolve the same policy verify composes with.
    "--invariants": frozenset({"verify", "corpus add", "phase0 run", "gate baseline"}),
    # The named library presets (aspect 2 of invariant-library): same surfaces as
    # the operator file, applied by name with zero JSON authoring.
    "--invariant-library": frozenset({"verify", "corpus add", "phase0 run", "gate baseline"}),
    "--no-default-invariants": frozenset({"verify", "corpus add", "phase0 run", "gate baseline"}),
    # The machine surface. `replay` and `corpus add` render human text only.
    # `gate baseline --json` prints the stored baseline document; `gate check
    # --json` prints the gate report (gate.json schema 1); `invariant infer
    # --json` prints the infer result (candidates, rejections, calibration,
    # artifact path).
    "--json": frozenset({"verify", "interop correlate", "interop export", "gate baseline", "gate check", "invariant infer"}),
    # Where a document is written. `interop export` writes the OTLP document back
    # out; `invariant infer` writes the authored invariant artifact. Both are
    # operator-named output files with the same never-partial contract, so the two
    # share the flag and it is declared here.
    "--out": frozenset({"interop export", "invariant infer"}),
    # Where corpus cases are read/written. `gate check` banks regression turns
    # into it by default (aspect 4 — divergence banking); `phase0 run` ingests
    # flagged turns into it; `corpus show` reads cases from it today.
    "--corpus-dir": frozenset({"corpus add", "phase0 run", "gate check", "corpus show"}),
    # Measure-without-writing: suppress the corpus WRITE, not the detection.
    # `phase0 run` ingests flagged turns into the corpus; `gate check` banks
    # regression turns into it. Both default-on, both with the same opt-out, so
    # the two surfaces cannot drift apart on the one flag that decides whether
    # a run touches the corpus at all.
    "--no-ingest": frozenset({"phase0 run", "gate check"}),
    # The A3 claim axis (C8). Shared by every surface that can evaluate a claim at
    # the instance level; `replay` and `corpus add` evaluate no instance-level
    # verdict, and `interop correlate` attaches existing verdicts only. `gate
    # baseline` evaluates the claim at bank time, so it can disable the axis.
    # `gate check` evaluates the claim on BOTH sides of the comparison, so it can
    # disable it too.
    "--no-claim-axis": frozenset({"verify", "phase0 run", "corpus run", "gate baseline", "gate check"}),
    # The INTERACTIVE A3 author surface: `belay verify` takes the author command as a
    # flag; the batch surfaces are env-only (`BELAY_CLAIM_AUTHOR`) by design (plan
    # open question, decided at plan time). `gate baseline` mirrors verify: a bank
    # whose expected set includes a claim needs the author surface. `gate check`
    # mirrors it the same way: a stored claim can only be re-derived and compared
    # when an author is supplied at check time.
    "--claim-author": frozenset({"verify", "gate baseline", "gate check"}),
    # The C10 triage budget (aspect surfaces): `belay verify` takes the triage
    # command as a flag; the other replay-bearing surfaces are env-only
    # (`BELAY_TRIAGE_AUTHOR`) by the same pinned decision as `--claim-author`
    # (tests/test_verify_claim_surfaces.py:202-219) — batch surfaces follow in a
    # later slice. The budget knobs and the kill-switch share the author's
    # surface: triage is the verify surface's budget in this slice.
    "--triage-author": frozenset({"verify"}),
    "--triage-threshold": frozenset({"verify"}),
    "--triage-top-n": frozenset({"verify"}),
    "--no-triage": frozenset({"verify"}),
    # The identity fallback for pre-record captures: `gate baseline` banks under
    # the override, `gate check` resolves the same baseline by it. Two surfaces,
    # one flag — the gate's join key.
    "--run-id": frozenset({"gate baseline", "gate check"}),
}


def _options(surface: str) -> frozenset[str]:
    """The long option strings a subcommand path carries, e.g. `corpus add`."""
    parser: argparse.ArgumentParser = cli._parser()
    for name in surface.split():
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        parser = subparsers.choices[name]
    return frozenset(
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    )


def _surfaces_carrying(flag: str) -> frozenset[str]:
    return frozenset(name for name in REPLAY_BEARING if flag in _options(name))


def test_every_declared_flag_is_carried_by_exactly_the_declared_surfaces():
    """The parity table is the fact. A surface that gains or loses a shared flag without
    a decision recorded here fails, and the failure names both sides."""
    actual = {flag: _surfaces_carrying(flag) for flag in EXPECTED}
    assert actual == EXPECTED, {
        flag: {"declared": sorted(EXPECTED[flag]), "actual": sorted(actual[flag])}
        for flag in EXPECTED
        if actual[flag] != EXPECTED[flag]
    }


def test_every_flag_shared_by_two_replay_bearing_surfaces_is_declared():
    """The discovery half: a NEW shared flag cannot appear on two surfaces unattended.

    Without this, the table above only guards flags someone remembered to add to it —
    which is precisely the failure mode (`--shell-server` sat on one surface for two
    weeks). Any flag reaching a second replay-bearing surface must be declared, with its
    exclusions stated, before this test goes green again.
    """
    shared = {
        flag
        for surface in REPLAY_BEARING
        for flag in _options(surface)
        if len(_surfaces_carrying(flag)) >= 2
    }
    assert shared - set(EXPECTED) == set(), sorted(shared - set(EXPECTED))
