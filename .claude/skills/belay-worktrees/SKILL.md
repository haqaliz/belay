---
name: belay-worktrees
description: Isolate parallel work in the Belay repo using the Claude Code worktree layout. Use when starting a new bug/feature that should not collide with another running Claude session, or when running the engine and the dashboard from different branches at once. Covers branch naming, worktree placement under .claude/worktrees, per-worktree uv/npm setup, and cleanup.
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Belay Worktree Workflow

## When to Use

- You have another Claude session running on a different branch in Belay and want to start a new bug/feature without colliding.
- You want to run two things side by side — e.g. the `belay` engine on one branch and the dashboard on another.
- The primary checkout is dirty and switching branches would mix work.

Don't use this for one-off file edits that finish in a single session — a worktree is overhead for nothing if you commit + push before the next branch switch.

## Layout — the official Claude Code pattern

Belay is a **single repo**. Worktrees live **inside it** at `.claude/worktrees/<name>/`. `.claude/worktrees/` must be in `.gitignore` so worktree contents never show up as untracked files in the primary.

```
/Users/aliz/dev/at/belay/                                    ← primary (master)
/Users/aliz/dev/at/belay/.claude/worktrees/bug-12/           ← bug #12 worktree
/Users/aliz/dev/at/belay/.claude/worktrees/feat-mcp-proxy-capture/
```

This is the layout documented at https://code.claude.com/docs/en/worktrees. Older sibling layouts (`belay.12` next to the repo) work but make `cd` paths awkward and don't auto-trigger `.worktreeinclude` for `claude --worktree`.

`.gitignore` already carries the `.claude/worktrees/` entry, so this is set up. Verify any time with `git check-ignore -v '.claude/worktrees/'` — keep the **trailing slash**: the pattern is directory-only, so a bare `.claude/worktrees` reports "not ignored" whenever the directory doesn't exist yet, which is a false alarm, not a missing rule.

## Branch naming convention

`<type>/<id>/<owner>` — owner is `aliz`. `id` is a GitHub issue number when there is one, otherwise a short descriptive slug.

- `bug/12/aliz`
- `feat/mcp-proxy-capture/aliz`
- `feat/replay-result-equivalence/aliz`
- `chore/pin-uv-version/aliz`

Worktree dir name drops the slashes: `<type>-<id>` (e.g. `bug-12`, `feat-mcp-proxy-capture`).

## The base branch is `master`

Belay's base branch is **`master`**, not `main`. Every branch-from, rebase target, and PR base is `master`. Never assume `main` exists.

`origin/master` **exists** (the planning docs + skills are pushed), so the normal flow below works. Always branch from `origin/master` rather than local `master` — it's the shared truth, and the local ref may be stale.

## Creating a worktree

### From master (new branch)
```bash
git fetch origin master
git worktree add -b feat/mcp-proxy-capture/aliz .claude/worktrees/feat-mcp-proxy-capture origin/master
```

### From an existing branch you already pushed
```bash
git worktree add .claude/worktrees/feat-mcp-proxy-capture feat/mcp-proxy-capture/aliz
```

### Via Claude Code's --worktree flag
```bash
claude --worktree feat-mcp-proxy-capture
```
This creates `.claude/worktrees/feat-mcp-proxy-capture/` on a new branch `worktree-feat-mcp-proxy-capture` based on `origin/HEAD`. Your preferred issue/slug branch names don't match that auto-generated name — when you name the work after an issue, create the branch first (as above), then `git worktree add` with the existing branch. Don't rely on `--worktree` to name it.

## Auto-copying gitignored config (`.worktreeinclude`)

A `.worktreeinclude` at the repo root lists gitignored files that should follow into new worktrees, consumed automatically by `claude --worktree`.

**Belay currently has no secrets/env files to copy** — the repo is docs-only today. Belay is BYOK for any LLM-assisted claim re-derivation (axis A3), so once a `.env` or local model config exists, create `.worktreeinclude` and list it there, then copy manually when you use bare `git worktree add` (the include is not re-processed after creation):

```bash
# only if such files exist
cp .env .claude/worktrees/feat-mcp-proxy-capture/
```

`.venv/`, `node_modules/`, and the engine's artifact dirs (`/traces/`, `/runs/`, `/_sandbox/`, `/corpus/local/` — all already in `.gitignore`) are intentionally **not** copied. The first two are large and regenerable; recreate the venv per worktree (below). The rest are the user's own run data and never leave the box, per the no-raw-data-egress guardrail in `CLAUDE.md`.

**Never copy captured traces or corpus cases between worktrees.** They're run state tied to the run that produced them, and Belay's replay guarantees depend on that provenance: a trace replayed against a pre-state it didn't record is not a verified run, it's a fabricated one. If a worktree needs run data, point at it by absolute path rather than duplicating it.

## Per-worktree setup (Python core engine — uv)

`.venv` is per-worktree and not shared:

```bash
cd .claude/worktrees/feat-mcp-proxy-capture
uv sync                       # build the venv from uv.lock
uv run pytest                 # run the test suite
uv run belay --help           # the CLI entrypoint
```

⚠️ **Greenfield caveat:** there is **no `pyproject.toml`, no `uv.lock`, and no `src/` yet**. `uv sync` will fail until the Python core is scaffolded, and `uv run pytest` has nothing to run. If your work is the scaffolding, create those files first (test-first: the failing test comes before the package). Skip this section entirely for docs-only work.

## Per-worktree setup (dashboard)

The dashboard (TypeScript, Next.js or Vue — not decided, see `CLAUDE.md`) **does not exist yet**. Once it does, `node_modules` is per-worktree and not auto-installed:

```bash
cd .claude/worktrees/feat-mcp-proxy-capture/dashboard
npm install
npm run dev                   # default port 3000
```

If the primary is already serving on 3000, override:
```bash
npm run dev -- -p 3001
```

## Switching between worktrees

```bash
git -C /Users/aliz/dev/at/belay worktree list
```

To jump into a worktree's Claude session, `cd` into the worktree dir and run `claude`. Resuming a session started in the primary on the same branch isn't supported — start a fresh session in the worktree.

## Cleaning up

After the PR merges and you no longer need the branch locally (see `belay-end-fast`):

```bash
git -C /Users/aliz/dev/at/belay worktree remove .claude/worktrees/feat-mcp-proxy-capture
git -C /Users/aliz/dev/at/belay branch -d feat/mcp-proxy-capture/aliz
```

`worktree remove` refuses if there are uncommitted or untracked changes. Either commit them first, or pass `--force` only if you're sure they should be discarded.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `git worktree add` fails: `invalid reference: origin/master` | Stale local refs | `git fetch origin master` first — `origin/master` exists |
| Branching from `origin/main` | Belay's base branch is `master` | `main` does not exist — always use `master` |
| Worktree contents appear as untracked in primary | `.claude/worktrees/` not ignored | Already in `.gitignore`; verify with `git check-ignore -v '.claude/worktrees/'` (trailing slash) |
| `uv sync` fails: no `pyproject.toml` | Python core not scaffolded yet (greenfield) | Expected — scaffold it (test-first) or skip for docs-only work |
| `uv run` reinstalls everything on first call in a worktree | `.venv` not shared between worktrees | Expected — `uv sync` once per worktree |
| `pytest` import errors in worktree | Forgot `uv sync` (no venv yet) | `uv sync` in the worktree root first |
| `git worktree add` fails: "already checked out" | Branch is checked out in another worktree (often the primary) | `git checkout master` in the conflicting worktree, then retry |
