# C2 — Sandbox + execution boundaries: Understanding note (Phase 2)

> ## ✅ DECIDED — Seatbelt + clonefile, macOS-only. Unblocked.
>
> **Docker was chosen first, then reversed** (founder, 2026-07-15). Recorded rather than tidied
> away, because the reasoning is the useful part:
>
> - **Docker is wedged on this machine** — the Desktop process is alive (PID 52219) and the socket
>   exists, but the daemon behind it is dead: **every command hangs >25s**, incl. `docker version`.
>   Re-tested with real timeouts; not a startup window. Reviving it may require a factory reset,
>   which destroys the founder's containers/images/volumes.
> - **`docker run` self-hosting is a *Phase 1* deliverable** (`ROADMAP.md`, Phase 1 packaging row).
>   **Phase 0 explicitly ships no packaging:** *"There is no dashboard, no packaging, and no launch
>   in this phase... Optimize for learning whether to continue."* Choosing Docker meant solving a
>   **Phase 1 portability problem during Phase 0**, while blocking Phase 0 on a dead daemon and
>   paying ~100× on the operation that runs before **every** replay.
> - **The Phase 0 corpus runs on this laptop** — ≥50 SWE-bench-lite runs (`ROADMAP.md:103`), on
>   macOS, where Seatbelt is verified and Docker is dead.
> - **The roadmap says ship exactly one and abstract late.** Seatbelt *is* that one. Docker/Linux
>   becomes C2's **second** slice when Phase 1 packaging actually needs it — earning the abstraction
>   rather than guessing it, which matters because SBPL and containers genuinely disagree about what
>   "scope" means.
>
> **The cost, stated so it is not a surprise later: C2 is macOS-only, CI moves to macOS runners, and
> the README must say so plainly.**

### Decisions taken (founder, 2026-07-15)

| # | Decision | Status |
|---|---|---|
| **Substrate** | **Seatbelt (`sandbox-exec`) + `clonefile(2)` via ctypes — macOS-only** | ✅ verified working; C2 proceeds |
| **Fidelity** | `clonefile(CLONE_ACL)` + 3 sidecar repairs (hardlinks, setuid, dir-mtimes) + **detect and REFUSE out-of-substrate loudly** | ✅ valid again — matches the substrate |
| **`openWorldHint` gate** | **C2 records the network policy in force as a fact; C4 decides the verdict.** Capture/sandbox stay opinion-free | ✅ |
| **Loopback** | **Spike before designing the test suite** — the network positive control depends on it | ✅ |
| ~~Docker~~ | Reversed. Becomes C2's second slice at Phase 1 packaging | ⏸️ deferred |

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

> **⚠️ Two corrections to earlier claims in this session (my error, recorded not buried):**
> 1. The lost symlink mtime was **`cp -Rc`**, *not* clonefile. **`cp -Rc` is measurably WORSE** — it
>    loses hardlinks, setuid, **and** mtime on symlinks/FIFOs (it recreates non-regular files fresh).
>    **Do not shell out to `cp -Rc`. Call `clonefile(2)` via ctypes.**
> 2. **"APFS normalizes" was wrong.** APFS is normalization-**preserving** and
>    normalization-**insensitive**: NFD bytes round-trip verbatim (unlike HFS+, which normalized on
>    store). **"Byte-identical" IS an honest claim** — *provided the hash uses raw readdir bytes*.
>    The trap is not the filesystem; it is a hash built from `str` paths after any normalization
>    step, which makes the drift invisible.

**`clonefile(2)` is reachable from stdlib via `ctypes` — zero deps hold, no shelling out.**
`os.clonefile` does not exist (verified: `[a for a in dir(os) if 'clone' in a] == []`). Via
`ctypes.CDLL(find_library("c"))` it **clones whole trees recursively in a single call**.
**`CLONE_ACL` (0x0004) is mandatory** — with flags=0 it **silently drops ACLs** (verified against the
real SDK header, not memory).

**Cost (412MB, 4804 files, measured):**
| Mechanism | Time | Disk |
|---|---|---|
| `clonefile(CLONE_ACL)` | **71ms** (27ms warm) | **3.1MB** (COW verified via `df`, not `du`) |
| `shutil.copytree` | 813ms | ~412MB |
| `cp -a` | 1206ms | 422MB |
| `bsdtar` create+extract | 3566ms | ~412MB |

**Fidelity gaps vs a torture tree (measured):**
| Mechanism | Loses |
|---|---|
| `bsdtar` | **birthtime only** — the fidelity champion; the only mechanism whose tree hash matched exactly |
| `cp -a` | hardlinks, birthtime |
| **`clonefile(CLONE_ACL)`** | **hardlinks, setuid, dir-mtime**, birthtime → *all three repairable* |
| `cp -Rc` | hardlinks, setuid, **symlink/FIFO mtime**, birthtime |
| stdlib `tarfile` (PAX) | xattrs, `st_flags`, sparseness, **ns-mtime DRIFT** (PAX stores float seconds), birthtime |
| `shutil.copytree` | **xattrs (⇒ resource forks)**, sparseness, hardlinks, **ABORTS on FIFO**, birthtime |

