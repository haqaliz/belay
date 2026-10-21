// @vitest-environment jsdom
// ApprovalPanel — the human side of the engine's file contract. It polls the
// pending holds, shows a countdown, writes the decision, and never claims a
// verdict: past the deadline the only text is the engine's fail-closed rule.

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApprovalHold } from "../server/types";
import ApprovalPanel from "./ApprovalPanel.vue";

const BASE = new Date("2026-10-21T10:00:00.000Z").getTime();

function hold(overrides: Partial<ApprovalHold> = {}): ApprovalHold {
  return {
    hold_id: "hold-1",
    tool: "write_note",
    request_id: 2,
    triggers: ["destructive"],
    created_at: BASE / 1000,
    timeout: 60,
    expires_at: BASE / 1000 + 60,
    ...overrides,
  };
}

interface MockResponse {
  status: number;
  body: unknown;
}

/** A fetch stub with one queue per route; the last entry repeats. */
function mockApi(routes: Record<string, MockResponse[]>): ReturnType<typeof vi.fn> {
  const calls: { url: string; method: string; body?: string }[] = [];
  const seen: Record<string, number> = {};
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body as string | undefined });
    const queue = routes[url];
    if (queue === undefined) throw new Error(`unmocked fetch: ${method} ${url}`);
    const index = seen[url] ?? 0;
    seen[url] = index + 1;
    const response = queue[Math.min(index, queue.length - 1)];
    return {
      ok: response.status < 400,
      status: response.status,
      json: async () => response.body,
    };
  });
  vi.stubGlobal("fetch", fn);
  (fn as unknown as { calls: typeof calls }).calls = calls;
  return fn;
}

function mountPanel(): ReturnType<typeof mount> {
  return mount(ApprovalPanel, { props: { now: () => Date.now() } });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ApprovalPanel", () => {
  it("renders nothing when the server is unconfigured", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    mockApi({ "/api/approvals": [{ status: 200, body: { configured: false, holds: [] } }] });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="approval-panel"]').exists()).toBe(false);
  });

  it("lists a pending hold with its tool, triggers and countdown", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    mockApi({ "/api/approvals": [{ status: 200, body: { configured: true, holds: [hold()] } }] });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.get('[data-testid="approval-tool"]').text()).toBe("write_note");
    expect(wrapper.get('[data-testid="approval-triggers"]').text()).toContain("destructive");
    expect(wrapper.get('[data-testid="approval-countdown"]').text()).toContain("60s");
    expect(wrapper.find('[data-testid="approve-btn"]').exists()).toBe(true);
  });

  it("counts down as the poll clock advances", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    mockApi({ "/api/approvals": [{ status: 200, body: { configured: true, holds: [hold()] } }] });
    const wrapper = mountPanel();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2000);
    expect(wrapper.get('[data-testid="approval-countdown"]').text()).toContain("58s");
  });

  it("posts an approval and refetches instead of deciding locally", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    const fn = mockApi({
      "/api/approvals": [{ status: 200, body: { configured: true, holds: [hold()] } }],
      "/api/approvals/decision": [{ status: 200, body: { ok: true } }],
    });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get('[data-testid="approve-btn"]').trigger("click");
    await flushPromises();

    const calls = (fn as unknown as { calls: { url: string; method: string; body?: string }[] }).calls;
    const post = calls.find((c) => c.url === "/api/approvals/decision");
    expect(post?.method).toBe("POST");
    expect(JSON.parse(post!.body!)).toEqual({ hold_id: "hold-1", decision: "approve" });
    // no optimistic removal: the row stands until the server stops listing it
    expect(wrapper.find('[data-testid="approval-hold"]').exists()).toBe(true);
    expect(calls.filter((c) => c.url === "/api/approvals").length).toBeGreaterThanOrEqual(2);
  });

  it("denies with the typed reason", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    const fn = mockApi({
      "/api/approvals": [{ status: 200, body: { configured: true, holds: [hold()] } }],
      "/api/approvals/decision": [{ status: 200, body: { ok: true } }],
    });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get('[data-testid="deny-reason"]').setValue("not this tree");
    await wrapper.get('[data-testid="deny-btn"]').trigger("click");
    await flushPromises();

    const calls = (fn as unknown as { calls: { url: string; method: string; body?: string }[] }).calls;
    const post = calls.find((c) => c.url === "/api/approvals/decision");
    expect(JSON.parse(post!.body!)).toEqual({ hold_id: "hold-1", decision: "deny", reason: "not this tree" });
  });

  it("disables the buttons at the deadline and names the fail-closed rule", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    mockApi({
      "/api/approvals": [
        { status: 200, body: { configured: true, holds: [hold({ timeout: 2, expires_at: BASE / 1000 + 2 })] } },
      ],
    });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="approval-timeout"]').exists()).toBe(false);

    await vi.advanceTimersByTimeAsync(2000);
    expect(wrapper.get('[data-testid="approve-btn"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="deny-btn"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="approval-timeout"]').text()).toBe("timed out — the engine fails closed");
  });

  it("refetches on a 409 and shows no decided state of its own", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
    mockApi({
      "/api/approvals": [
        { status: 200, body: { configured: true, holds: [hold()] } },
        { status: 200, body: { configured: true, holds: [] } },
      ],
      "/api/approvals/decision": [{ status: 409, body: { error: { cause: "hold-expired" } } }],
    });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get('[data-testid="approve-btn"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="approval-hold"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="approval-error"]').text()).toContain("hold-expired");
    expect(wrapper.text()).not.toContain("approved");
  });
});
