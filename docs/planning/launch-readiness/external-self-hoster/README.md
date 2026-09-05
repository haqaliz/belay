# External self-hoster — the launch gate's last open item

The READY-TO-PUBLISH gate
(`docs/planning/launch-readiness/CHECKLIST.md`) requires:

> **≥1 external self-hoster** before launch day (roadmap Phase-1 target: ≥3) —
> someone who is not you installed it and caught a real failure on **their**
> agent; their report is a corpus case.

Every other gate item is checked (2026-09-05). This is the only one that needs a
person who is not the owner. This directory is the package for finding that person:

| File | What it is |
|------|------------|
| `invite.md` | The one-page message to send to someone you trust. Friendly, honest, ~1 hour of their time. |
| `runbook.md` | The mission: install → put the proxy in front of their agent → catch a real failure → bank it as a corpus case → report. |
| `.github/ISSUE_TEMPLATE/external-self-hoster-report.md` | The report form they fill in — what a usable report must contain. |

## What counts as DONE (do not relax)

- A person who is **not** the owner installed `belay` on **their** machine
  (PyPI or the container) and ran it against **their** agent's MCP server.
- Their agent produced a turn the engine **FAILed** on a real failure — not a
  setup artifact, and not an `UNVERIFIED` (a false abstention is not a catch).
- They adjudicated it themselves (or with the owner) as a true positive and
  banked it with `belay corpus add --label true-positive`, so the report
  carries a **corpus case id**.
- Their report lands (issue via the template, or direct reply to the invite)
  and `belay corpus run` re-replays the case to `MATCH`.

The roadmap Phase-1 target is ≥3; the gate minimum is ≥1. Do not mark the gate
item on an invite sent — mark it on a **report received with a case id**.

## How to use this

1. Read `invite.md`; send it (edited as you like) to someone who runs agents on
   macOS or Linux with Python 3.10+.
2. Point them at `runbook.md` — it is written for a stranger.
3. When their report arrives, verify the corpus case yourself
   (`belay corpus run`), then tick the gate item.