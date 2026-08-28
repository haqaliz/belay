# Card — feat/verify-multi-server-seam/aliz

**Source:** no GitHub issue (`gh issue list` → "No Issues"; the repo's tracker is empty).
The source of record is the inline brief below, produced by the `belay-next` pick on
2026-08-28 against the committed record.

## Brief

Fix the **U9 replay seam**.

Today `belay verify --server` takes ONE server command (`src/belay/replay/client.py:342`,
`src/belay/replay/engine.py:416` — `server_command: Sequence[str]` threaded through the
whole replay path). So a turn whose tool that single server does not offer replays as
`MCP error -32602: Tool run_process not found`. That error reply *parses* as JSON and
*reproduces deterministically*, so `src/belay/verify/result.py:18` scores it
DIVERGED + DETERMINISTIC → **FAIL**.

That is a **false FAIL**, measured **171 times** in the gate mint
(`docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md:10`), hand-verified on
`trace-django__django-12125.jsonl` turn 8 (the trace records a real exit-0 `run_process`;
replay through the filesystem-only `--server` reproduces the -32602 error).

The **pre-registered disposition** said this would degrade honestly, not fail:
`docs/planning/mint-shell-toolset-run/prd.md:173` (risk P5) — *"Pre-stated composition:
echoed, UNVERIFIED-by-cause, never counted as replayed evidence; a divergence is a
recorded finding, not a silent adjustment."* The engine diverged from its own contract.

### Two halves

1. **Honesty half (must).** A turn whose recorded tool is offered by no replay server is
   **UNVERIFIED with a named cause**, never a result-equivalence FAIL.
2. **Coverage half (should).** `belay verify` accepts more than one `--server`, and each
   turn is routed to the server that offered its tool — decided from the trace's recorded
   `tools/list` snapshot (the `derive_annotations` fact the trajectory rule already reads),
   never guessed.

### Acceptance sketch (test-first, from the handoff)

1. A turn whose recorded tool is offered by no replay server → UNVERIFIED with a named
   cause, never a result-equivalence FAIL. Fixture from the committed `django-12125`
   capture.
2. `verify` accepts multiple `--server` specs; each turn routes to the server that offered
   its tool, decided from the trace's recorded `tools/list` snapshot.
3. Fail-closed on ambiguity: a tool offered by **zero** or by **two** servers is UNVERIFIED
   with a named cause — never routed on a guess.
4. Single-server traces produce **byte-identical** verdicts (regression).
5. The new cause is added to the closed `_REPLAYED_CAUSES` set
   (`src/belay/interop/attach.py:81`) in the same PR, with its guard test; the coverage
   line travels on every surface (`verify` text, `--json`, console, `corpus show`).

### Caveats carried in from the pick

- **This is a RECLASSIFICATION, not improved detection.** The UNVERIFIED rate rises by
  design. `11/60 = 18.3%`, the 11 hand-audited TPs, `precision 0.00`, `1/15`, `4/16` and
  every other published number stand **unedited** (the discipline `trajectory-toolset-rescope`
  set).
- Any newly-replayable trajectory FAIL (the 12 "unverifiable-by-seam") is **evidence for the
  owner to re-adjudicate**, never a verdict this unit re-decides.
- **R7** (UNVERIFIED dominance) is the risk this touches; **R5** (over-claiming what A2
  proves) is what it retires.
- Hazard from the record: `_REPLAYED_CAUSES` is a **closed** vocabulary with a guard test,
  and `interop-merge-repair` documents a unit that broke C9 silently by adding a cause
  without updating it.

## Related record (not issues — commits/docs)

- `docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md` — the 171-FAIL finding,
  the hand-verification, the corpus-banking consequence.
- `docs/technical/PHASE0_RESULTS.md:1159` — the same fact in the published record.
- `docs/planning/mint-shell-toolset-run/prd.md:109,173` — U9 and P5 as pre-registered.
- `docs/planning/phase0-gate-readiness/` — `interop-merge-repair`, the `_REPLAYED_CAUSES`
  hazard.
