# Spike: loopback bind/connect under Seatbelt `(deny default)` / `(deny network*)`

**Status: SOLVABLE.** All output below was RUN on this machine (macOS 26.5.2, arm64,
`sandbox-exec` at `/usr/bin/sandbox-exec`), not reconstructed from memory or docs. Nothing
in this file describes untested syntax.

## One-paragraph finding

Yes — a Seatbelt profile can permit loopback (127.0.0.1) traffic while a real external host
stays denied, using the SBPL host keyword `localhost` (not a per-IP allowlist, which is a
compile error per the brief). The exact rule is `(allow network-outbound (remote ip
"localhost:*"))`. For Belay's actual shape — an untrusted sandboxed subprocess that only
needs to be a network *client* talking to a trusted host-side listener (e.g. Belay's own
verifier/control socket), never a listener itself — **`network-outbound` alone is sufficient
and `network-inbound`/`network-bind` are not needed at all.** This is the recommended
production profile shape: it grants loopback-connect and denies everything else, including
egress to the sandboxed process's own LAN address once genuinely off-box, with zero inbound
surface added.

## Recommended profile (RUN, not reconstructed)

```lisp
(version 1)
(deny default)
(allow process*)
(allow sysctl-read)
(allow mach-lookup)
(allow file-read*)
(allow file-write* (subpath "/private/tmp/spike-loopback"))
(deny network*)
(allow network-outbound (remote ip "localhost:*"))
```

Scenario: a **trusted, unsandboxed** process runs a TCP listener on `127.0.0.1:18765` (this
is Belay's own control-plane socket, outside the sandbox boundary — never inside it). The
**sandboxed** subprocess is only ever the client. Actual test run:

```
=== trusted (unsandboxed) listener + SANDBOXED client, outbound-only profile ===
LISTEN_OK
CONNECT_OK
SERVER_GOT b'hello'
client rc=0
listener rc=0

=== same sandboxed client profile: egress to real external host still denied ===
EGRESS_FAIL PermissionError(1, 'Operation not permitted')
egress rc=1

=== does outbound-only profile ALSO allow the sandboxed process to bind/listen? (should FAIL - no network-inbound) ===
LISTEN_FAIL PermissionError(1, 'Operation not permitted')
sandboxed listen rc=1
```

Re-run twice more for stability — identical result both times (CONNECT_OK / egress
PermissionError / listen PermissionError in all 3 runs total). `egress.py` connects to
`1.1.1.1:80` (deny-all baseline from the brief); it fails with
`PermissionError(1, 'Operation not permitted')` under this profile exactly as it does under
the plain deny-network baseline, confirming the loopback allowance did not widen egress.

This is a **strictly narrower and cleaner control** than a profile with `network-inbound`
also open, because the sandboxed process gets zero inbound network surface — it can only
dial out to loopback, never accept a connection. If Belay's design needs the *sandboxed*
side to also listen (e.g. it runs its own local MCP-adjacent server), see the caveat below —
that shape is possible but weaker than advertised.

## Caveat found and worth flagging: `network-inbound`'s `(local ip "localhost:*")` does NOT scope the bind address

While confirming the tightest possible profile, I first tested (and initially assumed
correct) this variant with inbound added:

```lisp
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
```

This also passes the loopback connect/egress-denied tests above. But probing further:

```
=== bind to 0.0.0.0 under localhost-only profile (should FAIL) ===
LISTEN_ALL_OK
rc=0
```

A process under this profile can bind `0.0.0.0:<port>` (all interfaces) — `(local ip
"localhost:*")` on `network-inbound` only wildcards the **port**, not the address; it does
not actually restrict which interface the socket binds to. So `network-inbound` should be
treated as "may open some listening socket," full stop — **not** as "may only listen on
loopback." Anyone using this shape should not assume the address restriction is real.

I also checked whether `network-outbound`'s `"localhost:*"` restriction was similarly loose
(i.e. secretly permitting real LAN egress), since a first probe connecting to this machine's
own LAN IP (`192.168.1.21`) unexpectedly succeeded:

```
=== outbound connect to own LAN IP (not 127.0.0.1) under localhost-only profile ===
EGRESS_LAN_OK
rc=0
```

Investigated further: this is not a sandbox leak. Connecting to a machine's *own* configured
IP address is delivered by the kernel over the loopback path regardless of sandboxing (same
mechanism that makes `127.0.0.1` and `<own-LAN-IP>` behave alike for locally-terminated
connections). Confirmed by connecting instead to the LAN **gateway** (`192.168.1.1:80`, a
genuinely different host, not this machine):

```
=== control (no sandbox): connect to gateway 192.168.1.1:80 ===
EGRESS_GW_OK
rc=0

=== under localhost-only profile: connect to gateway 192.168.1.1:80 ===
EGRESS_GW_DENIED_BY_SANDBOX PermissionError(1, 'Operation not permitted')
rc=2

=== re-verify: own-machine LAN IP 192.168.1.21 (self) under same profile ===
EGRESS_LAN_OK
rc=0
```

So: `network-outbound (remote ip "localhost:*")` correctly denies egress to any genuinely
external host (confirmed against a real gateway, not just `1.1.1.1`), and only appears to
"allow LAN" because self-addressed traffic is loopback-equivalent at the kernel level, not
because the sandbox rule is loose. **The outbound restriction is sound. The inbound
restriction's address scoping is not** — that asymmetry is the one thing to remember from
this spike.

## Recommendation

Use `(allow network-outbound (remote ip "localhost:*"))` with **no** `network-inbound` /
`network-bind` grant as Belay's positive network control: the sandboxed subprocess is always
the client, dialing a trusted host-side control socket; the harness process (outside the
sandbox) owns the listener. This gives a real, narrow, verified loopback control with no
inbound attack surface, and keeps external egress denied under the same profile as proven
above. Do not grant `network-inbound` to the sandboxed side unless a future capability
genuinely requires the untrusted process to accept connections — and if it ever does, do not
rely on `(local ip "localhost:*")` to confine it to loopback; that confinement does not hold.

## What was run vs. what was read

- **RUN**: every profile and every test transcript in this file (`profile1.sb` through
  `profile_outbound_only.sb`, listener/client/egress/bind_all/egress_lan/egress_gw2 python
  scripts), via `sandbox-exec -f <profile> python3 <script>`, using `subprocess.run`/`Popen`
  with `capture_output=True` (not shell pipes), per the brief's warning about pipe `rc=$?`
  masking failures.
- **READ, not run**: `/System/Library/Sandbox/Profiles/appsandbox-common.sb` (lines
  ~410–428, the `network-client`/`network-server`/`system-network` macros) and
  `/System/Library/Sandbox/Profiles/system.sb` (lines ~272–300, `system-network`
  definition) — used only to look for a loopback-specific Apple macro. Finding: **Apple's
  own shipped profiles contain zero references to `127.0.0.1`, `loopback`, or `lo0`**
  (`grep -rn` across all of `/System/Library/Sandbox/Profiles/*.sb` returned no matches).
  `network-server`/`network-client` are full inbound/outbound-to-any-IP macros, not loopback
  scoped, and were not used in the final recommendation. The working rule came from directly
  testing the `"localhost:*"` host keyword mentioned in the brief's compile-error message
  ("host must be `*` or `localhost`"), not from any Apple macro.
- All throwaway spike code (`.sb` profiles, python test scripts, `harness.py`) lived under
  `/tmp/spike-loopback` and is **not** included in this commit.
