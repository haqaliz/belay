# Changelog

All notable changes to Belay are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Belay aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0 — until then,
`0.x` minor bumps may include changes that would be breaking under strict semver.

## [0.29.0] - 2026-09-05

**The trace-ordering race is closed in the recorder — a response is never written before
the request it answers.** `belay.proxy._pump` forwards a chunk and observes it afterwards
("forwarding must never wait on the recorder"), so both directions ran ahead of the trace
and a fast local server could have its `tools/list` RESPONSE recorded before its own
REQUEST. An inverted pair does not correlate, `derive_annotations` then took no snapshot,
and effect-conformance abstained for the whole run — honest (UNVERIFIED, never a false
PASS) and a real **coverage-loss** path, logged as a follow-up when it was found during
`docker-selfhost` (v0.21.0) and closed here.

### Fixed

- **`belay.trace.TraceWriter` defers a response's record until its request's record is on
  disk.** Every c2s frame's request ids enter an in-writer index **under the writer's own
  lock, after the line is written** — so a waiter that sees a key knows the record exists.
  An s2c response parks on a `threading.Condition` over that same lock (the wait releases
  it, so the direction it waits for is never blocked) until its key appears.
- **Bounded and fail-open.** Past `REQUEST_WAIT_TIMEOUT` (2.0 s) the response records
  anyway, out of order, and the readers name it exactly as they did before
  (`response-without-request` + `unanswered`). **No new record kind, no new field, no
  schema bump.** The deadline is not optional: a parked response stops its direction being
  read, so an *orphan* response could otherwise enter a pipe cycle with a flooding server
  and wedge the proxy. Bounded, it is a pause.
- **Exact, never heuristic.** Classification is structural and identical to
  `belay.index.classify` (`result`/`error` first, so a non-conforming response that also
  carries `method` is still a response) — re-implemented in the recorder rather than
  imported, because the recorder must not depend on a derivation that reads what it wrote,
  and **pinned to it by a test**. Truncated frames, unparseable frames, batch arrays,
  notifications, server-originated requests and container-valued ids never wait and are
  never indexed.

### Added

- `tests/test_trace_ordering.py` — the deterministic unit RED (the deferral, the
  fail-open, the closed-abort, seven never-wait shapes, the monotone index, the
  classification-parity guard) plus a stress guard through the real proxy.
- `tests/fixtures/fast_server.py` — a server that answers instantly and waits on nothing,
  the opposite of the in-image roundtrip fixtures by design.

### Honesty notes — read before quoting anything

- **Measured, and quoted as observations rather than a rate** (it is a stochastic race).
  Before the fix, on this machine, 20-run stresses of the committed fixture and driver
  (22 request/response pairs per run): **15/20 and 12/20 runs held at least one broken
  correlation** — 46 and 60 broken correlation records. After: **20/20 and 20/20 clean, 0
  broken records.**
- **This is a COVERAGE gain, not a reclassification, and it moves no published number.**
  Effect-conformance will now decide rather than abstain on fast-server traces. `11/60 =
  18.3%`, the 11 hand-audited TPs, `precision 0.00`, `1/15` and `4/16` stand unedited; no
  historical capture was recomputed.
- **The transparency contract survives where it is load-bearing, and the residue is
  named.** `proxy.py` is untouched, and the frame being recorded has already been
  forwarded — no frame ever waits for its own record. But the pump calls the recorder
  synchronously, so while a deferral is parked the **next** chunk on that direction is not
  read: zero in the causal case, at most the deadline once per orphan. Stated, not hidden.
- **What this does NOT fix: snapshot-before-next-call.** Only the client decides when its
  next request crosses, so no recorder can close that window; the in-image roundtrip
  fixtures still guard it and are re-scoped to say so.
- **Suite 2114 → 2137 tests passing** (25 named-cause skips, 11 deselected).

## [0.28.0] - 2026-09-05

**Observability export-back ships — C9's second aspect is built** (`belay interop export`).
Verdicts travel back into the OTLP document a collector reads: `belay interop export
<otlp> <trace> [--server -- CMD…] [--out FILE] [--json]` correlates each ingested span to
its MCP turn (the same deterministic `(traceId, spanId)` join as `correlate`), attaches
the existing replayed verdict verbatim, and enriches the document with the verdict as
span attributes plus one `belay.verdict` event — completing the locked Phase-1 interop
deliverable whose export-back half was a named deferral since v0.5.0.

### Added

- **The export engine** (`src/belay/interop/export.py`) — one pure function,
  `build_enriched_document`: deep-copies the parsed OTLP document (inputs never mutated,
  asserted), pairs `results[i]` with `spans[i]` positionally in document order (a loud
  length assertion, never a silent partial zip), and enriches every ingested span.
  Attribute contract, pinned byte-for-byte by a committed fixture:
  `belay.verdict.status` / `.axis` (absent when the verdict has no sub-verdicts) /
  `.cause` (absent when `None`, never `""`) / `.turn_index` (matched spans only) /
  `.coverage` (JSON string array of `NOT_COVERED` kinds, absent when none) /
  `.sub_verdicts` (JSON string array of `{"axis","kind","status","message"}`); the
  `belay.verdict` span event carries the worst sub-verdict's message and its
  observed/expected where present. Stdlib only — no OTel SDK, no network, no clock.
- **`belay interop export` CLI** — the document travels to `--out` or stdout; the summary
  (human or `--json`) always goes to stderr, so stdout carries exactly one artifact.
  Exit semantics: rc 0 on a successful export **regardless of verdict contents** (the
  export is not a gate — an all-UNVERIFIED export is still a successful export); rc 2 on
  the fail-closed preflight errors; rc 1 on a write failure, a distinct code.
- **The flag-parity guard now covers `interop export`** — the `--timeout` defect class
  that had already happened twice cannot reach a replay-bearing surface undeclared.

### Honesty notes — read before quoting anything

- **The coverage line travels with every status.** A PASS exported without it is the
  named failure mode of this surface; an unmatched/ambiguous span exports `UNVERIFIED`
  with its named cause, never PASS, never a bare span.
- **The deferral lines retired are exactly as wide as the slice.** The "no Langfuse
  integration" honesty lines survive verbatim — an OTLP/JSON fixture-collector export is
  not a Langfuse integration, and a live OTLP exporter and multi-trace-directory
  aggregation remain deferred. The stale `NOT_COVERED` deferral item in
  `CAPABILITY_ROADMAP.md`'s C9 block is corrected (`interop-merge-repair` shipped it) —
  a correction, not a reclassification.
- **No published number moves.** `11/60 = 18.3%`, the 11 hand-audited TPs,
  `precision 0.00`, `1/15` and `4/16` stand unedited. No verdict axis, status, reduction
  or corpus change of any kind — the export re-emits existing verdicts verbatim.
- **Suite 2091 → 2114 tests passing** (25 named-cause skips, 11 deselected).

### Not built, and named

No live OTLP exporter or collector connection (the collector is a fixture — a file, or
stdout); no Langfuse integration; no multi-trace-directory aggregation; no console-side
OTel export (a different surface). Launch assets are untouched — the `launch-demo/`
"export-back is deferred" claims are owner territory, as is the L7 checklist box.

## [0.27.0] - 2026-09-02

The **A3 claim axis ships — the last engine capability (C8)**. A model writes an executable
check for the agent's claim; **execution decides**: the check runs contained in the sandbox
against the recorded final state, and its **exit code** is the verdict — not the model's
opinion. A3 may emit only WARN / FAIL / UNVERIFIED, **never PASS**; a check that exits 0 is
**silence** (the claim re-derives; silence is not PASS), and a check that will not execute is
`UNVERIFIED` with a named cause, never a guess. This is the axis that catches **intent
drift** — faithful trace, in-policy actions, wrong meaning — and the one the Phase 1→2 gate
requires: *no shipped PASS is ever produced by A3, verified by test*.

### Added

- **The A3 evaluator** (`src/belay/verify/claims.py`) — instance-level, beside the
  trajectory rule: reads the trace's `claim` record, reuses the closed deterministic
  classifier as the trigger gate, materializes the recorded final state (replay of the
  final turn), runs the synthesized check under `contained` (network deny-all, bounded
  timeout), and emits at most one `A3/claim` verdict. Closed cause vocabulary:
  `NO_CLAIM_RECORDED`, `CLAIM_UNCLASSIFIABLE`, `NO_CHECK_AUTHOR`,
  `CHECK_DID_NOT_EXECUTE`, `FINAL_STATE_UNOBSERVABLE`. Every A3 verdict surfaces the
  check's **source** and **real exit code**.
- **The out-of-process BYOK check author** (`src/belay/verify/author.py`) —
  `BELAY_CLAIM_AUTHOR` (or `--claim-author` on `belay verify`) names a **local** command;
  the wheel gains no dependency and nothing leaves the box. No author configured → the
  axis is **absent**, named on the coverage line — never UNVERIFIED, never PASS. The
  live-model path is a `manual`-marked gate, never CI.
- **`--no-claim-axis`** on `belay verify`, `belay phase0 run` and `belay corpus run` —
  and **the refutation test**: the corpus re-runs with and without the flag and every
  PASS and every FAIL verdict is **identical** (the claim case SKIPs with
  `CLAIM_AXIS_DISABLED`, never REGRESSES). The test's docstring: *"this test is the
  company's positioning encoded as CI — it must never be weakened."*
- **Instance-level A3 on every surface** — the text A3 line beside the trajectory line,
  the JSON `claim_record` (absent key when absent — the pinned `--json` fixture is
  byte-unchanged), `A3/...` labels in `canonical_cause`, phase0 disposition
  (A3 FAIL → `VERIFIED_FLAGGED`, banks an **intent-drift** case; UNVERIFIED never flags),
  ledger/report **absent-never-zero**.
- **Corpus case schema v5** — the instance-level `claim` expected field
  (`{"status", "cause", "check": {"source", "exit_code"}}`), `{trace}-claim` id
  namespace, recompute on the A3 dimension, and the zero-LLM import guard's escape-hatch
  note amended deliberately (the author is out-of-process by construction).
- **The acceptance-4 re-scope, as tests** — the launch demo (the negative control) stays
  all-green **with A3 present** (the check re-derives the true claim → silence), and a
  synthetic corrupt-success fixture yields **A3 FAIL corroborating A1 trajectory FAIL on
  the same fixture, from an independent axis**, with A2 never FAILing on it (the axes
  stay non-redundant — asserted, not assumed).

### Unchanged, and pinned

- **`verdict.reduce` is untouched** — axis-agnostic by construction; A3's
  downgrade-only property falls out for free. A1 and A2 verdicts, `NOT_COVERED`
  semantics, and every per-turn surface are byte-identical.
- **The refutation guarantee is a test, not a doc line** — every PASS/FAIL verdict
  survives `--no-claim-axis`, enforced on the corpus and on the demo capture.
- **Absent-never-zero everywhere** — no author / no claim / silence renders as absence or
  named cause, never a fabricated clean and never a fabricated UNVERIFIED.

### Honesty notes — read before quoting anything

- **A3 is dark by default.** No author configured → the axis is absent. The coverage line
  names it, and the README carries the one-line configuration — but no stranger's run
  exercises A3 until they configure an author.
- **No real intent-drift case exists yet.** The corrupt-success fixture is synthetic; the
  mint's next run is where the A3 column gets its first real measurement. The value is
  **forward-looking**, stated plainly — the same discipline as the trajectory corpus.
- **Reclassification discipline holds.** `11/60 = 18.3%`, the 11 hand-audited TPs,
  `precision 0.00`, `1/15` and `4/16` stand unedited. No Phase-0 number, verdict axis or
  status moves.
- **Suite 2062 → 2091 tests passing** (25 named-cause skips, 10 deselected; the docker
  in-image and compose modules verified on re-run).

### Not built, and named

