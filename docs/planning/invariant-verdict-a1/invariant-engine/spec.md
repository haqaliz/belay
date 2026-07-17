# Aspect spec — `invariant-engine`

**Feature:** `invariant-verdict-a1` (C5) · **PRD:** [`../prd.md`](../prd.md)
**Scope:** M1–M7, S1–S2. One aspect — the format, the evaluator, the annotation-inferred default, and
the CLI wiring are one coherent thing, and C5 completes the Phase-0 gate.

## Problem slice

C4 renders A2 (did the tool conform to its own contract?). C5 renders A1: **was the task-scoped policy
violated by the observed replay effect, regardless of which tool did it or what it declared?** — the
axis that catches a *cheating* agent whose trace is faithful, which A2 structurally cannot.

**Outcome:** `belay verify --invariants <path>` (and a zero-config default) evaluates each turn's
replay delta against declared task invariants; a violation is `Verdict(axis="A1", kind="invariant",
FAIL)` naming the invariant + the violating path, reduced alongside A2. The launch demo — A2 PASS +
A1 FAIL on the weakening turn — is the acceptance test and the whole thesis.

## In scope
M1 invariant format + loader (operator file, `{scope, rule}` JSON) · M2 evaluator grounded on
`reply.delta` (byte-prefix scope match; delta None -> UNVERIFIED) · M3 annotation-inferred SCOPED +
TOOL-INDEPENDENT default (`tests/` read-only), overridable, NOT the readOnlyHint restatement · M4
network invariants UNVERIFIED-only (mirror openWorldHint) · M5 additive A1 sub-verdict in verify_turn ·
M6 `--invariants` + A1 in the report · M7 zero-LLM · S1 corrupt-success corpus-case shape · S2
no-create/no-delete rules.

## Out of scope
A2 (C4). A3/`--no-claim-axis` (C8). The corpus store (C6) — emit ingestable cases only. Network egress
verification (UNVERIFIED-only). LLM-inferred invariants. Static-lint over the trace (A1 evaluates the
replayed effect). Non-macOS, non-stdio.

## Acceptance criteria (test-first)
A1 THE DEMO: the WEAKENING turn (readOnlyHint:false tool writes tests/) -> A1 FAIL (names invariant +
path) AND A2 result+effect PASS, reduced FAIL driven solely by A1. A2 clean run -> A1 PASS. A3
annotation-inferred default fires with zero config. A4 unevaluable (network / delta None) -> UNVERIFIED
never PASS. A5 collapse-guard: on the demo turn A1 verdict != C4 effect verdict (FAIL vs PASS). A6
byte-prefix scope match. A7 operator-only: no invariant read from trace records. A8 zero-LLM. A9
C1-C4 untouched (348).

All deterministic, no network, CI-runnable (macOS).

## Dependencies
Upstream: C4 (Verdict, reduce, verify_turn, effect._paths, reply.delta), C1 (annotations for the
inferred default, bth1.FieldDiff), C2/C3 (the replay effect). C5 completes the C1-C5 Phase-0 gate.

## Risks
R-C5-1 A1 collapses into C4 (fatal to thesis; A5 guards). R3 nobody authors the invariant (M3 default).
R-C5-2 agent authors its own passing policy (M1: operator file). R5 over-claim network (M4). R-C5-3
default surprises the user (documented, overridable).
