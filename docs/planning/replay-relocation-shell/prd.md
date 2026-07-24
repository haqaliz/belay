# PRD — `replay-relocation-shell`

**Unit:** feat/replay-relocation-shell · **Owner:** aliz · **Date:** 2026-07-24
**Branch:** `feat/replay-relocation-shell/aliz` (off local `master` @ 603c75a — carries
`replay-batch-server-rooting`; unpushed to origin)
**Inputs:** `docs/planning/_card/issue.md`, `docs/planning/replay-relocation-shell/understanding.md`
**Parent:** `replay-absolute-path-fidelity` (v0.4.0) — this is its openly-filed shell follow-up
**Capability:** hardens **C3** (deterministic replay) + the **A2** verdict axis. A2 only.

---

## Problem Statement

Replay is faithful for MCP servers that pass an absolute path as a **whole-value** argument
(`{"path": "/root/x"}`) — the filesystem fix shipped in v0.4.0. It is **not** faithful for the
**shell server** (`mcp-server-commands`, tool `run_process`), which embeds the workspace path
*inside* a command string (`command_line: "python /root/x.py"`) or an `argv` list element.

**The defect is worse than a coverage gap — it is a silent false verdict (R5).** Confirmed by
the code map:

1. **Detection misses it.** `turn_needs_relocation` (`src/belay/replay/relocate.py:192-202`)
   tests only **whole-value** strings; `is_under("python /root/x.py", root)` normpaths the
   entire string → not under root → **False**. An embedded in-root path is not detected.
2. **So it is never even abstained.** `_relocation_decision` (`src/belay/replay/engine.py:290-324`)
   sees "no relocation needed" and replays **without** relocation **and without** UNVERIFIED.
   The `UNROOTABLE_SERVER_COMMAND` guard never fires for shell.
3. **The replay is contaminated.** Replay sets `cwd=scratch`, but the embedded command still
   holds the **original** absolute path, so it reads/writes the *original* workspace. A corrupt
   write is sandbox-denied (scratch is the write-root) → empty scratch delta → **effect PASS
   (false negative)**; a read leaks live state → **false positive**. Both **silent**.

**Why it matters for the thesis.** An agent that cheats *via shell* — `sed -i 's/assert/pass #/'
tests/foo.py`, `echo > tests/bar.py` — commits a genuine A1 corrupt-success. Today that turn is
**invisible**: not PASS-that-should-FAIL, but not-even-evaluated. Belay's core claim ("we catch
corrupt success") is quietly false for the shell surface. The parent spec named this openly —
*"the Phase-0 number's shell batch is known-contaminated, not silently so"*
(`replay-relocation/spec.md:34`) — at the doc level; at the **verdict** level it is silent, and
this unit closes that.

**Who has it:** first, the founder at the Phase-0 gate (the mint runs a shell batch,
`eval/minting_driver/batch.py:25`); more broadly, every Belay user running the shell server.

## Goals & Success Metrics

Success is a shell-turn verdict that depends **only** on the restored snapshot — either a
faithful PASS/FAIL after relocation, or an honest UNVERIFIED when the command cannot be proven
safe to relocate. **Never a false verdict, never a silent miss.**

| Metric | Target | Grounding |
|---|---|---|
| Silent-miss closed | A `run_process` turn with an embedded in-root path is **never** replayed un-relocated-and-un-flagged | detection acceptance |
| Contamination | Verdict is **invariant to live workspace state** (pristine / mutated / deleted → same verdict) for a relocatable shell turn | acceptance A1 |
| No content corruption | A command string carrying the root as **data** (not a path token) is not rewritten; the delta sees true content | acceptance B2 |
| Faithful catch | A genuinely corrupt shell edit (relocatable) **FAILs**; a benign one does **not** FLAG | acceptance B3/B4 |
| Honest abstain | A shell turn with an in-root path the rewriter cannot prove safe → **UNVERIFIED**, named cause, never PASS/FAIL | acceptance A-fallback |
| Regression | Every existing cwd-relative + filesystem-relocation replay test stays green | acceptance R |
| Determinism | Relocated shell replay is a pure function of (trace, snapshot) — no clock/network/ambient FS | non-functional |

## User Personas & Scenarios

Belay's ICP — the engineer who must answer "did this run actually do the right thing?" — running
an agent whose edits and test-runs go through the shell MCP server. Today Belay's verdict on
those turns is contaminated by whatever state the workspace happens to be in at replay time (or
silently unevaluated). After this, each shell turn either replays faithfully against the snapshot
or is honestly UNVERIFIED.

## Requirements

### Decisions locked in the interview (2026-07-24)

