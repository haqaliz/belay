# PRD — C1: MCP proxy trace capture

**Capability:** C1 (`docs/technical/CAPABILITY_ROADMAP.md:62-96`) · **Phase:** 0 · **Window:** week 1
**Dependencies:** none — *"This is the first commit of the engine"* (`:96`)
**Cuttable:** No — the wedge
**Branch:** `feat/mcp-proxy-capture/aliz` · **Slug:** `mcp-proxy-capture`
**Inputs:** `docs/planning/_card/issue.md` (derived brief), `docs/planning/mcp-proxy-capture/understanding.md` (Phase 2)

> **Authority order:** `CAPABILITY_ROADMAP.md` > `ROADMAP.md` > `CLAUDE.md`/`VISION.md` > the brief.
> Where this PRD departs from the roadmap's letter, it says so explicitly and gives the reason.

---

## Problem Statement

**Who.** Engineers running agents unattended who must answer *"did this run actually do the right
thing?"* and today cannot.

**The problem C1 solves.** Not that question — C1 answers **nothing**. It solves the prerequisite:
**there is no faithful, re-invocable record of what an agent did.** Every Belay verdict (A1, A2),
every replay, and the entire failure corpus is derived from this record. Without it there is no
engine.

**Evidence it's real.**
- 27–78% of benchmark-reported agent "successes" are corrupt successes (`ROADMAP.md:12`) — invisible
  without a per-step record grounded in what actually crossed the wire.
- Incumbents record but don't replay (`ROADMAP.md:9`), and our survey confirms it holds for MCP
  specifically: **every** MCP recorder surveyed stops at record + response-diff. **Zero re-execute
  against world state.**
- **The MCP spec never mentions proxies.** No interposition guidance, no middlebox conformance
  suite. "Correct" is defined by real client/server pairs, not the document — which is why the
  neutrality proof must be executable, not asserted.

**Why this framing and not "write a proxy."** The proxy is a means. The deliverables that outlive it
are **the trace schema** (*"the interchange format for the whole engine"*, `:80-81`) and **an
executable proof of behavior-neutrality**. C1 is judged on those.

---

## Goals & Success Metrics

| Goal | Metric | Target |
|---|---|---|
| Behavior-neutral | Byte-level differential: same client + server, with vs. without proxy | **Byte-identical** message streams |
| The neutrality test has teeth | A deliberately re-serializing proxy is rejected by the same test | **Fails on ≥1 message**, permanently in CI |
| Lossless capture | Every frame recorded; hostile-but-legal bytes survive round-trip | **100%**, no dropped frames |
| Tamper-evident | Hashes stable across two identical runs | **100% stable** |
| Honest on failure | Malformed/non-conforming server | **Recorded error, never a dropped turn** |
| Schema round-trips | Trace written by version N readable by version N | **Pass** |
| Deterministic | Full suite | **No network, runs in CI, stable across repeat runs** |
| Small and finished | Wall-clock to C2 handoff | **≤5 working days**; C1 merged before C2 starts (see R-C1-1) |

**Non-metric, stated deliberately:** *latency* is **not** a success metric and **must not** be
asserted equal. See "Behavior-neutrality means content, not timing."

### What "behavior-neutral" can actually be proven to mean

**The claim is narrower than the roadmap's wording, and we state the narrow version.**

`:74-75` says *"an agent run through the proxy must behave exactly as it does without it."* A
byte-level differential proves this by running the same client/server pair twice and comparing. But
**against a real MCP server that is nondeterministic** (varying ids, timestamps, progress tokens),
two runs differ **for reasons unrelated to the proxy** — so the differential is **unrunnable there**.

What C1 can prove: **"against a deterministic fixture, the proxy is byte-transparent."**
What C1 cannot prove: that no real server anywhere is perturbed.

Guardrail 7 — *"Never claim coverage we don't have"* (`:424-425`) — **applies to us, not only to the
product's output**. The README and any launch material must use the narrow claim. The Phase-0 corpus
(≥50 real runs) is *corroborating evidence* of neutrality, **not a proof**, and must be described as
such.

---

## User Personas & Scenarios

**Primary (today): the founder building C2–C5.** The only consumer of C1's output for weeks. C1 is
right if C2 can hang a state handle on a turn, C3 can re-invoke a recorded call **without the
original agent**, and C4 can produce a **concrete diff**.

**Secondary (Phase 0, week 3–4): the corpus run.** ≥50 SWE-bench-lite runs through the proxy
(`ROADMAP.md:103`). C1 is right if it survives 50 real runs without perturbing them.

**Eventual (Phase 1): the stranger who `docker run`s it.** Explicitly **not** served by C1 — no
packaging, no UI, no ergonomics in Phase 0 (`ROADMAP.md:86`).

---

## Requirements

### Must-have

