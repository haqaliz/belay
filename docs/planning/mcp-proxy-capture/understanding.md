# C1 — MCP proxy trace capture: Understanding note (Phase 2)

**Status:** pre-PRD. Written after a three-agent research fan-out, with every load-bearing
claim independently re-verified in this session (see *Verification log*).

**Source:** `docs/planning/_card/issue.md` (derived brief — no GitHub issue exists; the
tracker is empty). Authority order: `docs/technical/CAPABILITY_ROADMAP.md` > `docs/ROADMAP.md`
> `CLAUDE.md` / `VISION.md` > the brief.

---

## 1. What the work is really asking

Build the first code in the repo: a **transparent stdio MCP proxy that records every
`tools/call` losslessly and judges nothing**, plus the versioned on-disk trace format that
every later capability (C2–C9) reads.

The deceptive part: this reads like "write a proxy." It is really "**define the interchange
format for the whole engine**, and prove you can observe a connection without perturbing it."
The proxy is a means; the trace schema and the neutrality proof are the deliverables that
outlive it. `CAPABILITY_ROADMAP.md:80-81` — *"It is the interchange format for the whole
engine, so it gets a versioned schema on day 1."*

**The one-line acceptance that matters** is not "we captured a `tools/call`." It is *"the
client cannot tell we're here,"* proven by a byte-level differential test.

---

## 2. Placement on the verdict axes

**C1 sits on no axis. It emits no verdict.** This is not a technicality — it is the
capability's defining constraint (`CAPABILITY_ROADMAP.md:82`: *"Capture is **lossless and
opinion-free**. C1 makes no judgements — it records."*).

But C1 **determines what the axes can later say**:

- **A2 (replay)** needs the recorded result *structurally*, not just its hash — C4's
  acceptance demands *"the exact recorded-vs-observed diff in the message"*
  (`CAPABILITY_ROADMAP.md:199-200`). A hash yields "differs"; it cannot yield a diff.
  → **C1 stores content AND hash.**
- **A1 (invariant)** needs the annotation snapshot; C5's zero-config path is built entirely
  out of it (`CAPABILITY_ROADMAP.md:235-237`).
- **UNVERIFIED** needs a *named cause* (`CAPABILITY_ROADMAP.md:416-417`). The only place a
  cause can originate is C1's capture. A malformed response, a dropped connection, a
  never-arrived `tools/list` must each land in the trace as a **distinguishable recorded
  fact**.

**The integrity argument for byte-fidelity.** If the proxy re-serializes, the trace records
what *the serializer* would have sent, not what the agent sent — the proxy **launders the
exact tampering A2 exists to detect**. Byte-fidelity is what makes a message hash mean
anything. This elevates "don't re-serialize" from a quality preference to a correctness
requirement of the moat.

---

## 3. Guardrail check (`CAPABILITY_ROADMAP.md:407-425`)

| Guardrail | C1 status |
|---|---|
| No agent framework | ✅ The proxy never spawns/drives/prompts the agent. **Watch:** a "run the agent for you" convenience wrapper is the drift. |
| No bare LLM judge | ✅ Trivially — zero model calls in C1. |
| UNVERIFIED never PASS | ✅ C1 emits no status, but **must record the named causes** downstream axes cite. |
| No raw-data egress | ✅ Local-only writes. No telemetry, no phone-home, no default remote sink. |
| Better as models improve | ✅ Neutral. |
| Test-first | ✅ The four acceptance bullets become failing tests first. |
| Never claim coverage we don't have | ⚠️ **R6.** C1 cannot retire it, only make it measurable. |

**No guardrail violation found.** The work is squarely harness-side.

---

## 4. Contradictions and ambiguities — flagged, not papered over

### 4.1 🔴 "session start" is about to stop existing (13 days)

`CAPABILITY_ROADMAP.md:76` — annotations *"snapshotted from `tools/list` at **session
start**."*

