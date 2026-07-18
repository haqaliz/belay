# Changelog

All notable changes to Belay are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Belay aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0 — until then,
`0.x` minor bumps may include changes that would be breaking under strict semver.

## [Unreleased]

_Nothing yet._

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