**M1 · Transparent stdio proxy.** Agent → Belay → real MCP server. Belay spawns the real server as a
subprocess and presents its own stdin/stdout. stdio only.

**M2 · Forward original bytes, verbatim. Never re-serialize.**
*Decided on measured evidence (see Technical Considerations).* The forwarding path carries the
**original buffer**. A copy is parsed off the hot path for indexing. **Never forward the parse
output.**

**M3 · Full-duplex pump.** Two independent, message-type-agnostic async pumps. **Not** a
request/response state machine — under **2025-11-25 (current)** MCP servers originate requests
(`sampling/createMessage`, `roots/list`, `elicitation/create`, `ping`), and a request/response loop
deadlocks or drops the moment one arrives.

> **⚠️ This rationale expires in 13 days — and the design survives anyway. That is the point.**
> The **2026-07-28 RC removes server-initiated requests entirely** (SEP-2322), replacing them with
> **Multi Round-Trip Requests**: the server returns `resultType: "input_required"` with
> `inputRequests`, and the **client retries the original request — with a NEW request id** — carrying
> `inputResponses`. Roots, Sampling **and Logging** are deprecated wholesale (SEP-2577); `ping` and
> SSE resumability are removed (SEP-2575).
>
> **A proxy built around a request/response state machine would need a rewrite. Ours needs nothing**,
> because it does not model the conversation — it forwards bytes and never interprets. The RC
> *vindicates* the design rather than threatening it. This is the strongest available evidence for
> M2/M13: **the way to survive a protocol changing under you is to refuse to model it.**

**M4 · Correlate on `(direction, id)`.** Client- and server-originated ids are **separate namespaces
and may both start at 1**. Bare-id correlation cross-wires them. Responses carry no `method`, so
correlation must be by id. Correlation state lives in **our own side-table** — writing into `_meta`
would break byte-neutrality.

**M5 · Record every frame** as append-only JSONL, one frame per line: `seq` (monotonic), `dir`,
`raw` bytes, hashes, timestamps. **`tools/call` is a derived index over frames, not the unit of
capture.**
> *Departure from the roadmap's letter, deliberate.* `:76` says *"Capture per `tools/call`."*
> Neutrality forces us to pump every frame regardless, so recording them is ~free — and C2's
> denials, C3's nondeterminism marks, and C9's OTel correlation all need the other frames. This is a
> **superset** of the roadmap's ask; nothing it requires is lost.

**M6 · Store raw + hash both.** Every frame stores raw bytes, `hash_raw` (over bytes as received),
and `hash_canonical` (over a **documented, versioned** canonical form, e.g. `belay/jcs-v1`).
Losslessness survives; the canonicalization opinion is **explicit and versioned** rather than
silent; C4 diffs raw, C6 compares canonical.
**Forbidden:** canonicalize → hash → discard the original. That is lossy and silently defines away a
class of divergence C4 exists to catch.

**M7 · Annotation snapshot with a mandatory tri-state.** Snapshot tool annotations from `tools/list`.
Each of `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` records
**`declared-true` | `declared-false` | `not-declared`**, plus a separate fact for *"this tool had no
`annotations` object at all."*
> **Why this is non-negotiable.** Spec defaults are `readOnlyHint: false`, `destructiveHint: **true**`,
> `idempotentHint: false`, `openWorldHint: **true**` — fail-safe, but **a default is not a
> declaration**. An un-annotated tool defaulted to `readOnlyHint: false` would let C4 reason *"it
> mutated, it never claimed read-only, therefore fine → **PASS**"* — a **false PASS manufactured by a
> default**, exactly what `:193-194` and `:205-206` forbid. Only a tri-state distinguishes *declared
> permissive* from *declared nothing*.

**M8 · Re-snapshot on `notifications/tools/list_changed`.** Snapshots are **timestamped and
appended**, never overwritten.
> *Departure, deliberate.* `:76` says *"at session start"* (singular). Servers may change their tool
> list mid-session; a single snapshot verifies against a **stale contract**, and C4/C5 would inherit
> the staleness.

