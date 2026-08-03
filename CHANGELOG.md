# Changelog

All notable changes to Belay are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Belay aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0 — until then,
`0.x` minor bumps may include changes that would be breaking under strict semver.

## [Unreleased]

### Changed

- **What a green `belay corpus run` means — again, so read this before quoting one.** It now means
  *"no case regressed, **and** every recorded miss is still recorded as missed"*. It does **not**
  mean *"the engine catches everything in the corpus"*: a green run coexists with known,
  **declared** blindness, and that is the point of `STILL_MISSED` existing as its own outcome.
  This reading has had to be corrected twice before — the same green once certified that Belay
  still *mis-fired identically*, and later that the A1 rule still reached `PASS` on seven turns a
  human adjudicated false positives — so it is now said outright where a reader will hit it:
  `src/belay/corpus/run.py`'s module docstring and README's *Coverage & limits*, and in the
  negative on `corpus run`'s `--help` and its sign-off line, which state the `STILL_MISSED` count
  so a known-open miss is never mistaken for a clean full pass.
- **The corpus is no longer structurally confined to over-firing evidence.** `belay phase0 run`
  ingests flagged turns and nothing else, so a violation the detector *missed* could never become
  a case and an `FN` of `0` was an artifact of construction, not a measurement. A miss can now
  enter the corpus, be declared as one, and contribute a false negative to `corpus score`'s
  recall. **This is a capability, not a result** — whether any miss has actually been banked, and
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
  `REGRESSION`.
- **`belay corpus score` names where a false negative came from**, reporting how many `FN`-
  contributing cases are a human-banked recorded miss — a known blind spot the stored verdict
  already reflects, not a detection that failed today. `corpus show` prints the declaration
  (absent-vs-declared kept distinct) and `corpus list` carries a `recorded-miss` marker column.

### Fixed

- **`belay corpus add`'s help no longer claims a precondition it never enforced.** Four places
  said a case is composed from a *flagged* turn; nothing in the composition path has ever filtered
  on the recomputed verdict. A reader who trusted them went looking for a `FAIL` filter that does
  not exist and concluded the corpus structurally cannot hold a miss — the exact misconception
  this release removes. No behaviour changed; the strings did.

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

[Unreleased]: https://github.com/haqaliz/belay/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/haqaliz/belay/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/haqaliz/belay/releases/tag/v0.1.0
