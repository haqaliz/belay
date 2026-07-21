# Stage 1 — live findings (2026-07-22)

First live end-to-end drive of the batch harness, on one real SWE-bench-lite instance
(`pallets__flask-4045`). Models used: local Ollama `gpt-oss:20b`, then Gemini
`gemini-flash-latest` via its OpenAI-compatible endpoint (BYOK; no code change — the
driver's `LocalOpenAICompatModel` speaks OpenAI-compat). One-off driver:
`scratchpad/drive_one.py` (not committed — the "founder runs it by hand" step).

**Headline: the harness plumbing is proven end-to-end, and Stage 1 caught a CONFIRMED
replay-fidelity contamination in the *core engine* that would have made a scaled mint
publish a bogus violation rate. The number is BLOCKED on that core-engine issue, not on the
eval harness.**

---

## 1. What is proven (harness plumbing — all ✅)

Every stage ran against a **real** capture, not fixtures:

| Stage | Evidence |
|---|---|
| `run_mint` → real `git` bare-clone + `worktree add --detach` at `base_commit` | flask checked out; `captured` in the checkpoint |
| Per-instance `build_server_command(layout.work_dir)` | filesystem server pointed at the instance's own workspace |
| Gated capture (proxy + Seatbelt + snapshots) | Gemini run: 4-turn trace (111 KB), 4 manifests; gpt-oss run: 8 turns, 15 present snapshots |
| `bridge_capture` → `trace-<id>.jsonl` + `trace-<id>.manifests/` | exact stock-CLI layout produced |
| **Stock `belay phase0 run`** resolves the bridged layout (default resolution, no override) | ran replay over every turn — **the bridge's entire purpose, validated against reality** |
| Per-instance **error containment** | a bad `repo` value and two deprecated model ids were each recorded `failed` with a clear reason; the batch never crashed |
| `INSTRUMENT SUSPECT` on a no-verifiable-turns mint (gpt-oss) | fired correctly — refused a false 0% |

The fake-PIVOT risk on the single-instance path is retired: the stock CLI resolves the
renamed manifests and replays.

## 2. Model-behavior findings

- **`gpt-oss:20b` (local) is too weak to mint verifiable turns.** It issued only read /
  malformed calls — e.g. `read_text_file` with both `head` and `tail`, which the server
  rejects (`isError: true`). Replay faithfully reproduced the errors (A2 result-equivalence
  PASS) but an errored/no-op call has no effect to verify → honest UNVERIFIED → the whole
  mint read `INSTRUMENT SUSPECT`. Correct behavior; the model simply produced nothing to
  verify.
- **`gemini-flash-latest` does real work.** It read the file, issued a real `edit_file`,
  and the guard landed correctly (`blueprints.py:192`:
  `raise ValueError("'name' may not contain a dot '.' character.")`). This gave the
  harness a genuine state-mutating turn to verify — which is what exposed finding #3.
- **Gemini model availability (this key):** `gemini-2.5-flash` and `gemini-2.0-flash`
  return 404 "no longer available to new users"; **`gemini-flash-latest` works** for
  chat/completions + tool calls. The key is an `AQ.`-prefixed credential; use the
  `/v1beta/openai/` base URL with `Authorization: Bearer`.

## 3. ⚠️ CONFIRMED: replay verdicts are contaminated by live workspace state (core engine)

**This blocks a trustworthy number.** On the Gemini capture, `belay phase0 run` reported
`VERIFIED_FLAGGED`, violation rate **1/1 = 100%**, per-turn FAIL **2/4** — but the model's
edit was *correct*. The FLAGs are **false positives**.

**Confirmed by experiment, not inferred:** reverting the workspace to `base_commit`
(undoing the mint's edit) and re-running `belay phase0 run` over the *same* trace + manifests
**changed the per-turn verdicts** — turn 0 (`read_text_file`) flipped **FAIL → UNVERIFIED**,
per-turn FAIL went 2/4 → 1/4. A replay verdict must depend **only** on the restored
snapshot; that it moved with the live workspace is the contamination.

**Mechanism (identified):**
- The reference filesystem MCP server takes its root as a **launch argument**
  (`allowed_dir`) and the recorded tool calls carry **absolute paths** into the original
  workspace.
- `belay.replay.client` restores the snapshot into a fresh **scratch** dir and runs the
  server under `contained(server_command, workspace=scratch)`
  (`src/belay/sandbox/launch.py:181-223`). That builds a Seatbelt profile confining
  **writes** to scratch, but it **does not rewrite the server's argv** (`allowed_dir`) or
  the tool-call path arguments.
- So the server reads/targets the **original** workspace (Seatbelt permits reads outside
  the write-scope), and the restored scratch snapshot is effectively unused for this
  server. turn 0 read the *post-mint* file (guard present) vs the recorded *pre-mint*
  content → divergence → FAIL. turn 1's `edit_file` couldn't re-apply (guard already there,
  or the write to the original is denied) → FAIL.

**Why it hid:** the manual smoke asserts only that *some* turn is verifiable
(`disposition ∈ {VERIFIED_CLEAN, VERIFIED_FLAGGED}`) — a **false-positive FLAG satisfies
that assertion**. So the smoke "passing" never implied the verdict was *correct*.

**Scope & ownership:** this is a **core-engine** issue (`src/belay/replay` + `sandbox`),
**not** the eval harness. It is out of scope for `phase0-live-mint` (eval-only) and needs
its own unit of work. Candidate resolutions to investigate (not decided):
1. Replay restores the snapshot **into the recorded workspace path** (so `allowed_dir` and
   absolute paths align) instead of an anonymous scratch dir; or
2. The replay engine **rewrites** the server argv's root token and remaps recorded
   absolute tool-call paths from the original prefix to the scratch prefix; or
3. Belay documents that only servers operating within the sandboxed **cwd** (relative
   paths) are faithfully replayable, and the filesystem-server path needs (1) or (2).

**Consequence for the gate:** until this is resolved, filesystem-server FLAGs cannot be
trusted, so the violation rate from this path is not publishable. Scaling to 50 instances
now would have produced a ~100%-violation-rate artifact that is mostly false positives —
**exactly the outcome the pre-registered symmetric FP guard and the "verify ONE before
scaling" rule (R6) exist to prevent.** Stage 1 did its job.

## 4. Concrete usage corrections (feed the RUNBOOK)

- `belay phase0 run <dir> --server node <entry> <workspace>` takes **no `--` separator**
  before the server command. `--server` is `nargs=REMAINDER` and captures the rest
  directly; a leading `--` leaks to the top-level parser ("unrecognized arguments: --").
  (The RUNBOOK's `--server -- <cmd>` is wrong.)
- `InstanceRecord.repo` is the **`owner/name` slug** (e.g. `pallets/flask`), not a URL —
  `workspace.py` builds `https://github.com/<slug>.git`. A URL double-prefixes.
- Servers must be **pre-installed** and launched by absolute `node` path (`eval/servers/`),
  never `npx -y` behind the proxy (see the earlier npx finding, commit `324ed75`).
- BYOK via any OpenAI-compatible endpoint works unchanged: set `OPENAI_BASE_URL`,
  `OPENAI_API_KEY`, `BELAY_EVAL_MODEL`, and unset `ANTHROPIC_API_KEY` (the driver prefers
  Anthropic when its key is present).

## 5. Still open (deferred)

- **Multi-instance replay-server** with one `--server` and heterogeneous per-instance
  `work_dir`s was never reached — finding #3 blocks single-instance verdict trust first.
  Note #3 makes the static-`allowed_dir` problem worse at batch scale, since one `--server`
  cannot even name each instance's original workspace.
- `selected.json` (the mint set) remains ungenerated pending the launch-target /
  control-instance decisions — correctly deferred; there is no point drawing 50 instances
  while #3 blocks the verdict.