**M9 · Per-call resolved connection context.** Each frame records the **resolved** protocol version
and client identity, rather than pointing at a session-header record.
> **Not "session" — the word is now wrong.** The RC states verbatim: *"an open connection, such as a
> STDIO process, is **not** a conversation or session: clients may interleave unrelated requests on
> the same transport, and a server must not treat connection or process identity as a proxy for
> conversation or session continuity."* MCP becomes **a stateless protocol**: *"no state should be
> inferred from previous requests, even those on the same connection or stream."* Naming our T0→T1
> fact a "session" would encode a falsehood the spec explicitly forbids. It is a **connection
> window**.
>
> **Normative `_meta` keys (verified, citable):** `io.modelcontextprotocol/protocolVersion`
> (example value literally `"2026-07-28"`), `io.modelcontextprotocol/clientInfo`,
> `io.modelcontextprotocol/clientCapabilities` — **all REQUIRED on every client request**; a request
> missing any is malformed and the server **MUST** reject it `-32602`.
> **Why now.** The **2026-07-28** revision (locked 2026-05-21, **ships 2026-07-28**) removes the
> `initialize`/`initialized` handshake (SEP-2575) and the protocol-level session + `Mcp-Session-Id`
> (SEP-2567); version/clientInfo/capabilities move into `_meta` **on every request**. "Session start"
> has ~13 days to live. Per-call resolution reconstructs from **either** a handshake (≤2025-11-25)
> **or** per-request `_meta` (≥2026-07-28). Near-zero cost under raw-bytes forwarding; the
> alternative lands the migration during C2/C3 — i.e. on the critical path (R2).

**M10 · Forward everything; police nothing.**
- **Never rewrite** `protocolVersion`, capabilities, `_meta`, or `instructions`. Version negotiation
  is a two-message exchange **between client and server**; a pass-through proxy is safe *precisely
  because it does not participate*. Read the negotiated version; forward the bytes untouched.
- **Forward `stderr`.** Spec: servers MAY write **any** logging to stderr and clients **SHOULD NOT**
  assume it indicates error. Don't swallow it, don't treat it as failure.
- **Forward progress notifications immediately, unbuffered.** They reset client timeout clocks —
  buffering can cause timeouts on calls that would otherwise succeed.
- **Forward batch arrays** (invalid ≥2025-06-18) and flag non-conformant. **Neutral beats
  conformant: our job is to observe the connection, not police it.**
- **Never inject** — no synthetic `ping`, no capability edits, no injected tools.

**M11 · Honest failure recording.** A malformed / non-conforming server yields a **recorded, honest
error, never a dropped turn**. Distinguish, as recorded facts: JSON-RPC **protocol error** (`error`
member, no `result`) vs **tool execution error** (success envelope, `isError: true`).
> These are different on the wire, and **2025-11-25 moved the line** (SEP-1303: input-validation
> errors became execution errors "to enable model self-correction"). The same failure therefore has
> different shapes across revisions. **Record raw; derive classification.** Never conflate.
> Cancellation is racy by design — some requests **legitimately never get a response**; the writer
> must not leak entries or block awaiting one.

**M12 · Versioned, self-describing schema** with a documented rule for **unknown record types and
higher versions**. Records are self-describing enough to stand alone (C6 stores **slices**, not whole
runs).

**M13 · Capture is structurally unable to perturb — forward by streaming, observe by peeking.**
The forwarding path **streams bytes through in chunks** and is **never** frame-reassembled; the
capture branch receives only a **bounded copy** (cap it, e.g. 16 MiB) and **cannot** alter or block
the data path. Hashing and disk writes sit **off the forwarding path**; client timeouts are real and
our latency is inside them.
> **Design adopted from `mcpsnoop`'s audited source**, whose contract reads: *"Bytes are forwarded
> verbatim and ordering is preserved, observation is best-effort and never blocks or alters the data
> path."* Streaming makes byte-exactness a **structural property** rather than a behavior we must
> test for, and bounding the observed copy means a pathological frame cannot exhaust memory while
> the data path stays unbounded. *(Explicitly rejecting mitmproxy's addon model — synchronous
> mutation points on the hot path.)*
> **Consequence for M4:** the `(direction, id)` index is built from the peeked copy, so
> **indexing may be lossy on a frame exceeding the cap while forwarding stays exact.** That case
> must be recorded as a **named cause**, never silently indexed as absent.

**M14 · Local-only.** No telemetry, no phone-home, no default remote sink. Artifact root
**configurable**, default `/traces/` (already gitignored). `/runs/` left free for C2's per-run working
dirs; `_sandbox/` is C2's, `corpus/local/` is C6's.
> The Phase-0 corpus (≥50 runs) will not want to live in the source checkout — hence configurable on
> day 1.

**M15 · The trace is sensitive by construction — say so, don't silently create it.**
Lossless capture of `tools/call` arguments means the trace records **API keys, tokens, file contents,
and customer data verbatim**. C1 creates a new, permanent, plaintext store of exactly the material
the agent touches. This is R8 (*"Belay itself is the vulnerability"*) arriving in week 1, and it is
**in tension with losslessness itself**: redaction is the obvious mitigation and it is **lossy**,
which M6 forbids.

**Position (decided):**
- **Capture stays lossless.** Redaction at capture time would destroy the evidence A2 exists to
  diff, and a redacted trace cannot be replayed. **Never a capture-time filter.**
- **The trace inherits the sensitivity of the agent's most sensitive tool argument.** Documented
  prominently, not in a footnote.
