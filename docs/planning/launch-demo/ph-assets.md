# PH listing assets — draft

Launch-readiness checklist item S1 (`docs/planning/launch-readiness/CHECKLIST.md`).
**A draft, not a submission.** Every number here is re-derivable from a repo artifact;
if a claim below cannot be traced to one, it does not ship.

**Standing rule:** nothing on this page may claim more than the engine checks. The
coverage line travels with every verdict claim — a `PASS` quoted without it is the exact
failure mode the `NOT_COVERED` status exists to prevent.

---

## 1 · Tagline

> **Your agent said the tests pass. Belay re-ran them.**

The *"Your agent lied. Your dashboard didn't notice. Mine did."* line is **retired for the
demo's headline** (owner decision 2026-08-27, PRD M2‴): it is factually wrong about the
committed capture, where the agent did not lie. Keeping it would put a staged claim on the
front of a project whose entire pitch is that claims survive re-execution.

The replacement says what the artifact shows: the agent made a claim, and the verdict came
from re-running the thing, not from a model's opinion of it.

**Alternates**, same constraint:

- *Verdicts you can re-execute. Not a model's opinion of a model.*
- *Record what the agent did. Replay it. Then decide.*

---

## 2 · The number

> **11 of 60 agent runs claimed the work was verified without ever running anything —
> 18.3%, hand-audited, at n=60.**

**Never quote it bare, and never quote the raw ledger rate.** The mandatory form:

- The rate is **11/60 = 18.3%**, the hand-audited trajectory-axis violation rate over 60
  distinct fresh non-control SWE-bench-lite instances (`claude-opus-5`, one prompt).
- The raw ledger rate **37/52 = 71.2%** decomposes into **11 true positives + 12
  unverifiable-by-seam + 14 A2 replay artifacts** of the verify composition. **Quoting
  71.2% without that decomposition is wrong**, and the 14 artifacts are an instrument
  effect, not a violation rate.
- **n=60 × one model × one prompt is a measurement, not a base rate.** It does not
  generalize to "18% of agents lie."

Source: `docs/technical/PHASE0_RESULTS.md` → *The shell-toolset mint ran, and the gate
PROCEEDs — 2026-08-12*; ledgers under
`docs/planning/mint-shell-toolset-run/mint-run/ledgers/`, re-renderable with
`belay phase0 report`.

The literature figure (**27–78% of benchmark-reported successes are corrupt successes**,
[arXiv 2603.03116](https://arxiv.org/abs/2603.03116)) is context for *why the question
matters*. It is **not ours** and must never be presented as a Belay measurement.

---

## 3 · The demo gif

`assets/belay-demo.gif` — the console rendering the committed capture, regenerated from
the artifact by `npm run record:demo` (console/, manual: real browser, real re-execution).

Five beats: the capture's 7 turns in the feed → every turn `verifying…` with *coverage
unavailable* while the engine re-executes (**no placeholder PASS**) → the verdict lands,
PASS 7 / WARN 0 / FAIL 0 / UNVERIFIED 0 with the trajectory line *"PASS — the claim is
supported by 2 replayed command turn(s)"* → the end of the run → one turn opened onto its
sub-verdicts, including `effect:network NOT_COVERED`.

**What the gif is, said plainly wherever it appears:** the **negative control**. A real
agent (`claude -p`, told only *"make the tests pass"*) fixed the bug honestly, ran the
suite, and said so — and Belay agrees, showing exactly what that agreement covers. We
tried to capture a corrupt success on this repo and **could not**: 18 observed drives
across three conditions, two frontier models, zero corrupt successes
(`docs/planning/launch-demo/demo-capture/DRIVES.md`). Nothing was staged to fill the gap.
That is the honest version of the pitch, and the drive log is the exhibit.

Anyone can re-execute the artifact: `demo/README.md`.

---

## 4 · The coverage line (verbatim, on the listing)

> **macOS + Linux sandbox. Belay verifies what crosses the MCP boundary — an agent's
> built-in tools (Claude Code's `Bash`/`Edit`) do not. A `PASS` covers the dimensions
> Belay checks and excludes the network dimension entirely: there is no network
> instrument, so `openWorldHint` conformance is `NOT_COVERED` — never a network PASS and
> never a fabricated FAIL. `UNVERIFIED` is never rendered as `PASS`.**

Longer form: `README.md` → *Coverage & limits, stated exactly*.

---

## 5 · What Belay is (the one-paragraph positioning)

> Frameworks build the agent. Observability records what it did. **Belay is the third
> thing: the harness.** It proxies the agent's tool calls, runs them in a sandbox,
> snapshots each turn's real pre-state, and then **replays every call against that
> restored state** — rendering `PASS` / `WARN` / `FAIL` / `UNVERIFIED` grounded in
> re-execution and a state diff, never in a model's opinion of itself. Self-hosted;
> traces and state never leave your box. Apache-2.0.

The skeptic's one-command refutation of *"isn't this an LLM judge with extra steps?"* is
worth stating on the listing: **`belay --no-claim-axis` disables the only model-assisted
axis and every PASS/FAIL verdict must survive unchanged — enforced by a test.**

---

## Claims that must NOT appear

- Any Langfuse (or Phoenix/LangSmith/Braintrust) **integration**. C9's first slice ingests
  and correlates OTLP spans; **export-back is deferred**. A side-by-side screenshot that
  implies an integration is a staged claim.
- A **flag turn** in the committed capture. There isn't one — it is all green.
- **A3 / claim re-derivation.** Not built.
- **GHCR image pulls.** The image builds from the checkout; the publish job is deferred.
- Any recall/precision claim for the A1 rule. `corpus score` reads `precision n/a`
  (0 TP / 0 FP) and `recall 0.00 (0/1, n=1)`. **An `n/a` is a zero denominator, not a
  1.00.**

## Open, for the owner

- Which tagline ships (the recommendation is §1's first line).
- Whether the listing leads with the gif (the negative control) or with the number
  (11/60), given that the gif no longer shows a catch.
- Whether a second gif — the console rendering a run that *does* FAIL — is worth
  recording from the mint's banked captures. It would show the catch, but those captures
  are not committed to this repo, so it would not be reproducible by a reader the way the
  demo capture is. **Not done, deliberately; the decision is the owner's.**
