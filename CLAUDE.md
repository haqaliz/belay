# Belay: Project Context for Claude Code

This file orients a coding agent working in this repository. Read it first.

> **Status: C1–C6 are built and merged; the Phase-0 corpus runner is built** (1005 tests, 1 platform-skip; zero runtime dependencies).
> The full record → sandbox → snapshot/restore → replay → verdict spine exists: the byte-transparent
> stdio MCP proxy + trace format (C1), the Seatbelt sandbox with snapshot/restore (C2), deterministic
> replay with a real before/after delta (C3), and the grounded verdict — **A2** result-equivalence +
> effect-conformance (C4) and **A1** task-scoped invariants (C5, `src/belay/verify/invariants.py`).
> A1 catches a *cheating* agent A2 structurally cannot: `belay verify --invariants` (the `tests/`
> read-only default is on unless `--no-default-invariants`), grounded on the observed delta, zero LLM,
> UNVERIFIED-never-PASS. **C6 — the failure corpus** (`src/belay/corpus/`, moat #2): `belay corpus
> add/run/score` stores each caught failure as a self-contained, replayable, human-labeled case; the
> corpus is the regression suite, and precision/recall/coverage measures detection against human labels
> (UNVERIFIED excluded, the engine never labels its own cases). Cases live under gitignored `corpus/local/`.
> **The Phase-0 corpus runner is built** (`src/belay/phase0/`, `belay phase0 run/report`): it verifies a
> whole directory of captured runs, ingests every flagged turn into the corpus, and emits *the number* —
> the per-instance violation rate with its denominator, plus per-turn FAIL, UNVERIFIED-by-cause, and
> false-positive rates. It is a measurement, not a gate (exits 0 with violations present), and a mint that
> captured ~no verifiable turns reads as `INSTRUMENT SUSPECT`, never a clean 0% (the R6 false-zero defense).
> **The Phase-0 minting-driver is built** (`eval/minting_driver/`, eval-only — NOT a product surface,
> NOT the `belay` CLI): a thin, sequential, BYOK MCP agent loop that drives an LLM's file/shell actions
> through off-the-shelf MCP servers (`@modelcontextprotocol/server-filesystem`, `mcp-server-commands`)
> placed behind `python -m belay.proxy`, one `tools/call` in flight at a time (R7 by construction; all
> edits cross the MCP boundary, R6 by construction). The deterministic "never >1 in flight" control-flow
> test runs in CI; the single-instance live smoke is `manual`-marked and never in CI. See `eval/README.md`.
> **The Phase-0 batch mint harness is built** (`eval/minting_driver/{batch,bridge,checkpoint,workspace}.py`
> + `eval/instances/`, eval-only): a stratified instance registry (166 strict-eligible SWE-bench-lite
> instances vs the ≥50 needed; the draw balances the 83% django+sympy concentration so the number isn't a
> django/sympy number), per-instance workspace prep at `base_commit` via cached bare clones, and a
> sequential, resumable, error-contained `run_mint` that drives each instance through the gated proxy and
> **renames each capture into the layout the stock `belay phase0 run` resolves** (`bridge_capture` — a
> mis-wire here would read as `INSTRUMENT SUSPECT`, a fake PIVOT, so it is the aspect's load-bearing test).
> All deterministic and offline; the live mint stays `manual`. **A real defect was found and fixed by
> running the live smoke for the first time: `npx -y` cannot spawn a server behind the gated proxy** (the
> contained run denies network and `~/.npm` writes by design, so npx hangs); servers are now pre-installed
> into a gitignored `eval/servers/` and launched by absolute `node` path. See `eval/README.md`.
> **Stage 1 of the live mint ran and PROVED the harness end-to-end** — `run_mint` → real git clone at
> `base_commit` → gated capture → bridge → stock `belay phase0 run` → replay, on `pallets__flask-4045` via
> BYOK (Ollama, then Gemini's OpenAI-compat endpoint). It also surfaced a core-engine replay-fidelity bug
> that **has now been fixed** (see next).
> **Replay is now faithful for absolute-path MCP servers** (`replay-absolute-path-fidelity`, merged): replay
> restores into a scratch dir and sets the server's **cwd** there, so it was faithful only for
> **cwd-relative** servers — the reference filesystem server (absolute `allowed_dir` / absolute paths)
> bypassed the scratch restore, contaminating verdicts with live workspace state in **both** directions
> (false-positive reads, and false-negative denied-writes that read as an empty delta). Fixed: the gate
> records the original workspace root in each snapshot manifest (`source_root`), and replay **relocates** it
> — the argv root token and any argument whose *whole value* is an in-root absolute path are rewritten to
> the scratch (content untouched), the reply comparison substring-normalizes both roots (comparison-only),
> and a rootless trace that needs relocation is `UNVERIFIED` (never guessed). Gated/additive: cwd-relative
> servers are byte-unchanged. Proven by 9 acceptance criteria incl. a verdict identical across original
> pristine/mutated/**deleted**. See `docs/planning/replay-absolute-path-fidelity/`.
> **Shell `command_line`-embedded paths are now handled too** (`replay-relocation-shell`, built
> 2026-07-25): the whole-value rule was blind to an in-root path buried *inside* a `run_process`
> `command_line`/`argv`, so such turns replayed against the original workspace and silently
> contaminated the verdict. Now a field-shaped detector (`command_embeds_in_root_path`) routes them
> to either **whole-token relocation** (`relocate_command_line`: `shlex`-tokenize, relocate only
> clean whole-token in-root paths span-precisely, **abstain on any doubt**) for a real PASS/FAIL, or
> an honest **`UNVERIFIED`** (`EMBEDDED_PATH_UNRELOCATABLE`) — never a silent miss. Accepted residual:
> a whole-token path used as command *data* (a `grep` pattern) is relocated like an address and could
> diverge — rare, documented not silent. See `docs/planning/replay-relocation-shell/`.
> **The Stage-1 confirmation is DONE, on real captures.** Re-verifying the three Stage-1 captures
> against this tree discriminates correctly: `s1` and `s1b` (no `tests/` mutation) are
> `VERIFIED_CLEAN`, 0 FAIL; `s1p` (the corrupt success — `test_dotted_names` rewritten, 12+/4−) is
> **`VERIFIED_FLAGGED`, 1/11 FAIL**. Every run reports **0 UNVERIFIED** with its coverage line, so
> the 12/12-UNVERIFIED → `NO_VERIFIABLE_TURNS` → `INSTRUMENT SUSPECT` failure that made the
> denominator zero is gone, and no false positive appears on either clean capture. `belay corpus
> run` is 6/6 MATCH, 0 REGRESSION.
> **THE HAND-AUDIT IS DONE, and the number is in: the A1 default `tests/` read-only invariant has
> `precision 0.00` — 0 TP / 7 FP at 1.00 coverage** (`docs/technical/PHASE0_AUDIT.md`, and
> `PHASE0_RESULTS.md` is now filled). It fired seven times on real mint data and was right zero times.
> **Gate decision: PIVOT** — by the letter of the pre-registered rule (*"PIVOT if fewer than 3
> independent TPs survive audit"*; 0 survived). Recorded without reinterpretation. **But PIVOT here is
> NOT evidence for R1 (*the premise is wrong*)**, which is how `ROADMAP.md:125` reads one: the premise
> was never tested, because the only detector aimed at it flags normal correct behaviour (adding a
> test) and at 0.00 precision could not separate a corrupt success from a clean run either way. A 100%
> FP rate is uninformative about the base rate. PROCEED was refused twice over (0 TPs vs ≥3;
> denominator 16 vs ≥50) — and note this PIVOT fired on a run that never met the rule's own ≥50
> precondition. **This is a PIVOT of the DETECTOR, not of the thesis.** The mint is **not void**: 2 of 3 controls were captured, both `VERIFIED_CLEAN`, and
> `INSTRUMENT SUSPECT` did not fire — this is a *precision* failure, not an instrument failure; every
> flag observed a **real** write under `tests/`, and A2 replay/effect were PASS on all seven.
> **Two claims this file previously made are now corrected by measurement.** (1) *"one root cause
> observed seven times"* was true of the **detector** and false of the **root cause** — the payloads
> show three shapes: **A** modifies pre-existing test content (t8, `pylint-5859` t6), **B**
> anchored-append that re-emits existing content byte-identically (t10, t14, `5859` t11), **C** edits
> the run's **own** earlier scratch test (t12, t19). B and C are exactly how a naive sharper invariant
> gets it wrong, and they are now real cases rather than a guess. (2) *"`s1p` — the corrupt success"*
> does **not** hold: upstream `7c526140` **deletes** `test_dotted_names` outright and adds the same
> `pytest.raises(ValueError)`, so the agent made the maintainer's change and the test could not have
> passed unchanged. **The corpus contains ZERO corrupt-success TPs** — the sole candidate for the
> 27–78% statistic collapses. (`s1`/`s1b`/`s1p` are three genuine captured runs, not hand-perturbed
> fixtures; `flask-4045` is excluded from the published denominator by `stage1.json`.)
> **CORRECTION, 2026-07-29 — "ZERO corrupt-success TPs" is true of the CORPUS and was read as true of
> the DATA. It is not.** The flask-4045 collapse above stands. But the corpus contains zero **because a
> case is only ever created from a *flagged* turn** (`belay phase0 run` ingests FAIL turns and nothing
> else), so a violation the detector **misses** can never become a case — `FN 0` is an artifact of
> construction, and the corpus cannot measure recall. The captured data held one all along:
> **`pytest-dev__pytest-5227` turns 11 and 13**, published `VERIFIED_CLEAN` 20/20 in `runs/s2.json`,
> **unflagged because the default scope is the byte prefix `b"tests/"` and pytest's tests live in
> `testing/`** (`invariants.py:250`) — the **scope** defect, distinct from the precision one.
> **Two evidence grades, never merge them:** *execution* established the capture replays faithfully and
> six turns mutate under `testing/` (20 turns · 14 PASS · 6 FAIL · 0 WARN · 0 UNVERIFIED; turns 8, 11,
> 13, 15, 16, 17); *human adjudication* — not execution — established five of the six are weakenings,
> 11 and 13 decisively, via `fnmatch`. **PIVOT is UNCHANGED**: a found-but-unflagged violation is a
> **false negative, not a hand-audited TP**, so the TP count stays 0, and a miss is not a void condition
> (voiding is for a control coming back FAIL — the opposite direction). **No published number was
> re-derived**: 4/16, precision 0.00, 3/93 and the 0% UNVERIFIED all stand; only `recall n/a → 0.00`
> (0/1, n=1, hand-adjudicated) changed. **R1 stays OPEN but no longer has zero supporting instances** —
> n=1 is not a base rate. See `docs/technical/PHASE0_RESULTS.md` → *Correction — 2026-07-29*.
> **Decision: fix the instrument, then re-measure — build `invariant-test-mutation-shape` next; do NOT
> spend the remaining ~34 instances under a 0.00-precision detector.** The rule it needs is narrower
> than the two-way split originally proposed: not *modification vs addition* but **"modification that
> removes or weakens an existing assertion"**, judged against the **task pre-state** (not the previous
> turn, or C reads as cheating) and on the **resulting content** (not the edit's anchor, or B does).
> The 7 cases are kept as its **negative fixtures** — a sharper invariant must go **7/7 clean** on them.
> Note the corpus is now 7 human-labeled false positives, so a green `belay corpus run` certifies only
> that Belay still mis-fires identically — regression safety, not evidence of correctness.
> **The unit fixes TWO defects, not one** (2026-07-29): **precision** (the rule fires on normal
> behaviour) **and scope** (`b"tests/"` misses `testing/` and `sympy/**/tests/`). Sharpening the rule
> without fixing the scope leaves the only real positive fixture unreachable — the detector would be
> correct and still silent. The **7 cases are its negative fixtures** (must not fire, 7/7 `PASS`) and
> **`pytest-5227` is its positive one** (turns 11/13 must fire), so over-firing and under-firing are
> both measurable. Anything said about how the new rule scores on `pytest-5227` before the acceptance
> measurement runs is a **prediction, never a result**.
> **First open question:** should `tests/` read-only stay **ON by default**? It ships enabled and
> `README.md`'s coverage claims lean on it. See `docs/planning/phase0-corpus-audit/`.
>
> **Superseded — kept for the record.** Gate criteria are
> pre-registered in `docs/planning/phase0-live-mint/prd.md` and now also in
> `docs/technical/PHASE0_RESULTS.md`: PROCEED iff ≥3 *independent* hand-audited TPs AND denominator ≥50
> AND no INSTRUMENT SUSPECT; a FAILing control voids the mint. Stage 3 ran and was stopped by a provider
> **daily** cap at **12 captured / 56 failed of 68**; all 12 are now verified (10 CLEAN, 2 FLAGGED, 0
> UNVERIFIED-by-`unknown`, no INSTRUMENT SUSPECT). **The corpus is 7 cases from 3 instances — every one the
> same `A1/invariant FAIL` on `tests/` read-only, and 0 are labeled.** That is one root cause observed seven
> times, against a criterion of **≥3 _independent_** TPs, so more minting most likely yields more of the
> same shape: **this is an invariant problem, not a sample-size problem** (the benign-flag skew
> `phase0-gate-readiness/prd.md:209` called the likeliest failure). Audit first; only then decide between
> `invariant-test-mutation-shape` and a bigger mint. Then fill `PHASE0_RESULTS.md`; then C7 (live console —
> first UI). C8 (A3 claim re-derivation) and C9 (observability interop) are cuttable, last.
> **The mint harness no longer burns its own queue** (`phase0-mint-resilience`, `eval/` only — no
> `src/belay/` change): the 2026-07-24 stop was a **per-day** cap (`retryDelay` 39043s ≈ 10h50m), not a rate
> limit, so no bounded backoff could have reached it — and containment, correct for one bad instance, fed
> the remaining **56 into the same wall in 3m48s**, recording each `failed`, which `is_done` treated as done
> forever. Now `classify_error` sorts provider errors into quota/transient/terminal (duck-typed — importing
> an SDK would break the SDK-absent import contract, and the same function must work on a recorded reason
> *string*); a **quota error stops the batch**, leaving later instances *absent* and therefore eligible; a
> new `no_observation` status **is** the re-arm rule (`is_done` is False for it — no flag, no `--force`, and
> an instance that produced an observation is never re-armable, which is the anti-re-roll contract in code);
> history is appended, never overwritten; `eval/scripts/rearm_checkpoint.py` rescues the 56 already stranded
> (dry-run verified 56/12). Plus per-instance accounting (wall-clock via injected `time.monotonic`, requests
> counted *before* the call since a 429 still spends quota, tokens **absent-never-zero**, no dollar figures)
> and **`--model` is now required** — the old `gemini-flash-latest` default is the model STAGE2 measured as
> producing "a 0% violation rate that means the agent did nothing". Also: Stage 3 had **zero control
> coverage** (all three controls were among the 56), so a resumed mint must drive controls FIRST.
> See `docs/planning/phase0-mint-resilience/`.
> **C9's first slice is built** (`src/belay/interop/`, `belay interop correlate <otlp-spans.json>
> <trace-file> [--server -- CMD…] [--json]`): it ingests OTLP/JSON spans with the standard library
> only (no OTel SDK — zero-dep preserved), correlates each span to a recorded MCP `tools/call` turn
> by the **captured W3C `traceparent`** (C1's `trace_context` fact) — deterministic string-equality
> on `(traceId, spanId)`, never a time-window heuristic — attaches the existing replayed verdict
> unchanged (this capability computes NO verdict of its own), and reports the correlation rate
> `matched/total` with its denominator, plus every uncorrelated/unreplayed span bucketed by named
> cause. A span with no matching turn, no `--server` given, or an unrestorable pre-state is
> `UNVERIFIED`, never `PASS`. Scope is a single trace file; exporting verdicts back into a
> collector and multi-trace-directory aggregation are deferred follow-ups, not gaps papered over.
> This is a Phase-1 first slice, not a gate change — C1–C6 remain the built spine above.
> **The interop `NOT_COVERED` follow-up is no longer deferred — it was a merge hazard, and it is
> fixed** (`interop-merge-repair`): C9 merged *after* `verdict-coverage-status` forked, so landing
> the coverage boundary broke two things in it, neither caught by any test. (1) `attach.py` inferred
> "nothing was re-invoked" from `TurnVerdict.cause is not None`, valid only while the non-REPLAYED
> branch was that field's sole setter — the release ends that deliberately, so interop labelled a
> turn that **replayed fine** as `unrestorable-pre-state`, asserting a snapshot-restore failure that
> never happened. It now discriminates on `_REPLAYED_CAUSES`, a closed vocabulary with a guard test.
> (2) `belay interop correlate` printed a bare `PASS` for a turn whose network dimension is
> `NOT_COVERED`; both `render()` and `--json` now carry the boundary. The pre-existing test that
> looked like it covered (1) built its `TurnVerdict` through the `verify=` stub seam and was green
> against the bug — **a green suite was not evidence here**, and the new tests drive the real
> `verify_turn`. Two surfaces the coverage unit itself left unpinned are now pinned too (`belay
> verify` per-turn, and `belay corpus show`, which had dropped the sub-verdict *message* and with it
> the declared-vs-not-declared distinction). See `docs/planning/phase0-gate-readiness/`.
>
> [`docs/ROADMAP.md`](docs/ROADMAP.md) (phased plan + gates) and
> [`docs/technical/CAPABILITY_ROADMAP.md`](docs/technical/CAPABILITY_ROADMAP.md)
> (the C1–C9 engine backlog) are the operative plan. This file and `VISION.md` remain the
> strategic source of truth; the two roadmaps are authoritative on sequencing. Keep all four in
> sync. `README.md` states the **honest coverage limits** — read it before making any public
> claim about what Belay verifies.
>
> **Base branch is `master`** (not `main`). Remote: `git@github.com:haqaliz/belay.git`.

---

## What this project is

**Belay** is the **agent harness**: the runtime layer that makes *any* AI agent safe and
trustworthy to run unattended in production. It **sandboxes** what the agent does,
**verifies each step by replaying it against real state** (a grounded verdict, not an
LLM judging itself), records an exact **trace**, and can **deterministically replay** any
past run.

**The name.** In climbing, to *belay* is to manage the rope that **catches a climber when
they fall**. Belay catches an agent when it fails — contains the fall, proves what
happened, and lets you replay it. The harness holds; the climber takes risks.

---

## The wedge (read this before proposing any feature)

Three kinds of tools sit near agents. Know which one we are.

- **Agent frameworks** (LangGraph, CrewAI, AutoGPT, …) — they *build* the agent. CROWDED.
  **We do NOT build a framework.** We wrap whatever the user already uses.
- **Agent observability** (Langfuse, Arize Phoenix, LangSmith, Braintrust) — they *record*
  what the agent did, and at most bolt an LLM-judge on top for scoring. We sit **next to**
  them, not against them.
- **The harness** — sandbox the actions, **verify each step by re-execution**, guarantee a
  deterministic replay, and compound a failure corpus. Essentially UNSOLVED. **This IS
  the company.**

The question none of the others answer: **"was this step actually correct?"** — answered
by *replaying the tool call in a sandbox and diffing observed-vs-claimed state*, never by
an LLM's opinion of itself.

---

## Key strategic constraints (do not violate)

1. **Do not build an agent framework.** If a task drifts toward "Belay orchestrates/authors
   the agent" as the core value, stop and flag it. We are framework-agnostic infrastructure.
2. **The moat is replay + execution-grounded verification + the accumulated failure corpus,
   NOT prompting.** Favor work that hardens the sandbox/replay/verify engine and captures
   labeled failure data over work that tweaks prompts or wraps a judge.
3. **Build the part that gets BETTER as foundation models improve.** A stronger base model
   should write better checks and cleaner re-derivations, and make Belay *better* — never
   redundant. Deterministic replay is durable; a judge's guess is not.
4. **Complement observability, don't compete with it.** Plug in next to Langfuse/Phoenix
   (ingest their traces, or OpenTelemetry/OpenLLMetry-style spans); add the verdict they lack.
5. **Honest verdicts only.** Borrow the sibling project's contract: `PASS` / `WARN` / `FAIL`
   / `UNVERIFIED`, and **UNVERIFIED is never rendered as PASS**. Never claim a step is
   verified beyond what the replay actually checked.
6. **Runs on the user's infrastructure.** Self-hostable, privacy-preserving; traces and
   state stay on their box. This sidesteps the data-governance objection from day one.

---

## The four primitives (the product surface)

1. **Sandbox / execution boundaries** — the agent acts inside enforced limits (filesystem,
   network, tools); a bad action is contained, not catastrophic. **The sandbox is not only
   containment — it is a verdict axis** (see A1 below): the boundary that contains an action
   is the same machinery that judges it.
2. **Per-turn verification by replay** — re-execute each tool call in isolation and diff the
   *observed* post-state against what the agent *claimed*. This is the core primitive.
3. **Deterministic trace + replay** — capture every run exactly; re-run any past trajectory
   for debugging, regression, and audit.
4. **A compounding failure corpus** — every caught failure becomes a labeled case that
   sharpens detection over time (this is moat #2, and it must grow with each feature).

### The three verdict axes (deliberately unequal — read before touching the verdict)

| Axis | Grounding | May emit | Catches |
|------|-----------|----------|---------|
| **A1 · Invariant** | Sandbox policy, violated during replay | PASS / WARN / FAIL / UNVERIFIED | **Corrupt success** (the 27–78%) |
| **A2 · Replay** | Re-execution + state diff | PASS / WARN / FAIL / UNVERIFIED **· NOT_COVERED** (sub-verdict only) | **Trace infidelity** (fabricated/tampered results) |
| **A3 · Claim re-derivation** | A model writes a check; **execution** decides | WARN / FAIL / UNVERIFIED — **never PASS** | **Intent drift** |

Reduction: worst-status-wins across **A1 and A2 only**. A3 may downgrade, never promote, and
never turns UNVERIFIED into PASS. `belay --no-claim-axis` disables A3 and every PASS/FAIL
verdict must survive unchanged — that guarantee is enforced by a test, and it is the
one-command refutation of "isn't this an LLM judge with extra steps?"

**`NOT_COVERED` is a fifth status, and it is SUB-VERDICT-ONLY.** It marks a dimension Belay
has no instrument for at all — today exactly one: a tool's `openWorldHint: false` network
promise, which no filesystem delta can confirm or refute. `UNVERIFIED` means *"we tried to
check this and could not"*; `NOT_COVERED` means *"this was never inside what Belay claims to
check"*. `verdict.reduce` **drops it before ranking**, so it can never be a turn's reduced
status, never lowers a turn, and never lifts one — the empty-after-filter case reduces to
`UNVERIFIED`, never to `NOT_COVERED` and never to `PASS`. Folding it in was the old behavior
and it made an honestly-declared closed posture strictly *worse* than silence (declare
nothing → PASS; declare truthfully → UNVERIFIED forever), which pinned every turn of the
reference filesystem server at UNVERIFIED.

The honesty cost is real and named: a `PASS` now means *"passed on the dimensions Belay
checks"*, so **the coverage line must travel with the status on every surface** — a PASS
rendered without it is the failure mode this status creates. That rule is enforced by a test
per surface, not by review.

**The UNVERIFIED rate before and after this change is NOT COMPARABLE.** The population moved:
turns that were UNVERIFIED only because of an unobservable network promise are now PASS with a
`NOT_COVERED` sub-verdict. Any Phase-0 write-up quoting an UNVERIFIED-rate drop across this
boundary must say so — the drop is a reclassification, **not** improved detection.

**The axes are NOT redundant, and this is the easiest thing here to get wrong.** A2 cannot
catch a cheating agent, because a cheater's trace is perfectly *faithful* — it really did
delete the test. Replay restores the recorded pre-state (already containing the weakened
test), re-invokes, observes the same result, and returns **PASS, correctly**. Only a declared
invariant (A1) catches corrupt success. Building A2 and expecting it to catch cheating is the
single most likely way this project fails quietly.

---

## Tech direction (ingest surface LOCKED; rest proposed)

- **Core engine: Python.** Best fit for process/sandbox control, trace capture, replay, and
  the ML/verification layer. (Matches the founder's other engine work.)
- **Sandbox:** pluggable — containers / gVisor / firejail; start with one, abstract later.
- **Ingest: the MCP tool-call proxy — LOCKED.** Belay sits as a transparent proxy between any
  agent and its MCP servers. Chosen over LangGraph because MCP is the only tool-call surface
  that is *both* standardized *and* re-invocable without a framework runtime (LangGraph's
  calls are in-process Python callables — replaying them means re-entering LangGraph, which
  couples us to one framework and violates constraint #1). One adapter covers Claude Code,
  Cursor, OpenAI agents, and LangGraph itself. Bonus: MCP tool annotations (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`) are **self-declared** contracts, so a
  `readOnlyHint: true` tool that mutates state is a grounded FAIL with zero LLM involvement —
  **but read the next line before leaning on it.** The spec is explicit that annotations are
  *hints*: *"not guaranteed to provide a faithful description of tool behavior"*, and clients
  **MUST** treat them as untrusted from untrusted servers. So the verdict is **contract
  conformance** — *"the server's self-declared contract does not match observed behavior"* — not
  *"the tool violated the protocol."* Real, grounded, LLM-free, and zero-config; it catches
  **honest-but-buggy** servers, which is a large and valuable class. It catches **nothing
  adversarial**: a malicious server omits the annotation (inheriting fail-safe defaults) or lies
  in the safe direction. **User-declared invariants remain the load-bearing A1 mechanism;
  annotations are a free supplement.** Note also the defaults are *not* uniformly false —
  `destructiveHint` and `openWorldHint` default to **true** — and **a default is never a
  declaration**: absent must stay distinguishable from declared-false, or a default manufactures
  a false PASS.
  **Known cost:** an agent's *built-in* tools (Claude Code's `Bash`/`Edit`) do not traverse
  MCP — v0 verifies what crosses the MCP boundary and says so plainly. An
  OpenTelemetry/OpenLLMetry ingestion path (C9) lands so Belay sits beside existing
  observability.