- **Restrictive file modes** (owner-only) on trace files and the artifact root at creation.
- **Redaction, if it ever ships, is an opt-in *view/export* concern** (a later capability), never
  capture. This preserves "nothing is uploaded, ever" (`:282-283`) while keeping replay honest.
- **No secret-scanning heuristics in C1** — that is an opinion, and C1 is opinion-free (`:82`).

*This is stated as a requirement rather than an open question because shipping a plaintext secret
trove without saying so would be exactly the kind of quiet over-claim the project exists to oppose.*

### Should-have

- **S1 · Record annotation incoherence** as a fact: `destructiveHint`/`idempotentHint` are *"meaningful
  only when `readOnlyHint == false`"*. `readOnlyHint: true, destructiveHint: true` is incoherent, and
  the incoherence is itself signal.
- **S2 · State-handle slot, three-state, left empty.** `absent` / (reserved) `present(handle)` /
  (reserved) `unrestorable(cause)`. **C1 does not build snapshotting.**
  > If the slot can only express present/absent, C2 must either break the schema on its first commit
  > or overload "absent" to mean both *"C1-era trace"* and *"C2 tried and failed."* **Overloading
  > those is how a false PASS is born** — C3 (`:163`) and C4 (`:207-208`) both require UNVERIFIED for
  > an unrestorable pre-state.
- **S3 · Record `structuredContent` and its duplicate TextContent faithfully.** Servers SHOULD
  serialize structured output into a text block too, so **the same data commonly appears twice on the
  wire**. Record both; downstream must not double-count.
- **S4 · Session-window facts** (proxy live from T0 to T1) so R6's denominator is expressible.

### Nice-to-have

- **N1 · `belay proxy` CLI** thin enough to point an agent at. No other surface.
- **N2 · Per-server annotation distribution** as a byproduct (`:93-94`: the reference for C4).

---

## Trace Contract (the deliverable that outlives C1)

Illustrative, not final — settled in `tech-plan`:

```jsonc
// trace.jsonl — append-only, one frame per line
{
  "v": 1,                          // schema version
  "kind": "frame",                 // extensible: C2 appends "denial", C3 appends "nondeterminism"
  "seq": 4,                        // monotonic, capture-time
  "dir": "c2s",                    // c2s | s2c
  "raw": "<original bytes verbatim>",
  "hash_raw": "sha256:...",        // over bytes as received
  "hash_canonical": "sha256:...",  // over documented canonical form
  "canonical_form": "belay/jcs-v1",
  "t_in":  "...",                  // proxy-observed, OUTSIDE hashed content
  "t_out": "...",
  "observation_point": "proxy",    // never implies server-side timing
  "protocol_version": "2025-11-25",// resolved per-call (M9)
  "state_handle": {"status": "absent"}  // C2 fills; three-state (S2)
}
```

**Raw-byte embedding (decided).** `raw` is **base64** of the exact bytes as received.
> JSON-in-JSON re-escaping is *recoverable* but makes the "verbatim" claim rest on escaping
> correctness, and MCP mandates UTF-8 without guaranteeing every server obeys it — a non-conforming
> server (which M11 says we must record honestly, not drop) could emit bytes that are not valid
> UTF-8 and therefore not representable as a JSON string at all. **base64 round-trips exactly,
> unconditionally.** Cost: the trace is no longer eyeball-readable. Accepted — human-readability is
> **C7's** job (the console), not the interchange format's, and a `belay trace cat` decoder is cheap
> whenever it's wanted. *If human-readability is later judged essential, the fallback is a
> parallel decoded field — never replacing `raw`.*

**Hash stability, precisely.** *"Hashes are stable across two identical runs"* (`:88`) means:
**per-frame `hash_raw` and `hash_canonical` are byte-stable across two runs of the same
deterministic fixture.** It does **not** claim stability against real servers (varying ids,
timestamps, progress tokens) — that is not a proxy property and must not be asserted. A whole-trace
hash is **out of scope for C1** (C6's sliceable cases want per-record hashes; a roll-up is cheap to
add later and premature now).

**Invariants of the contract:**
1. **Timing lives outside hashed content.** Otherwise *"hashes stable across two identical runs"*
   (`:88`) can never pass. Schema-layout requirement, not an implementation detail.
2. **Timing is proxy-observed and says so.** A bare `duration_ms` meaning *"server time plus however
   long Belay took"* is a small over-claim, and guardrail 7 (`:424-425`) exists against exactly that
   genre. C9's span correlation joins against this number, so it must mean what it says.
3. **A turn is a set of append-only records keyed by turn id**, not one mutable record. C2's denials,
   C3's marks, and C6's sliceability all require it; append-only is a **correctness** property (C3:
   *"Replay never mutates the original trace"*, `:166`), not a style choice.

---

## Technical Considerations

**Language/toolchain.** Python. `.gitignore` already presumes **pytest, mypy, ruff, `.venv/`, and a
packaged dist** — the closest thing to a toolchain decision the repo has made. C1, as the first
commit, settles it.

