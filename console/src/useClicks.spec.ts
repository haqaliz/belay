// @vitest-environment jsdom
// useClicks — the click log: exactly ONE JSONL record per click, stamped with
// the injected clock; failures degrade silently (counted, never thrown).

import { describe, expect, it, vi } from "vitest";
import { useClicks } from "./useClicks";
import type { ClickEvent } from "./useClicks";

const fixed = new Date("2026-08-24T10:00:00.000Z");

describe("useClicks", () => {
  it("appends exactly one record per click, stamped with the injected clock", async () => {
    const records: ClickEvent[] = [];
    const post = vi.fn(async (record: ClickEvent) => {
      records.push(record);
    });
    const now = vi.fn(() => fixed);
    const tracker = useClicks({ post, now });

    tracker.track("expand-diff", "trace-clean.jsonl", 0);
    tracker.track("open-trace", "trace-clean.jsonl", null);
    tracker.track("open-replay", "trace-clean.jsonl", 0);

    expect(post).toHaveBeenCalledTimes(3);
    expect(records).toEqual([
      { trace: "trace-clean.jsonl", turn: 0, kind: "expand-diff", t: "2026-08-24T10:00:00.000Z" },
      { trace: "trace-clean.jsonl", turn: null, kind: "open-trace", t: "2026-08-24T10:00:00.000Z" },
      { trace: "trace-clean.jsonl", turn: 0, kind: "open-replay", t: "2026-08-24T10:00:00.000Z" },
    ]);
  });

  it("degrades silently when the log write fails — no throw, failure counted", async () => {
    const post = vi.fn(async () => {
      throw new Error("disk full");
    });
    const tracker = useClicks({ post, now: () => fixed });

    expect(() => tracker.track("expand", "trace-a.jsonl", 0)).not.toThrow();
    expect(() => tracker.track("expand", "trace-a.jsonl", 1)).not.toThrow();
    await new Promise((resolve) => setTimeout(resolve, 0)); // let the rejects settle
    expect(tracker.failures.value).toBe(2);
  });

  it("uses the default transport (POST /api/events) when none is injected", () => {
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    try {
      const tracker = useClicks({ now: () => fixed });
      tracker.track("expand", "trace-clean.jsonl", 0);
      expect(fetchMock).toHaveBeenCalledWith("/api/events", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trace: "trace-clean.jsonl", turn: 0, kind: "expand", t: "2026-08-24T10:00:00.000Z" }),
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});