**🔴 `os.listxattr` DOES NOT EXIST ON macOS** — CPython gates it to Linux. Therefore
`shutil.copystat` **silently drops every xattr on darwin**, and **macOS resource forks *are* the
`com.apple.ResourceFork` xattr** (verified). Whatever preserves xattrs preserves forks; `copytree`
preserves neither. Reading xattrs on macOS at all requires ctypes.

**🔴 Hardlink identity is the sharpest trap.** Only `bsdtar`/stdlib-`tarfile` preserve it. clonefile,
`cp -a`, `cp -Rc`, `copytree` **all** break `nlink=2` into two independent inodes — **content-identical,
so a content-only hash blesses it**.

**🔴 clonefile strips setuid** (`0o4711 → 0o0711`, security-motivated, silent) and **resets dir
mtimes**. Both invisible to a content-only hash.

**🟡 APFS is case-preserving, case-INSENSITIVE** — and nastier than expected: writing `casetest`
over `CaseTest` **keeps the name and silently overwrites the contents**. This does **not** break
same-filesystem restore (a `README`/`readme` collision cannot exist in the original either). It
breaks **cross-filesystem** restore (an ext4-captured tree replayed onto APFS) — which must be
**REFUSED, not attempted**.

**🟡 APFS REJECTS invalid-UTF-8 filenames** (`OSError 92 EILSEQ`, verified). Legal on ext4,
impossible on APFS. A cross-platform boundary, not a bug.

**Two ambient traps that would silently rot the suite:**
- **`com.apple.provenance` is injected by macOS on every file it creates.** After `copytree` dropped
  the real xattr, the file **still had one** — so a naive *"xattrs present?"* check **passes on a tree
  that lost all real xattrs**. Must be on an explicit ignore list.
