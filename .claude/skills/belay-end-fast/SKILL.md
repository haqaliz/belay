---
name: belay-end-fast
description: Use when finishing local work on a Belay unit of work after the PR is merged and you want to clean up without generating a completion report. Triggers on "belay-end-fast", "bef", "bef bug 12", "bef feat mcp-proxy-capture", "end fast".
arguments: "type id"
---

# Belay End (Fast Track)

## Overview

Closes out a unit of work's local state after the PR has merged: **master → pull → remove worktree → delete branch**, with an **optional new-version release**. No report (use `belay-end` / `be` for that).

**Invocation:** `bef <type> <id>` — e.g. `bef bug 12`, `bef feat mcp-proxy-capture`.

- `type` ∈ `bug | feat | feature | task | chore` (normalize `feature` → `feat`)
- `id` = the GitHub issue number, or the slug used at begin time
- Owner is `aliz`
- Branch: `<type>/<id>/aliz`; worktree dir: `.claude/worktrees/<type>-<id>`

Belay is a single repo, so this runs once. The base branch is **`master`**, never `main`.

## Pipeline

### Phase 0 — Safety check

Before removing anything:

- **Worktree clean?** `git -C <worktree> status --porcelain` must be empty. If not, stop — commit or stash first.
- **Branch merged?** Confirm the PR is merged (`gh pr view <PR> --json state,mergedAt` if reachable). `git branch -d` will refuse an unmerged branch on purpose; do not bypass with `-D` without explicit user OK.
- **You may be inside the worktree being removed.** Resolve the primary checkout first (Phase 1) and run all commands from there.

### Phase 1 — Master, pulled

Resolve the **primary** checkout (not the worktree). The first line of `git worktree list` is the primary:

```bash
PRIMARY=$(git worktree list | head -1 | awk '{print $1}')
```

Switch and pull, fast-forward only:

```bash
git -C "$PRIMARY" checkout master
git -C "$PRIMARY" pull --ff-only origin master
```

### Phase 2 — Remove worktree, delete branch

```bash
WORKTREE_NAME="<type>-<id>"   # e.g. bug-12, feat-mcp-proxy-capture
BRANCH="<type>/<id>/aliz"     # e.g. bug/12/aliz, feat/mcp-proxy-capture/aliz

git -C "$PRIMARY" worktree remove ".claude/worktrees/$WORKTREE_NAME"
git -C "$PRIMARY" branch -d "$BRANCH"
```

If `worktree remove` refuses due to uncommitted/untracked files, go back to Phase 0 — don't pass `--force` silently.

If `branch -d` refuses because the branch isn't merged into master, surface the message — the PR may not be merged, or there are unpushed commits. Don't use `-D` silently.

After both succeed, verify:

```bash
git -C "$PRIMARY" worktree list           # the worktree should be gone
git -C "$PRIMARY" branch --list "$BRANCH" # should print nothing
```

### Phase 3 — Release a new version (ALWAYS)

**Release machinery exists, so this phase ALWAYS runs — every finished unit of work cuts a new release.** [`RELEASING.md`](../../../RELEASING.md) is the source of truth; `.github/workflows/release.yml` publishes on a tag push, and `pyproject.toml` (`belay-harness`) + `CHANGELOG.md` carry the version and notes. Run this from the **primary** checkout on `master` (the merged work is already there after Phase 1). Do not `gh release create` by hand and do not build/upload artifacts manually — a tag push is the whole mechanism; let the workflow do it.

The steps (follow `RELEASING.md`):

1. **Version from the work type:** `feat`/`feature` → **minor** (`0.x+1.0`), `bug`/`chore`/`task` → **patch** (`0.x.y+1`). Read the current `version` in `pyproject.toml` and compute the next; confirm the exact `vX.Y.Z` with the user only if it's ambiguous, otherwise state it and proceed.
2. **Bump + changelog:** update `version` in `pyproject.toml` and move the `CHANGELOG.md` `[Unreleased]` notes into a new dated `## [X.Y.Z]` section (add a one-line entry describing this unit of work if `[Unreleased]` is empty). Commit to `master` as `aliz@foresightanalytics.ca` (maps to haqaliz).
3. **CI must be green first.** Push the bump commit to `master` and confirm the `CI` workflow passes (`gh run watch`) before tagging. Never tag on red CI — a release is irreversible (a PyPI version can never be reused, even if yanked).
4. **Tag and push** — this triggers the release:
   ```bash
   git tag -a vX.Y.Z -m "belay X.Y.Z" && git push origin vX.Y.Z
   ```
