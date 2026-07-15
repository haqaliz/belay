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

### `state_handle` is three-state, and empty in v1

Always `{"status": "absent"}` in v1. C2 will add `{"status": "present", ...}` and
`{"status": "unrestorable", "cause": ...}`.

The slot exists now, unused, on purpose. If it could only express present/absent, C2 would
have to overload `"absent"` to mean both *"recorded before snapshots existed"* and *"we
tried to snapshot and failed"*. A replay that cannot tell those two apart is how a false
PASS gets born.

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

## Explicitly not in v1

Correlation / `(direction, id)` indexing and the `tools/call` index (Task 6); annotation
snapshots (Task 7); session context and error classification (Task 8). No compression, no
rotation, no redaction.

**And no verdict.** C1 records; it does not judge. Nothing in this format expresses whether
anything was good, bad, or allowed.
