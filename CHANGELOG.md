# Changelog

All notable changes to Belay are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Belay aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0 — until then,
`0.x` minor bumps may include changes that would be breaking under strict semver.

## [Unreleased]

_Nothing yet._

## [0.4.0] — 2026-07-22

### Fixed

- **Replay is now faithful for absolute-path MCP servers** (`src/belay/replay`, `src/belay/sandbox`,
  `src/belay/snapshot`). Replay restores a snapshot into a scratch dir and sets the server's **cwd**
  there, so it was faithful only for **cwd-relative** servers. A server that takes an absolute root at
  launch and addresses files by absolute path — the reference `@modelcontextprotocol/server-filesystem`
  — bypassed the scratch restore, contaminating the verdict with **live** workspace state in **both**
  directions: false-positive reads (they leaked to the current file), and false-negative writes (a
  corrupt write to the original path was sandbox-denied → empty scratch delta → effect PASS, so a corrupt
  success went uncaught). The gate now records the original workspace root in each snapshot manifest
  (`source_root`), and replay **relocates** it: the server argv root token and any argument whose *whole
  value* is an in-root absolute path are rewritten to the scratch (file **content** is never touched),
  and the reply comparison substring-normalizes both roots (comparison-only). A trace lacking a recorded
  root that needs relocation is **`UNVERIFIED`** with a named cause, never guessed. **Gated and
  additive** — cwd-relative servers are byte-unchanged. Proven by 9 acceptance criteria, including a
  verdict identical across the original workspace being pristine, mutated, and deleted. Found by the
  first live Phase-0 mint. Shell servers that embed paths inside command strings (`command_line`) are a
  tracked follow-up (`replay-relocation-shell`).

### Added