The A3 WARN vocabulary stays empty (v0 emits FAIL / UNVERIFIED / silence only); a
caller-supplied final-workspace short-circuit for the evaluator's second replay is a
follow-on, not v0; C9 export-back and GHCR publish remain deferred by name; the A3
check grammar is an executable artifact with a declared argv — no structured check DSL.

## [0.26.0] - 2026-09-01

The failure corpus can now hold the trajectory axis — the axis that earned the Phase-0
number. Trajectory FAILs bank as corpus cases minted `f"{source_trace_id}-trajectory"` — an
**instance-level** namespace, disjoint from the per-turn `-turnN` cases by construction
(turn indices are integers). The shape that previously could never bank now does: an
instance whose **final turn** also carries a per-turn FAIL ingests **both** cases in one
verify pass, and `belay corpus run` recomputes both as MATCH. The old namespace targeted
the final turn's id, collided with the final turn's per-turn case, and the guard refused —
correctly — which is why zero of the shell-toolset mint's 23 trajectory FAILs banked and
`belay corpus score` read `n/a` on the axis that matters most.

### Added

- **Disjoint trajectory case ids** (`src/belay/corpus/add.py`) — the id minting is
  shape-aware: trajectory cases mint `f"{source_trace_id}-trajectory"`, derived and
  deterministic, never random. Per-turn ids are byte-identical; no schema bump (case v4
  already declares `trajectory`; the id is an implementation detail of the corpus dir
  name).
- **Final-turn coexistence** — trajectory FAIL + final-turn per-turn FAIL on one instance
  banks both cases in the same `_verify_one_trace` invocation (the per-turn loop runs
  first, the trajectory block second, and the second does not collide).
- **Score denominators proven real** — with `score()` unchanged, a labeled trajectory case
  (expected FAIL, human label true-positive) counts into precision/recall with a real
  denominator, proven end-to-end by test in a mixed per-turn + trajectory corpus.

### Unchanged, and pinned

- **Unrestorable pre-state stays unbankable.** A trajectory FAIL naming an unrestorable
  pre-state is refused with the named pre-state cause (the pre-state check runs before the
  collision check — ordering unchanged), and the instance keeps its real disposition and
  its place in the violation denominator.
- **Idempotent re-run refusal.** Re-running the same verify refuses both shapes with
  `CaseExistsError` ("already exists"); for the trajectory shape the rerun refusal
  preserves the stored case byte-identically, including a human label. No `--overwrite`
  anywhere.

### Honesty notes — read before quoting anything

- **No historical case was backfilled.** The shell-toolset mint's 11 hand-audited TPs were
  never re-banked — the s6 captures no longer exist on disk — so `corpus score` still
  reads `n/a` until a future mint runs under the fixed ingest. The value is
  **forward-looking**, stated plainly.
- **Reclassification discipline holds.** `11/60 = 18.3%`, the 11 hand-audited TPs,
  `precision 0.00`, `1/15` and `4/16` stand unedited. No verdict axis, status, or
  Phase-0 number moves.

### Not built, and named

`belay corpus run --shell-server` remains unexposed (library seam exists); standalone
`belay corpus add` trajectory support and any change to per-turn recompute are out of
scope; no verdict-axis or schema change (no v5).

## [0.25.0] - 2026-08-29

`belay verify` no longer emits a confident **FAIL** on a turn it never verified. A replay
server that does not offer the recorded tool answers **readably** — `no such tool`, or a
JSON-RPC error — and answers identically on every re-invoke, so the comparison DIVERGEd, the
classifier called the tool DETERMINISTIC, and `_deterministic_divergence_verdict` reported a
deterministic failure of a call that genuinely succeeded at capture. Every step correct, the
conclusion fabricated: nothing was re-executed, so nothing was refuted. What diverged is the
operator's `--server`, not the trace.

**Reproduced on the committed demo capture, and fixed there:** turn 0 (`run_process`,
replayed against a filesystem-only variant of `demo/server.py`) goes from
`"FAIL": 1, "UNVERIFIED": 0` to `"FAIL": 0, "UNVERIFIED": 1` with cause
`replayed but the boundary does not offer the tool`.

### Added

- **The boundary probe** (`src/belay/replay/probe.py`) — `offered_tools` asks a replay
  boundary what it offers by really spawning it, reusing `client.replay_turn` with
  `initialize` + `tools/list` frames rather than reimplementing sandbox, restore or
  relocation. Three-way and fail-closed: a set of names; `set()` when the boundary answered
  and offers nothing; **`None`** when the probe could not run or its answer could not be read
  — twelve distinct paths, and **never an empty set to mean "could not read"**. It never
  raises into the verdict path.
- **`belay verify --shell-server CMD`** — the per-tool routing parity `belay phase0 run` has
  had since `9138cea` (2026-08-14). Same single-quoted-string shape, `shlex.split` at use,
  fail-closed on an un-lexable string (exit 2, named). **Write it before `--server`**, which
  is an argparse remainder and swallows every token after it. A **flag-parity guard**
  (`tests/test_cli_flag_parity.py`) now fails if a flag reaches two replay-bearing surfaces
  undeclared — this defect class had already happened twice (`--timeout` in L7).
- **Three named causes**, each pointing at a different operator fix:
  `replayed but the boundary does not offer the tool` (name the right `--server` — and this
  is the count the gate mint needed), `boundary-ambiguous` (two configured servers claim the
  tool — name one), `boundary-undecided` (the probe was unrunnable or unreadable — make the
  boundary answerable). Folding them together would inflate exactly the number G4 counts.
- `resolve_server_argv` — the `{workspace}` substitution, exported so **one** site serves the
  replay and the probe, with an AST guard asserting there is no second one.

### Changed

- **Both A2 sub-verdicts abstain, not just one.** Result-equivalence and effect-conformance
  are computed from the same replay; gating only the first left the second reading *"the
  observed effect conforms"* about a turn where nothing ran (`readOnlyHint` is read from the
  **capture** — a declaration is not an observation). The gate sits ahead of the whole
  declared-vs-observed rule, so the mirror is closed too: a stray delta can no longer be
  scored against a declared `readOnlyHint: true` into a FAIL.
- **The probe runs before `classify_determinism`, so it is a saving, not a cost.** A
  not-offered turn settles in 2 boundary spawns instead of 4: ~146 ms → ~69 ms (**~52%
  less**) on the committed capture. A genuinely diverging turn on an *offered* tool pays one
  extra probe spawn, ~31 ms. Measured, not predicted.
- `effect:network` `NOT_COVERED` is deliberately **not** gated: it reports that *Belay* has no
  network instrument, which is true of every trace whether or not a turn re-executed.

### Fixed

- **`belay corpus run` recompute routed a shell turn to the wrong boundary** — `run_case` and
  `_recompute_trajectory_case` passed only the stored command, so a trajectory case's
  `run_process` turns silently recomputed against the filesystem command. The second boundary
  is now supplied by the caller, keyword-only, defaulting to today's behavior. **No schema
  bump**: case schema v4 still stores one resolved command, and banked cases load unchanged.
- **A broadcast JSON-RPC id could evict its twin after a trace merge** (`src/belay/index.py`).
  Pending requests keyed on `(direction, type(id), id)` with no session component were
  **overwritten**, so a reply could pair against the wrong request and `status` could
  misreport `duplicate-response` though both replies really happened. Pending requests are a
  FIFO queue now; a reply answers the oldest. Repairs the module against its own stated
  contract (*"appends rather than overwrites … a retried request cannot leak an entry"*).
- **C9 dropped the cause**: `interop correlate` rendered an abstaining span as a bare,
  causeless `UNVERIFIED` — invisible on the one surface built to sit beside an observability
  stack. And the per-turn kind column collided with its status (`A2 effect:networkNOT_COVERED`,
  since coverage shipped).

### Honesty notes — read before quoting anything

- **This is a RECLASSIFICATION, not improved detection.** The UNVERIFIED rate **rises by
  design** (risk R7). `11/60 = 18.3%`, the 11 hand-audited TPs, `precision 0.00`, `1/15`,
  `4/16` and every other published Phase-0 number **stand unedited**.
- **The mint's 171 per-turn FAILs are historical and were NOT recomputed.** They predate the
  2026-08-14 dual-server routing, and the s6 captures no longer exist on disk (a since-removed
  worktree; the holder backup holds `s1..s3` only). No mint was re-run or re-derived.
- **The broadcast-id fix could not be validated against real merged mint data** for the same
  reason. It is pinned by a **constructed** two-trace fixture with colliding ids — a
  legitimate test of the rule, **not a replay of history**. Its safety is evidenced instead by
  all four real traces in the repo correlating byte-identically under old and new algorithms,
  and by exhaustive enumeration of all 7381 frame sequences of length 0–4: 190 differ, and
  **every one contains two simultaneously-pending requests on one key** — the defect condition.
- **A2 kept its teeth.** Six anti-overreach tests were written *before* the abstention path
  existed and are untouched and green, including the shape closest to the defect — recorded
  success vs replayed `isError: true` on a tool the boundary **does** offer, which an
  over-broad "the replay came back an error" discriminator would swallow first. All six fail
  under a maximally over-broad discriminator; that was demonstrated by mutation, not assumed.
- **No verdict axis moved but A2.** A1, the trajectory rule and the claim classifier are
  untouched; A3 is still unbuilt. The trajectory axis is proved blind to this change:
  `assemble_turn_facts` reads only `replayed_is_error` and `tool_name`, pinned structurally so
  a future edit that taught it otherwise goes red.

### Not built, and named

N-server routing (deferred once already, on purpose), any trace-format provenance field, and
capture-side multiplexing — `src/belay/proxy.py` is one client<->server pipe by construction, so
a trace carries **no server provenance** and replay-time routing must be told, never inferred.
`belay corpus run --shell-server` is not exposed as a flag. `phase0 run --shell-server` still
lets an un-lexable string raise uncaught, where `verify` exits 2 with a named message — a real
asymmetry, recorded for a follow-up decision.

## [0.24.0] - 2026-08-28

The launch demo ships, and it is green — launch checklist L7's last aspect. The
corrupt success the locked spec promised **could not be produced on demand**: 18
observed drives across three conditions (two frontier models, an easy bug contract, a
genuinely hard one, an expensive-suite lever) yielded **zero**. Nothing synthetic was
substituted, so the demo ships what the drives produced — the **negative control**: a
real `claude -p` run, told only *"make the tests pass"*, that fixed the bug honestly,
ran the suite, and said so, verified 7/7 PASS, 0 UNVERIFIED, trajectory PASS
*"supported by 2 replayed command turn(s)"*. A detector that only ever fires is not a
detector. The measured corrupt-success shape (**11/60 = 18.3%**, with its
decomposition) is the companion exhibit, not the replacement.

### Added

- **`belay verify --timeout <seconds>`** — the per-replay timeout `corpus add`,
  `phase0 run` and `interop correlate` already carried. Without it, a trace whose turns
  outrun the fixed 10s default reports UNVERIFIED: an honest abstention, but one caused
  by the clock rather than by the run.
- **The console's replay context by default** — `BELAY_CONSOLE_VERIFY_SERVER` becomes
  `--server` (whitespace-split into argv tokens), and `--manifest-dir` defaults to the
  trace's `<stem>.manifests` sibling when it exists. Absent either, nothing is passed
  and the engine's fail-closed error stands — never a guessed server.
- **`demo/`** — the self-contained demo: fixture repo, the committed capture (trace,
  snapshots, manifests) with `PROVENANCE.md`, and a runbook. `tests/test_demo_capture.py`
  re-executes it on every PR and asserts the verdict has not moved.
- **`npm run record:demo`** — regenerates `assets/belay-demo.gif` from the artifact by
  driving the console with a real browser (manual, never CI). PNG decode and GIF encode
  both run inside the browser page: no ffmpeg, no image dependency.
- **`docs/planning/launch-demo/ph-assets.md`** — the PH listing draft, including a
  "claims that must NOT appear" list.

### Fixed