5. **Verify each channel is live before calling it done** (the honesty rule the product enforces — an unchecked channel is `UNVERIFIED`, not `PASS`): watch the release run (`gh run watch`), then confirm **PyPI** (`curl -s https://pypi.org/pypi/belay-harness/json | ...` shows the new version) **and** the **GitHub Release** (`gh release view vX.Y.Z`). Report which channels published and surface any job that failed; never claim a channel shipped without checking it.

**Release identity, do not get this wrong:** the release belongs to the **haqaliz** account (`git@github.com:haqaliz/belay.git`), never `playdolphia`/`aliz-manifold`. The workflow publishes with the repo token (owned by the repo); any manual step must run with `gh` active as haqaliz (`gh auth switch --user haqaliz`). Commit as `aliz@foresightanalytics.ca`.

**Deferred channels (do not fake them):** GHCR/Docker is deliberately deferred until the Linux sandbox slice — a Linux container can't run the macOS-only core — so v0.x releases publish **PyPI + GitHub Release only**. Do not add a container step until `RELEASING.md` says the Linux slice landed.

### Phase 4 — Comment on the issue (optional)

Optional, and only if there's a reachable GitHub issue. Ask first: *"Want me to post a short comment on the issue explaining what we did?"* If the user declines, there's nothing meaningful to say, or there's no issue (the work came from an inline brief), skip.

Otherwise:

1. **Draft a short note** (2–4 sentences). Sources, in order of preference:
   - What the user tells you to say.
   - The merged PR's title + description (`gh pr view <PR>`), if accessible.
   - A best-effort summary from the issue title and the change verb.

   Keep it friendly, light on jargon, no em dashes, no commit hashes, no file paths. The change verb matches the type: `bug → fixed`, `task → done`, `feat`/`feature → shipped`, `chore → done`. Example: *"Shipped the tool call recorder. Every call an agent makes through the proxy is now captured exactly, so a run can be replayed later instead of taken on trust. Let me know if anything looks off."*

2. **Confirm the draft** with the user before posting.

3. **Post it** via `gh`:

   ```bash
   gh issue comment "$ID" --body "<confirmed comment text>"
   ```

   On success `gh` prints the comment URL. Tell the user it landed. If `gh` errors (not authenticated, Issues disabled), surface it and stop — don't retry blindly.

## Common mistakes

| Mistake | Fix |
|---|---|
| Running from inside the worktree being removed | Resolve `PRIMARY` first, run commands from there |
| Checking out / pulling `main` | Belay's base branch is `master`; `main` doesn't exist |
| Using `git pull` (allowing merge) | Use `--ff-only` |
| Forcing branch delete with `-D` | Only after explicit user OK — `-d` refuses unmerged for a reason |
| Forcing worktree remove with `--force` | Same — never silently discard uncommitted work |
| Worktree dir vs branch confusion | Worktree dir is `<type>-<id>` (e.g. `bug-12`); branch is `<type>/<id>/aliz` |
| Posting the issue comment without confirmation | Draft first, show the user, only post after explicit OK |
| Trying to comment when the work has no issue | Skip Phase 4 — it came from an inline brief |
| Skipping the release, or asking whether to release | Phase 3 ALWAYS runs now — every finished unit cuts a release (feat→minor, bug/chore→patch) via a tag push; follow `RELEASING.md` |
| Hand-crafting a release (`gh release create`, manual upload) | A tag push is the whole mechanism; `release.yml` builds + publishes PyPI + the GitHub Release |
| Tagging on red CI | A release is irreversible (a PyPI version can't be reused); confirm CI green before the tag |
| Cutting a future release as `playdolphia` | The release is haqaliz's; switch with `gh auth switch --user haqaliz` |
