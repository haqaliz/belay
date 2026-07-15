# Belay trace format v1

The interchange format for the whole engine. C2 (sandbox), C3 (replay), C4 (verdict),
C6 (corpus) and C9 (OTel interop) all read what the proxy writes here, which is why every
record carries `v` from the first line ever written. **This format is versioned on day one
because it cannot be quietly changed later.**

> ### ⚠️ A trace is as sensitive as the agent's most sensitive tool argument
>
> Capture is verbatim and total. API keys, tokens, file contents and customer data cross the
> MCP boundary as tool arguments and results, and land in `raw` in **fully recoverable** form.
>
> Trace files are created owner-only (`0600`). There is deliberately **no redaction and no
> secret scanning**: both are opinions, capture is opinion-free, and a redacted trace cannot
> be replayed — which would defeat the only reason the trace exists. Treat a trace file as
> the credential it may contain.

---

## Physical format

One JSON object per line, UTF-8, newline-terminated: **JSONL, append-only**. Append-only is
what makes the file safe to read while a run is still in progress, and it means a reader
never has to trust a record it has not finished reading.

Written only when **`BELAY_TRACE_DIR`** is set. Unset, the proxy runs with no observer at
all and no file is created.

- The directory is created `0700` **if Belay creates it**. A pre-existing directory is left
  exactly as the operator configured it — Belay will not silently tighten (or loosen)
  permissions on a directory it does not own, because `BELAY_TRACE_DIR` may point at a
  shared or system path. The `0600` on the file is the guarantee that actually protects the
  contents.
- The file is created with `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)`. `O_EXCL` so
  we never adopt a file someone else made; the mode passed to `open` rather than a later
  `chmod` so there is no window in which the trace exists and is world-readable.

## The `frame` record

```jsonc
{
  "v": 1,                          // schema version
  "kind": "frame",                 // extensible; C2 appends "denial", C3 "nondeterminism"
  "seq": 4,                        // monotonic, capture-order, per-trace, across BOTH directions
  "dir": "c2s",                    // "c2s" (client->server) | "s2c" (server->client)
  "raw": "<base64 of the exact bytes>",
  "hash_raw": "sha256:...",        // over the bytes AS RECEIVED
  "hash_canonical": "sha256:...",  // over the canonical form; null if not valid JSON
  "canonical_form": "belay/jcs-v1",// null exactly when hash_canonical is null
  "t_in": "2026-07-15T12:53:16.684896+00:00",  // ISO-8601 UTC, proxy-observed
  "observation_point": "proxy",    // never implies server-side timing
  "truncated": false,              // the OBSERVED copy exceeded MAX_FRAME (16 MiB)
  "state_handle": {"status": "absent"}
}
```

### Why each field is the way it is

**`raw` is base64, not a JSON string.** A non-conforming server can emit bytes that are not
valid UTF-8 and therefore *cannot* be a JSON string at all. Those must be recorded honestly
rather than crash the writer or be coerced into something prettier. base64 round-trips
unconditionally. Human-readable rendering is the console's job, not the recorder's.

**Both hashes are stored; the original is never discarded.** Canonicalise → hash → discard
is lossy in exactly the direction that matters: the difference between the raw bytes and
their canonical form *is itself* a class of divergence the replay verdict exists to catch,
and a trace that threw it away cannot be asked about it later.

- `hash_raw` — identity of the octets. Never wrong, but too strict to compare across peers:
  two servers can send semantically identical JSON with different key order and disagree.
- `hash_canonical` — survives re-ordering, so it is the hash that can say *"the replay
  produced the same message"*. It is also the weaker claim, because canonicalisation
  necessarily discards.

**Timing lives outside the hashed content.** Neither hash is computed over `t_in` or any
other envelope field — only over frame content. This is a schema-layout requirement, not an
implementation detail: if timing fed a hash, two identical runs could never agree, and
"the replay produced the same bytes" would stop being expressible at all.

**`observation_point` is mandatory and always `"proxy"`.** Our timing includes our own
overhead. `t_in` is when *Belay* saw the frame — not when the server sent it, which we
cannot know. A field that silently meant "server time" would be a small lie, and this
project does not ship small lies.

**`truncated` describes the copy, never the wire.** The observed copy is bounded at
`MAX_FRAME` (16 MiB); the forwarded bytes are never bounded, truncated, or delayed. So
`truncated: true` means *we* recorded less than crossed the wire, and the frame's `raw` is
therefore incomplete — a fact a reader must not mistake for the client having received less.

