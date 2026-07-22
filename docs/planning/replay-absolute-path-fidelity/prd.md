# PRD — `replay-absolute-path-fidelity`

**Unit:** feat/replay-absolute-path-fidelity · **Owner:** aliz · **Date:** 2026-07-22
**Branch:** `feat/replay-absolute-path-fidelity/aliz` (off `master`)
**Inputs:** `docs/planning/_card/issue.md`, `docs/planning/replay-absolute-path-fidelity/understanding.md`
**Upstream:** the Phase-0 Stage-1 live mint (PR #7, `phase0-live-mint/.../STAGE1_FINDINGS.md` #3)

---

## Problem Statement

Belay's replay is **faithful only for cwd-relative MCP servers**. For servers that take an
**absolute root at launch** and address files by **absolute path** — the reference
`@modelcontextprotocol/server-filesystem` (`node <entry> <abs_root>`) among them — replay
is **silently wrong in both directions**, and the product says nothing about it:

- **False positive** — reads leak to *live* state (Seatbelt `(allow file-read*)` is
  globally unscoped, `seatbelt.py:244`), so a benign read diverges from the recorded reply
  → A2 FAIL. *Observed live in Stage 1.*
- **False negative** — a corrupt write to the original path is sandbox-**denied** (the
  original is not a replay write-root), so the scratch delta is empty → effect **PASS**. A
  genuine corrupt success goes **uncaught**. *This is the direction that breaks the thesis:
  "we catch corrupt success" is false for this whole class of servers.*

**Proven, not theorized:** reverting the Stage-1 workspace to `base_commit` and re-running
over the same trace changed the per-turn verdicts. The verdict moved with live filesystem
state — the definition of contamination for a supposedly deterministic replay.

**Who has this problem:** first, the founder at the Phase-0 gate — this blocks the
violation-rate number (R1, the only Fatal-impact risk). More broadly, **every Belay user
running an absolute-path MCP server** gets untrustworthy verdicts with no warning. The
reference filesystem server is the one the docs and the mint themselves use.

**Cost of the status quo:** the Phase-0 number cannot be published; and Belay's core claim —
execution-grounded verification — is quietly false for a large, common class of servers.

## Goals & Success Metrics

Success is a replay whose verdict depends **only** on the restored snapshot, for
absolute-path servers, without regressing the cwd-relative case.

| Metric | Target | Grounding |
|---|---|---|
| Contamination | A verdict is **identical** whether the original workspace is pristine, mutated, or deleted | acceptance #1 |
| False positive | A correct benign edit via an abs-path server does **not** FLAG | acceptance #2 |
| False negative | A genuinely corrupt edit via an abs-path server **does** FAIL | acceptance #3 |
| Regression | Every existing cwd-relative fixture test stays green | acceptance #4 |
| Honesty | A trace without a recorded root replays to a named `UNVERIFIED`, never a false verdict | acceptance #5 |
| Determinism | Replay stays a pure function of (trace, snapshot) — no clock/network/ambient FS | non-functional |

## Users & Scenario

Belay's ICP — the engineer who must answer "did this run actually do the right thing?" —
running an agent whose file edits go through the reference filesystem MCP server. Today
Belay's verdict on those turns is contaminated by whatever state their workspace happens to
be in at replay time. After this, the verdict reflects the recorded snapshot alone.

## Requirements

### Decisions locked in the interview (2026-07-22)

- **Record the original root in the snapshot manifest, per-turn.**
- **Remap only the workspace prefix**; absolute paths *outside* the recorded root are left
  unmapped (system reads like `/etc`, shared libs behave as today).
- **Old/rootless traces → `UNVERIFIED`** with a named cause — no inference from the
  `--server` argv token.
- **Additive**: relocation is a distinct step, gated on a recorded root *and* the presence
  of in-root absolute paths. When absent, replay behaves **exactly** as today.
- **Content is never mutated.** Relocation rewrites *only* the server argv root token and
  the **path fields inside `arguments`**. Reply root-substitution happens **only inside the
  comparison** (`result_equivalence`), transiently — the normalized reply is never persisted,
  and no content byte written to the scratch is ever touched. So a file that legitimately
  *contains* the workspace path, or a test asserting on it, is never corrupted; the delta
  sees real content.
- **Shell server:** the plan's **first task** determines whether `mcp-server-commands`
  (`run_process`) carries absolute paths needing the same relocation. If the same
  prefix-remap covers it, include it; if it is a distinct problem (a `cwd` arg, paths
  embedded in command strings), fix the **filesystem** case here and file the shell case as
  a **follow-up unit**, stated openly so the Phase-0 number is not silently half-contaminated.

### Must-have

1. **Record the original workspace root** (`gate._scope`) into the snapshot manifest at
   capture (`persist_snapshot` ← `gate.py:429`), read it back in `load_snapshot`, and thread
   it into `replay_turn`. Backward-compatible: a manifest without the field loads fine and
   yields a `None` root.
2. **Relocation pass, gated and additive.** When (and only when) a root is recorded and a
   replayed `tools/call` carries absolute paths **under that root**:
   a. **Rewrite the server argv** root token (the `<abs_root>` launch arg) → scratch root
      before spawn (`client.py:322`; scratch = `spawn.scope.snapshot_root`).
   b. **Remap recorded absolute path arguments** in the frame from original-root → scratch
      prefix (recursively over `arguments` string values), re-serializing the frame while
      preserving JSON-RPC id correlation (`_await_key`/`_matches`).
   c. **Normalize the reply comparison** so the recorded reply (original paths) and the
      replayed reply (scratch paths) compare equal in `result_equivalence` (`engine.py:375`)
      — symmetric canonicalization of both roots to a placeholder, applied only to the
      recorded root and the scratch root.
3. **Prefix rule:** remap a string iff its realpath'd form has the recorded root as a path
   prefix. Never rewrite tokens/paths outside the root. Root-matching uses the same
   realpath normalization the scratch root uses.
4. **Honest fallback:** a trace/manifest lacking the recorded root, replayed for a turn that
   *needs* relocation (abs paths present), yields **`UNVERIFIED`** with the named cause
   `original workspace root not recorded; cannot relocate absolute paths`. Never a false
   PASS/FAIL. A turn that needs no relocation (cwd-relative) is unaffected.
5. **A committed absolute-path fixture server** (an echo/edit server that takes an absolute
   root and uses absolute paths) so the whole class is exercised in CI. Its absence is why
   the bug survived the suite.
6. **Zero behavior change for cwd-relative servers** — every existing fixture and replay test
   stays green, including `test_replay_runs_against_a_scratch_copy_and_leaves_the_original_untouched`.

### Should-have

7. **Document the contract.** State in the trace/replay docs (`TRACE_FORMAT.md` /
   `CAPABILITY_ROADMAP.md` C3) that replay relocates the recorded workspace root for
   absolute-path servers, and what happens for out-of-root paths and rootless traces. The
   dig found **no** documented contract on absolute-vs-relative paths today — that silence
   is part of the bug.
8. **A `belay replay` / `phase0 run` surfacing** of the relocation (e.g. the UNVERIFIED
   cause is legible in the report) so a rootless mint is visibly UNVERIFIED, not silently
   mis-scored.

### Nice-to-have

9. **Re-mint the Stage-1 instance** once this lands to confirm the false positive is gone
   end-to-end (belongs to `phase0-live-mint` Stage 1, not here — but it's the real-world
   proof the fix worked).

## Technical Considerations

**Capability:** hardens **C2/C3** (snapshot/restore + replay) and the **A2** verdict axis —
the deterministic spine, the moat. No new capability; a correctness fix to an existing one.

**Verdict impact:** A2 only. It does **not** change what A2 *claims* — it makes A2's existing
claim (result-equivalence + effect-conformance against the restored pre-state) *true* for
absolute-path servers, where today it's contaminated. A1 and A3 untouched.
`UNVERIFIED`-never-`PASS` is strengthened, not weakened (the honest fallback).

**Determinism:** the bug *is* a determinism violation (verdict depends on ambient FS). The
fix restores determinism: given (trace, snapshot), the relocated replay is reproducible
regardless of the live workspace.

**Byte-transparency tension (stated, accepted):** the proxy captures exact wire bytes and
`raw` is hashed for *capture* fidelity. Relocation re-serializes a frame at *replay* time —
deliberately, to relocate paths — so the re-sent frame is not byte-identical to `raw`. That
is correct: the hash attests what was captured, not what replay relocates. The relocation
step is isolated so the capture-side byte-pump is untouched.

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **Over-broad remap** breaks a cwd-relative server that also passes an absolute path | Mitigated by the gated/additive design + the strict in-root prefix rule + keeping all relative fixtures green. |
| **Asymmetric reply normalization** trades false-positive for false-negative silently | Acceptance #2 **and** #3 are both required; the FN test is the guard. |
| **Realpath/symlink mismatch** between recorded root and scratch root causes a prefix miss | Root-matching uses the same realpath normalization as the scratch; a miss falls to the honest `UNVERIFIED`, not a false verdict. |
| **Frame re-serialization** desyncs JSON-RPC id correlation | The remap preserves the `id`; `_await_key`/`_matches` must be tested against a relocated frame. |
| **R1** (the premise) stays blocked until this ships | This unit *is* the unblock; it's the critical path to the number. |
| Scope creep into a general path-VFS | Explicitly out of scope — prefix remap only. |

**Open questions**
1. Reply normalization placement — inside `result_equivalence` vs a pre-pass on both
   replies. (Leaning: a small canonicalizer both call, so it's symmetric by construction.)
2. Does the shell server (`mcp-server-commands`, `run_process`) also carry absolute paths
   (in `cwd`/command strings) that need the same treatment, or is it cwd-relative? Verify in
   the plan; the mint uses both servers.
3. Exact manifest field name/shape for the root (`source_root`? `workspace_root`?) and its
   JSON schema + validation, consistent with the fail-closed manifest loader.

## Out of Scope

- **A general path-virtualization / VFS layer.** Prefix remap of the recorded workspace root
  only.
- **Inferring the root from the `--server` argv** (decided against — honest `UNVERIFIED`
  instead).
- **Restoring into the original workspace path** (rejected — violates C3 never-mutate-live-state
  and the load-bearing scratch-isolation test).
- **Bind-mount / symlink relocation** (non-portable, racy, privileged).
- **The Stage-1 re-mint and the Phase-0 number itself** — that resumes in `phase0-live-mint`
  after this ships.
- **A1 / A3 axes**, the proxy capture path's byte-transparency, and any model-in-the-loop.

## Self-Critique (Phase 4)

Scored against the `prd-generator` dimensions; gaps travel with the doc.

| Dimension | Score |
|---|---|
| Problem Definition | 🟢 both failure directions named, proven live, file-cited |
| User Understanding | 🟢 founder-at-gate + every abs-path-server user |
| Success Metrics | 🟡 see gap #2 — "identical verdict" needs a tie-break for legitimately-nondeterministic replies |
| Scope Clarity | 🟢 four rejected approaches named explicitly |
| Edge Cases & Risks | 🟡 see gap #1 — the remap's own failure modes (paths in replies, encoded paths) |
| Feasibility | 🟢 exact touch points from the dig |
| Verdict Honesty & Replay | 🟢 A2-only, UNVERIFIED-never-PASS strengthened, FN test required |

### 🔴 Gap 1 — the reply may contain absolute paths in forms the prefix rule can't see

Reply normalization (must-have 2c) assumes absolute paths appear as **plain string prefixes**.
But a real server reply can carry the path **encoded** — inside a unified-diff header
(`Index: /abs/...`, `--- /abs/...`), JSON-escaped, URL-encoded (`file:///abs/...`), or
concatenated into a message. Stage 1's `edit_file` reply was a **diff** with the absolute
path in the `Index:` line. A naive prefix-replace on the top-level reply string will catch
that particular case, but the PRD must state the rule precisely: **normalization operates on
the raw reply text (and any nested string values) by substituting the original-root and
scratch-root *substrings* wherever they appear**, not only as leading prefixes — and it must
be symmetric so both sides collapse to the same canonical form. Otherwise a correct edit
still FAILs on a path buried in the diff. **This is the most likely way the fix ships and
still false-positives.** Add an acceptance test whose recorded reply is a diff containing the
absolute path.

### 🔴 Gap 2 — "identical verdict" is untestable if the reply is legitimately nondeterministic

Acceptance #1 demands the verdict be identical pristine-vs-mutated-vs-deleted. But some
replies vary run-to-run for reasons unrelated to workspace state (timestamps, ordering) —
`verify_turn` already replays 3× and has a determinism gate. The metric must be stated as:
**the verdict is invariant to the *live workspace state* specifically**, holding all else
equal — not "byte-identical replies across runs." Otherwise the test conflates this fix with
pre-existing reply nondeterminism. Pin the fixture server to a **deterministic** reply so the
test isolates the workspace-state variable, and phrase #1 as "invariant to live workspace
state," not "identical."

### 🟡 Gap 3 — the shell server is an unresolved unknown that the mint depends on

Open question #2 (does `run_process` carry absolute paths?) is left for the plan, but the
Phase-0 mint uses **both** servers. If the shell server also needs relocation (a `cwd` arg,
absolute paths in command strings), then fixing only the filesystem case unblocks half the
mint and the number is *still* partly contaminated. Resolve this **in the plan's first
task**, before building — it may widen must-have 2 or add a second fixture.

### The question I'd want answered before greenlighting

**When the recorded root string appears in file *content* (not a path) — e.g. the agent's
edit writes the literal absolute path into a source file, or a test asserts on it — the
remap will corrupt it.** Is a blind substring substitution of the root safe, or does
relocation need to distinguish *path arguments/results* from *content*? The safe answer may
be to remap **only the argv root token and the `arguments` path fields**, and to normalize
the reply for **comparison only** (never persisting the normalized form, and never touching
content bytes written to the scratch). State that boundary, or the fix can silently alter
what the delta sees.

---

## Honesty Properties (non-negotiable)

1. A replay verdict depends **only** on (trace, snapshot), never on live workspace state.
2. `UNVERIFIED` is never rendered `PASS`; a rootless trace that needs relocation is
   `UNVERIFIED`, not guessed.
3. The fix must not trade the false positive for a false negative — both directions are
   tested.
4. No behavior change for the cwd-relative case that already works.
