---
name: belay-end
description: Use when finishing local work on a Belay unit of work after the PR is merged and you also need a completion report on Desktop. Triggers on "belay-end", "be", "be bug 12", "be feat mcp-proxy-capture", "end full".
arguments: "type id"
---

# Belay End (Full Track)

## Overview

Same cleanup as `belay-end-fast`, **plus** a completion report at the end via `belay-report`.

**Invocation:** `be <type> <id>` — e.g. `be bug 12`, `be feat mcp-proxy-capture`.
Arguments and conventions are identical to `belay-end-fast`.

## Pipeline

**REQUIRED SUB-SKILL:** Use `belay-end-fast` for the cleanup and release pipeline.

Run its **Phase 0 → Phase 3 exactly as written** (safety check → master + pull → remove worktree → delete branch, then the new-version release). Belay's base branch is **`master`**, never `main`. **Phase 3 ALWAYS runs** now that release machinery exists — every finished unit of work cuts a release (feat→minor, bug/chore→patch) via a tag push that `release.yml` publishes to PyPI + a GitHub Release; verify both channels live before calling it done. Only proceed to the report once cleanup verification AND the release both pass.

### Phase 4 — Completion report

**REQUIRED SUB-SKILL:** Use `belay-report` with the unit-of-work id and the corresponding type.

The two skills use slightly different type vocabularies — map before invoking:

| `be` arg | `belay-report` arg |
|---|---|
| `bug` | `bug` |
| `task` | `task` |
| `chore` | `task` |
| `feat` | `feature` |
| `feature` | `feature` |

Example: `be bug 12` → invoke `belay-report` with `bug` + `12` → writes `/Users/aliz/Desktop/bug-12-completion.md`.

`belay-report` fetches the issue via `gh` when reachable (otherwise works from the merged PR / what we just did) and produces the standard template. If it asks for a screenshot/video, provide one (or hand it to the user to attach), then confirm the file landed on Desktop.

### Phase 5 — Comment on the issue (optional)

Same approach as `belay-end-fast` Phase 4 — ask the user, draft (using the issue + the just-generated report as source material), confirm, then `gh issue comment <id>`. Skip if there's no reachable issue.

The comment can mirror the report's plain-English summary in a sentence or two. Same tone rules: no em dashes, no jargon, no commit hashes. Skip entirely if the user declines.

## Common mistakes

| Mistake | Fix |
|---|---|
| Running the report before cleanup | Phases 0–2 first; the report is last |
| Skipping the report on purpose | Use `belay-end-fast` / `bef` instead |
| Passing the wrong type to `belay-report` | Apply the mapping table (`feat`/`feature` → `feature`, `chore` → `task`) |
| Posting the issue comment before the report | The comment (Phase 5) comes after the report (Phase 4); the report's plain-English summary is good source material |
| Cleaning up against `main` | Belay's base branch is `master` |
| Skipping the release during end | The release is `belay-end-fast` Phase 3 and ALWAYS runs now (feat→minor, bug/chore→patch) via a tag push; it belongs to haqaliz, never playdolphia/aliz-manifold, and publishes PyPI + a GitHub Release |
| Posting the comment without confirmation | Draft first, confirm with the user, then post |