**`seq` is one sequence across both directions.** Allocated under the same lock as the
append, so it is a total order in capture order — not two interleaved sequences a reader
must reconcile. The two streams are independent, so ordering *between* directions means only
"when the proxy saw it", which is exactly what `observation_point` already says out loud.

### `state_handle` is three-state, and C2 fills it

`{"status": "absent"}` is still the default and still means exactly one thing: **no snapshot
was attempted**. C2 supplies the other two, via `TraceWriter.set_state_handle`:

```jsonc
// a snapshot exists and restores — and names what it could NOT preserve
{"status": "present", "handle": "9f2c…", "backend": "clonefile-apfs",
 "capabilities": ["acls", "clonefile", "dir-mtimes", "hardlinks", "special-modes"],
 "fidelity_gaps": ["UNRESTORABLE_ATIME", "UNRESTORABLE_CTIME",
                   "UNRESTORABLE_BIRTHTIME", "UNRESTORABLE_INODE_IDENTITY"]}

// we tried and could not, with a named cause and the entry that caused it
{"status": "unrestorable", "cause": "UNRESTORABLE_FIFO", "detail": "…",
 "source": "lstat", "path": "pipe"}
```

`present` **declares its own gaps** rather than implying none. atime, ctime, birthtime and
inode identity are unrestorable by anyone — BTH-1 excludes them and says why — so a bare
`present` would claim a fidelity the snapshot does not have.

The writer validates the slot but does not interpret it: it enforces that `status` is one of
the three and that `unrestorable` always names a `cause` (an unnamed refusal is
indistinguishable downstream from a shrug), while the meaning of each cause stays in
`belay.snapshot.substrate`. **These are facts, not verdicts.** C4 is what turns
`unrestorable` into UNVERIFIED; C2 never renders one.

The slot was reserved from the first line of trace ever written, on purpose. If it could only
express present/absent, C2 would have to overload `"absent"` to mean both *"recorded before
snapshots existed"* and *"we tried to snapshot and failed"*. A replay that cannot tell those
two apart is how a false PASS gets born.
`tests/test_substrate.py::test_absent_is_not_repurposed` holds that distinction open.

#### Whose handle is it — read this before grounding anything on the slot

The guarantee is **per direction and per frame kind**, and the difference is load-bearing:

- On a **`tools/call` frame (`dir: "c2s"`)** the handle is **that turn's own**, pinned to
  those exact bytes when the turn was gated. This is the one C4 reads and the only one that
  means *"the state this call was about to execute against"*. It is pinned by content hash
  rather than by arrival order, because the pump forwards a whole chunk before observing any
  of it: when one chunk carries two gated frames, both handles are set before either frame is
  recorded, and an order-based match would silently shift every handle by one.
  (`test_a_batched_write_resolves_each_tools_call_to_its_own_pre_state`.)
- On **any other frame** the handle is whichever was current when the frame was recorded. On a
  batched write that can be a *later* frame's. It means *"this was current when the frame was
  recorded"*, never *"this frame crossed after it"*. Do not ground a verdict on it.

A `tools/call` that ran **concurrently with another** carries
`{"status": "unrestorable", "cause": "UNRESTORABLE_CONCURRENT_TURN", "source": "turn-gate"}`.
That is not a snapshot failure — nothing broke. It says the turn overlapped another, so no
pre-state of it ever existed to capture. It is the common case for a batching client, and
C4 must render it UNVERIFIED rather than treat it as a missing file.

## The `connection_window` record

```jsonc
{
  "v": 1,
  "kind": "connection_window",
  "phase": "open",                 // "open" | "close"
  "seq": 0,
  "t_in": "...",
  "observation_point": "proxy"
}
```

Written by the proxy at both ends of a run: `open` is the first record in the file, `close`
the last. This is **the only statement in the trace about the period Belay was listening**,
and the frames cannot supply it — the first frame is when the *agent* first spoke, which is
not when the proxy went live, and the two are different claims.

**`close` means "we observed everything up to here", and that is load-bearing.** The proxy
stops observation *before* the writer closes, and waits for any observation already in
flight, so no frame can be observed into a closed trace. Without that, a client still
writing while the server exits could have a frame land after the fd was gone: it would
vanish, leaving a matched `open`/`close` pair and **no `capture_error`** — a trace that
reads as a complete capture and is not. `close` is therefore the last record in the file
by construction, never merely by luck of timing; no frame may carry a higher `seq`.