- **`open(fifo,"rb").read()` BLOCKS FOREVER** (verified; it hung the researcher's own suite). A naive
  tree walker deadlocks. **Gate on `S_ISREG` before opening anything.**

**The argument that decides the substrate:** A2 must restore pre-state before *every* re-invocation.
At 50 turns, **10ms vs `docker commit`-seconds** is the difference between replay being invisible and
replay being why nobody runs Belay. **The sandbox substrate and the snapshot substrate want to be the
same filesystem** — on macOS, APFS.

**Measured acceptance (the roadmap's actual test):**
```
pre-state hash    : e467b9b5…
snapshot          : 10.1 ms   (snapshot hash matches: True)
agent mutates     : 2380fa6c…  (differs: True)
restore           :  3.5 ms
post-restore hash : e467b9b5…
ACCEPTANCE: hash(restored) == hash(original) -> True
```
Backend = **`clonefile(CLONE_ACL)` + a sidecar repair of its three measured gaps** (relink hardlinks;
re-chmod setuid; restore dir mtimes deepest-first).

## 4b. The tree hash: BTH-1 (concrete, versioned, and it discriminates)

**A content-only hash would have blessed EVERY failure above.**

**IN:** version tag `BTH-1` · **raw readdir PATH BYTES** (never `str`, never normalized) · kind ·
`S_IMODE` (carries setuid/setgid/sticky) · `mtime_ns` · `st_flags` · uid/gid · size + sha256 content
(regular files) · symlink target as **raw bytes** · `st_rdev` · sorted `(xattr_name, sha256(value))`
minus ignore-list · **hardlink GROUP ID = first path in the group** (*not* the inode number).

**OUT, deliberately, and documented:** inode numbers + `st_dev` (unstable across restore) · **atime
(self-invalidating — hashing the tree reads files and changes it)** · ctime (unsettable) ·
**birthtime (unsettable by anyone, incl. tar)** · `st_blocks` (sparseness → a separate WARN, not an
identity diff) · raw `nlink` (implied by group structure).

**Ordering:** records sorted **by raw path bytes** — readdir order is not stable, and sorting by
`str` would reintroduce the normalization trap. **Structure:** `sha256("BTH-1\n" + concat(sha256(rec)))`
with `\x00`-joined `key=value` fields **so failures are legible field-by-field** rather than "two hex
strings differ".

**It is not a tautology** — measured: only `bsdtar` reproduces the tree (`MATCH`); clonefile, `cp -a`,
stdlib tarfile, and copytree all `DIFFER`. **Negative controls STABLE:** no-op re-extract · atime
churn · inode-number churn.

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

**🔴 The snapshot research makes the macOS-only case STRONGER, and the Linux case worse:**
**`ext4` has NO reflink**, and **GitHub Actions Linux runners are ext4** — so `clonefile`'s
copy-on-write trick has **no Linux equivalent in CI**. The Linux fallback is `bsdtar` (**50× slower**
— 3566ms vs 71ms) or a plain copy (**~412MB of real disk per snapshot instead of 3.1MB**). Also
`os.listxattr` exists on Linux but **not macOS**, so **stdlib copy fidelity is strictly better on
Linux** — meaning **a macOS-green test says nothing about Linux, and vice versa.**

> **This forces a design conclusion regardless of which substrate we ship:** a `SnapshotBackend`
> must expose **`capabilities()`**, the manifest must record **which backend produced it**, and
> restore must **REFUSE across backends whose capability sets differ**. That is not the premature
> abstraction the roadmap warns against — it is the honesty contract: a tree captured where xattrs
> exist cannot be truthfully restored where they don't, and pretending otherwise is a false PASS.

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
| `FIDELITY_GAP` | A property the snapshot cannot preserve. **Surfaced, never silently dropped.** |

**Expanded, from measurement (each is a named cause, never a silent skip, never PASS):**
- **Physically unsettable** → excluded from the hash *and documented*: `UNRESTORABLE_BIRTHTIME`
  (unsettable by **anyone**, incl. tar; APFS also clamps it to mtime), `UNRESTORABLE_CTIME`,
  `UNRESTORABLE_ATIME` (**self-invalidating** — hashing reads files and changes it),
  `UNRESTORABLE_INODE_IDENTITY`.
- **Privilege-gated:** `UNRESTORABLE_OWNERSHIP` (non-root cannot restore foreign uid/gid),
  `UNRESTORABLE_DEVICE_NODE` (mknod needs root), `UNRESTORABLE_IMMUTABLE_FLAG`.
  > Self-inflicted variant hit for real: an ACL of *"everyone deny delete"* made the researcher's own
  > scratch dir **undeletable**. **Snapshot GC must handle ACL'd/`uchg` trees or it strands disk.**
- **Out-of-substrate fs objects:** `UNRESTORABLE_SOCKET`, `UNRESTORABLE_FIFO_CONTENTS` (*the node
  restores; the queued bytes don't*), `UNRESTORABLE_OPEN_FD_STATE`, `UNRESTORABLE_MOUNT`,
  `UNRESTORABLE_DEV_PROC`.
- **Cross-filesystem IMPOSSIBILITY — must REFUSE, not attempt:** `UNRESTORABLE_CASE_COLLISION`
  (`README`+`readme`, ext4→APFS), `UNRESTORABLE_INVALID_UTF8_NAME` (EILSEQ, verified),
  `UNRESTORABLE_NORMALIZATION_COLLISION` (NFC+NFD coexisting on ext4, colliding on APFS),
  `UNRESTORABLE_XATTR_UNSUPPORTED`.
- **Outside the filesystem entirely — say this loudest:** `UNRESTORABLE_EXTERNAL_SERVICE`,
  `UNRESTORABLE_NETWORK_EFFECT`, `UNRESTORABLE_WALL_CLOCK` (*re-execution happens at a different
  time; time-dependent calls diverge legitimately*), `UNRESTORABLE_RUNNING_PROCESS`,
  `UNRESTORABLE_RANDOMNESS`, `UNRESTORABLE_DATABASE_STATE`.
  **This class is where A2/replay stops being able to say anything. The roadmap must not over-claim
  past it.**

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
5. **🔴 The mutation suite caught ITSELF passing for the wrong reason.** All 12 corruptions initially
   reported CAUGHT — but several were caught by the **parent directory's mtime** changing, not by the
   property under test. *"Symlink retargeted"* was caught by `d`'s mtime. After neutralizing dir
   mtimes it was **still** confounded by the symlink's own fresh mtime; only
   `os.utime(..., follow_symlinks=False)` isolated it. **This is the SIGABRT trap in another costume:
   right verdict, wrong reason — and it rots the moment dir mtimes are restored properly.**
   > **THE RULE FOR THIS REPO: "the hash changed" is NOT evidence the test works. Assert on WHICH
   > FIELD changed.** Two mutations (symlink-deref, hardlink-break) are **content-identical by
   > construction** and exist purely to kill a content-only hash.
6. **Repair-ablation must be a permanent test.** Disable each repair → the acceptance test MUST fail.
   Measured: `('hardlinks',)` → FAIL · `('suid',)` → FAIL · `('dirmtimes',)` → FAIL · all three →
   FAIL · all repairs on → PASS. **Every repair is load-bearing**, and this is the guard that stops
   someone "simplifying" one away and leaving a green suite.
7. **Narrowing the substrate is only honest if out-of-substrate entries are DETECTED and REFUSED
   loudly.** Silently ignoring a FIFO is exactly the *"UNVERIFIED rendered as PASS"* `CLAUDE.md`
   forbids.

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
