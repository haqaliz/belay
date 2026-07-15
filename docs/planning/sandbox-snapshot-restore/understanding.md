# C2 — Sandbox + execution boundaries: Understanding note (Phase 2)

**Status:** pre-PRD. Every load-bearing claim below was **run on this machine** and its output
recorded. Claims I could not verify are marked UNVERIFIED and must not be cited as fact.

**Source:** `docs/planning/_card/issue.md` (quotes `CAPABILITY_ROADMAP.md` §C2 verbatim — the
authoritative source; no inline brief was authored, deliberately).

---

## 1. What the work is really asking

Not "add a sandbox." C2 is **the engine's floor**: you cannot re-execute a turn without restoring
the state it ran against, so *containment and verification are the same machinery*. C3/C4/C5 all
block on it. It is **risk R2 (High/High)** and the schedule's critical path.

**The integration points already exist**, left deliberately by C1:
- `src/belay/proxy.py:300` — `subprocess.Popen(command, ...)` spawns the MCP server. **C2 wraps
  that spawn.** That is the whole hook.
- `src/belay/trace.py:156` — `"state_handle": {"status": "absent"}`, the **three-state slot C2
  fills** (`present` / `unrestorable`). C1's comment explains why: overloading `absent` to mean both
  *"C1-era trace"* and *"C2 tried and failed"* is how a false PASS is born.
- `TraceWriter` already has extensible record `kind`s → C2 appends `denial` records without a schema
  break.

## 2. Verdict axes

C2 emits **no verdict** (that is C4/C5), but it is **where A1 becomes possible**: *"the sandbox is
not only containment — it is a verdict axis"* (`CLAUDE.md`). C2 supplies the observed effects A1
evaluates against, and **originates the `unrestorable` signal** that must propagate to `UNVERIFIED`
rather than be guessed at. This is the first place the honesty contract becomes load-bearing code.

## 3. Verified findings — macOS sandbox

**`sandbox-exec` (Seatbelt) is DEPRECATED and FUNCTIONAL. Both. Neither cancels the other.**
- Exists: `/usr/bin/sandbox-exec`. `man 1 sandbox-exec` says *"DEPRECATED"*.
- Apple's suggested replacement (App Sandbox) **requires entitlements + a signed app bundle**, which
  a `Popen` of a third-party MCP server **can never satisfy**. **There is no third option.**
- **Verified containment matrix** — every vector denied (`Operation not permitted`, rc=1, no file):
  direct write outside scope · `../` traversal · symlink-inside→outside · `mv` out of scope ·
  **write from a grandchild process**.
  > The last two are load-bearing: SBPL matches on the **resolved** path, and **the sandbox is
  > inherited across fork/exec** — an MCP shell server (mostly a process spawner) cannot launder a
  > write through a child.
- **Network:** deny-all works (`connect → PermissionError [Errno 1]`, no packet, deterministic
  offline). Port allowlists work.
  **🔴 Per-host allowlists are IMPOSSIBLE** — `(remote ip "1.1.1.1:*")` is a *compile-time error*:
  `host must be * or localhost in network address`.
  → The only honest vocabulary is **`deny-all | allow-all | allow-ports`**. Per *"never claim a
  boundary we don't enforce"*, v0 must **reject a hostname allowlist at the API**, not accept one and
  silently not enforce it.
- **🟡 UNRESOLVED:** loopback bind under deny-default could not be made to work. Affects
  SSE/HTTP-transport MCP servers and **the positive-control design for network tests**. Stdio
  servers unaffected — another argument for stdio-only in v0. **Needs a spike.**
- **AF_UNIX sockets are governed by `network*`, not `file-write*`** — under `(deny network*)` a unix
  socket bind *inside* the allowed scope was still refused.

**Docker is INSTALLED and BROKEN here.** `docker info` → 500; `docker ps` hung, needed SIGKILL.
Not a fallback we currently have. `colima`/`podman` absent.