- **Scope = A + B in one unit, two aspects.** A (detect + honest UNVERIFIED) is the floor and the
  fallback; B (command-string relocation) is the value-add built on top of it.
- **Shell-UNVERIFIED is acceptable at the Phase-0 gate.** The number stands on the filesystem
  batch; recovered shell coverage from B is a bonus, not a gate requirement. **Consequence: no
  pressure to over-reach — the rewriter abstains liberally whenever a token is not a provably
  clean whole-value in-root path.**
- **Conservative boundary (the content-corruption guardrail).** Relocate **only whole-token**
  in-root absolute paths inside a properly tokenized command. If an in-root path appears as a
  *substring* of a token (`--file=/root/x`, `/root/x:/y`, inside a quoted blob) or tokenization
  is ambiguous → **abstain (UNVERIFIED)**, never a partial/guessed rewrite. This is the parent
  spec's asymmetry: arguments remap conservatively, replies normalize liberally.
- **Reply comparison is already handled — do not rebuild.** `canonicalize_reply`/`canonicalize_obj`
  (`relocate.py:146-189`) already substring-fold both roots; shell replies with embedded paths
  compare correctly today. Confirm with a test; add no new reply logic.
- **`cwd` already works — out of scope.** A shell turn using the whole-value `cwd` field + relative
  paths already relocates via the existing rule. This unit is only the embedded-in-command-string
  (and embedded-in-`argv`) case.

### Must-have

1. **A committed shell fixture server** (`run_process`-shaped) under `tests/fixtures/` — none
   exists. Mirrors `tests/fixtures/abs_path_editor_server.py`: a `run_process` tool taking
   `command_line` (embedded path), `argv` (list), and `cwd`, with a **deterministic** reply that
   carries the path (so tests isolate the workspace-state variable). Its absence is why the gap
   survived the suite. *(Aspect 1.)*
2. **Field-shaped detection of executed-command paths.** A new predicate
   `command_embeds_in_root_path` recognizes an in-root path embedded inside the shell server's
   **executed-command fields** — `command_line` (string) and `argv` (list element that embeds a
   path but is not itself a whole-value path). It does **not** inspect inert content fields
   (`new_content`/`newText`/`content`) or whole-value path args — those are already correct
   (whole-value paths anywhere, incl. `argv` elements, are relocated by the existing
   `remap_arguments`; content mentioning the root is preserved by the shipped v0.4.0
   content-boundary rule). A detected turn is routed to relocation or abstain — **never silently
   un-relocated**. *(Aspect 1.)* — **See self-critique Gap 2: the "server-agnostic substring
   anywhere" idea was BUILT AND REVERTED (`1f44cf2`); it regressed the filesystem content-mention
   case. The executed-command danger is inherently field/tool-shaped and cannot be inferred from
   annotations.**
3. **A new named UNVERIFIED cause** (e.g. `SHELL_COMMAND_UNRELOCATABLE`) as a sibling constant in
   `engine.py` (near `:101-114`), exported in `__all__` (`:574-578`), with a stable Phase-0 bucket
   label in `report.py` `_PREFIX_LABELS` (`:92-98`). Returned whenever a detected shell turn
   cannot be proven safe to relocate. *(Aspect 1.)*
4. **Command-string relocation, whole-token only.** Tokenize the command (POSIX `/bin/sh` lexing,
   per `eval/README.md:217-219`); rewrite **only** tokens whose *entire value* is `is_under` the
   recorded root → scratch prefix; rewrite is **span-precise** on the original string (locate the
   token span, replace exactly those bytes) so quoting/spacing/all other bytes are untouched.
   `argv` elements use the same per-element whole-value rule. *(Aspect 2.)*
5. **Abstain on anything not provably safe.** If any in-root path occurrence is not a clean
   whole-token path (substring-in-token, ambiguous quoting, un-lexable) → the turn is
   `SHELL_COMMAND_UNRELOCATABLE` (UNVERIFIED), decided **before** any spawn. *(Aspect 2.)*
6. **Gate wiring correctness.** The shell server carries **no argv root token**
   (`eval/minting_driver/servers.py:165-171`), so shell relocation is gated on the manifest
   `source_root` + a detected embedded in-root path — **not** on an argv token. Ensure the shell
   path does not wrongly hit `UNROOTABLE_SERVER_COMMAND` (whose logic keys on an argv token).
   *(Aspect 2.)*
7. **Zero behavior change for the existing cases** — every filesystem-relocation and cwd-relative
   test stays green, including the scratch-isolation test. *(Both aspects.)*

### Should-have