**Verified:** the current spec revision is **2025-11-25**. A **2026-07-28** revision is
locked (2026-05-21) and **ships 2026-07-28 — 13 days from today (2026-07-15)**. It removes
the `initialize`/`initialized` handshake (SEP-2575) **and the `Mcp-Session-Id` header and
protocol-level session** (SEP-2567). Protocol version, client info, and capabilities move
into `_meta` **on every request**; a new `server/discover` fetches capabilities on demand.

**Consequence:** "session start" is a concept with 13 days to live. The trace must treat
session context as **derived**, reconstructable either from a handshake (≤2025-11-25) or from
per-request `_meta` (≥2026-07-28). **Record resolved fields (protocol version, client
identity) per-call rather than pointing at a session-header record.** Cheap now, expensive
later.

**This is a genuine roadmap-vs-reality contradiction**, not a nitpick. The roadmap was written
against a protocol assumption that expires inside C1's own build window.

### 4.2 🔴 Annotation defaults are NOT uniformly false — and absent ≠ false

The roadmap treats annotations as a clean free contract. The spec is messier. **Verified
verbatim from `schema/2025-11-25/schema.ts`:**

| Field | Default when ABSENT |
|---|---|
| `readOnlyHint` | `false` |
| `destructiveHint` | **`true`** |
| `idempotentHint` | `false` |
| `openWorldHint` | **`true`** |

The defaults are **fail-safe** (absent ⇒ assume mutating, destructive, non-idempotent,
open-world), which *aligns* with C4's *"an absent contract is not a permissive one"*
(`:193-194`). But the **tri-state is still mandatory**, for a subtler reason than "defaults
are wrong":

> A tool with no annotations, defaulted to `readOnlyHint: false`, would let effect-conformance
> reason *"it mutated, and it never claimed read-only, therefore fine → PASS."* That is a
> **false PASS manufactured by a default**. C4 requires **UNVERIFIED** for an un-annotated
> tool (`:205-206`). Only a tri-state (`declared-true` / `declared-false` / `not-declared`)
> can express the difference between *"declared permissive"* and *"declared nothing."*

Also: `destructiveHint`/`idempotentHint` are **only meaningful when `readOnlyHint == false`**.
A tool declaring `readOnlyHint: true, destructiveHint: true` is **incoherent** — and that
incoherence is itself a recordable signal.

### 4.3 🔴 Annotations are *hints*, and `CLAUDE.md`'s framing over-claims

**Verified verbatim** from `schema.ts`:

> *"NOTE: all properties in ToolAnnotations are **hints**. They are not guaranteed to provide
> a faithful description of tool behavior... Clients should never make tool use decisions
> based on ToolAnnotations received from untrusted servers."*

And from the tools spec page:

> *"For trust & safety and security, clients **MUST** consider tool annotations to be
> untrusted unless they come from trusted servers."*

`CLAUDE.md:113-116` calls a `readOnlyHint: true` tool that mutates *"a grounded FAIL with zero
LLM involvement."* **The wire semantics support the check, but not the framing.** It is not
"the tool violated the protocol" — it is *"the server's **self-declared** contract does not
match observed behavior."*

