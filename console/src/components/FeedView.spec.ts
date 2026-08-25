// @vitest-environment jsdom
// FeedView + useFeed — the live feed: turns appear as the trace appends, a
// partial final line renders as PENDING (never a turn), and the strip stays
// honest (turn counts + pending, never invented verdicts). The poll clock and
// fetch are injectable; the test drives a mock trace through three states.

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DerivedTurn } from "../server/types";
import FeedView from "./FeedView.vue";

const t0: DerivedTurn = {
  ordinal: 0, seq: 4, id: 2, tool: "write_note", args: { file: "note.txt" }, result: null,
  isError: false, t_in: "2026-08-24T10:00:00.000000+00:00", truncated: false,
  stateHandle: { status: "absent" }, annotations: null, correlated: "answered",
};
const t1: DerivedTurn = {
  ordinal: 1, seq: 6, id: 3, tool: "list_files", args: { dir: "." }, result: null,
  isError: false, t_in: "2026-08-24T10:00:00.000000+00:00", truncated: false,
  stateHandle: { status: "absent" }, annotations: null, correlated: "answered",
};
const t2: DerivedTurn = {
  ordinal: 2, seq: 8, id: 4, tool: "ping", args: {}, result: null,
  isError: false, t_in: "2026-08-24T10:00:00.000000+00:00", truncated: false,
  stateHandle: { status: "absent" }, annotations: null, correlated: "answered",
};

interface FeedBody {
  cursor: number;
  pending: string | null;
  turns: DerivedTurn[];
  windows: { open: boolean; close: boolean };
  skipped?: unknown;
}

function mockFetch(queues: Record<string, unknown[]>): ReturnType<typeof vi.fn> {
  const calls: Record<string, number> = {};
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const queue = queues[url.split("?")[0]];
    if (queue === undefined) throw new Error(`unmocked fetch: ${url}`);
    const index = calls[url.split("?")[0]] ?? 0;
    calls[url.split("?")[0]] = index + 1;
    const body = queue[Math.min(index, queue.length - 1)];
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("FeedView", () => {
  it("shows turns as the trace appends; a partial line is PENDING, never a turn", async () => {
    vi.useFakeTimers();
    const listing = [
      { name: "trace-live.jsonl", path: "/traces/trace-live.jsonl", size: 100, mtime: "2026-08-24T10:00:02.000Z", turns: 2 },
    ];
    const feedQueue: FeedBody[] = [
      { cursor: 120, pending: null, turns: [t0, t1], windows: { open: true, close: false } },
      { cursor: 120, pending: '{"v":1,"kind":"frame","seq":99', turns: [t0, t1], windows: { open: true, close: false } },
      { cursor: 180, pending: null, turns: [t0, t1, t2], windows: { open: true, close: false } },
    ];
    mockFetch({
      "/api/traces": [{ traces: listing }],
      "/api/feed": feedQueue,
    });

    const wrapper = mount(FeedView, {});
    await flushPromises();
    await vi.advanceTimersByTimeAsync(750); // first feed poll after selection

    // initial state: 2 complete turns, no pending
    expect(wrapper.findAll(".feed-row")).toHaveLength(2);
    expect(wrapper.find('[data-testid="pending-line"]').exists()).toBe(false);

    // the trace appends a PARTIAL line: pending renders, the turn count does
    // NOT grow — a partial line is never a turn
    await vi.advanceTimersByTimeAsync(750);
    expect(wrapper.findAll(".feed-row")).toHaveLength(2);
    expect(wrapper.find('[data-testid="pending-line"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("pending line…");

    // the line completes: the third turn appears
    await vi.advanceTimersByTimeAsync(750);
    expect(wrapper.findAll(".feed-row")).toHaveLength(3);
    expect(wrapper.find('[data-testid="pending-line"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="feed-strip"]').text()).toContain("3 turns");
  });

  it("emits openTrace when a turn is clicked (recorded as a click)", async () => {
    vi.useFakeTimers();
    const listing = [
      { name: "trace-live.jsonl", path: "/traces/trace-live.jsonl", size: 100, mtime: "2026-08-24T10:00:02.000Z", turns: 1 },
    ];
    mockFetch({
      "/api/traces": [{ traces: listing }],
      "/api/feed": [{ cursor: 120, pending: null, turns: [t0], windows: { open: true, close: false } }],
      "/api/events": [{ ok: true }],
    });

    const wrapper = mount(FeedView, {});
    await flushPromises();
    await vi.advanceTimersByTimeAsync(750);

    await wrapper.find(".feed-row").trigger("click");
    expect(wrapper.emitted("openTrace")).toBeTruthy();
    expect(wrapper.emitted("openTrace")![0][0]).toBe("/traces/trace-live.jsonl");
  });
});