# Understanding — `replay-absolute-path-fidelity`

**Phase 2 of `belay-begin-fast`.** Grounded in a two-agent read of `src/belay/` on
2026-07-22 (worktree off `master`) plus the Phase-0 Stage-1 live repro (PR #7,
`STAGE1_FINDINGS.md` #3). Every claim below is file:line-cited from the dig.

---

## 1. What this really is

Belay's replay is **faithful only for cwd-relative MCP servers**. For servers that take an
**absolute root at launch** and address files by **absolute path** — the reference
`@modelcontextprotocol/server-filesystem` (`node <entry> <abs_root>`) among them — replay
is **silently wrong in both directions**. This is a **core-engine defect on the A2 replay
axis** (the moat), and it blocks the Phase-0 number (R1).

It is bigger than the Phase-0 blocker: **Belay cannot verify absolute-path servers at all**
today, and says nothing about it. That is a product-level honesty gap.

## 2. Confirmed mechanism (both directions)

Replay's only relocation is **cwd**: it restores the snapshot into a fresh scratch dir and
sets the server's cwd there (`client.py:313,317,322-330`). It rewrites **nothing** —
neither the server argv (`launch.py:222`, `scope.wrap` only prepends env, `scope.py:180`)
nor the recorded frame path arguments (`engine._gather_frames` base64-decodes and forwards
exact bytes, `engine.py:386-412`; `client.converse` writes them verbatim,
`client.py:265-290`). An absolute-path server ignores cwd, so:

- **Reads leak to LIVE state.** The Seatbelt profile is `(allow file-read*)` **globally
  unscoped** (`seatbelt.py:244`, comment at `:364` "Reads are NOT scoped"). So an absolute
  read returns the *current* original-workspace content. Recorded (pre-mint) ≠ replayed
  (post-mint) → **A2 result-equivalence FAIL on a benign read** → false positive. (Stage 1:
  the Gemini `read_text_file` turn.)
- **Writes to the original are DENIED.** The original workspace is **not** a write-root of
  the replay sandbox (`write_roots = (scratch, tmpdir)`, `scope.py:137-144`;
  `build_profile(scope=write_roots)`, `launch.py:209`). A corrupt write EPERMs, the scratch
  is untouched, and the delta (`diff_records(before, scan_tree(result.workspace))`,
  `engine.py:321-322`) is **empty** → **effect PASS** → **false negative**: a genuine
  corrupt success goes uncaught. *This is the scarier direction for a verification product.*

**Proven at runtime** (Stage 1): reverting the workspace to `base_commit` and re-running
over the same trace changed the per-turn verdicts. The verdict moved with live state — the
definition of contamination.

## 3. The load-bearing prerequisite: the original root is recorded NOWHERE

- Trace frame record carries `raw, hashes, truncated, state_handle` — **no root/cwd/workspace
  field** (`trace.py:229-260`). The original prefix survives only *implicitly* inside the
  base64 `raw` bytes.
- Snapshot manifest carries `handle, tree_path, backend, capabilities, fidelity_gaps,
  sidecar` — and `tree_path` is the **clone** location (`<snapshot_dir>/turn-NNNN`), **not**
  the original workspace (`persist.py:106-116`, `gate.py:420`).
- The gate **has** it (`TurnGate._scope` from `BELAY_SANDBOX_SCOPE`, `gate.py:298`, used only
  as the clone source `take_snapshot(self._scope, dest)`, `gate.py:424`) but **never
  persists it.**

**So step one of any remap fix is to start recording the original workspace root** — a
small addition to `persist_snapshot` fed from `gate._scope`, read back in `load_snapshot`,
threaded into `replay_turn`. Without a trustworthy FROM-prefix, remapping is guesswork.

## 4. The fix space (the PRD picks one)

**(a) Restore into the recorded original path** — REJECTED. It requires the server to write
the user's real workspace, directly violating C3's "replay never mutates live state"
(`client.py:12-19`, `CAPABILITY_ROADMAP.md:204`) and breaking the load-bearing test
`test_replay_runs_against_a_scratch_copy_and_leaves_the_original_untouched`
(`test_replay_client.py:129`). Also still needs the original root recorded.

**(b) Scratch-preserving prefix remap** — the C3-faithful direction. Three parts:
1. **Record** the original workspace root (§3 prerequisite).
2. **Rewrite the server argv** root token (the `<abs_root>` launch arg) from original →
   scratch before spawn (`client.py:322`, scratch known as `resolved`/`spawn.scope.snapshot_root`).
3. **Remap recorded absolute path arguments** in each replayed `tools/call` frame from the
   original prefix → scratch prefix (`engine._gather_frames` or `client.converse`) — which
   forces **frame re-serialization**, something the design deliberately avoids today
   ("read a copy for its id, never re-emit it", `client.py:45-49`).
4. **Normalize the reply comparison.** The *recorded* reply carries original absolute paths
   (e.g. a diff's `Index: /orig/.../blueprints.py`); the *replayed* reply carries scratch
   paths. `result_equivalence` (`engine.py:375`) must canonicalize both (map each root to a
   placeholder, or scratch→original) or it FAILs on the path strings alone. Stage 1's
   `edit_file` reply showed exactly this.

**Other options considered and rejected:** OS bind-mount / symlink the scratch at the
original path (not portable on macOS, racy, privileged); force relative tool paths (we don't
control the model or the server's absolute-path requirement).

## 5. Design tensions the PRD must resolve

- **Byte-transparency vs. remap.** The proxy is a byte pump and `raw` is exact wire bytes
  with hashes. Replay-time frame rewriting breaks byte-identity on the re-sent frame. That
  is acceptable *for replay* (we are deliberately relocating; the hash attests capture
  fidelity, not replay), but it must be stated, and the id-correlation logic
  (`_await_key`/`_matches`) must keep working on the rewritten frame.
- **Which strings are paths?** The remap rule must be principled and server-agnostic:
  *any string value under `arguments` (recursively) whose realpath'd form has the recorded
  original root as a path prefix* → swap that prefix to scratch. Paths outside the root
  (`/etc/...`) are left alone. Must handle realpath/symlink normalization consistently with
  how the scratch root is realpath'd.
- **The honest fallback.** If the original root is **absent** from a trace (old captures,
  or a capture that never recorded it), replay must **not** silently misbehave — it should
  degrade to a named `UNVERIFIED` ("cannot relocate absolute paths: original root not
  recorded"), never a false PASS/FAIL. `UNVERIFIED`-never-`PASS` holds.
- **Scope of the argv rewrite.** Only rewrite an argv token that *is* (or is under) the
  original root; never blindly rewrite arbitrary tokens.

## 6. Guardrails / axis

- **A2 replay axis**, the deterministic moat. The fix must keep replay a pure function of
  (trace, snapshot) — no clock, no network, no dependence on ambient live filesystem state
  (that dependence is precisely the bug).
- `UNVERIFIED` is never `PASS`; the fix must not manufacture a verdict where the pre-state
  or the remap cannot be established.
- Not an agent framework; no model in the loop.
- Keep every existing cwd-relative fixture test green — the fix must be **additive** for the
  absolute-path case, not a behavior change for the relative case.

## 7. Acceptance (the falsifiable core)

1. **Contamination regression:** a capture with absolute-path tool calls, replayed after the
   original workspace is **mutated or deleted**, yields a verdict identical to replaying it
   against a pristine original — i.e. the verdict depends only on the restored snapshot.
   (Deterministic, offline; a committed fixture server + synthetic trace, not the ephemeral
   Stage-1 capture.)
2. **No false positive:** a benign correct edit via an absolute-path server does **not** FLAG.
3. **No false negative:** a genuinely corrupt edit via an absolute-path server **does** FAIL
   (the write must land in the relocated scratch so the delta is real).
4. **No regression:** every cwd-relative fixture test stays green, including
   `test_replay_runs_against_a_scratch_copy_and_leaves_the_original_untouched`.
5. **Honest fallback:** a trace lacking the recorded original root replays to a named
   `UNVERIFIED`, never a false verdict.

## 8. Open questions for the PRD

1. **Where to record the original root** — snapshot manifest (per-turn, natural home) vs. a
   trace header record vs. both? The manifest is per-turn and already threaded into replay;
   likely the cleanest.
2. **Remap at the frame layer (`engine._gather_frames`) or a new dedicated relocation step?**
   Isolating it in one well-tested function keeps the byte-pump elsewhere clean.
3. **Reply normalization placement** — inside `result_equivalence`, or a pre-normalize pass
   on both replies? Must be symmetric and deterministic.
4. **Backfill / old traces** — captures made before this ships have no root. Fallback to
   `UNVERIFIED` (per §5) vs. best-effort inference from the `--server` argv token. Recommend
   the honest `UNVERIFIED`.
5. **Does this want a first-class "absolute-path server" fixture** committed to the repo (an
   abs-path echo/edit server) so the whole class is covered by CI going forward? (Strongly
   yes — the bug survived because no fixture exercised it.)
