---
name: belay-begin
description: Use when starting work on a Belay unit of work (a GitHub issue id or an inline brief) and you need stakeholder proposals (technical + non-technical PDFs with diagrams) before planning. Triggers on "belay-begin", "bb", "bb bug 12", "bb feat mcp-proxy-capture", "begin full".
arguments: "type id"
---

# Belay Begin (Full Track)

## Overview

Same pipeline as `belay-begin-fast`, plus a **proposal phase**: after the PRD is approved, produce diagrams and two review PDFs (technical + non-technical) for stakeholders, get approval, then plan.

**Invocation:** `bb <type> <id>` — e.g. `bb bug 12`, `bb feat mcp-proxy-capture`.
Arguments and conventions (type set, `<type>/<id>/aliz` branch, descriptive slug, worktree from `master`, GitHub-issue-or-inline-brief source) are identical to `belay-begin-fast`.

The two non-negotiables carry over from `belay-begin-fast`: **always work through the agents team** (every phase, including diagrams and the two proposals), and **implementation is test-first** via `superpowers:test-driven-development`, executed by the agents team.

## Pipeline

**REQUIRED SUB-SKILL:** Use `belay-begin-fast` for the base pipeline.

Run its **Phase 0 → Phase 4 and the ⛔ PRD review gate exactly as written** (worktree → gather context → deep dig → `prd-interview` → `prd-generator` → stop for PRD approval).

**Then, instead of going straight to tech-plan, insert Phase A below. Only after Phase A's approval gate do you run `belay-begin-fast`'s Phase 5 (tech-plan) and Phase 6 (implement — TDD via the agents team).**

### Phase A — Proposals (diagrams → PDFs)

Detailed steps, proposal structure, and `md-to-pdf` invocation: see `references/proposals.md`.

1. **Diagram** — Use `excalidraw`. From the approved PRD, draw as many diagrams as the work needs (system/architecture, data flow, sequence, before/after, etc.). Save to `docs/planning/{slug}/diagrams/*.excalidraw`.
2. **Export** — Use `excalidraw-to-svg` to render every diagram to `.svg` alongside the source.
3. **Write two proposals** (markdown, in `docs/planning/{slug}/proposals/`), embedding the SVGs. Both filenames are prefixed with the type and id so stakeholders can identify the source at a glance:
   - `<type>-<id>-technical-proposal.md` (e.g. `feat-mcp-proxy-capture-technical-proposal.md`) — for engineers: architecture, components, data flow, risks, effort.
   - `<type>-<id>-non-technical-proposal.md` — for stakeholders: problem, value, what changes for users, timeline, plain language.
   Generate the two in parallel (see Agents team).
4. **PDF** — Use `md-to-pdf` to produce `<type>-<id>-technical-proposal.pdf` and `<type>-<id>-non-technical-proposal.pdf`.

### ⛔ Approval gate — STOP

Present both PDFs. **Wait for the user's explicit approval** of the proposals before planning. Do not auto-advance.

### Final phases — Plan & implement

Run `belay-begin-fast`'s **Phase 5 (tech-plan)** → `docs/planning/{slug}/{aspect}/plan_YYYYMMDD.md`, then its **Phase 6 (implement)** — strict TDD (`superpowers:test-driven-development`) executed through the agents team (`superpowers:subagent-driven-development`), one agent per plan task, branch kept green (`uv run pytest`, once the Python core exists).

## Artifact layout (inside the worktree)

```
docs/planning/
├── _card/issue.md                    ← gh dump or inline brief
├── {slug}/prd.md                     ← PRD (approved at the first gate)
├── {slug}/diagrams/*.excalidraw|.svg ← Phase A
├── {slug}/proposals/<type>-<id>-technical-proposal.{md,pdf}
├── {slug}/proposals/<type>-<id>-non-technical-proposal.{md,pdf}
└── {slug}/{aspect}/plan_*.md         ← tech-plan
```

## Agents team (mandatory)

Run **every** phase through the agents team — never serially in the main thread.

**REQUIRED SUB-SKILL:** Use `superpowers:dispatching-parallel-agents`; use `superpowers:subagent-driven-development` for Phase 6.

- Base pipeline: fan out context-gathering across related issues/PRs (as in `belay-begin-fast`).
- Phase A: generate independent diagrams with parallel agents; write the technical and non-technical proposals concurrently (two agents, same PRD + SVGs).
- Phase 6: one agent per independent plan task, each in strict TDD.

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing proposals before the PRD is approved | Phase A starts only after the first ⛔ gate |
| One proposal for both audiences | Always two: technical and non-technical |
| Embedding `.excalidraw` instead of `.svg` | PDFs embed the exported SVGs |
| Skipping the proposal approval gate | Proposals must be approved before tech-plan |
| Diagrams/PDFs outside the worktree | Everything lives under the worktree's `docs/planning/{slug}/` |
| Overstating what a verdict proves in a proposal | Say which axis (A1/A2/A3) checks it; `UNVERIFIED` is never drawn as `PASS` |
| Implementing serially or test-after | Phase 6 is agents-team + strict TDD (RED before GREEN) |