Bytes the client sends *after* `close` are forwarded but not recorded, and that is not a
gap: the window states where observation ended, which is precisely the honest claim.

> ### Why `connection_window` and not `session_window`
>
> **Read this before "fixing" the name.** A session is a thing the protocol says does not
> exist. The 2026-07-28 revision states it verbatim:
>
> > "an open connection, such as a STDIO process, is **not** a conversation or session:
> > clients may interleave unrelated requests on the same transport, and a server must not
> > treat connection or process identity as a proxy for conversation or session continuity."
>
> and makes MCP explicitly stateless: *"all the information needed to process a request is
> contained in the request itself... no state should be inferred from previous requests, even
> those on the same connection or stream."*
>
> What these two records bracket is **one open pipe to one server process** — nothing more.
> Calling it a session would claim a continuity the spec refuses to grant, in a format that
> cannot be quietly changed later. **The reason is the point, not the label.**

It exists because "what share of what the agent did crossed the MCP boundary?" needs a
denominator. The agent's built-in tools (Claude Code's `Bash`/`Edit`) never traverse MCP, so
this window is the honest bound on what Belay could have seen at all.

**An `open` with no `close` is expected and honest**: the proxy was killed. The window's end
is then genuinely unknown, and a reader must not substitute the last frame's `t_in` for it.

## The `capture_error` record

```jsonc
{
  "v": 1,
  "kind": "capture_error",
  "seq": 12,                       // the point in capture order at which the direction went dark
  "dir": "s2c",
  "cause": "ValueError: disk on fire",
  "t_in": "...",
  "observation_point": "proxy"
}
```

Forwarding survives an observer that raises. **Observation does not, and must not pretend
otherwise.** Without this record the trace would simply end early *while looking complete* —
a false-completeness claim, and precisely the failure this product exists to catch.

Its `seq` is the point at which that direction stopped being observed. Frames after it, in
that direction, are **absent from the trace but did cross the wire**. The UNVERIFIED
contract's "named cause" originates here: a reader that sees a `capture_error` must not
report anything downstream of it in that direction as verified.

If the *writer itself* is what failed, the error is not written twice — it degrades to
stderr. Forwarding is never affected by any of this.

Three things raise a `capture_error`, and the last two are not observer bugs — they are
bytes Belay took custody of and could not record:

| `cause` names | What happened |
|---|---|
| an observer exception | Observation of that direction died. Forwarding continues. |
| `OSError` / `BrokenPipeError` | **Forwarding** failed mid-chunk — the peer is gone. The chunk was already out of the source pipe, so it is observed *before* this is recorded: the bytes existed and the trace says so, then says why delivery stopped. |
| `StreamEndedMidFrame` | The stream ended with an unterminated frame in the reassembly buffer. Those bytes reached the peer; they are **not** recorded as a frame, because a partial frame is not a frame. The cause says how many bytes went unrecorded. |

Mid-stream, an incomplete buffer is not a loss — the rest of the frame is still coming, and
nothing is recorded until a newline arrives. Only at EOF does the same silence become data
loss, which is why only EOF names it.

## `belay/jcs-v1` — the canonical form, and its honest limits

RFC 8785 (JSON Canonicalization Scheme) **semantics**: sorted keys, no insignificant
whitespace, UTF-8. Implemented as:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

It is a **subset**, and these are its known divergences from RFC 8785. They are named here
rather than discovered later:

- **Numbers are not canonicalised.** RFC 8785 requires every number be serialised as an
  ECMAScript double. We emit Python's repr, so a large integer keeps precision an RFC 8785
  implementation would round away, and some exponent forms differ. **Two Belay traces agree
  with each other; a Belay hash and a third-party RFC 8785 hash may not.**
- **Keys sort by Unicode code point, not UTF-16 code unit.** The two agree for every key in
  the Basic Multilingual Plane, and disagree only when a key contains an astral character
  (U+10000 and above), which RFC 8785 sorts by its surrogate pair.
- **Non-finite numbers are accepted.** `NaN` and `Infinity` are not JSON at all, but
  Python's parser takes them and the proxy does not police the wire.
