# Aspect A1 — `boundary-probe`

> The engine asks the replay boundary what it offers, and both A2 sub-verdicts abstain
> when it does not offer the recorded tool. **This aspect owns the mechanism and the
> decision; A2 (`cause-and-surfaces`) owns how the decision is labelled and rendered.**

## Problem slice

`belay verify` emits a confident **FAIL** on a turn whose tool the replay boundary never
offered. Reproduced verbatim on the committed demo capture — see `prd.md` → *Problem
statement*. The recorded turn genuinely succeeded; Belay reports a deterministic failure of
the agent's tool call.

Two independent A2 sub-verdicts are computed from the same replay, and **both** rest on the
same false premise:

- `render_result_verdict` -> `DIVERGED + DETERMINISTIC -> FAIL` (`src/belay/verify/result.py:18`)
- `render_effect_verdict` -> `declared-false + any delta -> PASS`, message *"the observed
  effect conforms"* (`src/belay/verify/effect.py:18-21`) — **fabricated confidence; nothing
  was observed.**

## In scope

1. **A `tools/list` probe**, run against the **same resolved argv, in the same sandbox, from
   the same restored snapshot** the replay used. It sends `initialize` + `tools/list` only —
   it must **never** enter the replayed conversation (`replay_turn` sends recorded frames
   through `converse`, `src/belay/replay/client.py:341-400`; injecting a frame would change
   what the server is sent and break byte-identical regression).
2. **Export the argv resolution.** `WORKSPACE_PLACEHOLDER` substitution is currently private
   to `engine.replay_turn` (`src/belay/replay/engine.py:508-521`) and never returned. Extract
   it into a shared helper used by **both** the replay and the probe. **Never duplicate it** —
   a second copy diverges silently.
3. **Gate on DIVERGED, before the determinism gate.** The probe runs only on a DIVERGED reply
   and **before** `classify_determinism` (which re-invokes `--replays` >= 3 times,
   `src/belay/verify/result.py:236-241`). Probing first *saves* 3 spawns on a not-offered
   turn rather than adding one.
4. **Three-way, fail-closed outcome** threaded into scoring as `tool_offered: Optional[bool]`:
   - offered by exactly one configured server -> **today's behavior, unchanged** (a real
     divergence still FAILs);
   - offered by **none** -> both A2 sub-verdicts abstain UNVERIFIED;
   - offered by **two or more** configured servers -> abstain UNVERIFIED (ambiguous);
   - probe could not run or could not be read (`None`) -> abstain UNVERIFIED with a
     **distinct** cause. **Absence of evidence is never evidence of absence.**
5. **`render_effect_verdict` gated on the same evidence** — it abstains instead of asserting
   *"the observed effect conforms"* when the boundary never offered the tool.
6. **Message enrichment from the recorded snapshot** (never a decision input): where the
   trace's own `tools/list` snapshot recorded the tool as offered, say so — *"the capture
   recorded this tool as offered; this replay boundary does not offer it."* The **decision**
   rests on the live probe alone.

## Out of scope

- The cause **strings**, bucket labels, `_PREFIX_LABELS`, `_REPLAYED_CAUSES`, and every
  rendering surface -> aspect `cause-and-surfaces`.
- `belay verify --shell-server` -> aspect `verify-shell-server`.
- N-server routing; any trace-format change; capture-side multiplexing; cross-turn caching
  (explicitly **not** in v1 — see `prd.md` M3b).
- Any change to A1 invariants, the trajectory rule, or A3.

## Acceptance criteria (failing tests first)

- **AC-1** A turn whose tool the replay server does not offer is **UNVERIFIED**, not FAIL —
  asserted end-to-end through the real `verify_turn`/`replay_turn` against a fixture server
  that omits the tool. Reproduces the PRD's live repro as a regression test.
- **AC-2 (anti-overreach, load-bearing)** A genuine deterministic divergence on a tool the
  boundary **does** offer still **FAILs**, message unchanged. Pinned for at least two shapes:
  a value mismatch, and a recorded-success vs replayed-`isError` where the tool IS offered.
  *This is the test that proves A2 did not lose detection power.*
- **AC-3** `render_effect_verdict` **abstains** rather than PASSing on a not-offered tool; the
  fabricated *"the observed effect conforms"* message cannot appear beside an abstaining
  result sub-verdict. (Directly pins the reproduced review finding 1.)
- **AC-4** A probe that cannot run or cannot be read yields UNVERIFIED with a cause **distinct
  from** "not offered" — never "not offered", and never a FAIL.
- **AC-5** A tool offered by **two or more** configured servers abstains, never routes on a
  guess.
- **AC-6 (no-op regression)** A trace whose every tool the server offers produces
  **byte-identical** output to today — the probe never fires on a non-DIVERGED reply, and the
  recorded conversation is unchanged.
- **AC-7 (resolution is shared, not copied)** `{workspace}` resolves identically for probe and
  replay, asserted through the single exported helper; a test pins that no second
  implementation exists (e.g. the helper is the only substitution site).
- **AC-8 (trajectory cannot move)** `replayed_is_error` is unchanged on a not-offered turn,
  and an instance-level trajectory verdict computed over such turns is **identical** before
  and after. Mirrors `trajectory-toolset-rescope`'s false-abstention invariant.
- **AC-9** Probe ordering: on a not-offered turn `classify_determinism` is **not** called
  (asserted by seam/spy), proving the 3-spawn saving rather than assuming it.
- **AC-10** Deterministic, offline, fixture servers only, no network, no `manual` marker.
  **Platform gating, corrected:** tests that drive REAL re-execution are **darwin-gated**
  with the existing named cause `replay-reinvokes-seatbelt` (the convention in
  `tests/test_verify_dual_server.py:86-89`, enforced by
  `tests/test_platform_gate_named_causes.py`). Pure-logic tests — routing resolution,
  three-way outcome, probe-failure handling — must be written so they run on **both**
  platforms, using the non-replay seams as `test_verify_dual_server.py` tests 3-5 do.

## Dependencies & sequencing

- **First aspect.** `cause-and-surfaces` consumes the `tool_offered` decision this produces;
  `verify-shell-server` is independent and may land in parallel.
- Touches `src/belay/verify/{result,effect,turn}.py` and `src/belay/replay/{engine,client}.py`.

## Risks specific to this aspect

- **Over-broad discriminator gutting A2** — the single most dangerous outcome. AC-2 is its
  guard and must be written **first**, before the abstention path exists.
- Probe cost on would-be-FAIL turns. Measure and report; do not assume.
- The probe needs a restored workspace (`contained(..., workspace=...)`,
  `src/belay/sandbox/launch.py:189-194`) — it restores the turn's own snapshot, so it asks
  *the same boundary the replay used*, not some other spawn.