- **The console's verdicts were unreachable.** It passed `verify --timeout` before the
  flag existed, so argparse answered `unrecognized arguments` with empty stdout and
  exit 2 and *every* console verify degraded to `empty-output`. Its own suite could not
  see it: the stub engine echoes argv and cannot object.
- **The console's subprocess wall killed authorised replays.** A fixed 60s wall against
  a 300s per-replay budget SIGTERMed a legitimate replay at 60.0s and reported
  `empty-output` — blaming the engine for its own kill. The wall is derived now
  (`timeout × turns-in-scope`, floored at 60s) and reports `console-wall-timeout`.
- **The console image had never worked under plain `docker run`.** It defaulted to port
  8787 on 127.0.0.1 and read `~/.belay/traces`, while the image `EXPOSE`s 8080 and is
  deployed against `/workspace`. Compose set all three by hand and was the only path
  that ever worked. The image carries its own defaults now.
- **The committed capture was incomplete.** The root `.gitignore` excludes
  `__pycache__/`, so seven snapshot directories were never committed and restore died
  stamping a directory absent from the clone. Invisible on the machine that made the
  capture — where they exist as ignored files — and caught by the first clean clone,
  which is exactly the "a stranger can reproduce it" claim. Guarded on the clone now.
- **The trace view leaked the operator's home directory** into the launch asset by
  heading with the raw absolute path.

### Changed

- **The record matches what shipped.** The README's demo alt text, `docs/ROADMAP.md`'s
  locked demo, `CAPABILITY_ROADMAP.md` and `live-console/prd.md` no longer claim a flag
  turn ("turn 7") or a Langfuse side-by-side; each correction quotes what it replaced.
  A real Langfuse integration is **not built** (C9 export-back remains deferred), and
  `tests/test_demo_assets.py` now fails the build if the README asserts a catch the
  committed capture does not contain.
- `demo/capture/` is excluded from `ruff`: the snapshots are the bytes replay restores,
  so `ruff --fix` on them would be trace tampering by linter.

### Unchanged, deliberately

No verdict axis, invariant, status, or Phase-0 number moves. A3 (claim re-derivation)
is still not built; the GHCR publish job is still deferred.

## [0.23.0] - 2026-08-25

The C7 live console ships — the launch surface (launch checklist L6): `belay verify
--json` emits the full verdict document (per-turn statuses, every sub-verdict incl.
NOT_COVERED and UNVERIFIED-with-cause, aggregate, coverage block always present,
exposure, trajectory) rendered from the same objects as the human report — text output
byte-identical, exit codes unchanged, contract pinned by a committed fixture; the
local-first Vue 3 + Vite + TypeScript console (`console/`) streams a live run feed by
tailing the append-only trace, renders every turn with its verdict and the FAILed
turn's diff, carries the coverage line on every surface and renders UNVERIFIED
distinctly from PASS (a correctness test, not a style one), replays any past turn, and
logs expand/clicks locally; the `console:` compose service ships with a HEALTHCHECK
(the L3 deferral item C7 resolves) and bundles the engine wheel built in-image. No
verdict axis, reduction rule, or trace format changed.

## [0.22.0] - 2026-08-24

The quickstart is the live install path (launch checklist L4): a new `install` CI job
(macOS + pinned ubuntu-24.04) builds the wheel and sdist and proves the installed
artifact runs — CLI surface, version stamp, zero-dependency import, `sandbox check`,
and a capture → verify roundtrip (`tests/test_artifact_install.py`, `@pytest.mark.install`);
the README's "until then, run from source" caveat is gone, replaced by
`uv tool install belay-harness` / `pipx` / `pip`; the docs are machine-checked
(`tests/test_quickstart_docs.py`); and a time-to-first-verdict runbook ships for the
remaining L4 clause (stranger-timed, post-merge). No change to the verdict spine.

## [0.21.1] - 2026-08-20

Documentation and tooling only — **no change to `src/belay/`**, so the installed
package behaves exactly as 0.21.0. Cut to keep the record and the release history in
step with what was decided after L3 shipped.

### Changed

- **PRD should-have 9 (`belay sandbox check` as a Docker `HEALTHCHECK` / entrypoint
  preflight) is recorded as NOT SHIPPED, deliberately**, rather than left looking
  unfinished. The capability it wanted did ship and is the load-bearing half: the probe
  is the re-measurement instrument, it runs in-container on every PR, and README gives
  the exact macOS re-probe command. The Docker *directive* is what does not fit —
  `HEALTHCHECK` is periodic liveness for a **long-running** container, and
  `ENTRYPOINT ["belay"]` is a one-shot CLI that exits, so it would never meaningfully
  run; an entrypoint preflight would probe the sandbox before every invocation
  including `belay --help`, which needs none. It becomes right when C7's console
  service exists, and the note now says so there.
- **The `belay-end-fast` skill carried an instruction v0.20.0 and v0.21.0 made false**
  ("GHCR/Docker is deliberately deferred until the Linux sandbox slice — a Linux
  container can't run the macOS-only core"). Both halves were stale. Corrected to the
  real boundary: the image exists and is validated in-container on every PR; the
  **publish** job is what does not — so the next release run is not told to defer
  something that already shipped.

## [0.21.0] - 2026-08-20

### Added

- **Belay ships as a container that runs the REAL sandbox** (launch checklist **L3**,
  `docker-selfhost`). A multi-stage `Dockerfile` (`python:3.12-slim`, non-root `belay`
  user at uid 1000 with `--user root` as the one-flag opt-in, `ENTRYPOINT ["belay"]`,
  `python -m belay.proxy` reachable) and a minimal `docker-compose.yml`. `docker build
  -t belay .` needs **nothing but the checkout** — the wheel is built inside the image,
  so there is no prebuilt-wheel step to get wrong and no stale wheel to install.
- **The substrate is RE-MEASURED inside the container, not inherited.**
  `THREAT_MODEL.md` is explicit that a new image must re-measure, so
  `tests/test_docker_inimage.py` does exactly that: the repo's whole suite runs in a
  throwaway dev container with **every skip's cause machine-checked** (an unknown or
  unnamed cause FAILs) — which is how the Landlock+seccomp escape matrix and the
  copy-fidelity snapshot round trips are covered, as modules inside that run;
  `belay sandbox check` decides the boundary by **using** it (`landlock kernel ABI 8
  (ok)`, `containment ok (a write outside the scope was refused)`, `seccomp ok (an
  AF_INET socket was refused)`); and a **capture → verify roundtrip is generated
  entirely in-container** — gated proxy over real stdio, real snapshot, then `belay
  verify` re-executing against the restored pre-state → `turn 0 write_note PASS`, A2
  replay PASS, A2 effect PASS, `effect:network NOT_COVERED`, coverage line printed.
  The trace is made in-image and never mounted (the no-raw-data-egress guardrail).
- **A `docker` CI job on pinned `ubuntu-24.04`** builds the image from every PR and
  runs all three container modules against it.
- **`THREAT_MODEL.md` gains a container section** where every claim cites the run that
  produced it: Landlock is the **host kernel's** and is not namespaced (a pre-5.13 host
  ⇒ the launcher refuses, exit 2, named cause — loud, never a bare spawn); Docker's
  default seccomp profile sits **under** Belay's BPF filter and the two compose by
  intersection (measured: `Seccomp: 2` in a stock container); overlayfs has no reflink
  ⇒ the copy path with the named `reflink-unavailable` cause; the cross-substrate
  corpus consequence bites (a macOS-banked case is **SKIP** with
  `UNRESTORABLE_CAPABILITY_MISMATCH` inside the container, never a guessed restore);
  the world-writable `/tmp` neighbourhood is restated, not fixed; and the docker.sock
  line stays closed.

### Changed

- **README's "no container yet" callout is replaced by the `docker run` quickstart**,
  carrying the kernel ≥ 5.13 requirement and the coverage line. `RELEASING.md` now says
  what is actually deferred: the image is built, the **publish channel** (GHCR) is the
  separate slice — and when it lands it should push the SAME image the `docker` job
  already validated rather than rebuilding an unvalidated one.
- **The claim split is stated wherever the claim is made.** CI asserts the
  **Linux-host** path (on the pinned runner the container's kernel *is* the runner's).
  The **macOS-host** path runs on Docker Desktop's Linux VM kernel, which CI cannot
  reach, so it ships as a **documented manual re-probe** with a recorded reference
  measurement to compare against — never asserted by CI.

### Fixed

- **`docker build -t belay .` failed on any machine that had not just run `uv build`.**
  The Dockerfile `COPY`d a prebuilt wheel and died at `lstat /dist`; the session
  fixture hid it by building the wheel first. The build is multi-stage now, and the
  fixture **sweeps** `dist/` before building, so every docker test proves the
  clean-checkout path.
- **`docker run --rm belay sandbox check --scope /workspace` exited 1** with
  "containment PROBLEM: the probe never ran" — `WORKDIR` creates the directory as root
  and the image then drops to `belay`, so the containment probe could not write inside
  the scope. `/workspace` is chowned to the container user. A boundary check that
  cannot run is worse than one that fails.
- **A trace-ordering race, found by the Linux CI runner.** `belay.proxy._pump` forwards
  each chunk and observes it afterwards — "forwarding must never wait on the recorder",
  the transparency contract — so a fast server can have its `tools/list` **response**
  recorded before its own **request**. An inverted pair does not correlate,
  `derive_annotations` takes no snapshot, and effect-conformance abstains. The
  degradation is honest (UNVERIFIED, never a false PASS) and the engine is unchanged;
  the roundtrip fixtures close the window by waiting on the trace itself rather than on
  a sleep. Stress: 40/40 in-container, from 18/20 before. **Logged as a follow-up** —
  it is a real coverage-loss path for any fast local server.

### Housekeeping

- `CHANGELOG.md`'s `[0.19.0]` and `[0.20.0]` sections were out of order (0.19 above
  0.20); reordered newest-first.

## [0.20.0] - 2026-08-15

### Added

- **The Linux sandbox slice — C2's second implementation, measured on ubuntu-24.04**
  (`linux-sandbox`, aspects A1–A4). The sandbox seam is now two substrates:
  - **A1 · mechanism decision** (`containment-spike`): the containment spike probed
    the pinned ubuntu-24.04 image and measured what works — bubblewrap is dead on
    stock runners (unprivileged user namespaces AppArmor-restricted), **Landlock
    (ABI 7) + seccomp** is the viable zero-dependency mechanism, Landlock's net
    domain cannot express loopback-only (`allow-ports` degrades with a named cause),
    and filesystem denials are EACCES — the same text an ordinary `chmod` produces.
    Decision cites the CI probe artifact (`probe_result.json`).
  - **A2 · Landlock + seccomp containment** (`linux-containment`): `src/belay/sandbox/linux.py`
    — the launcher (`python -m belay.sandbox.linux <policy.json> -- <cmd>`) installs
    a Landlock write-scope ruleset (write rights beneath the scope, EACCES refusal)
    and a seccomp deny-all filter (socket only for AF_UNIX; connect/sendto/sendmsg/
    sendmmsg EPERM; wrong arch → ENOSYS). The macOS escape matrix has Linux analogues
    (direct/`../`/symlink/`mv`/grandchild, live-listener network probes), denial
    records are shape-identical (`inferred: true, source: "child-stderr"`), and the
    first real Linux run surfaced and fixed four prediction bugs (dash vs bash exit
    codes, GNU quote-wrapped denial paths, the loopback probe's socket scope, a
    `GuardedSnapshot` API misuse).
  - **A3 · copy-fidelity snapshot backend** (`linux-snapshot`): `src/belay/snapshot/linux.py`
    — byte-identical snapshot/restore on the Linux substrate via a copy with the
    same sidecar repairs as clonefile (hardlinks, setuid, dir mtimes), `FICLONE`
    reflink probed per directory and never assumed (ext4 CI runners take the copy
    path), and the three reserved taxonomy causes (case collision, normalization
    collision, invalid UTF-8) reachable on case-sensitive byte-transparent
    filesystems. Capability-mismatch refusal preserved: a case banked on one
    substrate can never be guessed back on the other.
  - **A4 · ubuntu CI job + honest docs** (`linux-ci-docs`): `test (Linux)` on pinned
    ubuntu-24.04 runs the full suite (**1619 passed, 0 failed**); the gating split is
    user-confirmed — substrate-independent tests run on both platforms,
    substrate-specific tests have Linux analogues, and genuinely seatbelt-only tests
    (e.g. `test_sbpl_limits.py`, which pins against `sandbox-exec`) stay darwin-gated
    with a **named cause**. `tests/test_platform_gate_named_causes.py` scans every
    sandbox/replay gate and requires its reason to name a cause from README's
    platform coverage table. The corpus reverse gate now asserts the cross-substrate
    reality: a darwin-banked case re-verifying on Linux is SKIP with the named
    `UNRESTORABLE_CAPABILITY_MISMATCH` cause (the replay engine converts the restore
    refusal to UNVERIFIED — it used to crash). `THREAT_MODEL.md` gains the Linux
    section (what is enforced, what is not — the EACCES provenance ambiguity, the
    `allow-ports` degradation, reads un-scoped *by mechanism* on Linux, the R8
    launcher surface, the TMPDIR/world-writable `/tmp` difference, the
    cross-substrate corpus consequence); README badge and platform sections claim
    macOS + Linux, both measured; the Linux classifier lands in `pyproject.toml`.
    Launch checklist L2 marked ✅.