**🔴 Linux is UNVERIFIED — literature only, nothing run.** `bwrap` looks best on paper (single static
binary, argv-driven, bind-mounts give scope *by construction*), **but** it needs unprivileged user
namespaces, and **Ubuntu 23.10+ restricts those via AppArmor** — and GitHub Actions runners are
Ubuntu. **Whether `bwrap` runs on stock `ubuntu-latest` is unknown and decides the Linux story.**

## 4. Verified findings — snapshot fidelity (APFS)

**`cp -Rc` (APFS clonefile) preserves:** file mode ✅ · file `mtime_ns` ✅ · symlink stays a symlink
with correct target ✅ · empty dirs ✅.

**🔴 It LOSES the symlink's own mtime.** Measured: `1784131338477367249 → 1784131338482798035`.
> **This decides the tree hash.** A hash including symlink mtime fails every restore. A hash
> excluding it is honest **only if we say so**. Silently omitting it while claiming *"byte-identical"*
> is a false PASS manufactured by our own hash — structurally identical to the annotation-default bug
> C1 caught.

**🔴 APFS is case-INSENSITIVE by default** (verified: `Foo` matches `foo`). A tree containing both
`Foo` and `foo` **cannot round-trip**.

**🟡 Unicode:** APFS **preserves exact bytes on write** (NFC stored as NFC — no silent
normalization ✅), **but lookup is normalization-insensitive**: `café` (NFC) and `café` (NFD)
resolve to the **same file**, so both cannot coexist.

**Performance (from the sandbox brief, cited not re-run):** 57MB / 300 files → clone 0.03s, restore
0.03s, vs 0.07s plain copy. **The argument this makes is the important part:** A2 must restore
pre-state before *every* re-invocation. At 50 turns, 30ms vs `docker commit`-seconds is the
difference between replay being invisible and replay being why nobody runs Belay. **The sandbox
substrate and the snapshot substrate want to be the same filesystem** — on macOS, APFS.

## 5. 🔴 The decision this forces (for the gate)

**No single substrate covers macOS dev and Linux CI.** Seatbelt is macOS-only; `bwrap` is
Linux-only; Docker covers both in principle and is *broken here*.

The roadmap says **ship exactly one** — *"the abstraction is earned by the second, not designed for
it."* So this is a conscious choice, not a detail:

