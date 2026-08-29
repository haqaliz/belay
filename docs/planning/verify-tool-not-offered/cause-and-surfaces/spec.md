# Aspect A2 — `cause-and-surfaces`

> The decision A1 produces becomes a **named, countable, correctly-bucketed** cause that
> renders honestly on every surface. Without this aspect the fix is invisible to an operator
> and uncountable in a mint.

## Problem slice

`prd.md` G4: *"how many turns could not be verified because the boundary lacked the tool"* is
exactly the number the gate mint needed and could not produce. Today such turns would bucket
into the existing catch-all and be indistinguishable from unrelated result abstentions.

## In scope

1. **A new sub-verdict `kind`.** `_replayed_cause` builds
   `f"{REPLAYED_SUB_VERDICT} {axis}/{kind}: {message}"` (`src/belay/verify/turn.py:196-201`)
   and `canonical_cause` buckets by **prefix on `axis/kind`**. The existing entry
   `("replayed but unverified A2/replay", REPLAYED_RESULT_UNVERIFIED)`
   (`src/belay/replay/report.py:118`) already matches **every** result-axis abstention, so a
   new constant alone would sit **permanently unreached**. The abstention therefore gets its
   own `kind` (e.g. `replay:tool-not-offered`), mirroring the existing `effect:network`
   precedent. **`axis` stays `A2`.**
2. **`_PREFIX_LABELS` ordering.** The new entry must precede the `A2/replay` catch-all,
   exactly as `effect:network` precedes `effect`.
3. **Bucket constants** as module-level `REPLAYED_*` names in `src/belay/replay/report.py`,
   registered in `_REPLAYED_CAUSES` (`src/belay/interop/attach.py:81`). The guard test is
   reflection-based over `REPLAYED_*` names, so registration is enforced **only if** the
   constant is module-level — a hand-built inline string is invisible to it and would be
   misreported by C9 as `unrestorable-pre-state` (the `interop-merge-repair` bug class).
4. **Distinct causes** for: boundary-does-not-offer, ambiguous (2+ servers), probe-failed.
5. **Rendering on every surface**, each with its coverage line: `belay verify` text,
   `verify --json`, `corpus show`, `interop correlate` (text + `--json`), `phase0 report`'s
   UNVERIFIED-by-cause table, and the console.

## Out of scope

- The probe and the decision (aspect `boundary-probe`).
- Any new **status** — `NOT_COVERED` is *not* involved. This is *"we tried and could not"*
  (UNVERIFIED), never *"we have no instrument"*.
- The console's separate `EngineErrorCause` union (`console/src/server/types.ts:103-110`) —
  subprocess-level, must not be conflated with engine causes.

## Acceptance criteria (failing tests first)

- **AC-1 (the bucket is REACHED, not merely declared)** A not-offered turn's
  `TurnVerdict.cause` equals the new bucket label — **not** `REPLAYED_RESULT_UNVERIFIED`.
  *This is the test that would have caught the drafted M7 being dead-on-arrival.*
- **AC-2** `_PREFIX_LABELS` ordering pinned: the new prefix resolves ahead of the `A2/replay`
  catch-all, asserted by calling `canonical_cause` directly on both shapes.
- **AC-3** The reflection guard (`tests/test_interop_attach.py:476-495`) stays green, and a
  C9 correlation over a not-offered turn reports the **new cause**, never
  `unrestorable-pre-state` — the pre-state restored fine.
- **AC-4** The three causes are distinct and each round-trips through `canonical_cause`.
- **AC-5** One rendering assertion per surface (text, `--json`, `corpus show`, interop
  text+json, `phase0 report`, console), mirroring `tests/test_coverage_rendering.py`'s
  per-surface structure rather than inventing a new pattern.
- **AC-6** `phase0 report` counts the new bucket as its own line in the UNVERIFIED-by-cause
  table over a fixture batch.
- **AC-7** The console renders the new cause distinctly from PASS
  (`console/src/components/VerdictBadge.spec.ts` shape) and never as PASS.
- **AC-8** Existing pinned contracts stay green: `tests/fixtures/verify_json_snapshot.json`
  and `tests/test_verify_json.py:358` (the manifest-not-found path keeps `kind == "replay"`).

## Dependencies & sequencing

- **Depends on `boundary-probe`** for the decision it labels. Land second.

## Risks specific to this aspect

- A new `kind` changes the per-sub-verdict `kind` field in `--json` (`src/belay/verify/json.py:119`).
  Verified **not** to touch the `--json` coverage block, which counts only `NOT_COVERED`
  (`json.py:158-160`); and the text renderer groups by **axis**, not kind
  (`src/belay/cli.py:748-753`). Both facts must be pinned by test rather than trusted.