## [0.19.0] - 2026-08-15

### Added

- **THE PHASE-0 GATE PROCEEDED — the first gate run to clear its own pre-registered
  criteria** (`mint-shell-toolset-run`). The shell-toolset mint ran `claude-opus-5`
  through stages 1 → 2 → 3 under the freeze protocol (fresh roots `s6{a,b,c}`,
  `--toolset filesystem+shell`, composite transport, verbatim `run_process`): **60
  distinct fresh non-control instances** (≥50), **11 independent hand-audited TPs**
  (≥3), no `INSTRUMENT SUSPECT` in any stage, 4/4 controls `VERIFIED_CLEAN` (no D-3
  void), FP rate stated (0 adjudicated FPs of 23 trajectory FAILs) → **the canonical
  gate block PROCEEDs**. Hand-audited violation rate (trajectory axis): **11/60 =
  18.3%** — R1's quantitative form answered in the positive at n=60. Three named
  caveats, recorded not hidden: (1) all 171 per-turn FAILs are A2 replay artifacts of
  the U9 verify composition — the per-turn FAIL rate is an instrument artifact, never
  a violation rate; (2) the 23 trajectory FAILs split 11 true positives + 12
  unverifiable-by-seam — the number is trajectory-axis only, A1 compared 0 files at
  n=60; (3) zero trajectory FAILs bankable as corpus cases (case-id namespace
  collision + unrestorable pre-state) — `corpus score` reads `n/a`, and the
  id-collision is a recorded follow-up defect. The raw ledger rate 37/52 = 71.2%
  decomposes 11 TP + 12 seam + 14 A2 artifact; quote 18.3%, never 71.2%, without the
  decomposition. n=60 × one model × one prompt is a measurement, not a base rate.
  Ledgers at `docs/planning/mint-shell-toolset-run/mint-run/ledgers/` (byte-identical
  re-renders), audit at `docs/planning/mint-shell-toolset-run/audit-and-publish/`,
  decision in `PHASE0_RESULTS.md` → *The shell-toolset mint ran, and the gate
  PROCEEDs — 2026-08-12*. Launch checklist L1 marked ✅
  (`docs/planning/launch-readiness/CHECKLIST.md`).
- **Eval: stage-6 mint registries and trace merge** — `eval/instances/stage6{a,b,c}.json`
  (the run's registries, fresh draws excluding every previously-minted id),
  `eval/scripts/build_stage6_registries.py` (byte-reproducible generation), and
  `eval/minting_driver/trace_merge.py` (merges the composite transport's per-session
  traces into one per-instance capture, `run_batch` integration). Eval-only, not a
  product surface; test-pinned (1704 tests).

## [0.18.0] - 2026-08-14

### Added

- **The gate mint's verify composition: `run_process` turns replay against the shell
  server** (`phase0-gate-mint`, aspect `verify-dual-server`). `verify_turn` gains
  `shell_server_command`, resolved by the exact recorded tool name: a `run_process` turn
  with the flag given replays against the rootless pinned shell server command, every
  other turn against `--server` — so the trajectory rule's evidence (a replayed exit-0
  `run_process` before a verification claim) is finally observable on real shell turns,
  and the positive control's expected PASS is reachable. `belay phase0 run` gains
  `--shell-server CMD` (a single string, shlex-split at use, fail-closed on un-lexable
  input; **must precede `--server`**, which is `nargs=REMAINDER`); `run_batch` threads
  it per turn, and corpus ingest stores the command each flagged turn actually replayed
  against, so cases stay self-contained. Honesty unchanged: a shell turn whose outcome is
  unreadable or whose replay never happens is UNVERIFIED with its named cause, never PASS.
  Absent the flag, the composition is byte-for-byte the single-server spine (regression
  pinned).
- **The gate mint's stage registries** (aspect `registry-rescope`, eval-only): a
  committed `eval/instances/observed.json` — the 23 previously-minted instance ids,
  derived deterministically from the committed stage registries, `EXCLUDED_INSTANCE_IDS`,
  the s3-partial ledger and the live smoke, byte-reproducible — and three new stage files
  generated from `pool.json` + `observed.json` + `controls.py` (seeds 20260814):
  `s6stage1.json` (2 controls: CTL-1 + the new positive control), `s6stage2.json`
  (CTL-2 + CTL-3 + 7 fresh real, steering sentence verbatim), `s6stage3.json` (80 fresh
  real + 3 controls — the ≥50 gate denominator with attrition margin). The historical
  `stage1.json`/`stage4.json` are derivation sources and stay untouched.
- **Run-aspect drafts** (aspect `mint-run`, ledger-style): freeze scripts
  (`acceptance-stage{1,2,3}.sh`, `RUN=1`-gated, dual-server verify baked in), a stage
  runbook, and the adjudication templates (FLAGS/AUDIT/HAND_REPLAY/REPRODUCIBILITY +
  operator checklist) mirroring the re-mint discipline. The mint itself — stages s6a/b/c
  under the freeze protocol, the ≥50 denominator, the gate decision line for R1 — is the
  operator's next step and produces no number in this release.

### Changed

- `eval/README.md`: the verify section documents the dual-server `belay phase0 run`
  composition and its ordering constraint.

## [0.17.0] - 2026-08-12

### Added

- **The trajectory axis becomes ability-aware, and the mint gains a command tool**
  (`trajectory-toolset-rescope`) — the re-scope the voided re-mint's adjudication named as
  the next unit. Engine: `suite-before-success-claim` now abstains with two new closed
  causes — `NO_COMMAND_TOOL_OFFERED` (a `tools/list` snapshot exists and no command tool was
  offered before the claim) and `TOOLSET_UNKNOWN` (no snapshot, or a stale one) — and FAILs
  only when a command tool was actually offered with zero replayed exit-0 `run_process`
  turns before a verification claim. The remint's 5 false positives by construction
  (`suite-run-ability-not-offered`, precision 0.00) recompute UNVERIFIED with a named cause;
  the change is a reclassification, never improved detection, and no published number was
  re-derived. A false-abstention invariant is pinned by test: a trace containing a
  `run_process` turn can never abstain `NO_COMMAND_TOOL_OFFERED` — usage is proof of
  offering. Eval: the minting driver offers the pinned shell server
  (`mcp-server-commands@0.8.2`) alongside the filesystem server on one boundary — a
  composite transport with verbatim tool names and one call in flight, the shell server
  rooted at the per-instance workspace — selectable via `--toolset filesystem+shell`
  (default `filesystem`, so prior freeze invocations run identically). Controls: the write
  controls' task text steers completion-only claims (expected abstain, pinned via the
  classifier), and a new `control__flask-verify-with-command` is the trajectory axis's first
  positive control (expected PASS; held out of stage registries — composition is the next
  mint unit's decision). Corpus: declared-UNVERIFIED trajectory cases classify MATCH on
  recompute, and no-command-tool/command-tool fixtures bank the new behavior. The live
  dual-server smoke is `manual`-marked (operator step once `eval/servers/` is installed);
  migration and banked-population reclassification runbooks ship in
  `docs/planning/trajectory-toolset-rescope/`. **R1's quantitative form stays untested** —
  this unit makes the axis able to measure the population; the next mint is the gate
  decision.

## [0.16.0] - 2026-08-09

### Added

- **The re-mint ran under the trajectory invariant, and its own pre-registered control gate
  voided it** (`phase0-remint`) — a docs-and-measurement release, no engine change. Stage 2
  (3 controls + 7 fresh real, `claude-opus-5`) captured **10/10** with 57/57 turns PASS,
  0 UNVERIFIED and no `INSTRUMENT SUSPECT`; the write control's verification claim (zero
  command turns) came back **trajectory FAIL** and voided the mint per the pre-registered
  D-3 rule, so stage 3 (the ≥50 denominator) never launched. The hand-audit publishes the
  trajectory rule's **first real-text precision measurement — 0.00** (0 TP / 5 FP, coverage
  1.00): all 5 FAILs are false positives **by construction**, because the stage's MCP
  boundary offered no shell/`run_process` tool, so the rule's evidence was impossible to
  produce. The dated **VOID** decision line and RUNBOOK corrections carrying the trajectory
  era ship with it. R1's quantitative form remains untested; the next unit must offer a
  command tool on the boundary before the axis can measure this population.

## [0.15.0] - 2026-08-09

### Added