- **Phase-0 batch mint harness** (`eval/minting_driver/{batch,bridge,checkpoint,workspace}.py`,
  `eval/instances/`, eval-only). A stratified SWE-bench-lite instance registry (the draw balances the
  django+sympy concentration so the published number isn't an artifact of two repos), per-instance
  workspace prep at `base_commit` via cached bare clones, and a sequential, resumable, error-contained
  `run_mint` that drives each instance through the gated proxy and renames each capture into the layout
  the stock `belay phase0 run` resolves. Includes a configurable replay/request timeout threaded through
  `run_session`, and an end-to-end test that a short-denominator mint reads as `INSTRUMENT SUSPECT`
  (the R6 false-zero defense) rather than a clean 0%. See `docs/planning/phase0-live-mint/`.

### Notes

- **`npx -y` cannot spawn a server behind the gated proxy** — the contained run denies network and
  `~/.npm` writes by design, so `npx` hangs (npm misreports it as a "root-owned cache" bug). The eval
  harness now **pre-installs** the pinned MCP servers into a gitignored `eval/servers/` and launches them
  by absolute `node` path. Documented in `eval/README.md`.
- The batch harness is **eval-only** and not part of the shipped `belay-harness` wheel. The
  product-affecting change in this release is the replay-fidelity fix above.
- The live Phase-0 mint and its published number remain the next step: re-mint the Stage-1 instance to
  confirm the false positive is gone, then run the staged mint against the pre-registered gate criteria.

## [0.3.0] — 2026-07-21

### Added

- **Phase-0 minting-driver** (`eval/minting_driver/`) — the eval-only tool that produces the real traces
  the Phase-0 corpus runner consumes, closing the last gap before the Phase-0 violation-rate number can
  be published (risk R1). A thin, sequential, **BYOK** MCP agent loop: an LLM proposes one `tools/call`
  at a time against off-the-shelf MCP filesystem + shell servers
  (`@modelcontextprotocol/server-filesystem`, `mcp-server-commands`) placed behind `python -m
  belay.proxy`, so every file/shell action crosses the MCP boundary (**R6 by construction**) with exactly
  **one call in flight** (**R7 by construction**). Includes a model seam with a deterministic fake, an
  interactive newline-JSON-RPC stdio transport, gated capture wiring (all three `BELAY_*` vars, so turns
  are *verifiable* rather than the false-zero capture-only path), and two import-isolated reference
  clients (Anthropic + local OpenAI-compatible). See `eval/README.md` and `eval/instances.md`.

### Notes

- **Eval-only, not a product surface.** The driver lives under `eval/` and is **not** part of the shipped
  `belay-harness` wheel (`src/belay/` is unchanged), **not** a `belay` CLI subcommand, and **not** an
  agent framework — it wires existing pieces to mint traces. The published package is unchanged from
  0.2.0; this release marks the milestone.
- The deterministic "never >1 tool call in flight" control-flow test runs in CI; the single-instance
  live smoke is `manual`-marked and **never** runs in CI (it needs a live model + macOS + Seatbelt).

## [0.2.0] — 2026-07-19

### Added

- **Phase-0 corpus runner** (`src/belay/phase0/`, `belay phase0 run` / `belay phase0 report`). Verifies
  a whole directory of captured MCP runs, ingests every flagged (FAIL) turn into the failure corpus, and
  emits *the number*: the **per-instance violation rate with its denominator**, the per-turn FAIL rate,
  the `UNVERIFIED` rate by named cause, and the false-positive rate. It is a **measurement, not a gate**
  (exits `0` even with violations present). A batch that captured ~no verifiable turns is reported as
  `INSTRUMENT SUSPECT`, never a clean `0%` — a broken capture can't masquerade as a passing run. Reuses
  the C1–C6 engine verbatim through an injectable verifier/ingester seam (so the honesty arithmetic is
  tested cross-platform, no sandbox), with a darwin-gated end-to-end test proving the seam matches real
  replay. No verdict logic changed.

## [0.1.1] — 2026-07-18

### Changed

- New project logo (a figure-eight "belay knot" mark) and README header image. Repo/presentation
  only — the published package is functionally identical to 0.1.0 (assets are not shipped in the wheel).

## [0.1.0] — 2026-07-18

The first public release: the full **record → sandbox → replay → verdict** engine plus the
**failure corpus** (capabilities C1–C6). Python 3.10+, **zero runtime dependencies**, macOS only.

### Added

- **C1 · Byte-transparent capture.** A stdio MCP proxy (`python -m belay.proxy <server>`) that
  forwards bytes verbatim in both directions and writes an append-only, versioned trace of every
  frame. Byte-transparency is proven by a differential test that is itself proven to fail on a
  re-serializing proxy.
- **C2 · Sandbox + snapshot/restore.** The proxied server runs under macOS Seatbelt: writes outside
  `BELAY_SANDBOX_SCOPE` are refused by the kernel and recorded as named denials, and the network is
  denied by default (`BELAY_SANDBOX_NETWORK` widens it). Each `tools/call` is gated to snapshot its
  real pre-state (APFS `clonefile`) behind a manifest that declares its own fidelity gaps; sockets,
  devices, and FIFOs are refused by name rather than silently skipped.
- **C3 · Deterministic replay.** Any recorded turn is re-invoked against its restored pre-state,
  producing a real BTH-1 before/after delta; an unobservable post-state is `UNVERIFIED`, never `[]`.
- **C4 · The A2 replay verdict.** `belay verify` renders a per-turn `PASS`/`WARN`/`FAIL`/`UNVERIFIED`
  from result-equivalence and effect-conformance (does the filesystem effect match the tool's declared
  `readOnlyHint`?), grounded in re-execution with no model consulted.
- **C5 · The A1 invariant verdict.** `belay verify --invariants` holds a run to a task-scoped policy
  (default: `tests/` read-only, on unless `--no-default-invariants`), catching a *cheating* agent whose
  trace is faithful — corrupt success that A2 structurally cannot catch. Grounded on the observed delta;
  zero LLM; `UNVERIFIED` never rendered as `PASS`.
- **C6 · The failure corpus.** `belay corpus add/run/score/label/list/show` stores each caught failure
  as a self-contained, replayable, human-labeled case; `corpus run` re-replays the corpus as a
  regression suite (a regression is kept distinct from an unevaluable-here skip); `corpus score` reports
  precision, recall, **and coverage** against human labels, with `UNVERIFIED` excluded and the engine
  forbidden from ever labeling its own cases. Cases live under the gitignored `corpus/local/`.

### Known limits

- **macOS only** — the sandbox (Seatbelt) and snapshot (`clonefile`) are unverified on Linux; off macOS
  the sandbox raises rather than pretending to contain.
- **MCP boundary only** — an agent's built-in tools (e.g. `Bash`/`Edit`) do not traverse MCP and are
  invisible to Belay.
- **Parallel/batched tool calls** are recorded `unrestorable` and verify as `UNVERIFIED` — Belay does not
  serialize turns to make them capturable.
- **The A3 claim-re-derivation axis** (C8) is not built; the live console (C7) and observability interop
  (C9) are ahead on the roadmap.

[Unreleased]: https://github.com/haqaliz/belay/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/haqaliz/belay/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/haqaliz/belay/releases/tag/v0.1.0
