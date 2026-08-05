# Aspect — `live-smoke-confirmation`

**Unit:** `subscription-model-client` · **Order: LAST.** Hard-blocked by `claude-cli-model`.
**This aspect is the unit's exit criterion** (`prd.md` D-5) and the mint's go/no-go.
**Origin:** the 2026-07-28 spec named the one-instance rule as a *mitigation*; this aspect makes it
a **deliverable** — owner decision, 2026-08-05.

---

## Problem slice

The 2026-07-28 spec's headline risk is that **prompted tool-calls are more brittle than native
tool-use** and may degrade edit behaviour. `STAGE2_FINDINGS.md:25-39` records what that looks like
when it goes wrong: a model that only reads produces *"a 0% violation rate that means 'the agent
did nothing'"* — **worse than `INSTRUMENT SUSPECT`, because it looks like a result.**

The probe on 2026-08-05 showed the oracle returns a correctly-shaped tool call for a **toy** prompt
(`{"kind":"tool_call","name":"read_file",...}`). That is **one data point on a synthetic prompt**
and is not evidence that edit behaviour survives on a real repository. Twelve green offline tests
would not be either — they all fake the subprocess.

**Untested, this risk surfaces during an ~11 h batch, where it is expensive.**

## User outcome

Before any batch is funded, the owner knows — from a real run, not a prediction — whether the
subscription oracle actually drives a **file edit through the MCP boundary** on a real instance.

## In scope

- **One** instance, driven end-to-end: `run_mint` → real git clone at `base_commit` → gated
  capture through `python -m belay.proxy` → `bridge_capture` → **stock** `belay phase0 run` →
  replay.
- Run with `--provider claude-cli` and an **explicit** `--model`.
- The test is **`manual`-marked** and guarded **exactly** as `tests/test_minting_driver_smoke.py:111-117`:
  ```python
  pytestmark = [
      pytest.mark.manual,
      pytest.mark.skipif(
          not (sys.platform == "darwin" and os.environ.get("BELAY_EVAL_LIVE") == "1"),
          reason=(...),
      ),
  ]
  ```
  — the `manual` marker, `sys.platform == "darwin"`, and an explicit env opt-in. **Never in CI.**
- The run's **verbatim output committed**, under the freeze protocol.
- Which instance was used, which model, and the wall-clock, all recorded.

## Out of scope

- **Any batch.** One instance. If it works, funding the batch is the *next unit's* decision.
- Producing, quoting, or implying a **violation rate**. n=1 is not a base rate
  (`ROADMAP.md:280`).
- Adjudicating whether anything the agent did was a weakening. **Execution and human adjudication
  are separate evidence grades and are never merged** — this aspect produces execution evidence
  only.
- Changing the instance registry, the draw, or the A1 rule.
- Re-running until it passes. **Re-rolling after seeing a result is the anti-re-roll contract's
  whole subject.** A failure is a finding to fix, not a draw to repeat.

## Acceptance criteria

Judged against `prd.md` §2.1 **Rule A**, which was pre-registered before this ran.

1. **A real `edit_file` (or the server's equivalent write tool) crosses the MCP boundary** and
   appears in the capture. **This is the criterion the aspect exists for.** Reads alone are the
   STAGE2 failure and mean *do not launch a batch*.
2. **The capture is resolved by the stock `belay phase0 run`** with no bespoke path handling — a
   mis-wire here reads as `INSTRUMENT SUSPECT`, a fake PIVOT, which is why `bridge_capture` is the
   load-bearing test.
3. **`INSTRUMENT SUSPECT` does not fire.** If it does, that is a **wiring** report, never a result,
   and the batch stays unfunded.
4. **The turn replays**, with its coverage line, and the verdict is reported **whatever it is** —
   PASS, FAIL, and UNVERIFIED are all acceptable outcomes of this aspect. Only an *unreported* or
   *unexplained* verdict is a failure.
5. **No API key was used** — asserted from the run's own recorded provenance, not from intent.
6. **The recorded provenance names the model explicitly** and matches what was passed.
7. **The output is committed verbatim**, tooling commit first.
8. **The test is excluded from a default `uv run pytest`** — verified by running the default suite
   and confirming it is deselected, not merely marked.

## Dependencies & sequencing

- **Hard-blocked by:** `claude-cli-model` (all 20 criteria green).
- **Independent of:** `exposure-forecast` — they answer different questions and neither gates the
  other.
- **Blocks:** the follow-on mint unit. A red result here means the mint does **not** launch.

## Risks & open questions

- **R-5 (ToS) becomes live here.** Everything before this aspect is offline; this is the first
  outward-facing act on the subscription. It is an **owner-accepted assumption, not a settled
  fact** (2026-07-28), and the docs are silent on running one's own eval on one's own subscription
  and on unattended batch automation. **Re-confirm with the owner before running**, and put it in
  the published write-up's limitations rather than omitting it.
- **A pass here is thin evidence and must be published as such.** It establishes *"the path works
  at n=1"*, never *"edit quality is good"*. The distinction is the same one the record already
  draws for every other n=1 in this project.
- **A failure is informative and cheap, and that is the point.** The pre-registered reading
  (Rule A) already says what each failure shape means, so a red run does not become a negotiation.
- **Open: which instance?** It should be one whose repo has a real in-scope surface — otherwise a
  clean run proves nothing about editing. Candidates fall out of `exposure-forecast` if that
  aspect lands first; otherwise pick from the repos v0.12.0 measured exposure on (`pytest`,
  `flask`, `pylint`) and **say which and why**.
- **Open: does the workspace's MCP server expose a write tool under the name the prompt
  advertises?** The schemas are passed as prompt data, so a name mismatch would look like model
  failure when it is a wiring bug. Verify the advertised names against `tools/list` before
  concluding anything about the model.
