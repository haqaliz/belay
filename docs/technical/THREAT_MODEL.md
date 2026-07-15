# Belay threat model (C2: the Seatbelt sandbox)

**Belay executes untrusted agent actions. That makes Belay itself an attack surface.**
This document states what the C2 sandbox enforces, what it cannot express, and what it
cannot see at all. Every "enforced" claim below names the test that measures it. Every
"not enforced" claim is here because leaving it out would be the failure this project
exists to catch, committed by us.

**Scope of this document:** the sandbox and snapshot layer as it exists today, on
**macOS (darwin/arm64)**. Nothing here has ever been run on Linux — see
[Platform](#platform-macos-only-and-that-is-not-a-formality).

---

## Read this first: the sandbox is not yet in the proxy's path

Everything below describes what `belay.sandbox.seatbelt` enforces when a process is run
under it. **The proxy does not yet run your MCP server under it.**

`proxy.py` spawns the server with a plain `subprocess.Popen`. `BELAY_SANDBOX_SCOPE` names
the tree the **turn gate snapshots**; it does not contain anything. Today the sandbox is
reached through `belay sandbox check` and as a library, and it is real — but a server
started by `python -m belay.proxy` is **not contained by any of the boundaries described
here**.

Stated at the top because the alternative is a reader who concludes from the rest of this
document that their proxied server is sandboxed. It is not. Wiring containment into the
proxy's spawn path is the next step.

**M13 is therefore half-delivered, and saying so is the point of this section.** The default
scope (`scope.py`) is a real mechanism with its zero-config claim proven end-to-end against
a real MCP server — but it is reachable only from `belay sandbox check`. **R3 — "nobody
authors the invariant" — is mitigated for the check and not yet for a real run.**

**Why the default scope was not simply wired into the proxy now.** Because on its own it
would make things worse, not better. The TMPDIR relocation only earns its cost when a
sandbox is denying the real `$TMPDIR`. With no sandbox on the proxy path, the server can
already write to `/var/folders` unimpeded, so relocating `TMPDIR` would buy **no**
containment while adding all of its costs: temp files in the user's tree, temp files in
every turn's snapshot, and the socket/FIFO-in-TMPDIR hazard below turning every turn
`unrestorable`. The two halves must land together or not at all.

And landing them together is a real unit of work, not a bolt-on:

- **`seatbelt.run` is shaped for a short-lived command** — a blocking `subprocess.run` that
  unlinks the profile in a `finally` once the child exits. The proxy streams a long-lived
  server over pipes. Wiring needs a "give me the argv, keep the profile alive" seam that
  does not exist yet.
- **Denials are inferred from the child's stderr after it exits.** A long-lived proxied
  server never reaches that point, so denial capture for a live run needs a different
  mechanism entirely.
- **The network policy is an unmade product decision.** `deny-all` breaks any server that
  legitimately needs the network; `allow-all` contains nothing. There is no env var for it
  and picking one silently would be Belay authoring the boundary — the exact thing the
  default scope exists to avoid.

---

## The one-paragraph version

The sandbox contains **what a process can change**, on this machine, for as long as the
process runs. It does not contain what a process can **read**, it cannot express a
**per-host** network rule, it does not virtualise a clock or an entropy source, and it
sees **nothing** an agent does through its own built-in tools. What it does enforce, it
enforces in the kernel and we can prove it. What it does not, we say here rather than
letting someone infer it from the word "sandbox".

---

## What IS enforced

### Filesystem: five escape vectors, all contained and recorded

`tests/test_containment.py::test_escape_vector_is_contained_and_recorded` is parametrized
over five vectors. Each asserts the write was refused, the target does not exist, the
denial was recorded, and the recorded path is the one the child reported.

| Vector | The attack |
|---|---|
| `direct_write` | Write straight to a path outside the scope. |
| `dotdot_traversal` | `cd scope && echo > ../outside/f` — escape by relative path. |
| `symlink_out` | A symlink inside the scope pointing out of it; write through it. |
| `mv_out` | `mv` a file from inside the scope to outside. |
| `grandchild_write` | `sh -c "sh -c 'echo > outside/f'"` — escape via a spawned process. |

**`grandchild_write` is the one that matters most in the shape we actually ship.** The
Seatbelt profile is inherited across `fork`/`exec`, and an MCP shell or filesystem server
is mostly a process spawner. A boundary that held only for the direct child would be
worthless here.

The scope is `realpath`ed before the profile is built
(`test_scope_given_through_a_symlink_behaves_identically`). This is load-bearing, not
hygiene: `/tmp` is a symlink to `private/tmp`, and a profile granting `(subpath "/tmp/x")`
grants **nothing** — measured. Unresolved, Belay would hand a user a policy that silently
denies their own work while reading correctly on the page.

The scope is also escaped before it is interpolated into the policy
(`test_a_scope_containing_a_quote_cannot_break_out_of_the_profile`). A scope is data being
pasted into the language that enforces the policy; an unescaped `"` would be a policy
injection into the sandbox itself.

### Network

- **`deny-all`** is verified, and verified *against a live listener* so the refusal is the
  sandbox rather than an absent server
  (`test_deny_all_denies_the_very_same_loopback_connection`).
- **`allow-ports`** is verified in both directions: an allowed port connects
  (`test_loopback_is_reachable_while_real_egress_is_denied`), and a port outside the list
  is refused while a listener is live on it (`test_a_port_outside_the_allowlist_is_denied`).
- **`allow-all` is never the default and must be asked for**
  (`test_allow_all_is_not_the_default_and_must_be_asked_for`).

### Off macOS, the module raises rather than degrades

`test_unsupported_platform_is_raised_not_silently_degraded`. A no-op that returned success
would be Belay claiming a containment boundary that does not exist on that platform.

---

## What is NOT enforced, or cannot be expressed

### Reads are not scoped at all

The profile allows `file-read*` **wholesale**. The scope grants *writes*.

A sandboxed MCP server can read anything the invoking user can read: `~/.ssh`,
`~/.aws/credentials`, any file on the disk. The sandbox contains what the child can
**change**, not what it can **see**. Combined with a network policy other than `deny-all`,
a malicious server can read a secret and send it. **`deny-all` is what stands between
"can read your keys" and "can exfiltrate your keys"** — it is not a default we chose for
tidiness.

### Per-host network allowlists are a COMPILE-TIME ERROR, and are rejected at the API

SBPL cannot express them. Measured against the real compiler — **both** an IP literal and a
hostname are refused, so the address *form* is not the issue; any host that is not `*` or
`localhost` is:

```
$ sandbox-exec -f perhost.sb /usr/bin/true      # (allow network-outbound (remote ip "1.1.1.1:*"))
sandbox-exec: host must be * or localhost in network address
```

`tests/test_sbpl_limits.py::test_a_per_host_rule_is_a_compile_error` pins this against
`sandbox-exec` itself, with a control proving the rule `allow-ports` *does* emit compiles.
That test exists because the two API tests below prove only that **our Python raises** —
which is a different claim, and the weaker one. If a future macOS gained per-host syntax,
the stated reason for this whole restriction would silently become false and only that test
would notice.

So `NetworkPolicy` is a **closed enum** — `deny-all | allow-all | allow-ports` is the
entire vocabulary — and `allow_ports()` rejects anything that is not an `int` port, a
hostname included (`test_network_policy_rejects_a_hostname_allowlist`,
`test_network_mode_is_a_closed_enum`). Note the mechanism precisely: it is a **type check**,
not host detection. `allow_ports(["8080"])` is refused too, with a message about host
allowlists that is wrong about that particular input — the refusal is right, its
explanation is not.

The alternative was to accept a hostname and drop it. The user would then believe their
traffic was confined to an allowlist while it was confined to nothing. **A boundary that is
accepted and not enforced is worse than one that is refused**, because someone will trust
it. If you need per-host egress control, it is not here; put it in a layer that can
actually express it.

`allow-ports` means exactly: **outbound, to loopback, on these ports.** Nothing else.

### `network-inbound` is never granted, and would not mean what it looks like

The spike measured that `(local ip "localhost:*")` does **not** confine the bind address:
a process granted inbound can still bind `0.0.0.0`. The grant scopes the **port**, not the
interface.

Belay's sandboxed side is always the client dialing a trusted host-side socket, so it is
never granted the thing whose confinement does not hold. Do not add `network-inbound` to
the profile on the assumption that it restricts *where* a server listens. It does not.

### Seatbelt is access control, not a hypervisor

It virtualises **no clock, no entropy, no PIDs**. A sandboxed process reads the real time,
the real `/dev/urandom`, and real process ids.

This is why `UNRESTORABLE_WALL_CLOCK` and `UNRESTORABLE_RANDOMNESS` exist in
`substrate.UnrestorableCause` and are explicitly **deferred to C3/C4** rather than claimed
here: a snapshot cannot make `urandom` replay the same bytes, and no filesystem boundary
can. A replay that diverges for those reasons diverges legitimately, and anything that
reported such a run as a clean re-execution would be manufacturing a verdict.

### The sandbox does not contain effects that already left the box

A network call that was permitted and completed cannot be un-made by restoring a
directory, and no filesystem scan can see that it happened.
`UNRESTORABLE_EXTERNAL_SERVICE` and `UNRESTORABLE_NETWORK_EFFECT` name this, and are
deferred to C4 with the network policy recorded as the grounding fact
(`test_network_policy_is_recorded_as_a_fact`).

---

## Provenance: our denial records are INFERRED, and here is what that costs

Every denial Belay records carries:

```json
{"kind": "denial", "inferred": true, "source": "child-stderr", "detail": "<the verbatim line>"}
```

pinned by `test_denial_records_state_their_own_provenance`.

**What the record actually claims: *the child reported a permission error*. Not: *the
kernel told us it denied X*.** Those are different facts and the difference is not
academic.

**Why.** Seatbelt reports violations to the **system log**, not to the child's stderr in
any structured form, and not to the invoking process at all. There is no API that hands us
"the kernel denied this operation on this path". So Belay reads the child's own complaints
(`Operation not permitted`) and infers a denial from them. `log stream --predicate` would
give the kernel's own account and is the honest upgrade; it is async and needs a
subscription running before the child starts, so v0 takes the simple path and says so.

**What it costs — three failure modes, all real:**

1. **A denial the child does not print is invisible.** Measured, and this is the important
   one: a Python server whose `$TMPDIR` is outside the scope dies with
   `[Errno 2] No usable temporary directory found in [...]` and **no denial record at
   all**. `tempfile` catches every `EPERM` itself and reports its own aggregate error,
   never printing the marker string. The scope killed the server and Belay's denial list
   is **empty**. `tests/test_default_scope.py::test_the_filesystem_server_fixture_would_notice_a_tight_scope`
   pins this exact behaviour, and `belay sandbox check` keys on the **exit code** as well
   as on denials because of it.
2. **A child that lies produces a false denial.** Any process can print
   `foo: /etc/passwd: Operation not permitted` to stderr without being denied anything.
   Belay would record a denial that never happened. **A denial record is not evidence
   against an adversarial server** — it is a diagnostic for an honest one.
3. **The path is parsed, not reported.** Unix tools print `prog: <subject>: <error>`, so
   the subject is recovered by splitting on `": "`. A path containing `": "` parses wrong.
   `EACCES` ("Permission denied") is deliberately **not** treated as a denial marker: that
   is ordinary filesystem permissions, and claiming it would attribute the user's own
   `chmod` to Belay's boundary.

**Containment does not depend on any of this.** The boundary is the kernel's and it holds
whether or not the record is accurate or written at all
(`test_run_without_a_trace_still_contains`). Inference affects **what we can say about**
the denial, never whether it happened.

---

## Seatbelt is deprecated by Apple. It is also functional, and there is no third option.

Both halves are true and both belong in a threat model.

**It is deprecated**, in Apple's own words. From `man sandbox-exec` on this machine:

> `sandbox-exec – execute within a sandbox (DEPRECATED)`
>
> The sandbox-exec command is DEPRECATED. Developers who wish to sandbox an app should
> instead adopt the App Sandbox feature described in the App Sandbox Design Guide.

`man 3 sandbox_init` says the same of the underlying call. Apple may change or remove it,
and would owe us no notice. That risk is real and accepted, not hidden.

**It is also what actually works.** Read Apple's replacement carefully: *"Developers who
wish to sandbox **an app**"*. The App Sandbox requires **entitlements** and a **signed
application bundle**. Belay `Popen`s a third-party MCP server — `npx …`, `python -m …`,
whatever the user already runs. That process is not our bundle, is not signed by us, and
cannot be given our entitlements. **A `Popen` of an arbitrary third-party command can
never satisfy the App Sandbox's requirements.** The recommended replacement does not
address the case we are in. This is not a gap we have not gotten to; it is structural.

So: on macOS today, for containing a process you did not build and did not sign,
`sandbox-exec` is the mechanism that exists. There is no third option. We use the
deprecated thing, we say it is deprecated, and the risk that it changes under us is real
and accepted rather than hidden.

---

## Platform: macOS only, and that is not a formality

**Everything in this document was measured on macOS 26.5.2 / arm64.**

**Linux is entirely unverified — nothing has ever been run there.** Not "partially
supported", not "should work". `seatbelt.run` raises `UnsupportedPlatform` off darwin
rather than pretending. The snapshot backend is `clonefile`, which needs APFS: **ext4 has
no reflink**, and GitHub's Linux runners are ext4, so this approach has **no CI equivalent
there**. Linux/Docker is C2's second slice, at Phase-1 packaging.

Do not read any claim here as a claim about Linux.

---

## What Belay cannot see at all

**The sandbox's limit and the MCP boundary's limit are the SAME limit.**

Belay contains and observes the processes **it spawns** — the MCP servers it proxies.
Claude Code's `Bash` and `Edit` are in-process: they never traverse MCP, are never spawned
by our proxy, and are **never in our sandbox**. An agent can read a file, run a command, or
rewrite your working tree without a single byte crossing Belay and without touching the
boundary described in this document.

This is a real limit, not a temporary gap in the docs. Read a trace and a sandbox verdict
as *"here is what went over MCP"*, never as *"here is what the agent did"*.

---

## Belay's own attack surface (R8)

| Surface | Status |
|---|---|
| **Scope → SBPL injection** | Escaped and tested (`test_a_scope_containing_a_quote_cannot_break_out_of_the_profile`). |
| **Profile temp file** | Written via `mkstemp` (owner-only) and unlinked in a `finally`. A writable profile path would be a policy rewrite. |
| **`$PATH` hijack** | **Partial, and read this rather than the headline.** The three binaries *Belay itself* chooses are absolute: `/usr/bin/sandbox-exec`, `/bin/chmod`, `/usr/bin/env`. But the **server command is resolved through `$PATH`** — by `proxy.py`'s `Popen(argv)` and by `env` in `DefaultScope.wrap`. `$PATH` absolutely does decide what runs; it just cannot redirect Belay's own three. That is by design (`npx`, `python` and friends must resolve normally), so **a poisoned `$PATH` runs a different server, sandboxed** — it cannot substitute the sandbox itself. The three are pinned by `test_belay_names_its_own_binaries_absolutely`. |
| **The trace file** | **As sensitive as the agent's most sensitive tool argument.** Verbatim capture, no redaction, `0600`. See [TRACE_FORMAT.md](TRACE_FORMAT.md). |
| **Snapshot trees** | Clones of the workspace, with the same secrets in them, under `BELAY_SNAPSHOT_DIR`. They inherit the workspace's permissions, not the trace's `0600`. |
| **The gate cannot alter bytes** | Structural: `proxy.py` cannot import `json` (`tests/test_import_guard.py`), and the gate parses a **copy** it throws away (`test_byte_identity_holds_with_the_gate_installed`). |
| **A broken gate cannot stop the agent** | `test_a_broken_gate_cannot_stop_the_bytes`. A hung proxy is worse than an unsnapshotted turn. |

### The default scope's own consequences

The default scope relocates `$TMPDIR` **inside** the workspace so that a server needs no
hand-tuning (see [`src/belay/sandbox/scope.py`](../../src/belay/sandbox/scope.py)).

**Neither of the two consequences below exists on any shipped path today**, and saying
otherwise would contradict the top of this document. `default_scope()` is called **only**
from `belay sandbox check`, which runs a server once and takes no per-turn snapshots. The
turn gate — the only thing that snapshots per turn — is handed the raw
`BELAY_SANDBOX_SCOPE` and never sees a relocated `TMPDIR`. The two mechanisms do not yet
meet.

They will meet when containment is wired into the proxy, and at that point both of these
follow. They are recorded now, while the reasoning is in front of us, rather than
rediscovered then:

- **Temp files would land inside every turn's snapshot.** The gate snapshots the scope, and
  `TMPDIR` would be in it. That is *true* rather than tidy — those files really are in the
  tree — but it is a cost, not an accident.
- **A socket or FIFO under `$TMPDIR` would make every turn `unrestorable`.**
  `substrate.guard` refuses a tree containing one, by name (`test_a_socket_in_the_tree_is_detected_and_refused`).
  A server that opens a unix socket in its temp directory would then snapshot as
  `unrestorable` on **every** turn. That is the honesty contract working as designed, and
  it is the strongest argument against this TMPDIR placement — worth re-opening when the
  two halves are joined.

**Nothing widens a scope automatically.** `belay sandbox check` reports denied paths and
stops there (`test_check_never_widens_the_scope_itself`). A tool that widened the boundary
until its own error went away would be authoring the invariant — which is the risk the
default scope exists to retire, not to relocate.

---

## What this sandbox is FOR, and the class it does not catch

A1 (the invariant axis) catches **corrupt success**: the right end-state reached through a
path that violated a declared boundary. That is what the escape matrix above is.

It does **not** catch an adversarial server that stays inside the boundary. A server that
reads every secret it can see and writes only inside its scope is fully compliant with
this sandbox. If the server itself is the adversary, the boundary you need is
`deny-all` networking plus a scope containing nothing you care about — and you should be
reading the server's code, not our denial records (see failure mode 2 above).