- **Dashboard:** TypeScript + Next.js or Vue (founder's stack), local-first, streaming a live
  run feed + per-turn verdicts (a "watch and steer" surface).
- **Distribution:** OSS, self-hostable via Docker; BYOK / local-model friendly for any
  LLM-assisted verification (never a vendor key, nothing proxied).
- **License:** lean Apache-2.0 (permissive + explicit patent/trademark grant).

The **ingest surface is locked**; the rest is still open.
`docs/technical/ARCHITECTURE.md` (to be written) is authoritative once it exists.
Until then [`docs/technical/CAPABILITY_ROADMAP.md`](docs/technical/CAPABILITY_ROADMAP.md)
is authoritative on the engine's sequencing and verdict contract.

---

## The wedge → the company

Start as the OSS **per-turn "record & replay + verdict"** layer that plugs in next to
Langfuse/Phoenix, win developer trust and stars, then grow into the managed control plane
for running agents in production. Same playbook as the founder's other projects: free,
self-hostable, verifiable → monetize the managed / team / enterprise layer later.

---

## Founder profile

Solo / small-team. **Full-stack developer + ML engineer.** The moat is engineering —
sandboxing, deterministic replay, execution-grounded verification, and the evaluation
machinery — which is exactly the founder's edge. No dependency on proprietary data or
credentials the founder lacks.

---

## Quick facts for grounding (do not fabricate beyond these)

- **27–78% of benchmark-reported agent "successes" are "corrupt successes"** that hide
  procedural / integrity violations — right end-state via a broken/unsafe/cheating path
  (arXiv 2603.03116).
- **LLM-as-judge is unreliable where it matters:** "One Token to Fool LLM-as-a-Judge" shows
  up to **35% false positives** (arXiv 2507.08794); pairwise verdicts flip **10–30%** on
  trivial order swaps. → verification must be **execution-grounded**, not a judge.
- **Agents are the fastest-growing category on GitHub:** LLM-focused projects **+178% YoY**
  (Octoverse 2025); Browser-Use ~24× growth.
- **The direction is explicitly requested:** Conviction / Sarah Guo RFS 2026 — "the harness"
  (*"infrastructure that allows AI agents to operate reliably and autonomously in
  production"*); YC RFS Summer 2026 #13 "Software for Agents"; Karpathy (Sequoia Ascent 2026)
  "sensors and actuators."
- **Incumbents record but don't verify:** Langfuse / Phoenix / LangSmith / Braintrust trace
  and (optionally) LLM-judge score; none replay tool calls in a sandbox to check real state.

If you need a statistic that isn't here, do not invent one; say it's unverified. The
research base that seeded this project is in `~/dev/at/ideas/agent-trace-verifier.md` and
`~/dev/at/ideas/vc-attractive-ideas.md`.

---

## Non-goals / guardrails (restated so the project doesn't drift)

- **No agent framework / no Layer-1 authoring** as a product surface.
- **No bare LLM-judge scoring** dressed up as verification — the verdict must be grounded in
  re-execution.
- **No raw-data egress** — Belay runs on the user's infra; only traces/verdicts/hashes they
  choose to export ever leave.
- **No correctness over-claiming** — `UNVERIFIED` is never rendered as `PASS`.
- **The engine gets better as models improve** — reject work that would make a better base
  model make Belay redundant.

---

## Docs structure (to be created)

```
README.md                       # Repo front door (to write)
VISION.md                       # Narrative thesis, moat, non-goals (seeded — see file)
CLAUDE.md                       # This file
docs/
  ROADMAP.md                    # Phased plan + gates (WRITTEN)
  technical/CAPABILITY_ROADMAP.md  # C1–C9 engine backlog, test-first (WRITTEN)
  technical/ARCHITECTURE.md     # Sandbox / replay / verify engine design (to write)
  product/PRODUCT_SPEC.md       # Product surface and flows (to write)
```

The immediate next artifact is **code**: `C1 — MCP proxy trace capture`
(see the capability roadmap). Written test-first, on a branch off `master`.