- **Ship Seatbelt** → verified today, zero deps, no daemon, APFS clone makes snapshot ~free, carries
  the actual demo (an agent + MCP fs/shell server on the founder's laptop). **Cost: macOS-only; CI
  must be `macos-14`/`macos-15` (arm64, billed at a multiplier).**
- **Ship bwrap** → Linux/production-first, **but the dev machine cannot test it**, trading a verified
  substrate for an unverified one. `CLAUDE.md`'s own logic cuts against this: a sandbox we cannot
  test is not useful.
- **Ship Docker** → covers both in principle; broken here; daemon-dependent, and a daemon has a
  failure mode where the sandbox is *unavailable* and you must choose between running unsandboxed
  (never) or refusing to run. The kernel is always up.

**Recommendation: Seatbelt, macOS-only, stated plainly in the README.** Linux/bwrap becomes the
**second** implementation — which is precisely what *earns* the abstraction. Designing a `Sandbox`
ABC now against one implementation would encode SBPL's quirks as universal: **bwrap's bind-mount
model and SBPL's policy-match model disagree about what "scope" means**, and that is invisible until
the second exists.

## 6. 🔴 The insight that changes A2's soundness

**`openWorldHint` should hard-gate replay.** A tool call that touched the network under an allow-all
policy is **`UNVERIFIED` for A2, full stop** — replaying it would either **double-commit** the side
effect (POST to Stripe, send mail, mutate a remote DB) or diff against state the sandbox never owned.

→ **deny-egress-by-default is not posture; it is the precondition that makes A2 replay *sound*.**
And C1's tri-state annotation snapshot is the declared marker that gates it. C1's work and A2's
validity are directly connected, which neither the roadmap nor C1's PRD noticed.

## 7. The `unrestorable` taxonomy (named causes, not guesses)

| Cause | Meaning |
|---|---|
| `REMOTE_SIDE_EFFECT` | Effect already outside the box. **Uncontainable AND unrestorable.** Replay would repeat it. Gated by `openWorldHint` / allow-all network. |
| `PROCESS_INTERNAL_STATE` | FDs, connection pools, auth sessions, in-memory caches. Restorable in principle, **not by an fs snapshot**. Kill+respawn a stdio server per replay avoids most — another stdio-only argument. |
| `NONDETERMINISTIC_INPUT` | Clock, `random`/`urandom`, PIDs, hostname, `$TMPDIR` (per-boot on macOS), locale, scheduler interleaving. **Seatbelt virtualizes none of these — it is access control, not a hypervisor.** |
| `OUTSIDE_BOUNDARY` | Anything pre-sandbox; the proxy's own writes; **and the agent's built-in `Bash`/`Edit`** — which don't traverse MCP, aren't spawned by us, aren't in our sandbox. **The sandbox's limit and the MCP boundary's limit are the SAME limit.** Say it once, loudly. |
| `POLICY_INEXPRESSIBLE` | The substrate cannot express the requested policy (macOS per-host network). The honest answer is "cannot enforce", not a profile that pretends. |
| `FIDELITY_GAP` | A property the snapshot cannot preserve (symlink mtime; case-collision; unicode-normalization collision). **Surfaced, never silently dropped.** |

> **"Never let a timestamp diff render as FAIL — that's how you train users to ignore the verifier."**

## 8. Test traps (all three found empirically, not theorised)

1. **The over-strict profile that SIGABRTs the process.** A profile lacking `mach-lookup` **killed
   `/bin/sh` at launch (rc=134)** before it attempted the write. A test asserting only
   `not target.exists()` **PASSES against a sandbox that murders everything.**
   → **Assert the exact exit code AND the exact stderr string.**
2. **The `/tmp` realpath trap — a silent-grant bug, not just a test bug.** `/tmp` is a symlink to
   `private/tmp`. A profile granting `(subpath "/tmp/x")` **grants nothing**: I wrote to the
   supposedly-*allowed* dir and got `Operation not permitted`. **Belay must `realpath()` every path
   before it reaches a profile**, or it will hand users a policy that silently denies their own work.
3. **No positive control = no evidence.** Every "blocked" assertion is worthless without a paired
   test proving the same op **succeeds** when policy permits. Without it, an unplugged network passes
   the egress test forever. **This is the repo's standing anti-vacuity rule, and it has now caught a
   would-be-vacuous test three times.**
4. `rc=$?` after a pipe reports the *pipe's* status — a denied write reported rc=0.

## 9. Guardrail check

| Guardrail | C2 |
|---|---|
| No agent framework | ✅ We sandbox a subprocess we already spawn. We never author/drive the agent. |
| No LLM judge | ✅ Zero model calls. |
| UNVERIFIED never PASS | ✅ **This is C2's core deliverable** — the `unrestorable` signal with a named cause. |
| No raw-data egress | ✅ Local only. And deny-egress-by-default is now a *soundness* requirement too. |
| Never claim coverage we don't have | ⚠️ **The sharpest risk here.** Per-host network is inexpressible; symlink mtime is lost; case/unicode collisions can't round-trip; Linux is unverified. **Each must be stated, not implied away.** |
| Test-first | ✅ |

## 10. Open questions for the PRD

1. **Substrate: Seatbelt (macOS-only) vs bwrap (Linux-only) vs Docker (broken here)?** §5. *The
   decision.*
2. **Tree hash contents** — given symlink mtime is unpreservable, what's in v1 and what's an
   explicitly documented exclusion? §4.
3. **Loopback under deny-default** — unresolved; blocks the network positive control. Spike first.
4. **Does `bwrap` run on stock `ubuntu-latest`?** Unknown; decides the Linux story.
5. **Scope of "restorable"** — the roadmap says *"container filesystem overlay + one tool family"*.
   Which tool family? (Recommend: MCP filesystem server — it is the demo's substrate.)
6. **Does `openWorldHint`-gating belong in C2 or C4?** The *signal* is C1's; the *gate* is A2's.
   C2 should probably record the network-policy-in-force per turn and let C4 decide.
