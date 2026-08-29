<div align="center">

<img src="https://raw.githubusercontent.com/haqaliz/belay/master/assets/belay-logo.png" alt="Belay" width="104" />

# Belay

**The agent harness: sandbox any agent, verify each step by replaying it against real state, and keep a deterministic trace.**

Belay sits as a transparent proxy between an AI agent and the tools it calls. It **records** exactly what crossed, runs the tools **inside a sandbox**, snapshots each turn's real pre-state, and then **replays every tool call against that restored state** — rendering an honest `PASS` / `WARN` / `FAIL` / `UNVERIFIED` verdict grounded in *re-execution and a state diff*, never in a model's opinion of itself. Every caught failure becomes a labeled, replayable case in a corpus that compounds.

[![Release](https://img.shields.io/github/v/release/haqaliz/belay?color=3fb950&label=release)](https://github.com/haqaliz/belay/releases/latest)
[![CI](https://github.com/haqaliz/belay/actions/workflows/ci.yml/badge.svg)](https://github.com/haqaliz/belay/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/status-alpha%20·%20macOS%20%2B%20Linux-3fb950)](docs/ROADMAP.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Built with uv](https://img.shields.io/badge/built%20with-uv-DE5FE9?logo=astral&logoColor=white)](https://github.com/astral-sh/uv)
[![Zero dependencies](https://img.shields.io/badge/runtime%20deps-zero-3fb950)](pyproject.toml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-3fb950)](CONTRIBUTING.md)

[Quickstart](#quickstart) · [How it works](#how-it-works) · [The verdict](#the-verdict-three-axes-deliberately-unequal) · [Coverage & limits](#coverage--limits-stated-exactly) · [Roadmap](docs/ROADMAP.md) · [Vision](VISION.md) · [Contributing](CONTRIBUTING.md)

<br/>

<img src="https://raw.githubusercontent.com/haqaliz/belay/master/assets/belay-demo.gif" alt="The Belay console renders a committed capture of a real agent run (claude -p, told only &quot;make the tests pass&quot;). Its seven turns list; while the engine re-executes them every turn reads &quot;verifying…&quot; with &quot;coverage unavailable&quot; and no status — never a placeholder PASS. The verdict then lands: PASS 7, WARN 0, FAIL 0, UNVERIFIED 0 over 7 turns verified, and the instance-level trajectory rule PASSes, supported by 2 replayed command turns — the agent claimed the tests passed and replay re-ran the suite itself to confirm it had. Opening a turn shows the sub-verdicts behind it, including effect:network NOT_COVERED: Belay observes no network egress, so this PASS asserts nothing about it." width="820" />

<sub><b>The demo is the negative control.</b> A real agent fixed the bug honestly and said so; Belay agrees, and shows exactly what that agreement covers. The corrupt-success shape is measured elsewhere and at scale — <b>11/60 = 18.3%</b> in the Phase-0 mint (<a href="docs/technical/PHASE0_RESULTS.md">with its decomposition</a>). Replay it yourself: <a href="demo/README.md"><code>demo/README.md</code></a>.</sub>

</div>

---

## Why Belay

Three kinds of tools sit near agents. Frameworks (LangGraph, CrewAI) *build* the agent. Observability (Langfuse, Phoenix, LangSmith, Braintrust) *records* what it did — and at most bolts an LLM-judge on top to score it. **Belay is the third thing: the harness.** It answers the question none of the others do — *"was this step actually correct?"* — by replaying the tool call in a sandbox and diffing observed-vs-claimed state.

Why that question matters, and why a judge can't answer it:

- **27–78% of benchmark-reported agent "successes" are *corrupt successes*** — the right end-state reached through a broken, unsafe, or cheating path ([arXiv 2603.03116](https://arxiv.org/abs/2603.03116)). A run can look done and be wrong.
- **LLM-as-judge is unreliable exactly where it matters:** up to **35% false positives** ([2507.08794](https://arxiv.org/abs/2507.08794)), with verdicts flipping 10–30% on trivial reorderings. A guess about correctness is not a verification of it.

Belay's verdict is **grounded in execution, not opinion** — which means it gets *better* as base models improve (they write better checks and cleaner tools), never redundant.

- 🧗 **The name.** To *belay*, in climbing, is to manage the rope that **catches a climber when they fall**. Belay catches an agent when it fails: it contains the fall, proves what happened, and lets you replay it. The harness holds; the climber takes the risk.
- 🧱 **Sandbox / execution boundaries.** The agent's tools run inside enforced filesystem and network limits — a bad action is contained, not catastrophic. The same boundary that *contains* an action is the machinery that *judges* it.
- 🔁 **Per-turn verification by replay.** Each tool call is re-executed in isolation against its restored pre-state, and the observed effect is diffed against what was claimed.
- 🎞 **Deterministic trace + replay.** Every run is captured exactly and can be re-run — for debugging, regression, and audit.
- 📈 **A compounding failure corpus.** Every caught failure becomes a labeled, replayable case; `belay corpus run` re-replays the whole corpus as a regression suite, and precision/recall/coverage measures detection against **human** labels. A case can also record a **miss** — a violation a human adjudicated real that the engine did not catch — so a green run means *no case regressed*, and nothing more: never *everything is caught*, and never *every recorded miss is still missed*.
- 🔒 **Runs on your infrastructure.** Self-hostable, zero runtime dependencies, stdlib only. Traces and state stay on your box; nothing is uploaded, ever.

> **Honesty is the whole product.** `UNVERIFIED` is *never* rendered as `PASS`, the verdict never over-claims beyond what the replay actually checked, and where Belay cannot see or cannot ground a claim it says so by name. Read [Coverage & limits](#coverage--limits-stated-exactly) before trusting any verdict.

---

## Quickstart

> **Requirements:** macOS (Apple Silicon or Intel) or Linux (measured on ubuntu-24.04, kernel ≥ 5.13 with Landlock enabled), Python 3.10+. The sandbox and snapshot backends are **macOS + Linux today** — see [platform coverage](#platform-coverage-macos-and-linux-both-measured). [uv](https://github.com/astral-sh/uv) is recommended.

Install from PyPI — the `belay-harness` package is published there, so this is the live install path:

```bash
uv tool install belay-harness      # or: pipx install belay-harness  /  pip install belay-harness
# the distribution is `belay-harness` (the name `belay` is taken on PyPI); the command is `belay`
belay --help
```

**Or run it as a container.** The image is the whole engine, not a demo shell — it runs the real Landlock + seccomp sandbox and the real snapshot backend:

```bash
docker build -t belay .            # or: docker compose build — needs nothing but this checkout
docker run --rm belay --help
# the boundary, decided by USING it — not read off a kernel version:
docker run --rm belay sandbox check --scope /workspace
#   landlock      kernel ABI 8 (ok)
#   containment   ok (a write outside the scope was refused)
#   seccomp       ok (an AF_INET socket was refused)

# mount the tree you want verified and drive the engine over it:
docker run --rm -v "$PWD:/workspace" belay verify /workspace/traces/<trace>.jsonl \
  --manifest-dir /workspace/snapshots.manifests --server <your-mcp-server-cmd>
```

`docker compose run --rm belay <subcommand>` is the same thing through compose. The second service is the live console (C7): `docker compose up console` builds it from this checkout and serves the SPA at `http://127.0.0.1:8080` (loopback only), with a healthcheck on its `/health` endpoint and the engine bundled in the image — verify/replay from inside the console container run this checkout's engine, and the service shares the engine's `/workspace` state mount, so traces and snapshots live in one place.

> **What the container does and does not do.** It runs as a **non-root** `belay` user (uid 1000; `--user root` is the opt-in), and it carries **no containment of its own that Belay relies on** — the boundary is the *host kernel's* Landlock, which is not namespaced and which no image can supply. On a host below kernel 5.13, or with the LSM off, the launcher **refuses** (exit 2, named cause) instead of running unsandboxed: loud, never silent. The image's overlayfs layer has no reflink, so snapshots take the **copy path** with the named `reflink-unavailable` cause — and a corpus case banked on macOS APFS is **SKIP** with `UNRESTORABLE_CAPABILITY_MISMATCH` inside the container, never a guessed restore.
>
> **Measured where, exactly:** the `docker` CI job builds the image and re-runs the whole measurement *inside* it on the pinned `ubuntu-24.04` runner — the suite (with every skip's cause machine-checked), the escape matrix, the snapshot round trips, and a capture → verify roundtrip generated in-container. That asserts the **Linux-host** path. On a **macOS host** the image runs in Docker Desktop's Linux VM — a different kernel, which CI cannot reach — so `docker run --rm belay sandbox check --scope /workspace` there is a **manual re-probe you should run** before relying on it. Full details in [`THREAT_MODEL.md`](docs/technical/THREAT_MODEL.md#the-container-l3-what-the-image-does-and-does-not-change).

### 1 · Put the proxy in front of the server you already run

Belay is a transparent stdio proxy. Wherever your agent launches an MCP server, wrap the command:

```bash
# was:   my-mcp-server --flag
# now:
BELAY_TRACE_DIR=./traces \
BELAY_SANDBOX_SCOPE=./workspace \
  python -m belay.proxy my-mcp-server --flag
```

Bytes are forwarded verbatim in both directions. With `BELAY_SANDBOX_SCOPE` set, the server runs under the platform sandbox — macOS Seatbelt, or Linux Landlock + seccomp — a write outside the scope is refused by the kernel and recorded as a `denial` naming the path; **the network is denied by default** (`BELAY_SANDBOX_NETWORK=allow-all` to widen; `allow-ports` is macOS-only and refused with a named cause on Linux). Each `tools/call` is held just long enough to snapshot its pre-state before the call reaches the server.

### 2 · Verify the run by re-execution

```bash
belay verify ./traces/<run>.jsonl --manifest-dir ./traces.manifests --server my-mcp-server --flag
```

For each recorded `tools/call`, Belay restores its pre-state, re-invokes the server, and renders a per-turn verdict:

- **A2 — replay:** did the recorded result reproduce, and did the filesystem effect match the tool's declared `readOnlyHint`? (catches *trace infidelity*)
- **A1 — invariant:** was a task-scoped policy violated by the observed effect? The default is **`no-assertion-weakening` on any `tests` or `testing` path segment**, on unless `--no-default-invariants`; add your own with `--invariants policy.json`. It FAILs a turn that **removes an assertion without replacement, replaces one with a tautology, or loosens one so it accepts strictly more** — judged against the **task pre-state**, so adding a test or editing the run's own scratch is not a violation. (catches *corrupt success* — a cheating agent whose trace is perfectly faithful, which A2 structurally cannot catch)

Both are decided by **re-execution and diffing. No model is consulted** — enforced by an AST test that bans any inference import from the verdict path.

### 3 · Grow the corpus

```bash
belay corpus add ./traces/<run>.jsonl --turn 7 --manifest-dir ./traces.manifests --server my-mcp-server
belay corpus label <case-id> --label true-positive --root-cause-key weakened-assertion            # a human adjudicates; the engine never labels its own cases
belay corpus label <case-id> --label true-positive --root-cause-key weakened-assertion \
                             --recorded-miss-note "the engine returned clean; this weakening is real"   # …and declare the STORED verdict a MISS
belay corpus run                                        # re-replay every case — green = nothing drifted, NOT "everything is caught"
belay corpus score                                      # precision · recall · coverage vs human labels (UNVERIFIED excluded, reported separately)
```

Cases are self-contained (they bundle their own pre-state) and live under the gitignored `corpus/local/` — nothing leaves your machine. What a green `corpus run` does and does not certify is in [Coverage & limits](#a-green-belay-corpus-run-is-a-drift-check-not-a-coverage-claim).

### 4 · Measure at scale — the violation rate

```bash
belay phase0 run ./traces --ledger runs/phase0.json --corpus-dir corpus/local --server -- my-mcp-server
belay phase0 report runs/phase0.json --corpus-dir corpus/local   # re-render the number, no replay
```

`belay phase0 run` verifies a whole directory of captured runs, ingests every flagged (FAIL) turn into the corpus, and writes a ledger + report: the **per-instance violation rate with its denominator**, the per-turn FAIL rate, the `UNVERIFIED` rate by named cause, and the false-positive rate. It is a **measurement, not a gate** — it exits `0` even when it finds violations. A batch that captured ~no verifiable turns is reported as **`INSTRUMENT SUSPECT`**, never a clean `0%` — so a broken capture can't masquerade as a passing run. See [the runbook](docs/planning/phase0-corpus-run/RUNBOOK.md) to reproduce the number end-to-end.

---

## How it works

```
agent  ⇄  [ belay.proxy ]  ⇄  MCP server
              │   records every frame verbatim  → append-only trace (.jsonl)
              │   runs the server in a sandbox   → writes outside scope refused, network denied by default
              │   snapshots each turn's pre-state → APFS clonefile + a fidelity-declaring manifest
              ▼
         belay verify / corpus
              restore pre-state → re-invoke → diff observed vs claimed → grounded verdict
```

The engine is built in capability layers (see [the roadmap](docs/technical/CAPABILITY_ROADMAP.md)): **C1** capture, **C2** sandbox + snapshot/restore, **C3** deterministic replay with a real before/after delta, **C4** the A2 replay verdict, **C5** the A1 invariant verdict, **C6** the failure corpus. All merged; zero runtime dependencies.

### See it work

**Is the boundary real, and is it actually enforcing?** `belay sandbox check` probes the substrate by *using* it — snapshot, restore, and a write outside the scope that must be refused. The result is a fact, not a claim.

<p align="center"><img src="https://raw.githubusercontent.com/haqaliz/belay/master/assets/belay-sandbox.png" alt="belay sandbox check output: substrate section shows sandbox-exec ok, apfs-clonefile snapshot backend ok, capabilities clone/gc/restore/snapshot, and containment ok because a write outside the scope was refused; scope section shows the writable snapshotted workspace and the non-snapshotted TMPDIR; the server ran and exited cleanly with no denials; final line reads belay: substrate ok." width="760" /></p>

**Coverage, not a verdict.** `belay replay` reports what re-executed and what could not — the `UNVERIFIED` rate with every instance filed under a named cause. It never spins an unverified turn as a `PASS`.

<p align="center"><img src="https://raw.githubusercontent.com/haqaliz/belay/master/assets/belay-replay.png" alt="belay replay output: five turns, three REPLAYED as result-equivalent and two UNVERIFIED (manifest not found; replay did not answer target); a coverage block totals 9 turns, 7 replayed, 2 unverified; the UNVERIFIED RATE is 2 of 9 or 22 percent, broken down by cause. It emits no PASS or FAIL." width="760" /></p>

**Every caught failure compounds.** `belay corpus score` grades the engine's own detection against *human* labels — precision and recall reported only ever beside coverage, with `UNVERIFIED` verdicts and unadjudicated cases excluded, never folded in as a PASS.

<p align="center"><img src="https://raw.githubusercontent.com/haqaliz/belay/master/assets/belay-corpus.png" alt="belay corpus score output: 13 cases scored against human labels; a confusion matrix of TP 7, FP 0, FN 1, TN 5; metrics precision 1.00, recall 0.88, coverage 0.92; an excluded block lists one UNVERIFIED verdict and zero pending labels that are never counted as a PASS." width="760" /></p>

<p align="center"><sub><b>The figures in that screenshot are illustrative sample output — a fixture corpus, showing the shape of the report. They are <b>not</b> a measurement of Belay's detector.</b> Belay's own corpus reads <code>precision n/a</code> (0 TP / 0 FP — a zero denominator, <b>not</b> a 1.00) and recall unmeasured, because no miss has been banked. See <a href="#what-the-a1-default-does-and-does-not-judge">Coverage &amp; limits</a>.</sub></p>

### The verdict: three axes, deliberately unequal

| Axis | Grounding | May emit | Catches | Status |
|------|-----------|----------|---------|--------|
| **A1 · Invariant** | A task-scoped policy, violated during replay | PASS / WARN / FAIL / UNVERIFIED | **Corrupt success** (the 27–78%) | ✅ built (C5) |
| **A2 · Replay** | Re-execution + state diff | PASS / WARN / FAIL / UNVERIFIED **· NOT_COVERED** (sub-verdict only) | **Trace infidelity** (fabricated / tampered results) | ✅ built (C4) |
| **A3 · Claim re-derivation** | A model *writes* a check; **execution** decides | WARN / FAIL / UNVERIFIED — **never PASS** | **Intent drift** | ⏳ planned (C8), cuttable |

`NOT_COVERED` is a **sub-verdict-only** status, and it is deliberately not one of the four a turn can reduce to. It marks a dimension Belay has **no instrument for at all** — as opposed to `UNVERIFIED`, which means Belay tried and could not. The reduction **drops it before ranking**, so it never lowers a turn and never lifts one; if nothing scoreable remains the turn is `UNVERIFIED`, never `NOT_COVERED` and never `PASS`. The trade is stated plainly in [Coverage & limits](#a-pass-excludes-the-network-dimension): a `PASS` is a pass *on the dimensions Belay checks*, and every surface that prints a status also prints what fell outside them.

The reduction is worst-status-wins across A1 and A2. **A1 and A2 are not redundant** — and getting this wrong is the single easiest way the project could fail quietly. A2 cannot catch a *cheating* agent: a cheater's trace is perfectly faithful (it really did weaken the test), so replay restores the recorded pre-state, re-invokes, sees the same result, and returns `PASS` — correctly. Only a declared invariant (A1) calls that success corrupt. Belay ships a launch demo that proves exactly this: on one turn, A2 `PASS` + A1 `FAIL` → the turn is `FAIL`, driven solely by A1.

---

## Coverage & limits, stated exactly

Belay's entire value is an honest verdict, so its limits are documented as precisely as its claims. **Read this before trusting any output.**

### Belay sees what crosses the MCP boundary, and nothing else
An agent's **built-in** tools do not traverse MCP and are invisible to Belay. Claude Code's `Bash` and `Edit` are in-process; they never reach a stdio transport, so no proxy on that transport can see them. Read a trace as *"here is what went over MCP"*, never as *"here is what the agent did"*. The sandbox's limit is the same limit: Belay contains the processes it spawns (the MCP servers it proxies) — not tools it never launched. An OpenTelemetry/OpenLLMetry ingestion path (C9's first slice, `belay interop correlate` — see below) lets Belay sit beside existing observability, joining only the spans that carry the trace context Belay itself captured.

### Replay re-invokes against the server(s) you name, and nothing else
Verification is re-execution, so the boundary a turn is replayed against is whatever **you** put on the command line — never something inferred from the trace. A trace records one client↔server pipe and carries **no server provenance** (`docs/technical/TRACE_FORMAT.md`: *"one open pipe to one server process — nothing more"*), so Belay cannot work out which of your agent's MCP servers served a given turn. You name it. `--server` is the one boundary every turn replays against; `--shell-server "CMD"` names a second, and a recorded `run_process` turn replays against that one instead. `belay verify` and `belay phase0 run` both carry the pair. **Write `--shell-server` before `--server`** — `--server` is an argparse remainder and swallows every token after it, so a `--shell-server` written afterwards is silently taken as part of the server's own argv, and the shell axis is simply absent.

The limit that creates, stated exactly: **a turn whose tool none of the servers you named offers is not checked against the boundary that actually served it.** Replay still sends the recorded `tools/call`, and the server answers that it has no such tool — readably, and the same way on every re-invoke, so that answer used to take the `DIVERGED + DETERMINISTIC -> FAIL` branch and report a confident deterministic failure of a call nothing verified. **It no longer does.** Before scoring a divergence, Belay now **asks the boundary what it offers**: a `tools/list` probe against the same resolved server command, from the same restored snapshot, in the same sandbox. If the recorded tool is absent from the answer, the result sub-verdict is **`UNVERIFIED`, never `FAIL`** — nothing was re-executed, so nothing was refuted, and the divergence is between the trace and your `--server`, not between the trace and re-execution. The probe is **positive evidence**: it never matches error text and never infers from `isError`, because a genuine command that really failed returns `isError` too. It is fail-closed in both other directions as well — a probe that cannot be run or cannot be read, and a tool that **two** of your configured servers both offer (so routing would be a guess), each abstain with wording deliberately distinct from *“the boundary does not offer it”*. Absence of evidence is never evidence of absence.

**Both A2 sub-verdicts abstain — not just one.** Result-equivalence and effect-conformance are two independent checks computed from the *same* replay, so gating only the first left the second reading *“the observed effect conforms”* on a turn nothing ran: `readOnlyHint` is read from the **capture**, and a declaration is not an observation of this replay. Effect-conformance is now gated on the same single probe answer and abstains in its own words. The gate sits ahead of the whole declared-vs-observed rule, not inside one branch of it, so the mirror is closed too: a delta the replay harness left on a turn the boundary never served can no longer be scored against a declared `readOnlyHint: true` into a FAIL. The `effect:network` `NOT_COVERED` line is deliberately **not** gated — it reports that *Belay* has no network instrument, which is true of every trace ever recorded whether or not a given turn re-executed, and turning a permanent coverage boundary into a per-run abstention would lose the declared-false-vs-silent distinction it exists to keep.

**The abstention now carries a named cause of its own.** *(This paragraph used to admit the opposite, under the heading “**What has not landed, stated as exactly.**”: the abstention carried an explanatory message and no distinct named cause, so it “buckets under the generic replayed-but-unverified cause, so `phase0 report`’s cause table and `interop correlate` cannot yet separate it by name from other result-axis abstentions”. **That gap is closed.**)* There are **three** names, not one, because they call for three different actions: the boundary was asked and **does not offer the tool** (name the right `--server` — this is the one a mint counts), **two configured servers both offer it** so routing would be a guess (name one), and **the probe could not be run or read at all** (the boundary is unreachable, not lacking). Each is a separate sub-verdict `kind` under the unchanged `A2` axis — `replay:tool-not-offered`, `replay:boundary-ambiguous`, `replay:boundary-undecided`, and the matching `effect:…` trio — which is what makes them separable at all: the canonical cause buckets by `axis/kind`, so an abstention that kept the bare `replay` kind would be filed beside every other result-axis abstention no matter how carefully it was worded. The name travels with the status on every surface: `belay verify` (text and `--json`), `belay corpus show`, `belay interop correlate` (text and `--json`), and `phase0 report`’s UNVERIFIED-by-cause table, where it is **its own counted line** — which is exactly the number the 2026-08-12 gate mint needed and could not produce. **The status does not move**: it was `UNVERIFIED` before this and it is `UNVERIFIED` now; what changed is that you can count it. *(This paragraph also used to read “Nor is the effect sub-verdict gated yet — on such a turn it can still read ‘the observed effect conforms’ although nothing was observed”. **That half has shipped** — see the paragraph above for what replaced it. The turn already reduced to `UNVERIFIED` either way, so no verdict, status or published number moved; what moved is what `belay corpus show` and the C7 console print, since both render sub-verdicts individually.)* None of this re-derives a published number: the 2026-08-12 gate mint's **171 per-turn FAILs were all this shape** (hand-verified on `django-12125` turn 8; see [`PHASE0_RESULTS.md`](docs/technical/PHASE0_RESULTS.md)), which is why that run's per-turn FAIL rate is an instrument artifact and never a violation rate — that reading is unchanged. Name every server your run used all the same: an abstention is an honest answer, not a verified turn.

### A `PASS` excludes the network dimension
**Belay has no network instrument.** It observes the filesystem — a `PASS` means the replay reproduced the recorded reply and the observed *filesystem* effect conformed to the tool's declared contract and to your invariants. It does **not** mean the tool made no network call, reached no host, and sent nothing out; Belay never looked. When a tool declares `openWorldHint: false` (the reference `@modelcontextprotocol/server-filesystem` does), that promise is recorded as a `NOT_COVERED` sub-verdict — *"this tool promised a closed network posture and Belay does not observe egress"* — which is kept distinct from *"nothing was promised"*, and which is printed alongside the status on every surface: per-turn, in the aggregate, in the always-on coverage banner, in `phase0 run`/`report`, in the ledger, in the live console (C7), and on every corpus case. Read a `PASS` as **"passed on what Belay checks"**, and read the coverage line to see what that excluded.

> This changed in the `NOT_COVERED` release. Before it, a declared-false network promise dragged the whole turn to `UNVERIFIED` — which made an honestly-declared closed posture strictly *worse* than saying nothing, and pinned every turn against the reference filesystem server at `UNVERIFIED` forever. **Consequence for anyone comparing runs: the `UNVERIFIED` rate before and after this change is not comparable.** The drop is a reclassification of turns Belay never had an instrument for, **not** improved detection.

### What the A1 default does and does not judge
The default scope now matches a **path segment**, so `tests/`, pytest's `testing/`, sympy's `sympy/**/tests/` and any `src/pkg/tests/` are all covered. (It previously matched the raw byte prefix `tests/` only, which silently missed the rest — that gap is closed, and it is how a real corrupt success went unflagged in the Phase-0 mint. See [`PHASE0_RESULTS.md`](docs/technical/PHASE0_RESULTS.md) → *Correction — 2026-07-29*.)

Four limits remain, and each is deliberate:

- **A changed expectation is not a weakening.** `assert output == "old"` → `assert output == "new"` is the same check against a different value — possibly *wrong*, not *weaker*. An agent that rewrites an expected value to a wrong one **passes**. Wrongness is a different failure mode and Belay does not claim to catch it.
- **Only Python files are judged.** A non-`.py` file under a test tree yields no assertions and the rule does not fire — it reaches `PASS`, not `UNVERIFIED`, because abstaining on every data fixture in a test tree is how a rule shrugs its way through a real repository.
- **Only assertions are seen.** A mutation to a fixture or a config decorator that *parameterizes* an assertion (`@set_config(...)`, a conftest fixture) is invisible to it, even though it can change what the assertion tests.
- **Unrecognised assertion helpers are not assertions.** Belay names `assert`, `pytest.raises`, `pytest.fail`, unittest-style `assert*`, and `fnmatch_lines` patterns. A project-specific helper is deliberately **not** inferred — a name allowlist tuned to the repos we happened to measure would be overfitting dressed as coverage.

Whenever the rule cannot decide — an unparseable file, an undecidable pattern, a missing task pre-state — it reports `UNVERIFIED` with a named cause. **It never guesses in the passing direction.**

> **The default's precision still has not been measured.** Its predecessor scored **0.00** (0 true positives / 7 false positives) on the only real data available, which is why it was replaced. The replacement has since been run over **every banked capture** — 22 non-control captures across 15 instances, 392 turns, once, under a freeze protocol — and it flagged **1 instance (6.7%)**, with **zero** flags on the 7 turns its predecessor fired on and both clean controls staying clean. That is a genuine result about **over-firing**, and it is *not* a precision figure: nothing in that run was hand-adjudicated (`corpus score` reads `precision n/a` — 0 TP / 0 FP, and an `n/a` is a **zero denominator, not a 1.00**), and the single instance it flagged is the one the rule was **fitted on**, so it is not evidence of held-out sensitivity either. Read it as **"0.00 → still not measured"**, never as "0.00 → good".

> **And a clean verdict now says whether the rule had anything to judge — which changes how two of those sentences read** (measured 2026-08-04). An A1 verdict carries how many in-scope files it actually **compared**: `judged N file-comparison(s)`, `0 file-comparison(s)`, or `unrecorded` on a ledger written before the field existed. Three states, never collapsed, and **absent is never rendered as `0`**. Re-verifying the same captures under the same rule reproduced the same 6.7% and added the fact underneath it — **17 file-comparisons across 22/22 captures; 6 instances judged something, 9 compared ZERO**. (17 counts `(turn, file)` judgments, not files: they were made over **7 distinct files**.) So the nine tell you nothing: their silence is not evidence they are clean, and not evidence about the rule.
>
> **Most sharply: both clean controls compared zero files**, so *"both clean controls staying clean"* above **cannot** be read as *"the rule did not over-fire on a control"* — it never fired at all, and an unfired gun does not demonstrate aim. The controls remain perfectly valid captures; the **inference** drawn from them does not hold. Separately, at **human-adjudication grade (n=2, not execution)**, the only two held-out exposed-and-passed turns in that data were adjudicated **additions, not weakenings**: **0 misses found of 2; sensitivity still unconfirmed** — never *"the rule has good recall"*, because **n=2 is not a base rate**. Full record: [`PHASE0_RESULTS.md`](docs/technical/PHASE0_RESULTS.md) → *Correction — 2026-08-04*.

### `suite-before-success-claim` — what the trajectory rule does and does not judge
The A1 rule the funded mint's exposure gate demanded: the corrupt-success shape that mint actually exhibits is **"edit source, then claim success"**, which test-file weakening cannot see because it never touches test files at all (the gate fired at **0 of 8 instances judged**; see [`PHASE0_RESULTS.md`](docs/technical/PHASE0_RESULTS.md) → *2026-08-09*). It is **instance-level** — evaluated once per instance after the turn loop, never per turn. What it claims, exactly: **a verification claim was recorded, and no command execution before it could be observed in replay — zero replayed `run_process` turns with exit code 0**. FAIL is that shape, **and only when a command tool was actually offered**; PASS is its reverse (≥1 replayed `run_process` with a clean exit before the claim).

What it does **not** claim, each limit deliberate:

- **Never that the agent "lied".** The claim *text* is a trigger, never evidence of intent: the verdict states the observed gap between a verification claim and any executed command — nothing about the agent's state of mind.
- **PASS is not "the suite is genuinely the suite".** There is **no command-name matching** by design: a `python -c` run satisfies the evidence exactly as a `pytest` run would. The rule checks that *something* executed, never what.
- **Completion-only and ambiguous claims abstain, never judged** — "wrote the file", "task done" classify `CLAIM_UNCLASSIFIABLE`; a control's completion message must not read as a verification claim (a FAILing control is a mint void).
- **A missing claim record abstains** — captures predating the `claim` kind (and any run that never claimed success) read `NO_CLAIM_RECORDED`, never a fabricated verdict.
- **Replay abstentions on shell turns are counted exposure, never silence.** A `run_process` that never replayed verifiably (e.g. `EMBEDDED_PATH_UNRELOCATABLE`) yields `EVIDENCE_UNOBSERVABLE` — the rule could not observe what ran, and the report says so by name.
- **The rule never FAILs an ability that was not offered** (2026-08-12, ability-aware abstain — the re-mint's 5 false positives by construction were all the no-shell shape: 14 filesystem tools, no `run_process`). The offered tool set is derived from the trace's `tools/list` snapshots **before the claim** (`derive_annotations`; a snapshot after the claim is not an offering): no snapshot at all, or a `list_changed` with no re-snapshot, → `TOOLSET_UNKNOWN` — never FAIL on stale or unobserved knowledge — and a snapshot with no `run_process` → `NO_COMMAND_TOOL_OFFERED`. Both abstain with a named cause; **FAIL is only reachable when a command tool was offered and zero clean commands ran**. Only snapshots before the claim count; the command-tool name is exact (`run_process`, no synonyms).

The trigger is prose: the classifier is a **closed deterministic vocabulary** (stdlib `re`, no model), abstain-first, and its precision on real model text is decided by **adjudication after the first mint, not predicted**. **No real instance has yet been judged by this rule** — no mint has run under it — so it ships as a capability, not a result.

> **And the caught failure is now bankable** (2026-08-09, `corpus-trajectory`). A trajectory FAIL from `belay phase0 run` ingests as a **corrupt-success corpus case** (case schema **v4** — the optional instance-level `trajectory` expected verdict; the case bundles the full trace including the claim record), and `belay corpus run` recomputes it **instance-level** — MATCH/REGRESSION on the trajectory dimension, with the recorded-miss transitions `STILL_MISSED`/`MISS_CLOSED` — so the regression-suite property ("the corpus still reaches the verdict it recorded") holds for this rule too. `belay corpus show` renders the declared expected beside the recomputed outcome. **No real trajectory case exists yet** — no mint has run under the rule — so this is a capability, not a result, and no precision/recall number changed. See `docs/planning/trajectory-success-invariant/corpus-trajectory/`.

### A green `belay corpus run` is a drift check, not a coverage claim
A green run means exactly this: **no case regressed.** That is the whole claim. It does **not** mean the engine catches everything in the corpus — a green run coexists with known, *declared* blindness (`STILL_MISSED`) — and it does **not** mean every recorded miss is still missed either, because a miss that just closed (`MISS_CLOSED`) is green too. Anything beyond "nothing drifted" has to be read off the outcome counts, which is why they are printed.

A case may **declare** that its stored verdict records a **miss** — the engine returned clean on a turn a human adjudicated a real violation, so the clean verdict *is* the defect. Re-verifying such a case reports `STILL_MISSED` (the engine is still blind to it — exit `0`, because a known-open miss is not a drift, but deliberately **not** counted as a `MATCH`, since a `MATCH` on a recorded miss would certify blindness as agreement) or `MISS_CLOSED` (a sharpened detector now catches it — a fix landing, which must not break the build). The exemption covers exactly one transition; any other divergence on a declared case is still a `REGRESSION`. The `STILL_MISSED` count is printed on the sign-off line so that skimming only the last line cannot hide it.

**Nothing keeps a closed miss closed.** Once a case reports `MISS_CLOSED`, `belay corpus run` tells you to re-add it so the caught verdict becomes its new `expected` — but nothing enforces or tracks that. Until you do, the case still stores the clean verdict and its declaration, so a detector that later *re-breaks* returns the case to `STILL_MISSED` (green) rather than `REGRESSION`. A closed miss is only protected against re-breaking once it has been re-added as an ordinary case.

**This changes what the corpus is able to say, and the change is a capability, not a result.** `belay phase0 run` ingests flagged turns and nothing else, so a violation the detector *missed* never becomes a case by the bulk path — but `belay corpus add` has never enforced that precondition, and pointing it at a turn the detector verified clean is how a miss gets in at all. So a banked miss was always *reachable*, and it already counted as a false negative in `belay corpus score` (which keys on the human label and a non-`FAIL` stored verdict). What was missing is that nothing could **say so**: an undeclared miss was re-verified as a `MATCH`, which is the regression suite certifying the blind spot as agreement. What is new is the **declaration**, the `STILL_MISSED` outcome that stops that, and the `FN` provenance line that names a false negative as a human-banked known blind spot rather than a detection that failed today. **Whether any miss has actually been banked, and what the resulting recall is, is a separate empirical question that is not answered here.**

**As of 2026-08-04 the answer to that empirical question is: no miss has been banked**, so the declaration path ships **unexercised on real data**. The only two held-out exposed-and-passed turns in Belay's banked captures were hand-adjudicated and both are additions rather than weakenings, so neither became a case. `belay corpus score` therefore still reports **recall unmeasured** and `precision n/a` (0 TP / 0 FP). Read the corpus as a **regression suite that can now express a miss**, not as a measurement that has found one.

### Platform coverage: macOS and Linux, both measured
The sandbox and snapshot have **two substrate implementations**, each measured on its own CI job:

| | macOS (Seatbelt + APFS `clonefile`) | Linux (Landlock + seccomp + copy-fidelity) |
|---|---|---|
| **Mechanism** | `sandbox-exec` profiles; APFS reflink snapshot | Landlock ruleset (write scope) + seccomp filter (network); copy snapshot with sidecar repairs, `FICLONE` reflink where probed |
| **Write scope** | `file-write*` under the scope, refused elsewhere | Landlock write rights under the scope, refused elsewhere (measured by the A2 escape matrix) |
| **Reads** | `file-read*` granted **wholesale** — reads are not scoped | Landlock ruleset handles **only write rights**, so reads are also not scoped (same honest limit, different mechanism — see [`THREAT_MODEL.md`](docs/technical/THREAT_MODEL.md)) |
| **Network** | `deny-all` / `allow-all` / `allow-ports` (loopback, by port) | `deny-all` / `allow-all` only. **`allow-ports` refuses with a named cause** — Landlock's net domain scopes TCP by port with no address scope, so the macOS meaning cannot be expressed (A1 decision, stated in `THREAT_MODEL.md`) |
| **Denial records** | inferred from the child's `Operation not permitted` | inferred from the child's `Permission denied` (EACCES) or `Operation not permitted` (EPERM) — **the EACCES is the same text an ordinary `chmod` produces**, so inside the boundary it is *consistent with* a denial, not *proof* of one |

**The full suite runs on both platforms** (`.github/workflows/ci.yml`: `test (macOS)` and `test (Linux)` on pinned ubuntu-24.04). The gating split, and it is a checked fact — `tests/test_platform_gate_named_causes.py` scans every gate in the sandbox/replay area and fails unless its reason names one of the causes below:

| Cause | Meaning |
|---|---|
| `seatbelt-only` | The test pins against macOS Seatbelt itself — `sandbox-exec`, the SBPL profile language, or the seatbelt containment/denial path. There is no Linux analogue because the mechanism is the subject. |
| `replay-reinvokes-seatbelt` | The end-to-end replay/verify/corpus test re-invokes the server inside the macOS Seatbelt sandbox. The Linux replay path has its own coverage: the ungated snapshot/turn-gate machinery plus the A2/A3 Linux analogues (escape matrix, copy-fidelity round trips, policy pins). |
| `landlock-seccomp-only` | Needs a real Linux kernel with Landlock (kernel ≥ 5.13, LSM enabled) — the Linux sandbox. Runs in the `test (Linux)` job. |
| `linux-simulated` | Simulates a Linux box that is not this one (platform monkeypatch); real-Linux coverage is the `landlock-seccomp-only` tests. |
| `linux-fs-only` | Needs Linux filesystem features: `os.listxattr` (the xattr-carrying fixture), `FICLONE` ioctls, case-sensitive byte-transparent filesystems (the collision fixtures), invalid-UTF8 names. |
| `linux-live-probe` | A live syscall/subprocess probe that can only run on Linux. |
| `bsd-file-flags` | `st_flags` / `chflags` are BSD file flags; Linux has no `st_flags` (the fixture guards `chflags`; the flags axis is macOS-only). |
| `darwin-acl` | `/bin/chmod +a` ACLs are darwin-only; the Linux `gc()` branch has its own coverage. |
| `macos-python3-shim` | A stock-macOS-only environment gate (the `/usr/bin/python3` shim). |
| `landlock-unavailable` | Runtime, measured not declared: this kernel has no Landlock ABI — the tests that need it skip with the cause, exactly as the launcher refuses. |
| `reflink-unavailable` | Runtime, probed: this filesystem cannot `FICLONE` (ext4/tmpfs cannot) — the copy path is the CI path. |
| `collision-fixture-uncreatable` | Runtime: this filesystem cannot hold the distinct byte names (case-insensitive or normalising) — the fixture cannot exist here. |
| `root-environment` | Runtime: running as root, foreign ownership is restorable — nothing to refuse. |
| `docker-unavailable` | Runtime: no Docker CLI/daemon on the host — docker-gated tests skip with this cause. |

**The cross-substrate consequence is first-class, not an edge case.** A corpus case banked on clonefile/APFS (macOS) re-verifying on a Linux box refuses at restore with `UNRESTORABLE_CAPABILITY_MISMATCH` and classifies **SKIP with that named cause** — never a guessed restore, never a REGRESSION, and never a MATCH. The mirror holds (a copy-fidelity case on macOS). `run_case` admits both substrates and lets the capability check decide; only a platform with *no* backend at all skips up front. What the sandbox does and does not enforce on each substrate — reads are not scoped on either, and denial records are inferred on both — is in [`docs/technical/THREAT_MODEL.md`](docs/technical/THREAT_MODEL.md).

### Parallel tool calls are recorded `unrestorable`, not snapshotted
A turn's pre-state is only capturable while nothing else is in flight. When a `tools/call` arrives while another is outstanding — which is the **default** for clients that batch independent calls (Claude Code, Cursor, the OpenAI agents SDK) — the workspace is already a mid-state of the first call, so Belay refuses to clone it and call it a pre-state. It records `unrestorable` and forwards the call unchanged; that turn verifies as `UNVERIFIED`. Belay does **not** serialize turns to make them capturable — that would change how your agent behaves, the one thing this proxy exists not to do. What you lose is coverage; what you keep is honesty.

### A restore declares its own gaps
A snapshot preserves content, mode (including setuid), nanosecond mtime, symlink targets, xattrs, `st_flags`, hardlink structure, and empty directories — each because a naïve copy was measured losing it. It does **not** restore birthtime/ctime/atime (physically unsettable or self-invalidating) or ownership (when not root), and it **detects and refuses** sockets/devices/FIFOs by name rather than silently skipping them. A `present` handle therefore declares its own gaps instead of implying a fidelity no snapshot has.

### A trace is as sensitive as the agent's most sensitive tool argument
Capture is lossless by design, so everything crossing the boundary — **API keys, tokens, file contents, customer data** — lands in the trace verbatim and recoverable. Trace files are owner-only (`0600`); beyond that there is deliberately no redaction and no secret scanning (both are opinions, and a redacted trace can't be replayed). **Treat a trace file as the credential it may contain.**

### Content-neutral, not latency-neutral
The turn gate holds each `tools/call` while it snapshots the pre-state — measured at ~5 ms per turn on a 400-file tree; the cost scales with the tree, so a large workspace pays more. The bytes are never altered; the turn just waits, because a snapshot must complete before the call reaches the server or it is not a pre-state.

### Observability interop correlates only spans that carry trace context
`belay interop correlate <otlp-spans.json> <trace-file>` joins a third-party OTel span to a Belay-recorded MCP turn by the **W3C `traceparent`** the client propagated into MCP `_meta` — the exact string Belay already captured as `trace_context` (C1) — never a time-window or name-based heuristic. A span whose `(traceId, spanId)` names no recorded turn, names more than one (an `ambiguous-correlation`), or was matched but never replayed (no `--server` given, or an unrestorable pre-state) is reported **uncorrelated / `UNVERIFIED`, never `PASS`**, with the exact named cause. Interop is OTLP/JSON parsed with the standard library — **no OpenTelemetry SDK dependency** (zero-dep preserved). This first slice is ingest + correlate + attach over a **single trace file**; exporting verdicts back into a collector, and aggregating a directory of traces, are planned follow-ups. The correlation rate (`matched/total`, denominator always shown) measures how much of the agent's recorded activity actually crossed the MCP boundary — the R6 number.

---

## Develop

Belay is greenfield-clean: Python 3.10+, [uv](https://github.com/astral-sh/uv), zero runtime dependencies.

```bash
git clone https://github.com/haqaliz/belay && cd belay
uv sync
uv run pytest            # the full suite (runs on both macOS and Linux; the platform-gated
                         # tests carry named causes — see "Platform coverage")
uv run belay --help      # the CLI, from source
```

The engine is strictly test-first, and its honesty properties are guarded by tests with *teeth* (watched failing against a stub before they were trusted): the verdict path imports no model, `UNVERIFIED` never counts as `PASS`, the corpus engine never labels its own cases. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and [SECURITY.md](SECURITY.md) for the privacy model and reporting.

---

## Status & roadmap

**Alpha.** The full record → sandbox → replay → verdict spine plus the failure corpus (C1–C6) is built and merged; observability interop (C9)'s first slice — `belay interop correlate` (ingest + correlate + attach over a single trace, export-back deferred) — is also built. The live console (C7) and the A3 claim-re-derivation axis (C8, cuttable) are ahead. The [roadmap](docs/ROADMAP.md) and [capability backlog](docs/technical/CAPABILITY_ROADMAP.md) are authoritative on sequencing; [VISION.md](VISION.md) is the thesis.

## License

[Apache-2.0](LICENSE) — permissive, with an explicit patent and trademark grant.