Still a real, grounded, LLM-free A1 signal, and a valuable one — but it catches
**honest-but-buggy** servers, a large class. It gives **nothing against an adversarial
server**, which simply omits the annotation (inheriting fail-safe defaults) or lies in the
safe direction. **Frame as "contract conformance," not "protocol violation."** User-declared
invariants remain the load-bearing A1 mechanism; annotations are a zero-config supplement.
This should be corrected in `CLAUDE.md` (a doc fix, out of C1's code scope).

### 4.4 🟡 "Behavior-neutral" vs. "timing is captured"

`:74-75` demands the agent *"behave exactly as it does without it"*; `:76` captures **timing**.
A proxy unavoidably adds latency. **These cannot both hold in the strong sense.**

Resolution: the acceptance test asserts **byte-identical *responses***, not identical timing
(`:88`). So the operative definition is **content-neutrality on the wire**; the docs never
claim latency-neutrality. Therefore:
- The C1 test **must not** assert timing equivalence — that would assert something false.
- Recorded timing is **proxy-observed** and includes proxy overhead. A bare `duration_ms`
  meaning "server time plus however long Belay took" is a small over-claim, and G7
  (`:424-425`) exists against exactly that genre. **Record the observation point, or record
  inbound+outbound timestamps and let readers compute.**
- **Timing must live outside the hashed content**, or *"hashes are stable across two identical
  runs"* (`:88`) can never pass. Schema-layout requirement, not an implementation detail.
- Client timeouts are real and our latency is inside them. Hashing/disk writes must be **off
  the forwarding path**.

### 4.5 🟡 "Lossless" vs. content-addressing — needs an explicit decision

Hashing is additive, so `:78` and `:82` don't conflict outright. **But a hash is only
opinion-free if taken over the bytes as received.** Canonicalizing first (sorting keys,
normalizing unicode) encodes an opinion about what differences don't matter — and C4's
result-equivalence *inherits that opinion as its definition of divergence*. Meanwhile `:88`
demands **stable hashes across two identical runs**, and raw-byte hashes of a server with
nondeterministic key order are unstable.

**Proposed resolution:** store **raw bytes**, hash **both** the raw bytes and a *documented,
versioned* canonical form. Losslessness survives; the opinion is explicit rather than silent;
C4 diffs raw while C6 compares canonical. **What must never happen:** canonicalize → hash →
discard the original. That is lossy and silently defines away a class of divergence C4 exists
to catch. **Open question for the PRD — must be decided, not defaulted.**

### 4.6 🟡 Where does the trace go? Four gitignored dirs, no spec

`.gitignore:16-21` is the **only** artifact-layout statement in the repo:
```
/traces/
/runs/
/_sandbox/
/corpus/local/
```
`_sandbox/` is C2's, `corpus/local/` is C6's. **Nothing says whether C1 writes to `/traces/`
or `/runs/`, and they overlap conceptually.** C2/C3/C6 all resolve paths against this choice.
Must be **picked and stated**, not absorbed by convention. Also: these are repo-root defaults,
so C1 writes engine artifacts inside the source checkout by default — fine for the no-egress
guardrail, but the Phase-0 corpus (≥50 SWE-bench-lite runs, `ROADMAP.md:103`) will not want to
live there. **A configurable artifact root is worth having on day 1.**

### 4.7 🟡 "Versioned schema on day 1" is under-tested by its own acceptance

`:91` requires only *"A trace written by version N is readable by version N."* That is a
**round-trip test, not a compatibility test** — a format could carry a version field nothing
ever reads and still pass. The real test arrives at C2 (which appends new record types).
Ship the version field and a **documented rule for unknown record types / higher versions**;
do **not** build a migration framework in week 1.

### 4.8 🟡 The single-snapshot assumption

`:76` says annotations are snapshotted **once**. MCP servers may change their tool list
mid-session via `notifications/tools/list_changed`. **Cache once and you verify against a
stale contract** — C4's effect-conformance and C5's inferred invariants would inherit the
staleness. Record *when* the snapshot was taken; allow a later snapshot as an **appended
record**. Small hole, cheap to leave room for, lands squarely on "an absent contract is not a
permissive one."

### 4.9 🟢 Brief vs. files — one correction

The brief says *"fixtures and the eventual corpus must use off-the-shelf MCP filesystem +
shell servers."* `ROADMAP.md:41` says this of **demos and the Phase-0 corpus**, not of C1's
unit fixtures — and `:91` requires C1's tests be **deterministic, no network**. **Off-the-shelf
servers are the Phase-0 corpus substrate; C1's acceptance tests use fake, in-repo servers.**
Conflating them would put third-party servers in CI.

---

## 5. Architecture consequences (evidence-backed)

### 5.1 The SDK cannot be on the forwarding path — verified in source

| | `mcp` 1.28.1 (current stable) | `mcp` 2.0.0b2 (beta, stable targeted 2026-07-27) |
|---|---|---|
| Emit | `model_dump_json(by_alias=True, **exclude_none=True**)` | `model_dump_json(by_alias=True, **exclude_unset=True**)` |
| `extra` on JSONRPC envelopes | `allow` | **`None`** → unknown top-level fields **dropped** |
| Failure mode | drops explicit nulls (`{"params":null}` → gone) | drops unknown fields |

**v1 and v2 are unfaithful in different, incompatible ways.** Neither can carry a byte-identity
claim. Additionally v1 normalizes key order and escapes non-ASCII (`"café"` → `"café"`),
and v1 hard-fails on batch arrays with ValidationError.

**Decision: hybrid.** Forward the **original buffer**; parse a **copy** to a dict for
routing/trace-indexing, off the hot path. The apparent tension (byte-identity vs. parsing)
dissolves — *parsing-to-read* and *parsing-to-re-emit* are different operations. **Never
forward the parse output.** This also absorbs the 2026-07-28 migration at near-zero cost
(`_meta`-per-request rides through as an opaque dict inside `params`), whereas an SDK-typed
proxy inherits whichever failure mode its pinned version has.

### 5.2 stdio only for v0

Newline-delimited JSON-RPC, UTF-8, **no Content-Length framing** (MCP diverges from LSP here).
Server MUST NOT write non-MCP to stdout; **stderr is for all logging and MUST NOT be read as
failure** — forward it, don't swallow it. Streamable HTTP adds SSE, session headers,
resumability, and OAuth — all materially harder to proxy neutrally, and stdio is the actual
demo surface (Claude Code / Cursor local servers).

### 5.3 Full-duplex pump, not a request/response state machine

**The most likely way a naive C1 breaks under a real agent.** MCP is bidirectional: servers
originate requests (`sampling/createMessage`, `roots/list`, `elicitation/create`, `ping`). A
"read request → forward → read response → forward" loop **deadlocks or drops** the moment a
server initiates. Model as **two independent async pumps, message-type-agnostic**. Corollary:
**two independent id spaces** (client-originated and server-originated ids may both start at 1
and collide) → **correlate on `(direction, id)`**, never bare id. Responses carry no `method`,
so correlation must be by id.

### 5.4 Forward everything, police nothing

Progress notifications reset client timeout clocks — **buffering them can cause timeouts on
calls that would otherwise succeed**; forward immediately, unbuffered. Cancellation is racy by
design: some requests **legitimately never get a response**, so the trace writer must not leak
entries or block awaiting one. Batch arrays are invalid ≥2025-06-18 but **forward them anyway**
and flag as non-conformant — *neutral wins over conformant; our job is to observe the
connection, not police it.* Never rewrite `protocolVersion` (negotiation is a two-message
exchange between client and server; a pass-through proxy is safe **precisely because** it
doesn't participate — read the negotiated version, forward the bytes untouched). Adding
anything to `_meta` breaks byte-neutrality → keep correlation in our own side-table.

---

## 6. Competitive reality (changes the emphasis, not the plan)

- **`mcpsnoop`** (Go, 267★, created 2026-06-27) **already claims byte-verbatim forwarding** —
  the contract we assumed was unclaimed. It has **no verdict layer**; its "replay" is a TUI
  call-level re-invoke. *(README-derived, source unaudited.)*
- **Nothing in Python occupies our slot.** `mcp-recorder` (0.5.0, 9★) is explicitly
  protocol-level, not byte-level. `mcp-rec` (0.1.0, 1★) abandoned. `mcp-vcr` 0.1.3 (2026-07-01)
  — **unverified, no repo link; worth 10 minutes to inspect.**
- **Nobody verifies.** Every surveyed project stops at record + *response*-diff. **Zero
  re-execute-in-sandbox-and-diff-world-state. A1/A2 is unoccupied.**
- **mitmproxy names our problem:** *client-replay* (re-send to the live server) **is A2**;
  *server-replay* (serve recorded responses to a live client) is a **mock** and can never
  produce a verdict. **Every MCP tool surveyed ships server-replay and calls it "replay."**
  → Belay must name A2 distinctly or be read as another mock server.
- **Also from mitmproxy:** its addon hooks are **synchronous mutation points on the hot path**
  — a design C1 should explicitly reject. Behavior-neutrality means the capture branch must be
  **structurally unable** to alter or block forwarded bytes.

**Implication:** the capture surface **will commoditize** (267★ in three weeks). This *confirms*
rather than threatens the thesis — `CLAUDE.md` already says the moat is the verdict + corpus.
It does raise the cost of over-investing in capture polish. C1 should be **correct, small, and
finished**, then move to C2.

---

## 7. Open questions for the PRD

1. **Hashing:** raw-only, canonical-only, or both? (§4.5 — recommend both, canonical form
   documented + versioned.)
2. **Artifact root:** `/traces/` or `/runs/`? Configurable root on day 1? (§4.6)
3. **Trace granularity:** one record per turn, or a growing set of append-only records keyed by
   turn id? (Append-only + C2's denials + C3's nondeterminism marks + C6's *sliceable* cases all
   argue for the latter.)
4. **Session context:** commit now to per-call resolved fields to absorb 2026-07-28? (§4.1 —
   recommend yes.)
5. **Timing:** single `duration_ms`, or inbound+outbound timestamps? (§4.4 — recommend the
   latter, plus an explicit observation-point field.)
6. **Scope of "capture":** every message, or only `tools/call`? The roadmap says *"Capture per
   `tools/call`"* (`:76`) but neutrality requires pumping **everything**. Recommend: **record
   all frames** (JSONL, one frame per line), and treat `tools/call` as a **derived index** over
   them. Costs nothing, and C9's OTel correlation + C2's denials need the other frames anyway.
7. **`--no-claim-axis` etc. are not C1's** — confirm no CLI surface beyond what C1 needs.

---

## Verification log (what I checked myself, not via agent)

| Claim | Method | Result |
|---|---|---|
| Current spec revision = 2025-11-25 | WebFetch `modelcontextprotocol.io/specification/versioning` | ✅ verbatim: *"The **current** protocol version is 2025-11-25"* |
| 2026-07-28 RC removes initialize + session | WebFetch official MCP blog RC post + WebSearch corroboration | ✅ locked 2026-05-21, ships 2026-07-28, SEP-2575 / SEP-2567 |
| Annotation defaults + hints/untrusted note | WebFetch `schema/2025-11-25/schema.ts` | ✅ verbatim; `destructiveHint`/`openWorldHint` default **true** |
| SDK re-serializes | Read installed source | ✅ v1 1.28.1 `stdio/__init__.py:155,172`; v2 2.0.0b2 `client/stdio.py:174` |
| v1/v2 `extra` divergence | Introspected `model_config` in both venvs | ✅ v1 `allow` (all 4 envelopes); v2 `None` (types moved to `mcp_types` 2.0.0b2) |
| Differential test works | Ran the suite | ✅ 4 passed in 0.40s |
| `.gitignore` artifact dirs | Read file | ✅ lines 16–21 as quoted |
| No GitHub issues/PRs | `gh issue list` / `gh pr list` | ✅ both empty |

**Not verified (flagged, not guessed):**
- `mcpsnoop` / `mcp-recorder` transport + transparency claims are **README-derived, source
  unaudited**; `mcpsnoop`'s version is unverified.
- `mcp-vcr` 0.1.3 — **contents uninspected, no repo URL.** The one unresolved unknown.
- Real-world annotation adoption rates beyond `server-everything` (13/13 annotated) — **not
  surveyed**. Do not build the demo around annotation-derived checks until measured.
- The 2026-07-28 **spec text** itself was not fetched (only the RC blog post + SDK betas). The
  *fact* of the pivot and the date are solid; the replacement mechanism's exact shape is
  directionally right but **not quotable**.
- Wider gateway landscape (Docker MCP Gateway, mcp-context-forge, Lasso, mcp-guardian) —
  **unresearched.**