- **Duplicate object keys collapse** to the last occurrence. RFC 8785 leaves this undefined.

Every one of these is a reason `hash_raw` is stored too — it has none of these caveats.

**When the frame is not valid JSON** — including when it is not valid UTF-8 —
`hash_canonical` and `canonical_form` are both `null`. They are null together, always: a
canonical hash with no named form is unverifiable, and a form naming a hash that does not
exist is a claim about bytes we could not parse. An absent canonical form is honest; a
fabricated one is not.

## The unknown-kind rule (required of every reader)

A reader that encounters an **unknown `kind`**, or a **`v` higher than it understands**,
must:

1. **Skip the record**, and
2. **Record that it skipped it.**

Never silently drop it — that is a false-completeness claim, the same category as a silent
capture error. Never crash — an old reader must survive a new writer.

There is deliberately **no migration framework**. Version 1 is `v: 1`; a future version will
say so, and this rule is what makes that safe.

---

# Derived records

Everything below is a **derived index**: a view computed by *reading* a trace, never written
by the proxy and never mixed into the capture path. The modules are `belay.index`,
`belay.annotations`, `belay.connection` and `belay.errors`.

Two properties hold across all of them.

**They never mutate a frame.** Correlation lives in a side table, not in the frame's `_meta`.
Writing into a frame would break the byte-neutrality the differential gate exists to protect
and would make the trace something Belay edited rather than something Belay observed. The
replay engine is entitled to assume the frames are exactly the bytes that crossed the wire.

**They are recomputable.** Every one of them is a function of bytes the trace already holds,
so a bug here is fixed by re-deriving, not by a migration. This is why classification is
derived rather than decided at capture time and baked in — see the error records below,
where the protocol has already moved the line once.

**And still no verdict.** C1 records; it does not judge. Nothing in this format expresses
whether anything was good, bad, or allowed.

## Tri-state: how a declared flag is recorded

**A default is not a declaration.** This is the single most important encoding rule in the
format, and it applies to tool annotations and to `isError` alike.

The MCP spec supplies a value when the wire omits one — annotations default to
`readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: false`, `openWorldHint:
true`, and an absent `isError` is *assumed* false. Those defaults are correct for deciding
how to **treat** a message and wrong to **record**, because they erase the difference between
*the peer said false* and *the peer said nothing*.

Concretely: an un-annotated tool recorded as `readOnlyHint: false` licenses a downstream
check to reason *"it mutated, and it never claimed read-only, therefore fine → PASS"*. The
tool declared nothing; the only honest verdict is **UNVERIFIED**; the PASS was manufactured
by a default. So every such flag is recorded as one of:

| `state` | Means |
|---|---|
| `declared-true` | the wire carried `true` |
| `declared-false` | the wire carried `false` |
| `not-declared` | the key was **absent**. Not `false`. **Never a default.** |
| `declared-non-boolean` | present, but not a boolean (a third-party server sent `"yes"`, or `null`). The raw value rides along in `declared_value`. |

**No spec default appears anywhere in `src/belay`** — not even as a constant. There is
deliberately nothing there for a future edit to reach for.

## `correlation` and `index_gap` (`belay.index`)

```jsonc
{
  "kind": "correlation",
  "origin": "c2s",                 // the direction the REQUEST travelled: its id SPACE
  "id": 1,
  "method": "initialize",          // from the request; responses carry no method
  "request_seq": 1,
  "response_seq": 5,               // null when unanswered
  "status": "answered"             // "answered" | "unanswered" | "response-without-request"
}
```

**Keyed on `(direction, id)`, never the bare id.** MCP is full-duplex: a server originates
requests of its own, in **its own id namespace**, which legitimately starts at 1 — exactly
where the client's starts. `id:1` therefore routinely exists twice in one connection meaning two
different things, and a bare-id table silently answers questions about one with the other.