8. **Document the contract** in `TRACE_FORMAT.md` / `CAPABILITY_ROADMAP.md` C3: replay relocates
   whole-token in-root paths inside shell commands, and abstains (UNVERIFIED, named cause) for
   embedded paths it cannot prove safe. Update the C3 doc line that currently defers shell.
9. **Report legibility:** the new cause is legible per-turn and bucketed in the Phase-0 report so
   a shell-heavy mint is visibly UNVERIFIED-by-cause, not silently mis-scored.

### Nice-to-have

10. **Re-mint a shell-using instance** once this lands to confirm end-to-end (belongs to
    `phase0-live-mint`, not here).

## Technical Considerations

**Pipeline position:** capture (untouched) → sandbox restore (untouched) → **replay relocation
(this)** → verdict. Capture-side byte-transparency is not touched; relocation is replay-only, and
re-serializing a shell frame at replay time is the same accepted byte-transparency tension the
parent PRD documented (the hash attests capture, not replay relocation).

**Verdict impact: A2 only.** It does not change what A2 *claims*; it makes A2's existing claim
true for the shell surface, and strengthens UNVERIFIED-never-PASS via the abstain path. A1 and A3
untouched. (A1 benefits indirectly: once a shell edit relocates faithfully, the observed delta A1
evaluates is real — a shell-based `tests/` violation becomes catchable rather than invisible.)

**Determinism:** the bug *is* a determinism violation (verdict depends on ambient FS). The fix
restores determinism for relocatable turns and abstains for the rest.

