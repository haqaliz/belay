# Belay: Vision

> Every team is shipping agents. Almost none of them can trust one to run unattended.

---

## The bet in one sentence

The valuable, defensible problem in production AI agents is not *building* the agent. It is
**catching it when it fails** — sandboxing what it does, verifying each step by
re-execution, guaranteeing a deterministic replay, and compounding a corpus of real
failures. Belay is the harness that does that around *any* agent, on the user's own infra.

---

## Why now

- **Capability is no longer the blocker; reliability is.** Frameworks make agents easy to
  build. What's missing is the layer that proves an unattended run did the right thing.
- **The failure is measured, not hypothetical.** **27–78% of benchmark-reported agent
  "successes" are "corrupt successes"** — the agent reached the right end-state through a
  broken, unsafe, or cheating path (arXiv 2603.03116). Outcome-only scoring is blind to it.
- **The usual fix — an LLM judge — is itself unreliable.** Up to **35% false positives**
  ("One Token to Fool LLM-as-a-Judge", arXiv 2507.08794); verdicts flip **10–30%** on
  trivial perturbations. The only trustworthy signal is **re-execution against real state**.
- **The market is the hottest in open source.** LLM projects **+178% YoY** on GitHub
  (Octoverse 2025); agents that *act* (browser/terminal/computer control) are the fastest
  sub-category — and every one of them needs a harness.
- **The direction is being explicitly requested** by the people who fund it: Conviction /
  Sarah Guo's "the harness" RFS, YC's "Software for Agents," Karpathy's "sensors and
  actuators."

---

## The founder's unfair advantage

The moat is **engineering** — sandboxing, deterministic replay, execution-grounded
verification, and the evaluation machinery that compounds a failure corpus. That is exactly
a **full-stack developer + ML engineer's** edge. Belay depends on **no** proprietary dataset,
credential, or model the founder lacks: the hard part is infrastructure, and infrastructure
is the strength.

---

## Why it's defensible ("gets better as models improve")

The durable core is deterministic replay + observed-vs-claimed state diffing + the
accumulated corpus of labeled failures. A stronger base model writes **better checks** and
**cleaner re-derivations** — it makes Belay sharper, never redundant. A judge's guess gets
cheaper to fool; a re-executed diff does not.

---

## Positioning

- **Not an agent framework.** We wrap the framework the user already chose.
- **Not another observability dashboard.** Langfuse / Phoenix / LangSmith *record*; Belay
  sits beside them and adds the one thing they lack — a grounded per-turn verdict.
- **The verdict contract is honest:** `PASS` / `WARN` / `FAIL` / `UNVERIFIED`, and
  `UNVERIFIED` is never dressed up as `PASS`.

---

## The wedge → the company

1. **OSS on-ramp:** a per-turn "record & replay + verdict" layer that plugs in next to
   existing observability. Free, self-hostable, verifiable. Win developer trust and stars.
2. **Team layer:** shared runs, regression gates in CI, an approval gate for risky agent
   actions, the failure corpus as a shared asset.
3. **Control plane:** the managed layer that runs agents in production reliably — the
   business.

Same playbook as the founder's other projects: earn trust with a free verifiable tool,
monetize the managed/enterprise layer later.

---

## Non-goals

- Authoring or orchestrating agents (that's the crowded, commoditizing layer).
- Bare LLM-judge scoring dressed up as verification.
- Anything requiring raw-data egress, proprietary datasets, or credentials the founder lacks.
- Any design where a better base model would make Belay redundant.

---

## The one-line mantra

**Let the agent take risks. Belay catches the fall, proves what happened, and replays it.**