**Classification is structural, never by method.** `result`/`error` present ⇒ response;
`method` + `id` ⇒ request; `method`, no `id` ⇒ notification. Responses carry no `method` to
key on, and a non-conforming server that stamps `method` onto a response (one exists in this
repo's fixtures) would fool a classifier that looked for it.

**`unanswered` is not an error.** Cancellation is racy by design, so a request that never
gets a response is legal; it is recorded as unanswered rather than waited on. Nothing blocks
and nothing leaks. `response-without-request` is the mirror image: the proxy attached
mid-connection and the request predates capture.

`tools/call` is **a filter over these entries**, not a unit of capture (`belay.index.tool_calls`).

**`duplicate-response`: a request does not own exactly one response.** A second reply to an
id already answered is **appended as its own entry**, never written over the first —
overwriting would leave the trace asserting a reply that did not happen while silently losing
one that did.

> **There is a second correlation model, deliberately not built: MRTR (SEP-2322).** The
> 2026-07-28 revision removes server-originated requests entirely. A server needing input
> returns `resultType: "input_required"` with `inputRequests`, and **the client retries the
> original request under a NEW request id** carrying `inputResponses`. Correlating that is a
> *retry chain*, not a pairing — a different problem, not this one with a flag.
> `(direction, id)` is a **strict superset** that survives both worlds, so it stays. No RC
> servers exist yet: naming the fork costs a paragraph, guessing at it costs a format version.

```jsonc
{ "kind": "index_gap", "seq": 7, "dir": "c2s", "cause": "truncated: ..." }
```

A frame that could not be indexed — truncated observation, unparseable bytes, an unknown
shape. **Named, never silently indexed as absent**: "there was no request" and "we could not
read the request" are different facts, and a reader that conflates them reports the second as
the first. This is where the UNVERIFIED contract's *named cause* originates.

## `annotation_snapshot`, `annotation_staleness`, `annotation_gap` (`belay.annotations`)

```jsonc
{
  "kind": "annotation_snapshot",
  "source_seq": 6,                 // the tools/list RESPONSE frame
  "t_snapshot": "...",             // when Belay OBSERVED the contract
  "tools": [
    {
      "name": "mystery",
      "annotations_object": "absent",   // "present" | "absent" - carried no `annotations` at all
      "annotations": {
        "readOnlyHint":    {"state": "not-declared"},
        "destructiveHint": {"state": "not-declared"},
        "idempotentHint":  {"state": "not-declared"},
        "openWorldHint":   {"state": "not-declared"}
      },
      "incoherence": []
    }
  ]
}
```

**Snapshots are appended and timestamped, never overwritten.** A server may change its tools
mid-connection and say so with `notifications/tools/list_changed`; a single snapshot would
verify every later call against a stale contract. Each snapshot keeps its own time so *"which
contract was live when that call happened?"* stays answerable.

`incoherence` records, without resolving it, that a tool declared `destructiveHint` or
`idempotentHint` alongside `readOnlyHint: true` — which the spec makes meaningless
("meaningful only when `readOnlyHint == false`"). Both declarations survive verbatim.
**Recording the contradiction is C1's job; adjudicating it is not.**

```jsonc
{ "kind": "annotation_staleness", "seq": 7, "cause": "notifications/tools/list_changed observed; no later tools/list ..." }
{ "kind": "annotation_gap", "seq": 4, "tool": "rm", "cause": "no tools/list response was captured before this call ..." }
```

`annotation_gap` is the answer to *"`tools/list` never arrived"*: the annotations are
`not-declared` **with a named cause**, so downstream can tell "the server declined to say"
from "we never asked".

## `connection_context` (`belay.connection`)

```jsonc
{
  "kind": "connection_context",
  "seq": 8,
  "protocol_version": {"status": "resolved", "value": "2025-11-25", "source": "handshake"},
  "client": {"status": "resolved", "value": {"name": "t", "version": "1"}, "source": "handshake"}
}
```

One per frame — **resolved onto the frame, not a pointer to a header**. That looks
like redundancy and is insurance: the **2026-07-28** revision deletes the thing a pointer
would point at. It removes the `initialize`/`initialized` handshake (SEP-2575) and the
protocol-level session and `Mcp-Session-Id` (SEP-2567), moving version, client identity and
capabilities into `_meta` on **every request**. A trace whose context lived in a header would
go blank the day a client updates.

Resolution order, never departed from:

1. **the `initialize` handshake**, if captured — `source: "handshake"`. The version is the
   server's **negotiated** choice from the initialize *response*, not the client's proposal.
2. **per-request `_meta`** — `source: "request_meta"`, with `source_key` naming the exact key
   that matched. The normative 2026-07-28 keys are
   `io.modelcontextprotocol/protocolVersion` and `io.modelcontextprotocol/clientInfo`, and
   **only** those are recognised: resolving context out of a key no revision defines would be
   a fabrication. A response inherits the context of the request it answers, via correlation.
3. **`{"status": "unknown", "cause": "..."}`** — never a guess. There is no `value` key at all.

**A negotiated version is not applied to frames that precede the negotiation.** Frames before
the initialize response resolve to `unknown` with a cause. Back-dating would be the cheap kind
of lie: locally harmless, and it destroys the trace's ability to say when the contract took
effect.

When `_meta` is present but carries no recognised key, the cause **names the keys it did
carry**. If Belay's idea of the key names is ever wrong, that surfaces as a loud named gap
rather than as a client that appears to have declared nothing.

## `trace_context` (`belay.connection`)

```jsonc
{
  "kind": "trace_context",
  "seq": 3,
  "traceparent": "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01",
  "tracestate": "vendor=opaque",   // only the keys that were actually present
  "baggage": "key=value"
}
```

`traceparent` / `tracestate` / `baggage` are reserved in `_meta` as an **explicit exception to
the reverse-DNS prefix rule**, for W3C Trace Context / OpenTelemetry propagation — trace
context is becoming protocol-native rather than a bolt-on, which is the ground C9 (OTel
interop) stands on.

**Recorded verbatim and interpreted not at all.** Stitching spans, joining to a parent trace,
or deciding what any of it means is the OTel bridge's job. C1's entire duty here is to not
lose it. Emitted only when at least one key is present: a record per frame announcing "no
trace context" would be noise, not a fact.

## Explicitly not recorded

`io.modelcontextprotocol/clientCapabilities` — REQUIRED on every RC client request, and
resolvable exactly like the other two. Not recorded because nothing downstream asks for it
yet and the brief scoped connection context to version + client identity. It is a
five-line addition to `belay.connection` when a consumer appears.

## `error_classification` and `classification_gap` (`belay.errors`)

```jsonc
{
  "kind": "error_classification",
  "seq": 8,
  "id": 3,
  "method": "tools/call",          // via correlation; the response itself carries none
  "protocol_error": {"status": "absent"},   // or {"status":"present","code":-32602,"message":"..."}
  "result": "present",             // "present" | "absent"
  "is_error": {"state": "declared-non-boolean", "declared_value": null},
  "result_type": {"status": "not-declared"}, // or {"status":"declared","value":"complete"}
  "structured_content": {"status": "present", "also_serialised_as_text": [0]}
}
```

Two failures that **must never be conflated**:

- **Protocol error** — a JSON-RPC `error` member and **no `result`**. The call did not happen;
  there is no tool output because the tool was never reached.
- **Tool execution error** — a *successful* envelope carrying a `result` whose payload declares
  `isError: true`. The call happened; the tool ran and reported failure from inside.

**The line between them has already moved once.** The 2025-11-25 revision (SEP-1303)
reclassified input-validation failures from the first to the second, to enable model
self-correction. The same underlying failure therefore has different wire shapes across
revisions — which is precisely why the classification is a **derived view over raw bytes we
already keep**, never a rewrite of them. `result` and `protocol_error` are recorded
independently, so a non-conforming server that sends both is visible as what it is.

`is_error` follows the tri-state: **absent ⇒ `not-declared`, not `false`.** The spec *assumes*
false; an assumption is not a declaration.

`protocol_error.code` is recorded **verbatim**, whatever it is. That is what makes the RC's new
grounded, LLM-free codes readable for free when servers start sending them — `-32020`
HeaderMismatch, `-32021` MissingRequiredClientCapability, `-32022` UnsupportedProtocolVersion
(all renumbered within the draft; `-32020`–`-32099` is now reserved for the spec), and
resource-not-found's move from `-32002` to `-32602`. **None of them are special-cased here**:
recording the raw code is what lets a later capability read them without this layer having
taken a view.

`result_type` follows the same discipline as the annotations, for the same reason. The RC
requires every result to carry `resultType` (`"complete"` | `"input_required"`) and requires
clients to *treat* an absent one from an earlier-protocol server as `"complete"`. **That is an
assumption, not a declaration** — every server shipping today omits the field, and
materialising `"complete"` would record all of them as having declared something none of them
said. `"input_required"` is the MRTR shape; it is recorded as a plain fact and the retry chain
is not modelled (see `correlation` above).

`structured_content.also_serialised_as_text` lists the indexes of `content` text blocks whose
text parses to the same JSON as `structuredContent`. Servers SHOULD emit both, so **the same
data commonly crosses the wire twice**; naming the duplication stops a reader counting one
payload as two independent facts. Equality is compared on parsed JSON, not text, because the
text block is the server's own serialisation and may differ in key order.

```jsonc
{ "kind": "classification_gap", "seq": 9, "cause": "unparseable: JSONDecodeError: ..." }
```

A malformed or non-conforming frame is **recorded with a named cause, never a dropped turn** —
and the turns either side of it still classify.

## Explicitly not in v1

No compression, no rotation, no redaction. No MRTR retry-chain correlation (see `correlation`
above: `(direction, id)` is a strict superset and survives, but the chain itself is not
modelled). No `clientCapabilities`. No interpretation of trace context.

---

# Coverage and limits

**What a reader of this format is entitled to conclude, and what it must not.** Everything
below is a property of the capture, so it belongs next to the format rather than only in the
README. These are permanent characteristics of C1, not gaps awaiting a patch.

## The trace covers the MCP boundary. That is not the same as the agent.

An agent's **built-in tools do not traverse MCP**. Claude Code's `Bash` and `Edit` are
in-process calls; they never reach a stdio transport, so nothing on that transport can observe
them. An agent can read a file, run a command, or rewrite a working tree and leave **no record
in this trace at all**.

So a trace answers *"what went over MCP?"* and never *"what did the agent do?"*. The
`connection_window` pair is the only honest denominator available: it bounds the period Belay
was listening, and says nothing about what happened outside the boundary during it. **A
consumer that reports trace coverage as agent coverage is making a claim this format does not
support** — and it is the claim most likely to be made by accident.

## Byte-transparency is proven against a fixture, and corroborated everywhere else

The supported claim, exactly:

> Against a **deterministic fixture**, the proxy is byte-transparent — proven by
> `tests/test_differential.py`, which is itself proven to fail on a re-serialising proxy by
> `tests/test_teeth.py`.

**Not** *"no real server is ever perturbed."* A byte-level differential is **unrunnable**
against a real, nondeterministic server: two runs differ on ids, timestamps and progress
tokens for reasons unrelated to the proxy, so there is no byte-identity to assert. Runs
against real servers are **corroborating evidence, not proof**.

This is why `hash_raw` exists on every frame. The differential proves the proxy does not
perturb the fixture; `hash_raw` is what lets a *later* consumer check any individual frame
against the bytes recorded, without re-running anything.

A real `mcp` SDK client completing a handshake through the proxy
(`tests/test_real_client.py`) is a **compatibility** result and carries no byte-level weight:
its fixture is conforming, so a re-serialising proxy would pass it. The two tests are not
redundant and neither is a stronger version of the other.

## The trace is as sensitive as the agent's most sensitive tool argument

Restated here because it is a property of the format, not advice: capture is verbatim and
total, so API keys, tokens, file contents and customer data land in `raw` **fully
recoverable**. Files are `0600`. There is deliberately **no redaction and no secret scanning**
— both are opinions, capture is opinion-free, and a redacted trace cannot be replayed, which
is the only reason the trace exists. Treat the file as the credential it may contain.

## Nothing in this format is a verdict

**C1 records; it does not judge.** No record here — written or derived — says whether anything
was correct, safe, or permitted. `incoherence`, `index_gap`, `annotation_gap`,
`classification_gap` and `capture_error` name **facts and their absences**, deliberately
stopping short of adjudicating them.

The tri-state encoding exists to keep it that way: recording *"the peer said nothing"* as
`false` would manufacture the licence for a downstream PASS out of a spec default. The value of
this format to a later verdict is precisely that it took no view.

## The revision this was built against

Developed against MCP revision **`2025-11-25`**.

The **`2026-07-28`** revision removes the `initialize`/`initialized` handshake (SEP-2575),
protocol-level sessions and `Mcp-Session-Id` (SEP-2567), and server-initiated requests
(SEP-2322). The capture path forwards bytes and does not model the conversation, so it is not
expected to be affected, and the format anticipates the change where it had to choose (see
`connection_context`'s resolution order and `correlation`'s note on MRTR).

**Anticipated is not tested. Belay does not claim support for `2026-07-28`** — no server
implementing it exists to test against. The design notes above explain why the format should
survive it; they are not evidence that it does.
