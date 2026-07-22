# Aspect — `replay-batch-server-rooting`

**Unit:** `phase0-mint-execution` · **Sequence:** 1 of 5 — **blocks every other aspect**
**Placement:** `src/belay/{replay,phase0,cli}` + tests. Core engine.

---

## Problem slice

`belay phase0 run` takes **one static** `--server` command for a whole batch directory
(`src/belay/phase0/runner.py:90`; threaded at `:115,174,200`; parsed at `src/belay/cli.py:1044`).
Each trace's `source_root` is read correctly per turn from its own manifest
(`src/belay/replay/engine.py:388`), so tool-call **arguments** relocate to the scratch — but
the server's **argv allow-root** only moves when it is under *that trace's* recorded root
(`src/belay/replay/relocate.py:93-108`). `remap_argv` returns a `changed` flag saying whether
anything moved; `src/belay/replay/client.py:371` **discards it via `[0]`**.

So in a heterogeneous batch the server is spawned rooted at the wrong workspace, rejects the
scratch paths, the reply diverges from a recorded success, `classify_determinism` re-runs the
same broken command and calls it DETERMINISTIC, and `src/belay/verify/result.py:18` returns
`DIVERGED + DETERMINISTIC → FAIL`.

**User outcome:** a batch verdict means what it says. A replay that cannot be correctly rooted
says **UNVERIFIED** instead of **FAIL**, and a batch of heterogeneous instances can be
verified through one invocation.

---

## In scope

### (b) The honesty floor — lands first

1. `client.replay_turn` consumes `remap_argv`'s `changed` flag. When relocation is **on**
   (a `source_root` is recorded **and** the turn's arguments hold in-root absolute paths) and
   **no argv token moved**, the turn is **UNVERIFIED** with a named cause — the server is not
   spawned at all.
2. A module-level cause constant beside `ROOTLESS_RELOCATION`
   (`src/belay/replay/engine.py:97-103`), worded so an operator reading a report can tell it
   apart from the rootless case. It is a *different* failure: the root **was** recorded, the
   **server command** can't reach it.
3. The cause propagates through `verify_turn` → `canonical_cause` → the phase0 report's
   UNVERIFIED-by-cause table, exactly as `ROOTLESS_RELOCATION` does
   (`src/belay/verify/turn.py:125-131`, `src/belay/phase0/runner.py:178-181`).

### (a) The seam — lands second

4. `run_batch` accepts a **per-trace** server-command resolver instead of a static list:
   `server_command_for: Callable[[Path], list[str]]`, mirroring
   `eval/minting_driver/batch.py`'s `build_server_command(layout)` seam.
5. The CLI keeps `--server` working unchanged for the homogeneous case (it becomes a resolver
   returning a constant), and gains a way to vary the root per trace. **The CLI surface for
   the heterogeneous case is a design decision for the plan** — options include deriving the
   root from each trace's own recorded `source_root` (no new flag; strictly more correct) or
   an explicit mapping file. Prefer the no-new-flag option if it holds up: the engine already
   knows each trace's root, so requiring the operator to restate it is redundant and is
   exactly what went wrong.

---

## Out of scope

- **Shell `command_line`-embedded paths** — `replay-relocation-shell`, a separate unit.
- Any change to what a verdict **claims** on any axis. A1/A2/A3 semantics are untouched;
  this restores the fidelity of A2's inputs and adds an UNVERIFIED path.
- The eval harness (`eval/`) — later aspects.
- Relaxing the whole-value absolute-path remap rule (`relocate.py`), which is deliberate and
  content-preserving.

---

## Acceptance criteria (test-first — these are the failing tests)

The gap that let this survive is that **every** relocation e2e case builds the server command
from the same root as the capture (`tests/test_replay_relocation_e2e.py:99` `_server_cmd(root)`,
used at :312, :339, :369, :401, :488, :592). Every criterion below must break that symmetry.

1. **`test_mismatched_server_root_is_unverified_not_fail`** — capture against root A, replay
   with a server command rooted at unrelated root B. Result is **UNVERIFIED** with the named
   cause. Asserts explicitly that it is **not FAIL** — this is the regression that would have
   published a ~100% rate.
2. **`test_mismatched_server_root_does_not_spawn`** — the mis-rooted server process is never
   started (no side effects, no wasted work). Assert via a spawn seam/fixture, not by timing.
3. **`test_matching_server_root_is_byte_unchanged`** — the existing homogeneous path is
   unaffected; a clean single-root capture yields the same verdict it does today. The whole
   fix must be additive.
4. **`test_cwd_relative_capture_unaffected`** — no `source_root`/relocation → today's path
   exactly. (Guards the gate that keeps cwd-relative servers byte-unchanged.)
5. **`test_rootless_and_unrootable_causes_are_distinct`** — the two UNVERIFIED causes are
   different strings and land in different report buckets.
6. **`test_heterogeneous_batch_verifies_through_one_invocation`** — **the load-bearing
   criterion.** Two captures from two *different* workspace roots, bridged into one batch
   dir, verified in a single `run_batch` call. Both instances get correct verdicts; neither
   is a false FAIL.
7. **`test_heterogeneous_batch_verdict_survives_original_workspace_deletion`** — repeat
   criterion 6 after **deleting both original workspaces**. Verdicts identical. This is the
   in-the-wild version of the guarantee v0.4.0 proved only in fixtures, and it is the
   strongest available proof that no live state leaks into a batch verdict.
8. **`test_phase0_report_surfaces_the_new_cause`** — an unrootable turn appears in the
   UNVERIFIED-by-cause table under its named cause, never as PASS and never as FAIL.

All deterministic, offline, fixture servers only, runs in CI. The existing suite (624 passed)
stays green.

---

## Dependencies and sequencing

- **Depends on:** nothing. Off `master` @ v0.4.0.
- **Blocks:** `mint-entrypoints`, `mint-execution`, `audit-and-publish`. **No live inference
  spend before this merges** — that is the whole point of sequencing it first.
- (b) before (a): (b) is the failing-test honesty floor and is independently correct; (a)
  builds on it. With (b) alone a heterogeneous batch is all-UNVERIFIED → `INSTRUMENT SUSPECT`
  → no number, which is *honest but useless*. (a) is what produces a denominator.

---

## Open questions / risks

- **CLI surface for (a)** — decide in the plan (see in-scope item 5). Deriving each trace's
  root from its own manifest is the strongest candidate and removes an operator footgun.
- **Requirement 1 raises the UNVERIFIED rate by design** (risk R7). That is correct behavior,
  but if it dominates a real mint it is a *gate signal* and must be reported as such, not
  engineered away.
- **`classify_determinism` re-runs a broken command N times** before the FAIL is reached
  (`src/belay/verify/turn.py:180`). With (b) short-circuiting earlier this becomes moot for
  the mis-rooted case, but the general "deterministically broken ≠ deterministic tool"
  confusion is worth a note — it is what converted a spawn failure into a confident FAIL.
