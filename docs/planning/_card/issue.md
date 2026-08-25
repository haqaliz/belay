# Card: Live console — the launch surface (launch checklist L6 / C7)

Source: inline brief from the `belay-next` handoff + `docs/planning/launch-readiness/CHECKLIST.md` item L6 + `docs/technical/CAPABILITY_ROADMAP.md` §C7. No GitHub issue exists; the id lives in the branch and PR.

## Brief

L6 of `docs/planning/launch-readiness/CHECKLIST.md` — **C7, the live console**: a local-first, self-hosted web surface that streams a live run feed with per-turn verdicts (PASS/WARN/FAIL/UNVERIFIED) and renders past traces offline with the concrete diff on FAILed turns. It is the visual a Product Hunt launch demos — today the launch demo is CLI output and gifs. DONE = the C7 acceptance criteria from `CAPABILITY_ROADMAP.md` (§C7, lines 710–739): a recorded trace renders every turn with its verdict; a FAILed turn shows its diff; **an UNVERIFIED turn renders distinctly from PASS (a snapshot/DOM test — a correctness test, not a style test, because the whole product rests on it)**; the console works fully offline against a local trace; and the coverage line travels with the status on every surface (the `NOT_COVERED` contract, enforced by test per surface). "Watch and steer" (replay-from-here: any past turn re-runnable from the console) is in scope per §C7. The tech stack is open per `CLAUDE.md` ("TypeScript + Next.js or Vue"); the founder's primary stack is Vue 3 + TypeScript (global env). The PRD must decide: framework, how the console talks to the engine (subprocess CLI vs a local server), and how streaming is delivered. The nearest feasibility risks: the verdict-rendering honesty contract (UNVERIFIED never colored/grouped/summarized as PASS — the repo enforces this per surface by test), and the eval-data intent (§C7: which turns humans click into, which verdicts get overridden).

## DONE criteria (from CHECKLIST.md L6 + C7 acceptance)

> ☐ L6 · C7 live console ("watch and steer") — DONE = local-first live run feed with streaming per-turn verdicts (PASS/WARN/FAIL/UNVERIFIED + the coverage line on every surface), per the CAPABILITY_ROADMAP C7 spec and its acceptance tests. This is the visual a PH launch demos — today it's CLI output and gifs.

C7 acceptance (test-first): (1) a recorded trace renders every turn with its verdict; the FAILed turn shows its diff; (2) an UNVERIFIED turn is asserted to render distinctly from PASS (a snapshot/DOM test — correctness, not style); (3) the console works fully offline against a local trace; (4) every surface carries the coverage line with the status (the `NOT_COVERED` rule, enforced by test per surface).

## Blockers / dependencies

- **Depends on nothing unshipped:** C1–C6 + C9 slice are built; L1–L5 done. The checklist's Block C may start — Block B (installability) is closed.
- **Known caveat (named before the dig):** the verdict-rendering honesty contract is the load-bearing risk — the console is the surface where `UNVERIFIED`-as-`PASS` would be most damaging (the exact failure mode the repo's coverage-line rule exists to prevent). R5 (over-claiming what A2 proves) territory. Also: C7 is "No — the launch surface" in the cuttable column — it is NOT cuttable; C8 (A3) is.

## Open questions (flag for the PRD)

- Framework: Next.js vs Vue (founder's primary stack is Vue 3 + TypeScript)?
- How does the console reach the engine: spawn `belay verify`/`belay replay` subprocesses (zero-dep, local-first, honest) vs a local engine server?
- Streaming: file-tail of the live trace vs an engine-published event stream?
- Does the console render verdicts from a `belay verify --json`-style artifact (deterministic, offline) or compute them itself (no — the engine owns verdicts)?
- Scope of "watch and steer" in this slice: replay-from-here only, or approval/override too (Phase 2 per ROADMAP)?

## Context links

- Launch checklist: `docs/planning/launch-readiness/CHECKLIST.md` (L6 at lines 217–231; Block C; READY-TO-PUBLISH gate at 246–262)
- C7 spec: `docs/technical/CAPABILITY_ROADMAP.md` §C7 (lines 710–739); sequencing table line 865 ("C7 | Live console | Wk 5–6 | 1 | No — the launch surface")
- Verdict contract: `CLAUDE.md` (axes table; the `NOT_COVERED` block; "the coverage line must travel with the status on every surface — enforced by a test per surface")
- Trace format: `docs/technical/TRACE_FORMAT.md`
- Stack: `CLAUDE.md` tech direction ("Dashboard: TypeScript + Next.js or Vue (founder's stack), local-first")
- `belay-next` handoff: pick L4 (shipped); L6/C7 named as the next-highest-leverage capability