**The SDK cannot be on the forwarding path — measured, not assumed.**

| | `mcp` 1.28.1 (current stable) | `mcp` 2.0.0b2 (beta; stable targeted 2026-07-27) |
|---|---|---|
| Emit | `model_dump_json(by_alias=True, **exclude_none=True**)` | `model_dump_json(by_alias=True, **exclude_unset=True**)` |
| `extra` on JSONRPC envelopes | `allow` | **`None`** → unknown top-level fields **dropped** |
| Failure mode | drops explicit nulls (`{"params":null}` → gone) | drops unknown fields |

Verified in installed source (`v1 client/stdio/__init__.py:155,172`; `v2 client/stdio.py:174`; v2
moved types to a separate `mcp_types` package). v1 also rewrites key order and escapes non-ASCII
(`"café"` → `"café"`), and hard-fails batch arrays with `ValidationError`.
**v1 and v2 are unfaithful in different, incompatible ways** — neither can carry a byte-identity
claim. `stdio_client` owns the subprocess *and* the parse loop *and* the emit loop, yielding only
typed streams: **there is no injection point between them.**

→ **Decision: hybrid. Raw bytes on the forwarding path; parse a copy with stdlib `json` off the hot
path. No SDK runtime dependency.** The apparent tension (byte-identity vs. parsing) dissolves:
*parsing-to-read* and *parsing-to-re-emit* are different operations. This also absorbs the
2026-07-28 migration at near-zero cost (`_meta`-per-request rides through as an opaque dict inside
`params`), whereas an SDK-typed proxy inherits whichever failure mode its pinned version has.

**The integrity argument (why this is correctness, not taste).** Under an SDK pump the trace records
what *Pydantic* would have sent, not what the agent sent — **the proxy would launder the exact
tampering A2 exists to detect**. Byte-fidelity is what makes a message hash mean anything.

**Behavior-neutrality means content, not timing.** `:74-75` demands the agent *"behave exactly as it
does without it"*; `:76` captures **timing**; a proxy unavoidably adds latency. These cannot both
hold in the strong sense. The acceptance test asserts **byte-identical *responses*** (`:88`) — not
identical timing — so the operative definition is **content-neutrality on the wire**, and the docs
never claim latency-neutrality. **The test must not assert timing equivalence; that would assert
something false.** Added latency is worth *measuring* as a metric, not asserting as zero.

**stdio first.** Newline-delimited JSON-RPC, UTF-8, **no Content-Length framing** (MCP diverges from
LSP — do not carry LSP assumptions over). Servers MUST NOT write non-MCP to stdout. Buffer and split
on `\n`: the one-line rule binds the **sender**, and read boundaries do not align with message
boundaries. Streamable HTTP adds SSE, session headers, resumability, and OAuth — materially harder to
proxy neutrally, and stdio is the actual Claude Code / Cursor surface.

**Why build a proxy at all, when `mcpsnoop` exists?** The sharpest challenge to this PRD: `mcpsnoop`
(Go, 267★) already claims byte-verbatim stdio forwarding and writes JSONL. Consuming it would free
week 1 for **C2 — the actual critical path**. Reasons to build anyway, stated so they can be
falsified rather than assumed:

1. **The format must be ours to version.** C1 is *"the interchange format for the whole engine"*
   (`:80-81`). C2 appends denials, C3 appends nondeterminism marks, C5 versions invariants with the
   trace, C6 slices it. A format we don't control cannot absorb that, and we would be one upstream
   refactor from a broken engine.
2. **Its transparency claim is unaudited** (README-derived). Adopting it means inheriting an unproven
   claim as our foundation — the precise error this project exists to oppose.
3. **A Go binary is a real dependency** for a Python engine that must `docker run` cleanly (Phase 1)
   and stay self-hostable.
4. **The state-handle slot (S2) has no analogue** in a tool with no sandbox.