- **The trajectory success invariant — `suite-before-success-claim` — ships** (the re-scope
  the funded mint's exposure gate demanded, `trajectory-success-invariant`). A default-on,
  instance-level A1 rule: the suite must be executed before a success claim, judged A1-style
  against observed replay effects. A new `claim` trace record captures the agent's final
  claim at session close (minting driver appends `Done.reason`; `max_steps` writes nothing);
  a conservative deterministic classifier (stdlib, abstain-first) triggers only on
  verification claims — completion-only and ambiguous claims abstain with named causes. The
  rule FAILs a verification claim with zero replayed exit-0 `run_process` turns (the
  corrupt-success shape this population exhibits: edit source, claim success), PASSes with
  evidence, and abstains honestly (`NO_CLAIM_RECORDED` / `CLAIM_UNCLASSIFIABLE` /
  `EVIDENCE_UNOBSERVABLE` — never a silent PASS). Instance-level rules are excluded from the
  per-turn loop by construction, so no per-turn verdict changes. A trajectory FAIL marks the
  instance `VERIFIED_FLAGGED` and counts in the violation rate; ledger, `phase0 report`, and
  `belay verify` carry the verdict additively (absent-never-zero). Trajectory FAILs bank as
  corrupt-success corpus cases (case schema v4) and `belay corpus run` recomputes them
  instance-level (MATCH/REGRESSION, recorded-miss transitions).
  **No real instance has yet been judged by this rule** — no mint has run under it — so it
  ships as a capability, not a result; precision is decided by adjudication after the first
  mint, and the re-mint is the next gate decision. No published number was re-derived.

## [0.14.0] - 2026-08-09

### Added

- **The funded mint ran, and was stopped by its own pre-registered exposure gate.** The
  `phase0-mint-run` unit drove `claude-opus-5` on the subscription path through two stages under
  the freeze protocol: stage 1 (1 control) `VERIFIED_CLEAN`; stage 2 (3 controls + 7 fresh real)
  captured 8/10 — **3/3 controls clean** (including the third control's first live coverage),
  **35/35 turns PASS, 0 UNVERIFIED, no `INSTRUMENT SUSPECT`**. Every real instance edited
  **source**, never a `tests/`/`testing/` path, so the A1 rule judged 0 files and the exposure
  gate stopped the run before the ≥50 denominator stage. **Not a detector PIVOT, not the STAGE2
  no-op failure, not a void** — the population × model × prompt produces zero A1-visible
  behavior; R1's quantitative form remains untested, and the next unit re-scopes the axis.
  **eval + docs only: no `src/belay/` change, no verdict on any axis.** Ledgers committed and
  re-renderable via `belay phase0 report`.
- **`--safe-mode` ships in the claude-cli oracle argv.** Probed 2026-08-09 (auth survives the
  flag from a scrubbed env, committed verbatim), asserted on the constructed argv with `--bare`
  still asserted absent — the oracle is isolated from the operator's hooks, plugins, and
  `CLAUDE.md` without touching authentication.
- **Controls-first stage registries for the funded mint** (`eval/scripts/build_stage4_registry.py`,
  deterministic and offline, + `eval/instances/stage4a.json` / `stage4.json`).

## [0.13.0] - 2026-08-05

### Added

- **A third mint provider, so the Phase-0 mint no longer needs a metered API key.** `ClaudeCliModel`
  (`eval/minting_driver/clients/claude_cli_client.py`) drives the `claude` CLI as a subprocess on
  credentials the operator already holds. The mint had no affordable path — the entry point
  registered two metered providers and Stage 3 died on a **daily** cap — and this removes that
  blocker without changing what a capture proves. **eval-only: no `src/belay/` change, no capability,
  no verdict on any axis.**
  **R6 and R7 still hold by construction, not by policy.** The oracle is granted **no tools**
  (`--tools ""` **and** `--strict-mcp-config`, each asserted separately on the constructed argv), the
  MCP schemas travel as *data in the prompt*, and `loop.py`/`batch.py` are **byte-unmodified** behind
  a pinned content hash plus a meta-test that the guard notices an edit. A content hash rather than a
  merge-base diff, deliberately: a merge-base check goes vacuous the moment the branch lands.
  **No API key is read or passed**, asserted on the constructed **child env** rather than only the
  argv — `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` are scrubbed **by
  absence, never by empty string**, because an empty value still occupies its precedence slot. The
  test sets all three before asserting absence: one that passed only on a machine without a key would
  certify nothing. Stdlib-only, so the zero-dependency contract holds trivially rather than by
  discipline. **96 tests, all 20 acceptance criteria; suite 1342 → 1492.**
- **An offline exposure forecast** (`eval/scripts/forecast_exposure.py`): **29/65 launched task
  descriptions mention test work (44.6%)**, pool 59/166 (35.5%), controls partitioned out, `unknown`
  counted and stated. Deterministic, no network, no model, and it reproduces an independently derived
  figure exactly — which is the check that the instrument is sound.

### Changed

- **`--max-turns` is treated as a no-op and the client owns its own bound.** Probed: the flag is
  absent from `claude --help`, is accepted silently, and `--max-turns 1` still produced `num_turns:
  2`. The bound is `DEFAULT_MAX_STEPS` plus a client-owned subprocess timeout.
- **Error classification is wired through base-class selection rather than a new branch in the
  shared classifier.** `subprocess.TimeoutExpired` is **neither** a `TimeoutError` **nor** an
  `OSError`, so it would have classified `terminal`; `FileNotFoundError` **is** an `OSError`, so a
  missing binary would have classified `transient` and been retried twice for a condition that can
  never succeed. `resilience.py` is untouched: `ClaudeCliTimeoutError` derives from `TimeoutError`
  and `ClaudeCliBinaryMissingError` deliberately does not derive from `OSError`. Asserted end to end
  through the real `classify_error`, never by class name — the class name is what misled here.
- **`max_tokens` on the subscription path is refused rather than ignored.** The CLI exposes no
  reply-length flag, and accepting the value would report a cap that does not exist.

### Notes

- **This release does not run the mint, fill the ≥50 denominator, clear the Phase-0 gate, or test
  R1.** All four stand exactly where 0.12.0 left them, and `4/16`, `precision 0.00`, `3/93`,
  `recall 0.00`, `1/15` and the 17-judgment exposure figure are unedited.
- **One live instance was driven as the unit's exit criterion**, once, under the freeze protocol:
  `pytest-dev__pytest-7432` on `claude-opus-5`, 87.4 s, trajectory `search_files → search_files →
  read_text_file → edit_file → read_text_file`, 5 turns all PASS, no `INSTRUMENT SUSPECT`. A real
  write crossed the MCP boundary. **"The path works at n=1"** — never *"edit quality is good"*.
- **That run's sharpest finding argues against its own release's forecast.** Exposure was **zero**:
  the agent edited `src/_pytest/skipping.py` — **source, not tests**. An agent *correctly* fixing a
  bug edits source, so low exposure may be a property of **the work** rather than of the instance
  draw. The forecast's claim that 44.6% is a **floor** was **withdrawn the same day**: `pytest-7432`
  is one of the 29 it counted and produced zero, so with one error in each direction the sign of the
  bias is unknown. The pre-registered decision (fund the mint) is unchanged; only its warrant is
  weaker.

## [0.12.0] - 2026-08-04

### Fixed

- **Declaring a recorded miss on an already-banked case no longer writes a v3 field under a v2
  version.** `belay corpus label --recorded-miss-note` round-trips the case through
  `dataclasses.replace`, which preserved the `schema_version` read from disk — and **every**
  human-labeled case in existence is `schema_version: 2`, so the realistic first declaration wrote
  `{"schema_version": 2, "recorded_miss": {…}}`. Pre-v3 code reading that ignores the field and
  returns `MATCH`: the regression suite certifying a blind spot as agreement, which is the exact
  silent misclassification the version bump exists to prevent. Introducing a declaration now carries
  the bump with it; an ordinary relabel, which writes no v3 field, leaves the version exactly as
  loaded.

### Changed

- **The exposure count is reported as `file-comparison(s)`, not `file(s)` — the noun was wrong, the
  number was not.** `files_compared` is summed across turns (`phase0/runner.py`, which already said
  *"It is NOT a count of distinct files, and must never be read against a file count"*), so it counts
  `(turn, file)` **judgments**. Every aggregate surface said "file(s)" anyway: `belay phase0 report`,
  `belay phase0 combine`, `belay verify`, and the published record. **No count, threshold or verdict
  changes** — the measured total is still 17, now correctly named, and it was made over **7 distinct
  files**. The per-sub-verdict message in `verify/invariants.py` keeps `file(s) compared`, where the
  count really is distinct files. The published claim that two methods agreed *"to the file"* is
  narrowed to what was actually shown: the static survey counted 17 **writes**, the instrument 17
  **judgments**, and they agree **event for event, instance for instance** — file-level agreement was
  never established.
- **`belay verify` no longer prints the state name `no opportunity` beside a non-zero in-scope
  count.** `exposure: no opportunity — 1 file(s) in scope, 0 compared` contradicts itself: a file
  *was* in scope. It now reads `exposure: 1 file(s) in scope, 0 file-comparison(s) — this carries no
  information about the rule`, matching the phase-0 surfaces, which dropped the same "given nothing
  to judge" framing for the same reason. The state name stays in the code; it is not a claim the
  output can make about a turn where the rule was handed a file and correctly found nothing in it to
  weaken.

- **What a green `belay corpus run` means — again, so read this before quoting one.** It means
  *"no case regressed"*, and that is the whole claim — literally `CorpusRun.has_regression`. It
  does **not** mean *"the engine catches everything in the corpus"*: a green run coexists with
  known, **declared** blindness, and that is the point of `STILL_MISSED` existing as its own
  outcome. It does **not** mean *"every recorded miss is still recorded as missed"* either — a
  miss that just closed (`MISS_CLOSED`) is green too, and in that run a recorded miss is
  precisely *not* still missed. Anything past "nothing drifted" has to be read off the printed
  outcome counts. This reading has had to be corrected twice before — the same green once
  certified that Belay still *mis-fired identically*, and later that the A1 rule still reached
  `PASS` on seven turns a human adjudicated false positives — so it is now said outright where a
  reader will hit it:
  `src/belay/corpus/run.py`'s module docstring and README's *Coverage & limits*, and in the
  negative on `corpus run`'s sign-off line, which states the `STILL_MISSED` count, and on its
  `--help`, which says such counts are stated plainly so a known-open miss is never mistaken for
  a clean full pass.
- **A banked miss can now be recognised as one, which is what the corpus was missing.** Careful
  about what changed: `belay phase0 run` ingests flagged turns and nothing else, so a violation
  the detector *missed* never becomes a case by the bulk path — but `belay corpus add` has never
  enforced that precondition, so a miss was always *reachable*, and it already counted as a false
  negative in `corpus score` (which keys on the human label and a non-`FAIL` stored verdict, and
  does not consult the new declaration). What was missing is that nothing could **say so**: an
  undeclared miss re-verified as a `MATCH`, i.e. the regression suite certifying a known blind
  spot as agreement, and an `FN` of `0` read as a measurement when the corpus had simply never
  been pointed at one. The declaration, `STILL_MISSED`, and the `FN` provenance line are what is
  new. **This is a capability, not a result** — whether any miss has actually been banked, and
  what the resulting recall is, is a separate empirical question that nothing in this release
  answers.

### Added

- **A corpus case can declare that its stored verdict records a MISS** — the engine returned clean
  on a turn a human adjudicated a real violation, so the clean verdict *is* the defect. Declared
  by a human via `belay corpus label --recorded-miss-note "…"` (case schema **v3**); the note is
  **required**, mirroring the existing rule that a `true-positive` label requires a root cause — a
  human asserting the engine missed something must say what. Presence of the field *is* the
  declaration, absent is a normal case byte-for-byte, and there is no code path from a verdict, a
  status, or a label to setting it. A declaration on a case whose stored verdict is already `FAIL`
  is rejected at load and at label time: a miss that was caught is a contradiction.
- **Two `belay corpus run` outcomes, reachable only for a declared case.** `STILL_MISSED` — the
  engine still does not catch it; exit `0`, but deliberately **not** a `MATCH`, because `MATCH` on
  a recorded miss certifies blindness as agreement. `MISS_CLOSED` — a sharpened detector now
  catches it; exit `0`, so CI does not go red for a fix. The exemption covers **exactly one**
  transition (the reduced status and the A1 `invariant` sub-verdict(s) both moving `PASS → FAIL`,
  everything else byte-identical), decided by constructing that one patched expectation and
  demanding exact equality rather than by inspecting a diff. Any other divergence — an A2 move, a
  `WARN`, an `UNVERIFIED` without an environment cause — is still a `REGRESSION`, on a declared
  case as much as on any other. `has_regression`, and therefore the exit contract, counts only
  `REGRESSION`. **A documented limit:** nothing keeps a closed miss closed. The command tells you
  to re-add a `MISS_CLOSED` case so the caught verdict becomes its new `expected`, but nothing
  enforces or tracks that — until you do, a detector that re-breaks returns the case to
  `STILL_MISSED` (green), not `REGRESSION`.
- **`belay corpus score` names where a false negative came from**, reporting how many `FN`-
  contributing cases are a human-banked recorded miss — a known blind spot the stored verdict
  already reflects, not a detection that failed today. `corpus show` prints the declaration
  (absent-vs-declared kept distinct) and `corpus list` carries a `recorded-miss` marker column.

### Fixed

- **`belay corpus add`'s help no longer claims a precondition it never enforced.** Five places
  said a case is composed from a *flagged* turn; nothing in the composition path has ever filtered
  on the recomputed verdict. A reader who trusted them went looking for a `FAIL` filter that does
  not exist and concluded the corpus structurally cannot hold a miss — the exact misconception
  this release removes. The fifth was the `corpus` sub-parser's own one-liner (*"labeled,
  replayable cases from flagged runs"*), which renders on `belay --help` — the most-read surface,
  and one an `add --help` test structurally cannot reach. No behaviour changed; the strings did.
- **A stored `expected` carrying an unknown extra top-level key can no longer reach
  `MISS_CLOSED`.** The miss-closing patch is now built *from* `expected` rather than from the two
  top-level keys the recompute produces, so an unrecognised key rides into the patch and equality
  fails. `STILL_MISSED` always compared `expected` whole, so such a case could previously reach
  the exempting outcome while being structurally unable to reach the non-exempting one. The new
  rule is strictly narrower — the extra case is now a `REGRESSION` — and asserts no schema.

- **Record correction: the shipped `0.10.0` sentence "a violation the detector misses can never
  become a case … the corpus cannot measure recall" is false as a capability statement, and its
  first half was already false when it was written.** The `## [0.10.0]` entry below is left
  **byte-identical** — Keep a Changelog does not rewrite shipped entries, and that entry handled
  the `0.9.0` sentence the same way, by pointing back at it from the next release. `belay phase0
  run` does ingest FAIL turns and nothing else, so a miss never arrives by the *bulk* path — but
  `belay corpus add` has **never** enforced that precondition, and `metrics.py`'s FN branch was
  implemented and unit-tested throughout. What was genuinely missing is that nothing could
  **declare** a stored miss, which this release adds. **`FN 0` is now empirical rather than
  structural.**

- **Record correction: "both controls `VERIFIED_CLEAN` — no detector false positive on a control"
  does not follow, because both controls compared ZERO files.** The measurement is published in
  `docs/technical/PHASE0_RESULTS.md` → *Correction — 2026-08-04*, run once under the freeze
  protocol over the same banked captures under the **same** detector (script `f9e9957` containing
  no result → verbatim output `8ec398d`; ledgers committed at `7ab5ba3` and re-derivable with
  `belay phase0 report`). **The headline is unchanged at 1/15 = 6.7%** — the rate was never the
  question. What is new underneath it: **17 file-comparisons across 22/22 captures — 6 instances
  judged something, 9 compared ZERO, 0 `unrecorded`**, with the instrument's delta-based count
  reproducing an independent static survey **exactly, instance for instance** — the survey counted
  17 **writes**, the instrument 17 **judgments**. **17 is a count of `(turn, file)` judgments, NOT
  of files**: they were made over **7 distinct files**, and file-level agreement was never
  established and is not claimed.

  **State the control finding exactly and do not inflate it.** The controls are **not void** — they
  were captured, replayed and verified, and nothing about them is wrong. What is withdrawn is one
  **inference**: a control the rule never judged cannot demonstrate the rule does not over-fire.
  The **blindness clause** is likewise **narrowed** to the six instances actually judged, and
  **dissolves** for the other nine — there was never a question to answer there.

  **Separately, in its own evidence grade — human adjudication, n=2, not execution:** the only two
  held-out exposed-and-passed turns in the banked data (`pytest-dev__pytest-5692` s3 turn 8,
  `pytest-dev__pytest-6116` s3 turn 15) are **additions, not weakenings**. **0 misses found of 2
  adjudicated; sensitivity still unconfirmed** — never *"the rule has good recall"*, because **n=2
  is not a base rate**, and **not comparable** to the recorded `recall 0.00 (0/1, n=1)`: different
  detector, different population, different adjudication set. Consequently **no miss was banked**,
  and the recorded-miss path added in this release ships **unexercised on real data**.

  **What this is not.** **Not a gate run** — the pre-registered ≥50 clause counts *instances
  minted* and is detector-independent, so **the 2026-07-29 PIVOT stands on the identical clause**
  and **R1 remains OPEN and untested**. **Not a precision or recall number.** **No published number
  was re-derived:** `4/16`, `precision 0.00`, `3/93`, `0% UNVERIFIED`, `recall 0.00` and `1/15` all
  stand unedited; only annotations and new figures were added.

## [0.11.0] - 2026-07-31

### Added

- **A ledger now records which detector produced it** — the A1 rules and scopes in force, plus an
  optional caller-injected version. A ledger without that field (every ledger written before this
  release) loads unchanged and renders the literal word **`unrecorded`**, with a clause saying its
  numbers must not be assumed current. Absent is never treated as corrupt *or* as current.
- **`belay phase0 combine LABEL=PATH …`** merges N run ledgers into one population and states its
  dedup rule in words. A **capture** is `(stage label, trace_id)`; an **instance** is a `trace_id`
  — because a `trace_id` is the trace file's stem and is therefore **not unique across stages**,
  so two stages of one instance share it while being genuinely different observations. Both
  denominators are reported (instances as the headline, captures alongside), and every instance
  whose captures disagree is named.
- **Controls are partitioned out of the headline violation rate** and reported in their own block,
  with the ids treated as controls named rather than only counted. A FAILing control is reported
  as a **detector false positive** and explicitly *not* as a mint-void condition — void belongs to
  a fresh mint, and conflating the two would manufacture a fake PIVOT.
- **`belay phase0 run --no-ingest`** for a pure measurement that writes no corpus cases, with a
  report note distinguishing *not attempted* from *attempted and failed* — an unlabelled empty
  ingest bucket otherwise reads as "nothing could be added".

### Fixed

- **`belay.__version__` now reads the installed distribution** instead of a hardcoded `"0.0.0"`
  that had drifted from the shipped release — a literal in `__init__.py` and the version in
  `pyproject.toml` are two places to state one fact. The old smoke test asserted only that it was
  a *non-empty string*, which passed against the drift the whole time. A phase-0 ledger now
  records that version as its code identity; it previously recorded `None` **on purpose**, because
  the only version reachable was known-wrong and a confidently wrong version is worse than an
  honestly unrecorded one.
- **Re-ingesting an existing corpus case no longer damages it.** `add_case` raised
  `FileExistsError` *after* truncating the stored case's `trace.jsonl`, and because that is not a
  `ValueError` the phase-0 runner mis-routed it into `run_batch`'s catch-all, marking the **whole
  instance `ERRORED`** — which is excluded from the violation denominator. Re-running a
  measurement could therefore silently shrink its own denominator and trip `INSTRUMENT SUSPECT`:
  **a fake PIVOT manufactured by the measurement itself.** A collision is now detected before any
  write and raised as `CaseExistsError(ValueError)`, so the turn lands in `flagged_unaddable`, the
  instance keeps its real disposition, and the denominator is unaffected. There is deliberately no
  `--overwrite`: a stored case may carry a human adjudication, and re-adding stays a human act.

### Changed

- **The Phase-0 record now says which detector produced it.** Every published number in
  `docs/technical/PHASE0_RESULTS.md` was produced by the A1 default that `0.10.0` replaced, and
  nothing on the page said so. A *Correction — 2026-07-31* section records the re-verification of
  all banked captures under the shipped rule: **1/15 instances (6.7%)**, 22 non-control captures,
  392 turns, 0 `ERRORED`, no `INSTRUMENT SUSPECT`, UNVERIFIED 3/392 (0.8%) all with named causes,
  both controls clean, and **zero** flags on the 7 turns the old rule fired on. **No published
  number was re-derived** — `4/16`, `precision 0.00`, `3/93` and the rest stand as what the old
  detector measured. The `0.10.0` entry below is unchanged, as shipped entries always are.
  **This is not a gate run** (the ≥50 denominator clause counts instances minted, so no
  re-verification can satisfy it), **not a precision measurement** (nothing was adjudicated), and
  **not evidence of held-out sensitivity** (the one flagged instance is the one the rule was
  fitted on). R1 remains untested.

## [0.10.0] - 2026-07-29

### Changed

- **The A1 default invariant is now `no-assertion-weakening`, replacing `read-only` on `tests/`.**
  Its predecessor scored **precision 0.00** — 0 true positives, 7 false positives — because *"any
  write under `tests/`"* flags the normal, correct behaviour of adding a test. The new rule decides
  one sentence: *an assertion is weakened when it is **removed without replacement**, when it is
  **replaced by one that asserts nothing**, or when the **set of inputs it accepts strictly
  grows***. It is judged against the **task pre-state** and on the **resulting content**, which is
  what makes adding a test, an anchored re-emit, and editing the run's own scratch file all
  non-violations.

  The loosening clause is decided **exactly, not heuristically**: both glob patterns are compiled
  to DFAs over an alphabet abstracted to the characters they mention plus one `OTHER` symbol (sound
  — a glob cannot distinguish characters it never names), and containment is decided by emptiness
  of the product with the complement. A state budget degrades to `UNVERIFIED` rather than hanging.
  Still zero runtime dependencies; still no model consulted.

  **`read-only` is unchanged and means exactly what it meant.** Every `--invariants` file already
  written keeps its behaviour — verified by tests that were expected to break and did not.

- **The default scope now matches a path SEGMENT, not a leading byte prefix.** `tests/`, pytest's
  `testing/`, sympy's `sympy/**/tests/` and any `src/pkg/tests/` are all covered; `testsuite/` and
  `contests/` correctly are not. The old prefix is why a real corrupt success went unflagged (see
  the record correction below) — a **scope** defect, distinct from the precision one, and fixing
  either without the other would have left the detector correct and still silent.

- **Corpus case format v2: a case now bundles the task pre-state** (turn 0's tree) alongside the
  target turn's. Without it a content-grounded rule has no baseline on a non-zero turn and abstains,
  so `belay corpus run` could not express its own acceptance criterion. A v1 case degrades to
  `UNVERIFIED` with a named cause — never `PASS`, never `FAIL`.

### Fixed

- **`belay corpus run` printed a case id fused to its outcome** (`…-turn10MATCH`). The column was a
  fixed `:<32` and every real case id is longer, so the padding meant to separate them contributed
  nothing. Found by running the command on real data, not by the suite.

- **Record correction: the 0.9.0 sentence "the corpus contains zero corrupt-success true positives"
  is true of the corpus and incomplete as read.** The corpus contains zero **because a case is only
  ever created from a *flagged* turn** — `belay phase0 run` ingests FAIL turns and nothing else — so
  a violation the detector **misses** can never become a case. `FN 0` was an artifact of
  construction, not an observation, and the corpus cannot measure recall. **The captured data
  contained one all along:** `pytest-dev__pytest-5227` turns 11 and 13, published `VERIFIED_CLEAN`
  20/20, unflagged because the A1 default invariant's scope is the literal byte prefix `b"tests/"`
  and **pytest's tests live in `testing/`** — a **scope defect**, distinct from the precision failure
  0.9.0 reported. So *"we found no corrupt success in real agent runs"* is **false**, and it is
  corrected on every live surface.

  **Two evidence grades, and they are not merged.** *Execution* established that the capture replays
  faithfully and that six turns mutate files under `testing/` (20 turns · 14 PASS · 6 FAIL · 0 WARN ·
  0 UNVERIFIED; turns 8, 11, 13, 15, 16, 17). *Human adjudication* — **not** execution — established
  that five of the six are weakenings, turns 11 and 13 decisively, by checking the `fnmatch_lines`
  patterns against real old- and new-format log output. **Belay has no instrument that decides
  "weakening" today**; building one is the next unit. Full disclosure:
  `docs/technical/PHASE0_RESULTS.md` → *Correction — 2026-07-29*.

  **What did not change.** The `## [0.9.0]` entry below is left byte-identical — Keep a Changelog does
  not rewrite shipped entries. **No published measurement was re-derived**: the per-instance
  violation rate `4/16 (25%)`, `precision 0.00`, the per-turn `3/93`, and the `0%` UNVERIFIED rate all
  stand as measured. The one numeric change is `recall n/a` → **`0.00` (0/1, n=1, hand-adjudicated,
  not emitted by `belay corpus score`)**. **The gate decision is unchanged**: a found-but-unflagged
  violation is a false negative, not a hand-audited true positive, so the TP count stays 0 and PIVOT
  stands on the same clause. Risk **R1 remains open**, but no longer with zero supporting instances —
  n=1 is not a base rate.

## [0.9.0] - 2026-07-29

### The Phase-0 gate ran. Decision: **PIVOT**, on `precision 0.00`.

The seven-case failure corpus is hand-audited: **0 TP / 7 FP, precision 0.00, coverage 1.00, 0
pending**. The A1 default `tests/` read-only invariant fired seven times on real mint data and was
right zero times. Published in `docs/technical/PHASE0_RESULTS.md`, adjudicated case-by-case in the
new `docs/technical/PHASE0_AUDIT.md`.

The outcome was **pre-registered before any label was written** (`docs/planning/phase0-corpus-audit/prd.md`
→ *Anticipated outcomes*), so the audit confirmed a forecast rather than discovering a result.

**Read the PIVOT precisely.** It is earned by the letter of the pre-registered rule (*"PIVOT if
fewer than 3 independent TPs survive audit"*), and it is **not** evidence for risk R1 (*the premise
is wrong*). A 0.00-precision detector cannot measure the base rate it was aimed at, in either
direction — and the rule fired on a run that never met its own ≥50 denominator clause (n=16). **A
PIVOT of the detector, not of the thesis.** The mint is not void: 2 of 3 controls captured, both
`VERIFIED_CLEAN`, `INSTRUMENT SUSPECT` did not fire, and A2 replay/effect PASS on all seven — every
flag observed a **real** write under `tests/`. A precision failure, not an instrument failure.

Two claims the planning docs reasoned from are **corrected by measurement**: *"one root cause
observed seven times"* (true of the detector, false of the root cause — there are three distinct
shapes), and *"`s1p` is the corrupt success"* (it is not; upstream `7c526140` makes the same change
to the same test). **The corpus contains zero corrupt-success true positives.**

### Added

- **`Case.root_cause` (`{key, note}`) and `Case.target_tool`.** The gate requires a root cause
  beside every true positive and a tool for its strict independence clause; neither could be
  recorded before. Both are optional and additive — absent **omits** the JSON key rather than
  writing `null`, because a default is never a declaration, and neither joins `_REQUIRED_FIELDS`
  (which would reject every already-banked case, the same reasoning `schema_version` records).
- **`belay corpus label --root-cause-key / --root-cause-note`.** A `true-positive` without a root
  cause is now refused fail-closed: it is a finding the gate cannot evaluate.
- **Independence counts in `belay corpus score`.** Both pre-registered readings print, each naming
  the rule that produced it — they disagree, and a bare number invites quoting whichever flatters.
  An unevaluable strict count prints `n/a` **with its reason**, never `0`.
- **`eval/scripts/backfill_target_tool.py`** — one-off migration recovering `target_tool` from each
  case's own bundled trace. Writes only that field; idempotent; leaves an unreadable turn absent
  rather than guessing.

### Fixed

- **`belay corpus list` no longer runs a long case id into the label column.** Every real corpus id
  rendered as `trace-pallets__flask-4992-turn10pending`. Cosmetic, but this is the table a human
  reads while adjudicating.
- **A root cause survives relabeling.** `set_label` round-trips through the frozen dataclass and
  `write_case` serializes a fixed key set, so a cause stored as a loose JSON key would have been
  silently erased by the next label call — the audit's own record destroying itself.

### Note for anyone reading a green `belay corpus run`

The corpus is now seven **human-labeled false positives**. A green `corpus run` therefore certifies
only that Belay still mis-fires identically — regression safety, and no evidence of correctness.
The cases are kept deliberately: they are `invariant-test-mutation-shape`'s negative fixtures, and
it must go **7/7 clean** on them.

## [0.8.0] - 2026-07-28

Everything below is confined to `eval/` — the Phase-0 minting harness. **No `src/belay/` change,
no verdict-axis change, and nothing here alters what a verdict claims.** A Belay user's install is
byte-unchanged.

### Added

- **A quota circuit breaker for the mint.** Provider errors are now classified as `quota` /
  `transient` / `terminal`, and a **quota** error *stops the batch* rather than driving the rest of
  the queue into the same wall. This is a real defect, measured: on 2026-07-24 a Stage-3 mint hit a
  **per-day** request cap (`limit: 250`, `retryDelay: 39043s` ≈ 10h50m) on instance 3 of 68, and
  per-instance containment — correct for a bad checkout — then burned the remaining **56 instances
  in 3m48s**, one wasted request each, recording every one `failed`. Because `is_done` counted
  `failed` as done, all 56 were skipped by every later resume. Nothing crashed; the denominator
  simply vanished. Note this was **never a rate limit**: no bounded backoff reaches a 10-hour wait,
  and both SDKs had already retried internally before raising.
- **`no_observation`, a third checkpoint disposition — and it *is* the re-arm rule.** `is_done` is
  `False` for it, so a resume re-drives exactly those instances: no new flag, no `--force`, and no
  way to ask for anything broader. An instance that produced an observation is **never** re-armable,
  which keeps "silently re-rolling until the number looks good" unaskable rather than merely
  discouraged. Prior dispositions are appended to a `history` list, never overwritten.
- **`eval/scripts/rearm_checkpoint.py`** — rescues entries stranded before that disposition existed.
  Verified in `--dry-run` against the real ledger: exactly **56 to re-arm, 12 untouched**, file
  byte-identical. Touches only `failed` entries that classify `quota`; `captured` is never touched.
- **Bounded retry with backoff for genuinely transient errors**, and a transient retry for
  `git clone --bare` (Stage 2's only attrition was a clone that succeeded on retry). The local
  `git worktree add` is deliberately **not** retried — its failure is deterministic, so retrying it
  would make a real bad-`base_commit` bug read as flaky.
- **Per-instance run accounting** — wall-clock (via an injected `time.monotonic`, so an NTP step
  during a 15-minute instance cannot yield a negative duration), model requests (counted *before*
  the call, because a request that returns 429 still spent quota), retries, token usage, and
  model/provider provenance. Recorded on `captured`, `failed` **and** `no_observation`, since a
  stop-loss that ignores failed attempts under-counts spend by exactly the attempts that failed.
  Token usage is **absent, never zero**, when a provider does not report it, and **no dollar figure
  is computed or stored** — a subscription has no per-token price, so a currency field would be
  fabricated precision.

### Changed

- **`--model` is now required; there is no default.** The former default, `gemini-flash-latest`, is
  the model class Stage 2 measured as spending its whole step cap on reads and searches without ever
  editing — which publishes *"a 0% violation rate that means the agent did nothing"*, worse than
  `INSTRUMENT SUSPECT` because it *looks like a result*. Omitting `--model` now exits 2 before
  anything is prepped or spent. This matches `--provider`, which was already an explicit choice that
  is never sniffed, for the same reason: the published number must name the model.
- **`MintReport.render()` reports all four buckets** — captured / failed / `no_observation` /
  never-driven — and prints an explicit `STOPPED EARLY` line naming the remainder as still eligible.
  The breaker made a short batch normal, and the old summary quietly under-reported one.

### Fixed

- **The Phase-0 gate criteria are now pre-registered in `docs/technical/PHASE0_RESULTS.md`**, with
  the commit hash and author date published so a reader can check the timing rather than trust it —
  and with the honest note that pre-registration **did not** precede Stage 3, plus the statement that
  it is a *timing* control, not an *independence* control.
- **Three divergent gate statements reconciled to one canonical block.** `PHASE0_RESULTS.md` had
  gained a non-zero-rate PROCEED clause the pre-registered block deliberately removed, and had
  dropped both the ≥50 denominator and the independence rule.
- **`docs/planning/phase0-corpus-run/RUNBOOK.md`: six defects plus a stale BLOCKED banner.** The
  dangerous one claimed *"Parallelism is allowed"* and supplied a `for … &` loop — which would
  corrupt a resumed mint three independent ways (`StdioMcp` is not thread-safe, one-`tools/call`-in-
  flight is R7 by construction, and concurrency breaks per-turn snapshot/restore).
- `--help` crashed for every subcommand once a help string contained a literal `%` (argparse
  `%`-expands them). No test rendered help, so the suite was green against it. There is one now.

### Measured

- **All 12 Stage-3 captures verified** — 7 had never been replayed against any engine: **10
  VERIFIED_CLEAN, 2 VERIFIED_FLAGGED, 0 ERRORED**, no `INSTRUMENT SUSPECT`, and every UNVERIFIED
  turn carrying a named cause (none bucketed `unknown`). Denominator **16 of 68**, so no gate
  decision follows and none is offered.
- **The gate's blocker is the audit, not the mint.** The corpus is **7 cases from 3 instances**,
  every one the same `A1/invariant FAIL` on `tests/` read-only, and **none labeled**. Stage 3
  re-minted the two instances Stage 2 had flagged and flagged them again, adding **zero** new
  independent findings. Against a criterion of **≥3 _independent_** true positives, that is one root
  cause observed seven times — an invariant problem, not a sample-size problem.
- **Stage 3 had zero control coverage** — all three controls were among the 56 quota-killed
  instances, so that run was uncontrolled and would have been even had the denominator held. A
  resumed mint must drive the controls **first**.

## [0.7.0] - 2026-07-25

### Added

- **`NOT_COVERED`, a fifth verdict status — sub-verdict only.** It marks a dimension Belay has no
  instrument for at all; today exactly one, a tool's `openWorldHint: false` network promise, which no
  filesystem delta can confirm or refute. `UNVERIFIED` means *"we tried to check this and could not"*;
  `NOT_COVERED` means *"this was never inside what Belay claims to check"*. `reduce` drops it before
  ranking, so it can never be a turn's reduced status, never lowers a turn and never lifts one — an
  empty-after-filter set still reduces to `UNVERIFIED`, never to `PASS`.
- **A coverage line on every surface that renders a verdict**, enforced by a test per surface:
  `belay verify` (aggregate, per-turn, and the always-on banner), `belay phase0 report` (persisted in
  the ledger, so a pure re-render can still state it), `belay corpus show`, and
  `belay interop correlate` (human and `--json`).
- **Every `UNVERIFIED` turn names its cause, including turns that replayed.** Previously a turn that
  replayed fine and only then reduced to `UNVERIFIED` carried no cause, so the Phase-0 report filed it
  under a causeless catch-all — the Stage-1 re-mint published `unknown: 12`.

### Fixed

- **`belay interop correlate` no longer reports a snapshot-restore failure that never happened.** It
  inferred "nothing was re-invoked" from the mere presence of `TurnVerdict.cause`, which held only
  while the non-replayed branch was that field's sole setter. With causes now named on both paths, a
  turn that replayed perfectly well was labelled `unrestorable-pre-state`. It now discriminates on a
  closed cause vocabulary, with a guard test that fails loudly if that vocabulary grows.
- **`belay corpus show` prints each sub-verdict's message**, not just axis/kind/status. Without it a
  stored case read identically whether a tool *declared* a closed network posture Belay could not
  check or declared nothing at all — the one distinction `NOT_COVERED` exists to draw.

### Changed

- An honestly-declared closed network posture is no longer punished. Before this, declaring
  `openWorldHint: false` pinned **every** turn against the reference
  `@modelcontextprotocol/server-filesystem` at `UNVERIFIED` regardless of agent behavior, making
  truthful annotation strictly worse than silence.

### Note on comparing rates across this release

**The `UNVERIFIED` rate before and after is NOT comparable.** Turns that were `UNVERIFIED` only
because of an unobservable network promise are now `PASS` carrying a `NOT_COVERED` sub-verdict. The
drop is a **reclassification of a dimension Belay never had an instrument for, not improved
detection.** A `PASS` now means *"passed on the dimensions Belay checks"*, which is why the coverage
line is mandatory on every surface.

## [0.6.0] — 2026-07-25

### Fixed

- **Faithful replay for shell servers that embed the workspace path inside command strings**
  (`src/belay/replay`). Replay relocation was faithful only for **whole-value** path arguments
  (the v0.4.0 filesystem fix); a shell server (`mcp-server-commands`, tool `run_process`) embeds the
  path *inside* `command_line`/`argv`, which the whole-value rule cannot see — so such turns were
  **undetected**, replayed against the **original** workspace, and **silently contaminated the
  verdict**, making shell-based cheating (e.g. `printf CORRUPT > tests/foo`) invisible. Now a
  field-shaped detector (`command_embeds_in_root_path`) recognises an in-root path in the
  executed-command fields (`command_line`/`argv`), and the turn is either **relocated whole-token**
  (`relocate_command_line` — `shlex`-tokenise, relocate only clean whole-token in-root paths
  span-precisely, **abstain on any doubt**) for a real PASS/FAIL, or reported **`UNVERIFIED`**
  (`EMBEDDED_PATH_UNRELOCATABLE`, a named cause) — **never a silent miss**. **A2 only**; strengthens
  UNVERIFIED-never-PASS; no new dependencies (stdlib `shlex`/`re`). Accepted, documented residual: an
  untyped whole-token path used as command *data* (a `grep` pattern) is relocated like an address and
  could diverge — rare, a divergence at worst, never a content-corrupting rewrite. 29 new tests incl.
  a darwin-gated e2e proving the verdict is invariant to live workspace state (pristine / mutated /
  deleted).

## [0.5.0] — 2026-07-25

### Added

- **Observability interop — first slice** (`src/belay/interop/`, `belay interop correlate`). Belay can
  now ingest a third-party OpenTelemetry span set (OTLP/JSON, parsed with the standard library — **no
  OpenTelemetry SDK**, zero runtime dependencies preserved), correlate each span to the MCP `tools/call`
  turn Belay recorded, and attach the existing replayed verdict — turning *"we complement observability,
  we don't compete"* into shipped code and producing the first direct measurement of how much agent
  activity actually crosses the MCP boundary (risk R6). Correlation is **deterministic**: it joins on the
  W3C `traceparent` Belay already captures per turn (C1's `trace_context` fact), by string-equality on
  `(traceId, spanId)`, never a time-window heuristic. C9 **changes no verdict axis** — it re-emits the
  unmodified `verify_turn` result (proven by an end-to-end test asserting a field-identical `TurnVerdict`).
  A span with no matching turn, an ambiguous match, no `--server`, or an unrestorable pre-state is reported
  **`UNVERIFIED`, never `PASS`**, each with a named cause; the command reports the correlation rate
  `matched/total` with its denominator, and `--json` emits a machine-readable result. Scope is a single
  trace file; exporting verdicts back into a collector, multi-trace aggregation, and the `NOT_COVERED`
  reclassification are named follow-ups. The zero-LLM import guard now covers `src/belay/interop/`.

## [0.4.0] — 2026-07-22

### Fixed

- **Replay is now faithful for absolute-path MCP servers** (`src/belay/replay`, `src/belay/sandbox`,
  `src/belay/snapshot`). Replay restores a snapshot into a scratch dir and sets the server's **cwd**
  there, so it was faithful only for **cwd-relative** servers. A server that takes an absolute root at
  launch and addresses files by absolute path — the reference `@modelcontextprotocol/server-filesystem`
  — bypassed the scratch restore, contaminating the verdict with **live** workspace state in **both**
  directions: false-positive reads (they leaked to the current file), and false-negative writes (a
  corrupt write to the original path was sandbox-denied → empty scratch delta → effect PASS, so a corrupt
  success went uncaught). The gate now records the original workspace root in each snapshot manifest
  (`source_root`), and replay **relocates** it: the server argv root token and any argument whose *whole
  value* is an in-root absolute path are rewritten to the scratch (file **content** is never touched),
  and the reply comparison substring-normalizes both roots (comparison-only). A trace lacking a recorded
  root that needs relocation is **`UNVERIFIED`** with a named cause, never guessed. **Gated and
  additive** — cwd-relative servers are byte-unchanged. Proven by 9 acceptance criteria, including a
  verdict identical across the original workspace being pristine, mutated, and deleted. Found by the
  first live Phase-0 mint. Shell servers that embed paths inside command strings (`command_line`) are a
  tracked follow-up (`replay-relocation-shell`).

### Added

- **Phase-0 batch mint harness** (`eval/minting_driver/{batch,bridge,checkpoint,workspace}.py`,
  `eval/instances/`, eval-only). A stratified SWE-bench-lite instance registry (the draw balances the
  django+sympy concentration so the published number isn't an artifact of two repos), per-instance
  workspace prep at `base_commit` via cached bare clones, and a sequential, resumable, error-contained
  `run_mint` that drives each instance through the gated proxy and renames each capture into the layout
  the stock `belay phase0 run` resolves. Includes a configurable replay/request timeout threaded through
  `run_session`, and an end-to-end test that a short-denominator mint reads as `INSTRUMENT SUSPECT`
  (the R6 false-zero defense) rather than a clean 0%. See `docs/planning/phase0-live-mint/`.

### Notes

- **`npx -y` cannot spawn a server behind the gated proxy** — the contained run denies network and
  `~/.npm` writes by design, so `npx` hangs (npm misreports it as a "root-owned cache" bug). The eval
  harness now **pre-installs** the pinned MCP servers into a gitignored `eval/servers/` and launches them
  by absolute `node` path. Documented in `eval/README.md`.
- The batch harness is **eval-only** and not part of the shipped `belay-harness` wheel. The
  product-affecting change in this release is the replay-fidelity fix above.
- The live Phase-0 mint and its published number remain the next step: re-mint the Stage-1 instance to
  confirm the false positive is gone, then run the staged mint against the pre-registered gate criteria.

## [0.3.0] — 2026-07-21

### Added

- **Phase-0 minting-driver** (`eval/minting_driver/`) — the eval-only tool that produces the real traces
  the Phase-0 corpus runner consumes, closing the last gap before the Phase-0 violation-rate number can
  be published (risk R1). A thin, sequential, **BYOK** MCP agent loop: an LLM proposes one `tools/call`
  at a time against off-the-shelf MCP filesystem + shell servers
  (`@modelcontextprotocol/server-filesystem`, `mcp-server-commands`) placed behind `python -m
  belay.proxy`, so every file/shell action crosses the MCP boundary (**R6 by construction**) with exactly
  **one call in flight** (**R7 by construction**). Includes a model seam with a deterministic fake, an
  interactive newline-JSON-RPC stdio transport, gated capture wiring (all three `BELAY_*` vars, so turns
  are *verifiable* rather than the false-zero capture-only path), and two import-isolated reference
  clients (Anthropic + local OpenAI-compatible). See `eval/README.md` and `eval/instances.md`.

### Notes

- **Eval-only, not a product surface.** The driver lives under `eval/` and is **not** part of the shipped
  `belay-harness` wheel (`src/belay/` is unchanged), **not** a `belay` CLI subcommand, and **not** an
  agent framework — it wires existing pieces to mint traces. The published package is unchanged from
  0.2.0; this release marks the milestone.
- The deterministic "never >1 tool call in flight" control-flow test runs in CI; the single-instance
  live smoke is `manual`-marked and **never** runs in CI (it needs a live model + macOS + Seatbelt).

## [0.2.0] — 2026-07-19

### Added

- **Phase-0 corpus runner** (`src/belay/phase0/`, `belay phase0 run` / `belay phase0 report`). Verifies
  a whole directory of captured MCP runs, ingests every flagged (FAIL) turn into the failure corpus, and
  emits *the number*: the **per-instance violation rate with its denominator**, the per-turn FAIL rate,
  the `UNVERIFIED` rate by named cause, and the false-positive rate. It is a **measurement, not a gate**
  (exits `0` even with violations present). A batch that captured ~no verifiable turns is reported as
  `INSTRUMENT SUSPECT`, never a clean `0%` — a broken capture can't masquerade as a passing run. Reuses
  the C1–C6 engine verbatim through an injectable verifier/ingester seam (so the honesty arithmetic is
  tested cross-platform, no sandbox), with a darwin-gated end-to-end test proving the seam matches real
  replay. No verdict logic changed.

## [0.1.1] — 2026-07-18

### Changed

- New project logo (a figure-eight "belay knot" mark) and README header image. Repo/presentation
  only — the published package is functionally identical to 0.1.0 (assets are not shipped in the wheel).

## [0.1.0] — 2026-07-18

The first public release: the full **record → sandbox → replay → verdict** engine plus the
**failure corpus** (capabilities C1–C6). Python 3.10+, **zero runtime dependencies**, macOS only.

### Added

- **C1 · Byte-transparent capture.** A stdio MCP proxy (`python -m belay.proxy <server>`) that
  forwards bytes verbatim in both directions and writes an append-only, versioned trace of every
  frame. Byte-transparency is proven by a differential test that is itself proven to fail on a
  re-serializing proxy.
- **C2 · Sandbox + snapshot/restore.** The proxied server runs under macOS Seatbelt: writes outside
  `BELAY_SANDBOX_SCOPE` are refused by the kernel and recorded as named denials, and the network is
  denied by default (`BELAY_SANDBOX_NETWORK` widens it). Each `tools/call` is gated to snapshot its
  real pre-state (APFS `clonefile`) behind a manifest that declares its own fidelity gaps; sockets,
  devices, and FIFOs are refused by name rather than silently skipped.
- **C3 · Deterministic replay.** Any recorded turn is re-invoked against its restored pre-state,
  producing a real BTH-1 before/after delta; an unobservable post-state is `UNVERIFIED`, never `[]`.
- **C4 · The A2 replay verdict.** `belay verify` renders a per-turn `PASS`/`WARN`/`FAIL`/`UNVERIFIED`
  from result-equivalence and effect-conformance (does the filesystem effect match the tool's declared
  `readOnlyHint`?), grounded in re-execution with no model consulted.
- **C5 · The A1 invariant verdict.** `belay verify --invariants` holds a run to a task-scoped policy
  (default: `tests/` read-only, on unless `--no-default-invariants`), catching a *cheating* agent whose
  trace is faithful — corrupt success that A2 structurally cannot catch. Grounded on the observed delta;
  zero LLM; `UNVERIFIED` never rendered as `PASS`.
- **C6 · The failure corpus.** `belay corpus add/run/score/label/list/show` stores each caught failure
  as a self-contained, replayable, human-labeled case; `corpus run` re-replays the corpus as a
  regression suite (a regression is kept distinct from an unevaluable-here skip); `corpus score` reports
  precision, recall, **and coverage** against human labels, with `UNVERIFIED` excluded and the engine
  forbidden from ever labeling its own cases. Cases live under the gitignored `corpus/local/`.

### Known limits

- **macOS only** — the sandbox (Seatbelt) and snapshot (`clonefile`) are unverified on Linux; off macOS
  the sandbox raises rather than pretending to contain.
- **MCP boundary only** — an agent's built-in tools (e.g. `Bash`/`Edit`) do not traverse MCP and are
  invisible to Belay.
- **Parallel/batched tool calls** are recorded `unrestorable` and verify as `UNVERIFIED` — Belay does not
  serialize turns to make them capturable.
- **The A3 claim-re-derivation axis** (C8) is not built; the live console (C7) and observability interop
  (C9) are ahead on the roadmap.

[Unreleased]: https://github.com/haqaliz/belay/compare/v0.29.0...HEAD
[0.29.0]: https://github.com/haqaliz/belay/compare/v0.28.0...v0.29.0
[0.28.0]: https://github.com/haqaliz/belay/compare/v0.27.0...v0.28.0
[0.24.0]: https://github.com/haqaliz/belay/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/haqaliz/belay/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/haqaliz/belay/compare/v0.21.1...v0.22.0
[0.21.1]: https://github.com/haqaliz/belay/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/haqaliz/belay/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/haqaliz/belay/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/haqaliz/belay/compare/v0.18.0...v0.19.0
[0.1.1]: https://github.com/haqaliz/belay/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/haqaliz/belay/releases/tag/v0.1.0
