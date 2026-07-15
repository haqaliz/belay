# PRD — C2: Sandbox + execution boundaries

**Capability:** C2 (`docs/technical/CAPABILITY_ROADMAP.md`) · **Phase:** 0 · **Window:** weeks 1–2
**Dependencies:** C1 ✅ merged (PR #1) · **Cuttable:** **No — the critical path (R2, High/High)**
**Branch:** `feat/sandbox-snapshot-restore/aliz` · **Slug:** `sandbox-snapshot-restore`
**Inputs:** [`_card/issue.md`](../_card/issue.md) (C2 verbatim), [`understanding.md`](./understanding.md) (measured research)

> **Authority:** `CAPABILITY_ROADMAP.md` > `ROADMAP.md` > `CLAUDE.md`/`VISION.md`.
> **Every substrate and fidelity number in this PRD was measured on the dev machine**, not read.
> Claims that were not run are marked UNVERIFIED and must not be cited as fact.

---

## Problem Statement

**C2 is the engine's floor, not a feature.** *"You cannot re-execute a turn without restoring the
state it ran against"* — so **containment and verification are the same machinery**. C3 (replay),
C4 (A2), C5 (A1) all block on it. It is **risk R2: High probability, High impact**, and the roadmap
is explicit: *"if it slips, the whole calendar slips."*

**Who.** Immediately: the founder building C3–C5, and the Phase-0 corpus (≥50 SWE-bench-lite runs
through the proxy, on this laptop). C2 is right if C3 can restore a pre-state and re-invoke against
it, and if an escape attempt is contained **and recorded**.

**Evidence it's real.** C1 shipped the trace with `state_handle: {"status": "absent"}` — a
three-state slot deliberately left empty for exactly this capability, with a comment explaining that
overloading `absent` to mean both *"C1-era trace"* and *"C2 tried and failed"* is how a false PASS is
born. C2 fills it.

---

## Goals & Success Metrics

| Goal | Metric | Target (measured baseline) |
|---|---|---|
| Restore fidelity | `hash(restored) == hash(original)` on a torture tree | **PASS** (achieved: 10.1ms snapshot / 3.5ms restore) |
| Containment | Every escape vector denied **and recorded** | direct · `../` · symlink · `mv` · **grandchild** — all contained |
| Replay is not the bottleneck | Snapshot+restore per turn | **<50ms** (achieved ~14ms; `docker commit` would be seconds) |
| Honesty | Every unsupported property has a **named cause** | 100% — **no silent skips** |
| Tests can fail | Repair-ablation + mutation suite | Disabling **any** repair MUST fail the acceptance test |
| Small and finished | Wall-clock | **≤5 working days** — C3 waits |

**Non-metrics, deliberately:** Linux support (Phase 1). Portability (Phase 1 packaging).
Container images (Phase 1).

---

## Users & Scenarios

**Primary: the founder building C3–C5.** C2 is right if `snapshot()` → agent mutates → `restore()`
→ tree is byte-identical, in milliseconds, and the `state_handle` slot is filled with a truthful
value (`present` **or** `unrestorable` **with a cause**).

**Secondary: the Phase-0 corpus.** ≥50 runs on macOS. C2 must survive them without becoming the
reason a run is slow or a verdict is wrong.

**Explicitly NOT served:** the Phase-1 stranger who `docker run`s it. Phase 0 ships no packaging.

---

## Requirements

### Must-have

**M1 · One substrate: Seatbelt (`sandbox-exec`), macOS-only.**
Spawn the MCP server inside a Seatbelt profile. **The hook already exists**: `proxy.py:300`'s
`subprocess.Popen(command, ...)`. C2 wraps that spawn; nothing else in the proxy changes.
> **Deprecated AND functional — both true.** Apple's replacement (App Sandbox) needs entitlements +
> a signed bundle, which a `Popen` of a third-party MCP server **can never satisfy**. There is no
> third option. Verified working on macOS 26.5.2 arm64.

**M2 · Enforced boundaries, and only the ones we can enforce.**
- **Filesystem scope** — verified contained: direct write · `../` traversal · symlink-out · `mv`-out
  · **write from a grandchild process**.
  > The grandchild case is load-bearing: **the sandbox is inherited across fork/exec**, and an MCP
  > shell server is mostly a process spawner. SBPL matches on the **resolved** path.
- **Network policy** — the vocabulary is **`deny-all | allow-all | allow-ports`**, and **nothing
  else**.
  > 🔴 **Per-host allowlists are a COMPILE-TIME ERROR**: `(remote ip "1.1.1.1:*")` →
  > `host must be * or localhost in network address`. **The API MUST REJECT a hostname allowlist**
  > rather than accept one and silently not enforce it. Guardrail: *never claim a boundary we don't
  > enforce.*
- **Per-tool allow/deny.**
- **A denied action is contained AND recorded as a denial** — never silently dropped.
  C1's `TraceWriter` already has extensible record `kind`s → C2 appends `kind: "denial"` with no
  schema break.

**M3 · `realpath()` every path before it reaches a profile.**
> 🔴 **A silent-grant bug, not a style rule.** `/tmp` is a symlink to `private/tmp`. A profile
> granting `(subpath "/tmp/x")` **grants nothing** — a write to the supposedly-*allowed* dir returned
> `Operation not permitted`. Without this, Belay hands users a policy that silently denies their own
> work while looking correct.

**M4 · Snapshot/restore: `clonefile(2)` via `ctypes`, with `CLONE_ACL`.**
- `os.clonefile` does not exist (verified). `ctypes` **is stdlib**, so **zero runtime deps hold** —
  no shelling out.
- **Clones whole trees recursively in ONE call.** Measured: 412MB / 4804 files → **71ms, 3.1MB of
  real disk** (COW verified via `df`, not `du`).
- **`CLONE_ACL` (0x0004) is mandatory** — with `flags=0` it **silently drops ACLs**.
- **Do NOT shell out to `cp -Rc`** — measurably worse: it additionally recreates non-regular files
  fresh, losing symlink/FIFO mtimes.

**M5 · Repair clonefile's three measured gaps. Each is load-bearing.**
clonefile silently loses **hardlink identity**, **setuid** (`0o4711 → 0o0711`), and **dir mtimes** —
**all three invisible to a content-only hash**. Repair, deepest-first: relink hardlinks · re-chmod
setuid · restore dir mtimes.
> **Ablation is a permanent test.** Measured: disabling `hardlinks` → FAIL · `suid` → FAIL ·
> `dirmtimes` → FAIL · all three → FAIL · all on → PASS. This is the guard that stops someone
> "simplifying" a repair away and leaving a green suite.

**M6 · The tree hash: BTH-1. Versioned, documented, and it discriminates.**
- **IN:** `BTH-1` tag · **raw readdir PATH BYTES** (never `str`, never normalized) · kind ·
  `S_IMODE` (carries setuid/setgid/sticky) · `mtime_ns` · `st_flags` · uid/gid · size + sha256
  content · symlink target as **raw bytes** · `st_rdev` · sorted `(xattr_name, sha256(value))` minus
  ignore-list · **hardlink GROUP ID = first path in the group** (*not* the inode number).
- **OUT, and documented as excluded:** inode numbers + `st_dev` · **atime (self-invalidating —
  hashing reads files and changes it)** · ctime (unsettable) · **birthtime (unsettable by anyone,
  incl. tar)** · `st_blocks` (sparseness → a separate WARN, not an identity diff) · raw `nlink`.
- **Ordering: sorted by RAW PATH BYTES.** readdir order is not stable; sorting by `str` would
  reintroduce the normalization trap.
- **Structure:** `sha256("BTH-1\n" + concat(sha256(rec)))`, records `\x00`-joined `key=value` **so a
  failure names the field** rather than printing two differing hex strings.
> **A content-only hash would have blessed EVERY failure above.** BTH-1 is measured to discriminate:
> only `bsdtar` MATCHes; clonefile / `cp -a` / stdlib tarfile / copytree all DIFFER. **Negative
> controls STABLE:** no-op re-extract · atime churn · inode churn.

**M7 · Narrow the substrate — then DETECT and REFUSE loudly.**
Supported: **regular files, dirs, symlinks**. Everything else (FIFOs, sockets, devices) is
**detected and refused with a named cause**.
> *"Narrowing the substrate is only honest if you detect out-of-substrate entries and refuse loudly.
> Silently ignoring a FIFO is exactly the UNVERIFIED-rendered-as-PASS that `CLAUDE.md` forbids."*
> Also: **`open(fifo,"rb").read()` BLOCKS FOREVER** (verified — it hung the researcher's own suite).
> **Gate on `S_ISREG` before opening anything.**

**M8 · The `unrestorable` signal, with a named cause, filling C1's slot.**
`state_handle` becomes `{"status":"present", ...}` or `{"status":"unrestorable","cause":...}`.
**Never guessed, never silently absent.** Taxonomy in `understanding.md` §7 — physically unsettable ·
privilege-gated · out-of-substrate · cross-filesystem impossibility · **outside the filesystem
entirely** (the class where A2 stops being able to say anything).

**M9 · C2 records the network policy in force per turn — as a FACT.**
`{"kind":"network_policy","turn":N,"policy":"deny-all"|"allow-all"|"allow-ports"}`.
**C2 does not decide replayability. C4 does.**
> **Why this matters beyond bookkeeping:** a call that touched the network under allow-all is
> **`UNVERIFIED` for A2, full stop** — replay would either **double-commit** the side effect (POST to
> Stripe, send mail) or diff against state the sandbox never owned. **Deny-egress-by-default is not
> posture; it is the precondition that makes A2 replay *sound*.** C1's tri-state `openWorldHint`
> snapshot is the declared marker that gates it. **Neither the roadmap nor C1's PRD noticed this
> connection.**

**M10 · A threat model doc.** Belay executes untrusted agent actions, so **Belay is itself an attack
surface** (R8). Must state what is enforced, what is not, and what is inexpressible.

**M12 · 🔴 The turn gate — C2 must BLOCK the data path, and C1 made that structurally impossible.
Resolve it deliberately.**

To snapshot a turn's **exact** pre-state, the snapshot must complete **before the `tools/call`
reaches the server**. That means **holding the request**. But:
- C1's capture branch is **structurally unable to block or alter the data path** (by design), and
- `proxy.py` **never imports `json`** — it cannot recognise a `tools/call` at all, and
- doing it in the observer is a **RACE**: the call may already have executed.

**This changes what the proxy is, and it is the most consequential design decision in C2.**

**Resolution (decided):** add a **`before_frame` gate hook** to `proxy.run()`.
- C2's module (not `proxy.py`) parses a **copy** to detect turn boundaries, blocks while
  snapshotting, then the proxy forwards the **ORIGINAL bytes**.
- **Byte-identity is preserved** → C1's differential and teeth tests **still pass untouched**; they
  assert **bytes**, never timing (`README`: *"the neutrality claim is narrow"*).
- **`proxy.py` stays `json`-free** → C1's import guard still passes; the parse lives behind a
  callback in C2's module. *Parsing-to-read and parsing-to-re-emit remain different operations.*
- **The honest cost: ~14ms added per turn, ON the data path, inside the client's timeout budget.**
  **This must be stated in the README, not discovered.** C1 explicitly claimed content-neutrality,
  **never latency-neutrality** — that distinction was written down precisely so this could be paid
  honestly.
- **When the sandbox is disabled, no gate is installed** and the proxy is exactly C1's byte pump.

**M13 · 🔴 Scope config is R3 in disguise — name it now, don't discover it at launch.**

The research found an over-strict profile **SIGABRTs the process**. At product level that is:
**what happens when the MCP server legitimately needs to write outside the scope it was given**
(temp files, caches, lockfiles, `$TMPDIR`)? If the answer is *"the user widens the scope"*, the
boundary is **user-authored** — which is **R3 (High/High): "nobody authors the invariant."**

**C2 is inheriting R3 a phase early.** Mitigations, in order:
1. **A sane default scope** covering what a filesystem/shell MCP server actually needs (the tool's
   working tree + a sandboxed `$TMPDIR`), so the common case needs **zero configuration**.
2. **A denial is a recorded fact with the exact path** — so widening scope is a *diagnosis*, not a
   guessing game. The trace tells the user precisely what to allow.
3. **`belay sandbox check`** (N1) — a one-shot self-test that says whether the substrate works
   *and whether the scope is too tight for this server*, before a real run.
4. **Never silently widen.** A denial is contained and recorded; the fix is explicit.

**M11 · Local-only.** No egress, no telemetry. Snapshots live under the configurable artifact root
(`/_sandbox/` is already gitignored for this).

### Should-have

- **S1 · `SnapshotBackend.capabilities()`**, and the manifest records **which backend produced a
  snapshot**; restore **REFUSES across differing capability sets**.
  > Not the premature abstraction the roadmap warns against — **the honesty contract**. `os.listxattr`
  > **does not exist on macOS** (CPython gates it to Linux), so `shutil.copystat` **silently drops
  > every xattr on darwin**, and **macOS resource forks ARE the `com.apple.ResourceFork` xattr**.
  > A tree captured where xattrs exist **cannot be truthfully restored where they don't**. Pretending
  > otherwise is a false PASS.
- **S2 · Snapshot GC must handle ACL'd / `uchg` trees.** An ACL of *"everyone deny delete"* made the
  researcher's own scratch dir **undeletable**. Without this, C2 strands disk.
- **S3 · `com.apple.provenance` on an explicit xattr ignore-list.** macOS injects it on every file it
  creates — so a naive *"xattrs present?"* check **passes on a tree that lost all real xattrs**.
- **S4 · Restore-fidelity rate per tool family + the unrestorable taxonomy** as eval data (predicts
  the UNVERIFIED rate, R7).

### Nice-to-have

- **N1 · `belay sandbox check`** — a one-shot self-test that the substrate works on this machine.

---

## Technical Considerations

**The integration points already exist**, left by C1:
| C1 artifact | C2 use |
|---|---|
| `proxy.py:300` `Popen(command)` | **The hook.** C2 wraps the spawn in a Seatbelt profile. |
| `trace.py:156` `state_handle: {"status":"absent"}` | **The slot.** C2 fills `present`/`unrestorable`. |
| `TraceWriter` extensible `kind`s | C2 appends `denial`, `network_policy` — no schema break. |
| `hashing.py` sha256 + `belay/jcs-v1` | BTH-1 reuses the hashing seam. |

**Verdict impact: C2 emits no verdict** (that is C4/C5) — **but it is where A1 becomes possible**:
*"the sandbox is not only containment — it is a verdict axis."* C2 supplies the observed effects A1
evaluates, and **originates the `unrestorable` signal** that must reach `UNVERIFIED` rather than be
guessed. **This is the first place the honesty contract becomes load-bearing code.**

**Guardrails.** No agent framework (we sandbox a subprocess we already spawn; we never author or
drive the agent). No LLM judge (zero model calls). No egress. Test-first. ✅ No violation.

---

## Risks & Open Questions

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| **R2** | *Roadmap risk.* **C2 is harder than budgeted and everything blocks on it.** | **High/High** | Narrowest substrate that carries the demo; abstract late. The hard part is **measured and already working** (10.1ms/3.5ms, acceptance PASS) — which retires most of R2 **before planning**. |
| **R-C2-1** | **macOS-only.** CI must move to macOS runners (arm64, billed at a multiplier). Linux is **entirely unverified** — nothing was run there. | High | Stated in the README. Docker/Linux is C2's **second slice** at Phase-1 packaging, which is what *earns* the abstraction. **`ext4` has no reflink and GitHub's Linux runners are ext4**, so clonefile has **no CI equivalent** there — a real Phase-1 problem, not a Phase-0 one. |
| **R-C2-2** | **Seatbelt is deprecated.** Apple could remove it. | Med | No alternative exists for a spawned CLI. Deprecated since ~10.7 and still carrying Apple's own sandboxes and Chrome's renderer. The `Sandbox` seam means a second implementation is additive. |
| **R-C2-3** | **A containment test that passes for the wrong reason.** An over-strict profile **SIGABRTed the process (rc=134)** before it attempted the write — a test asserting only `not target.exists()` **PASSES against a sandbox that murders everything**. | **High** | **Assert the exact exit code AND the exact stderr string**, and pair every deny with a **positive control**. Repo standing rule; has now caught a would-be-vacuous test **three times**. |
| **R-C2-4** | **A restore test that passes for the wrong reason.** The mutation suite **caught itself**: several corruptions were detected by the **parent dir's mtime**, not the property under test. | **High** | **"The hash changed" is NOT evidence the test works — assert on WHICH FIELD changed.** Neutralize dir mtimes; two mutations (symlink-deref, hardlink-break) are **content-identical by construction** and exist purely to kill a content-only hash. |
| **R-C2-5** | **Loopback under deny-default is UNRESOLVED** and the network positive control depends on it. | Med | **Spike first, before designing the suite.** If unsolvable, the control is subprocess-to-subprocess. Stdio servers don't need loopback — another stdio-only argument. |
| **R7** | *Roadmap risk.* Unrestorable/nondeterministic state makes UNVERIFIED the default verdict. | High | The taxonomy + per-family fidelity rate is the measurement. **"Never let a timestamp diff render as FAIL — that's how you train users to ignore the verifier."** |
| **R8** | *Roadmap risk.* **Belay runs untrusted actions; Belay is the attack surface.** | High | M10 threat model. **Never claim a boundary we don't enforce** — hence the network vocabulary is a closed enum and hostname allowlists are **rejected at the API**. |

| **R-C2-6** | **The gate blocks the data path** (~14ms/turn). A SWE-bench run makes many calls; the overhead is real and lands inside the client's timeout budget. | Med | M12. Measured at ~14ms, not seconds (`docker commit` would have been). **Measure total overhead across the Phase-0 corpus and publish it** — if it is material, that is a finding, not something to hide. |
| **R-C2-7** | **The sandbox gets turned off.** If the gate is slow or the scope needs hand-widening per server, someone runs with `--no-sandbox` — and **Belay is a recorder again**, the exact category `CLAUDE.md` says we are not. | **High (thesis)** | M13's zero-config default scope + denials-as-diagnosis + `belay sandbox check`. **Track it as a Phase-0 metric: how often was the sandbox disabled, and why.** A sandbox nobody leaves on is a failed capability regardless of how well it contains. |

**Open questions:**
1. **Loopback** (R-C2-5) — spike before the suite. *Decided: spike.*
2. **Which tool family first?** Recommend the **MCP filesystem server** — it is the demo's substrate.
3. **Does the sandbox profile need per-server customization**, or is one profile + a scope path enough
   for v0? Recommend the latter until a second server proves otherwise. **Related to M13/R3** — if
   every server needs a hand-tuned profile, the invariant-authoring problem arrives early.
4. **Effort breakdown behind "≤5 days"** is not written down, and the **torture-tree fixture is
   substantial and unowned**. Resolve in `tech-plan`.
5. **At what point does the founder turn the sandbox off?** (R-C2-7.) The honest answer shapes M13's
   priority. Worth deciding *before* the Phase-0 corpus runs, because that is when we will find out
   empirically and it will be too late to design for.

---

## Out of Scope

- **Any verdict.** C2 records effects and denials; **C4/C5 judge.** No PASS/FAIL/UNVERIFIED emitted —
  C2 *originates* the `unrestorable` fact, it does not render a verdict from it.
- **Replay / re-invocation** (C3). **Diffing** (C4). **Invariants** (C5).
- **Docker / Linux / bwrap** — C2's second slice, Phase-1 packaging. **Not now.**
- **gVisor, firejail, seccomp.**
- **Streamable HTTP / SSE transports** — stdio only (and loopback is unresolved anyway).
- **Restoring: birthtime · ctime · atime · ownership-when-not-root · sockets · devices · FIFO
  contents.** Each **named**, never silently skipped.
- **Cross-filesystem restore** — REFUSED, not attempted.
- **A `Sandbox` ABC designed for substrates that don't exist yet.** The abstraction is earned by the
  second implementation. `SnapshotBackend.capabilities()` (S1) is the exception, and it is an honesty
  requirement rather than a portability one.

---

## Acceptance Criteria (test-first — failing tests before any code)

From `CAPABILITY_ROADMAP.md` C2, plus the guards the research proved necessary:

| # | Criterion |
|---|---|
| **A1** | **A turn's pre-state restores byte-identically** — `BTH-1(restored) == BTH-1(original)` on a torture tree (regular files, dirs, symlinks, hardlinks, setuid, xattrs, `st_flags`, empty dirs, unicode NFD names). |
| **A2** | **Escape is contained AND recorded** — direct · `../` · symlink-out · `mv`-out · **grandchild**. Each: no file, **exact rc**, **exact stderr**, **and a `denial` record in the trace**. |
| **A3** | **Positive control** — the same write **succeeds** when policy permits, and the same egress **succeeds** under allow-all. *Without this, an unplugged network passes the egress test forever.* |
| **A4** | **Unrestorable yields the signal, never a silent success** — an out-of-substrate entry (FIFO) is **detected and refused with a named cause**; `state_handle` = `unrestorable` + cause. |
| **A5** | **Repair-ablation** — disabling `hardlinks` / `suid` / `dirmtimes` (each, and all) **MUST fail A1**. All on → PASS. |
| **A6** | **Mutation suite, field-attributed** — 12 corruptions each caught **by the field under test**, not by a parent dir's mtime. Incl. two content-identical mutations (symlink-deref, hardlink-break) that a content-only hash cannot catch. |
| **A7** | **Negative controls STABLE** — no-op re-snapshot · atime churn · inode churn must **not** move BTH-1. |
| **A8** | **Hostname allowlist is REJECTED at the API** — not accepted-and-unenforced. |
| **A9** | **`realpath` normalization** — a scope given as `/tmp/x` must behave identically to `/private/tmp/x` (no silent grant-nothing). |

All: **deterministic, no network, CI-runnable** (macOS runners).

> **Explicitly NOT asserted, because it would be false:** Linux behaviour · cross-filesystem restore ·
> birthtime/ctime/atime restoration · ownership when not root · that Seatbelt is not deprecated.