**Falsifier:** if an audit shows `mcpsnoop`'s format is versioned, extensible, and its transparency
holds, then **reusing its trace as a C1 *input adapter* is worth reconsidering** — which is C9's
shape anyway (ingest someone else's trace, add the verdict). **Not a week-1 decision, but the audit
is cheap and it is an open question below, not a settled one.**

**Verdict impact: none, by design.** C1 sits on **no axis** and emits **no verdict** — *"Capture is
lossless and opinion-free. C1 makes no judgements — it records"* (`:82`). But it **determines what the
axes can later say**: A2 needs the result **structurally** (a hash yields *"differs"*, never a
**diff** — and C4's acceptance demands the diff, `:199-200`), A1 needs the annotation snapshot
(C5's zero-config path is built entirely from it, `:235-237`), and **UNVERIFIED needs a *named
cause*** (`:416-417`) that can only originate in C1's capture.

**Guardrail check.** No agent framework (the proxy never spawns/drives/prompts the agent — a "run the
agent for you" wrapper is the drift to watch). No LLM judge (zero model calls). No egress. Test-first.
✅ No violation.

---

## Risks & Open Questions

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| **R-C1-1** | **Over-investing in capture.** `mcpsnoop` (Go, 267★ in 3 weeks) already claims byte-verbatim forwarding. Capture **will** commoditize; the moat is the verdict. Every day here is a day off **C2 — the critical path (R2, High/High)**. | **High** | **C1 is correct, small, and *finished*.** Scope-add gets deferred to C2+ by default. This is the top risk. |
| **R6** | *Roadmap risk.* Interesting failures never cross MCP (built-in `Bash`/`Edit` bypass). | High | C1 **cannot retire it** — only make it measurable (C9 produces the number). Fixtures + corpus use MCP FS/shell servers. Record session-window facts (S4) so the denominator is expressible. |
| **R-C1-2** | **Annotation over-claim.** `CLAUDE.md:113-116` calls a `readOnlyHint: true` tool that mutates *"a grounded FAIL with zero LLM involvement."* Spec is emphatic they are **hints**, *"not guaranteed to provide a faithful description of tool behavior"*, and clients **MUST** treat them as untrusted from untrusted servers. | **Fatal (trust)** — R5 genre | Reframe as **"contract conformance"**, not "protocol violation." It catches **honest-but-buggy** servers (large, valuable) and **nothing adversarial** — a malicious server omits the annotation (inheriting fail-safe defaults) or lies safely. **User-declared invariants remain load-bearing A1; annotations are a zero-config supplement.** → **`CLAUDE.md` wording fix, outside C1's code scope.** |
| **R-C1-3** | **Naive proxy breaks under a real agent** — server-originated requests deadlock a request/response loop. | High | M3 + M4. The most likely way a naive C1 fails. |
| **R-C1-4** | **A vacuously green test.** Observed for real while building the prototype: a broken fixture made both sides emit nothing and compare equal. **A green suite proving nothing — the exact failure mode Belay exists to catch.** | **High** | **Fixture-guard test** asserting the fixture still carries hostile bytes, + the teeth test. **Repo norm: every differential needs an anti-vacuity guard.** |
| **R-C1-5** | Schema under-designed → C2 breaks it on its first commit. | Med | Extensible record kinds (M12) + three-state handle slot (S2). **But do not gold-plate:** `:91` only tests N→N round-trip; the real versioning test arrives at C2. **No migration framework in week 1.** |
| **R-C1-6** | Naming: **mitmproxy distinguishes *client-replay* (re-send to live server — *this is A2*) from *server-replay* (serve recorded responses — a **mock**, can never produce a verdict). Every MCP tool surveyed ships server-replay and calls it "replay."** | Med | Name A2 distinctly from day 1 or be read as another mock server. |
| **R-C1-7** | **The trace is a plaintext secret store.** Lossless capture records tokens, keys, and customer data verbatim. R8 arrives in week 1, and the obvious mitigation (redaction) is **lossy** and therefore forbidden at capture. | **High** | **M15.** Lossless capture + owner-only file modes + prominent documentation; redaction deferred to an opt-in **view/export** concern, never a capture-time filter. |
| **R-C1-8** | **The neutrality proof is narrower than the roadmap's wording.** A differential is unrunnable against a nondeterministic real server, so we prove transparency **against deterministic fixtures only**. | **Med (trust)** | State the narrow claim in the PRD, README, and launch material. The Phase-0 corpus is **corroborating evidence, not proof**. Guardrail 7 applies to us, not just to the product. |
| **R-C1-9** | **Two correlation models, not one.** The RC's MRTR (SEP-2322) correlates by **retry-chain with a NEW request id per retry**, not by `(direction, id)` pairing. `requestState` is how a server correlates an elicitation across retries. A trace schema assuming one-request-one-response-forever cannot express an MRTR chain. | **Med** | `(direction, id)` is a **strict superset** and survives both (the RC removes server-originated ids entirely), so C1 keeps it. **Do not build MRTR; do not foreclose it.** **Escalate to `CAPABILITY_ROADMAP.md`: this is a real design fork for C3/C4 and should be named there before replay is built.** |

### 📌 Escalations to `docs/technical/CAPABILITY_ROADMAP.md` (outside C1's code scope)

Verified against the normative RC text; the roadmap describes the **outgoing** protocol as though it
were stable. Worth a pass before C1 merges:

1. **C1's "snapshot annotations at session start"** (`:76`) — "session" ceases to exist (SEP-2575).
   Superseded by M9 here (per-call resolved connection context).
2. **The A1 axis gains free, grounded, LLM-free failure signals** the roadmap doesn't mention:
   `-32020 HeaderMismatch`, `-32021 MissingRequiredClientCapability`, `-32022
   UnsupportedProtocolVersion`, plus a formal error-code allocation policy (`-32020`–`-32099`
   reserved for the spec). These arrive **free on the wire** with zero LLM involvement — exactly the
   kind of grounding A1 wants.
3. **C9 (OTel interop) got easier AND more strategically urgent.** The RC reserves
   `traceparent`/`tracestate`/`baggage` in `_meta` as an explicit exception to the prefix rule,
   citing W3C Trace Context and the **OTel semantic conventions for MCP**. Trace context is becoming
   **protocol-native**, not a bolt-on — "we sit beside Langfuse/Phoenix" becomes partly a
   protocol-level story. **Logging's deprecation (SEP-2577) points the ecosystem at OTel as its
   migration path**, i.e. straight at C9's surface. C9 may deserve to move earlier than week 8.
4. **The MRTR correlation fork** (R-C1-9) — C3/C4 need two models, not one with a flag.
5. **The wedge still looks right.** MCP is *consolidating, not fragmenting* (stateless core, one
   transport, formal deprecation policy, OTel on-ramp). But **the thing we locked to is changing
   under us in under two weeks**, and the roadmap should say so rather than read as though
   2025-11-25 were permanent.

**Open questions (not blocking C1's first test):**
1. **Canonical form** — JCS (RFC 8785) or a Belay-defined form? Must be documented + versioned either
   way. *Decide in `tech-plan`.*
2. ~~`mcp-vcr` audit~~ — **RESOLVED. Source audited (sdist 0.1.3 downloaded and read).** It does
   **not** occupy C1's slot, and consuming it is **not viable**:
   - **`payload` is `"type": "object"`** in `schemas/transcript-schema-v1.json` — it stores the
     **parsed** JSON-RPC object, **not raw bytes**. It therefore *cannot* make a byte-identity claim,
     and it is the "canonicalize → discard the original" failure mode **M6 forbids**, shipped.
   - **No hashing anywhere** (`grep sha256|hashlib|blake2|md5` → nothing). **No content-addressing,
     no tamper-evidence.**
   - **`messages` is `additionalProperties: false`** — a **closed schema**. C2's state handle and
     C3's nondeterminism marks could not be appended without a format break. Validates M12's
     extensible record kinds.
   - **Different audience and mode.** README: *"Verify your current code against all snapshots"* — it
     is a **server regression** tool (record → snapshot → verify), i.e. **golden-snapshot
     server-replay**. It tests *your MCP server*; Belay verifies *the agent*. Inverse audience.
   - **Convergence worth noting:** its `dir: c2s|s2c` matches our naming, and `protocol_version` is
     *"Captured lazily"* — independent evidence that **M9's per-call resolution problem is real**.
     Its `incomplete_reason` enum (`timeout|server_crash|pipe_error|malformed_response`) is a
     named-cause pattern worth borrowing for M11.
   - **The human-readability fork is real, and we take the other branch deliberately.** Its
     git-diffable YAML is bought *precisely* by giving up byte fidelity. **Our base64 `raw` is the
     differentiator, not an oversight.**
3. ~~`mcpsnoop` source audit~~ — **RESOLVED. Source audited** (`internal/proxy/stdio.go`).
   **Its transparency claim is stated in the source, not just the README**, and the architecture
   backs it:
   > *"Transparency contract. Bytes are forwarded verbatim and ordering is preserved, observation is
   > best-effort and never blocks or alters the data path."*
   - **Adopt its shape (it is better than this PRD's implied design).** It **streams the data path in
     chunks** and hands the Sink only a **bounded copy** (`maxFrameBytes = 16 MiB`), so the forward
     path is byte-exact *by construction* and a pathological line cannot exhaust memory. **This PRD
     implied line-buffered forwarding — i.e. frame reassembly on the hot path. Superseded: forward by
     streaming, observe by peeking a bounded copy.** This is M13 done properly and it strengthens the
     mitmproxy-addon rejection.
   - **Still build, not consume:** Go binary (a real dep for a Python engine that must `docker run`),
     its sink format is not ours to version (`:80-81`), **no verdict layer**, no state-handle slot.
     The **falsifier did not fire** — its format is not offered as a versioned interchange contract.
   - Its `internal/proxy/redact.go` + `redact-secrets`/`redact-key`/`redact-path` config is
     **independent evidence that R-C1-7 is a real user expectation, not our invention.**

**Audit verdict: build C1 as specified.** Neither tool occupies the slot; `mcp-vcr` is lossy and
aimed at server authors, `mcpsnoop` is byte-faithful but verdict-free and unversioned. **Nothing
found re-executes against world state — A1/A2 remains unoccupied.** Two design improvements adopted
(streaming-chunk forwarding; `incomplete_reason`-style named causes).

### ⚠️ Provenance note on the prior-art findings

The competitive survey in this PRD originated from a subagent whose work **was never reviewed by the
agent that spawned it**, and which was subsequently **disowned** — despite it claiming to have "read
the source myself."

**Every load-bearing claim from it was therefore independently re-verified** against the GitHub and
PyPI APIs before this PRD was approved: `mcpsnoop` (268★, Go, dates, description), `mcp-vcr` (0.1.3,
upload time, absent repo URL), `mcp-recorder` (0.5.0, summary, `devhelm/` links). **All held.**

**It turned out true is not the same as it was verified.** Recorded here because a PRD for a project
whose thesis is *"execution-grounded verification, not a confident-sounding claim"* must not itself
rest on an unverified chain. **Anything from that survey not listed above as re-verified — including
`agent-vcr`, the wider gateway landscape, and all star counts and "abandoned" judgements — remains
UNVERIFIED and must not be cited as fact.**
4. **Annotation adoption in the wild is unmeasured.** `server-everything` is 13/13 annotated, but that's
   a reference server. **Do not build the demo around annotation-derived checks until measured** — this
   is R3's real exposure.
5. **Concurrent interleaving is not deterministically reproducible from wire order alone.** Record
   `seq` + timestamps and be honest that wire-order replay reconstructs *a* valid ordering, not *the*
   ordering. **An UNVERIFIED boundary worth naming explicitly** rather than papering over. *(C3's
   problem; C1 must not foreclose it.)*

---

## Out of Scope

- **Any verdict, any axis.** No PASS/WARN/FAIL/UNVERIFIED emitted. (C4/C5/C8)
- **Snapshot/restore.** The state-handle slot is **defined and left empty**. Guessing the substrate
  pre-empts C2's *"start with the narrowest restorable substrate... abstract **late**"* (`:109-110`)
  with zero information. (C2)
- **Re-invoking or replaying anything.** (C3)
- **Diffing anything.** (C4)
- **Invariants**, including annotation-inferred. (C5)
- **Corpus format / precision-recall.** (C6)
- **Any UI.** Phase 0 ships none (`ROADMAP.md:86`).
- **Streamable HTTP / SSE / OAuth.** stdio only.
- **Non-MCP surfaces** (Claude Code `Bash`/`Edit`). R6, demand-pulled Phase 2.
- **Packaging / `docker run` / time-to-first-verdict.** Phase 1.
- **Off-the-shelf MCP servers in unit tests.** They are the **Phase-0 corpus** substrate
  (`ROADMAP.md:41`); C1's tests are **fake, in-repo, no network** (`:91`). Pin exact versions when the
  corpus runs — bare `npx -y` resolves latest and silently breaks determinism.
- **A migration framework.** (R-C1-5)

---

## Acceptance Criteria (test-first — these are written as failing tests before any code)

Direct from `CAPABILITY_ROADMAP.md:84-91`, plus the guards the prototype proved necessary:

1. **Behavior-neutrality.** Fake MCP server + scripted client, with and without the proxy →
   **byte-identical** streams. *The gate everything else hangs from.*
2. **Teeth.** A deliberately re-serializing proxy is **rejected** by (1). *Permanent in CI — the
   executable form of the no-SDK-on-the-forwarding-path argument.*
3. **Anti-vacuity.** The fixture still carries hostile-but-legal bytes (scrambled key order,
   non-ASCII, explicit nulls, unknown fields, interleaved unsolicited notification). *Guards against
   the green-but-empty failure observed for real.*
4. **Capture completeness.** Every `tools/call` appears with args, result, and annotations; **hashes
   stable across two identical runs**.
5. **Tri-state annotations.** `not-declared` is distinguishable from `declared-false`. *Directly
   guards C4's "an absent contract is not a permissive one."*
6. **Honest errors.** Malformed / non-conforming server → **recorded error, never a dropped turn**;
   protocol error and `isError: true` are distinguishable.
7. **Schema round-trip.** Version N written → version N readable. Deterministic, no network.
8. **Real-client compat.** A real `mcp` SDK client drives through the proxy successfully. *SDK is a
   **dev-only** dependency, never runtime.*
9. **Byte-exact round-trip through the trace.** Frames recovered from `raw` are **byte-identical** to
   what crossed the wire — including a **non-UTF-8 / non-conforming** frame, which must round-trip
   rather than crash the writer. *Proves base64 embedding and M11 together.*
10. **Trace files are owner-only** at creation (mode asserted). *M15 in code, not prose.*

All tests: **deterministic, no network, CI-runnable.**

> **Explicitly NOT asserted, because it would be false:** timing equivalence between direct and
> proxied runs (R-C1-8); hash stability against a real, nondeterministic server; that any real
> server is unperturbed. C1 proves byte-transparency **against deterministic fixtures**.