**Seams (from the map):** `relocate.py` (new command-string primitive + detector branch),
`client.py:294-324` (`_relocate_frame` shell branch), `engine.py:290-324` (`_relocation_decision`
+ new cause constant), `report.py:92-98` (bucket). New fixture under `tests/fixtures/`.

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **Content corruption** — rewriting a root that appears as *data* in a command | Mitigated by whole-token-only + span-precise rewrite + abstain-on-doubt; acceptance B2 is the guard. No gate pressure to relax it. |
| **Tokenization drift** — re-quoting a command changes bytes | Avoided by span-precise replacement on the original string (locate via lexer, replace only the path token's bytes), not tokenize-and-rejoin. |
| **`UNROOTABLE_SERVER_COMMAND` misfire** for the root-less shell server | Must-have 6: shell relocation is gated on manifest root + embedded path, not an argv token; explicit wiring test. |
| **Abstain-everything** — the rewriter is so conservative it never relocates, recovering no coverage | Acceptable per the gate decision (shell-UNVERIFIED is fine); acceptance B1/B3 prove the *relocatable* path actually works so it is not a no-op. |
| **R5** (over-claiming what replay proves) | This unit removes a silent over-claim; the abstain path is the honesty backstop. |
| **R1** (the premise) | Not blocked by this — the number stands on the filesystem batch; this hardens the shell surface. |

**Open questions (for the plan):**
1. Exact lexer: `shlex.split(..., posix=True)` for `/bin/sh` semantics — does it faithfully model
   the server's actual shell invocation, and how are un-lexable strings (→ abstain) detected?
2. `argv`-list vs `command_line`-string: confirmed same per-token whole-value rule; verify the
   `run_process` schema shape the real server emits for each (fixture models both).
3. Does any legitimate `run_process` reply need normalization beyond the existing substring fold?
   (Believed no — confirm with the diff-reply-style test.)

## Out of Scope

- **A general shell parser / path-VFS / partial-token rewriting.** Whole-token remap or abstain.
- **The `cwd` whole-value field** (already handled) and the filesystem server (already shipped).
- **Inferring a root from argv** for the root-less shell server (decided against — abstain).
- **Reply-normalization changes** (already substring-folds; confirm only).
- **A1 / A3 axes, the capture byte-pump, any model-in-the-loop.**
- **The Stage-2 mint and the Phase-0 number itself** (resumes in `phase0-live-mint`).

## Self-Critique (Phase 4)

Scored against the `prd-generator` dimensions; gaps travel with the doc to the review gate.

| Dimension | Score |
|---|---|
| Problem Definition | 🟢 both directions named, mechanism proven by the code map, file-cited, tied to the thesis (shell cheating is invisible today) |
| User Understanding | 🟢 founder-at-gate + every shell-server user |
| Success Metrics | 🟡 see Gap 3 — no stated target for the relocate-vs-abstain ratio; "B recovers little" must be an *acceptable* outcome, not a silent failure |
| Scope Clarity | 🟢 whole-token-only, abstain boundary, four out-of-scope rejections |
| Edge Cases & Risks | 🟡 see Gap 1 — span recovery from a lexer is the real feasibility risk |
| Feasibility | 🟡 see Gap 1 — aspect 2 hinges on recovering byte spans shlex discards |
| Verdict Honesty & Replay | 🟢 A2-only, UNVERIFIED-never-PASS strengthened, named cause, zero LLM, on-moat |

### 🟡 Gap 1 — span recovery is the aspect-2 feasibility crux, and it must fail safe

The span-precise rewrite (aspect 2, must-have 4) needs the **exact byte offset** of each
whole-token path in the original command string. `shlex` discards positions. If offsets can't be
recovered faithfully (quoting, adjacent operators, `$VAR`), the design cannot do a byte-precise
replace — and tokenize-and-rejoin reintroduces re-quoting drift the PRD forbids. **Mitigation
(and a genuinely nice property): when a span can't be recovered, the turn *abstains* (UNVERIFIED)
— B degrades to A, never to a false verdict.** So the risk is *coverage*, not correctness. Make
"span recovery" the first task of the aspect-2 plan (a spike): if a position-preserving tokenizer
isn't cheap, B ships as "relocate the easy whole-`argv` case, abstain the `command_line` case" and
still beats today.

### 🟡 Gap 2 — tool-name-keyed detection is brittle; prefer a content-shaped detector — ⚠️ REVERSED at build (2026-07-24, `1f44cf2`)

**The content-shaped "substring anywhere, any server" detector was built (`0470499`) and then
reverted.** It over-fired: a filesystem `edit` whose `new_content` merely *mentions* the workspace
root was flagged embedded → abstained (UNVERIFIED), regressing the shipped v0.4.0 content-boundary
case (relocate the `path`, preserve content) and violating must-have 7 / honesty property #5. The
lesson: the embedded-path danger is about paths the server will **execute/resolve**, which no MCP
annotation exposes — so detection must key on the known executed-command fields (`command_line`,
`argv`), reverting toward the spec's original field/tool-shaped intent. The narrowed detector
`command_embeds_in_root_path` restores the filesystem case with no test change. **Documented
limitation:** a *different* shell server using differently-named executed-command fields would not
be detected (its whole-value paths are still caught by the existing rule); extensible when one
appears, and honest rather than an over-broad false-abstain on working cases.

Must-have 2 keys the shell branch on the tool name `run_process`. That reintroduces
server-specificity the parent design deliberately avoided (the whole-value rule is
server-agnostic). A renamed tool, or a *different* shell server, would silently miss again.
**Recommended: detect the risk generally — an in-root root string that appears as a *substring*
of a string argument that is *not itself a whole-value path* → route to relocate-or-abstain,
regardless of tool name.** The *relocation primitive* stays shell-specific (tokenizing is
`/bin/sh`-shaped), but the *miss-closing detector* should be general, so no server slips silently.
This strengthens honesty property #3 across all servers, not just `mcp-server-commands`. **Resolve
in the aspect-1 plan** — it may simplify must-have 2 and widen the fixture's coverage claim.

### 🟡 Gap 3 — state that low recovered coverage is a success, not a failure

Because the boundary is deliberately conservative and shell-UNVERIFIED is acceptable at the gate,
B may abstain on the majority of real commands (agents often pass paths as flag substrings:
`--output=/root/x`). The PRD must state explicitly: **the floor (A: no silent miss) is the win;
any coverage B recovers is a bonus.** Otherwise a reviewer later reads a high abstain rate as the
feature underdelivering. Add a success line: "a shell turn is *either* faithfully relocated *or*
honestly UNVERIFIED — 100% of detected shell turns; the relocated fraction is reported, not
targeted."

### The question I'd want answered before greenlighting

**How many real Stage-1 shell commands would actually be relocatable (whole-token path) vs
abstained (substring path)?** If a quick scan of the captured Stage-1/Stage-2 shell traces shows
agents overwhelmingly embed paths as flag substrings, then aspect 2 buys little over aspect 1, and
the honest move is to ship A now and gate B on that evidence. One `grep` over the captured shell
`command_line` values would size the payoff before building the hard part.

---

## Honesty Properties (non-negotiable)

1. A shell-turn verdict depends **only** on (trace, snapshot), never on live workspace state.
2. `UNVERIFIED` is never rendered `PASS`; an un-provably-safe shell command is UNVERIFIED with a
   named cause, never guessed.
3. No silent miss: a detected embedded in-root path is always either relocated or abstained.
4. The fix must not trade the silent miss for a content-corruption false verdict — both the
   relocatable-catch (B3) and the content-not-corrupted (B2) tests are required.
5. No behavior change for the cwd-relative / filesystem cases that already work.
