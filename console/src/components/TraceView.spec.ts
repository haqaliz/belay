// @vitest-environment jsdom
// TraceView — acceptance 1: a fixture trace renders every turn with its
// verdict and the FAILed turn shows its diff; the aggregate strip renders the
// engine's counts; the no-engine state renders distinctly.

import { flushPromises, mount } from "@vue/test-utils";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VerifyJsonDoc } from "../server/types";
import TraceView from "./TraceView.vue";

// Vitest runs with cwd = console/; the jsdom environment renders import.meta.url
// as an http URL, so fixture paths resolve from the filesystem instead.
const fixtures = path.join(process.cwd(), "fixtures");

const failedDoc = JSON.parse(
  readFileSync(path.join(fixtures, "verify-failed.json"), "utf8"),
) as VerifyJsonDoc;

function mockFetch(routes: Record<string, unknown>): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const [pattern, body] of Object.entries(routes)) {
      if (url.startsWith(pattern)) {
        return { ok: true, status: 200, json: async () => body };
      }
    }
    throw new Error(`unmocked fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("TraceView", () => {
  it("renders every turn with its verdict; the FAILed turn shows its diff (acceptance 1)", async () => {
    // /api/trace must return a derived view; build it by hand-decoding the
    // fixture frames (same shape the server's deriveTurns emits).
    const view = {
      path: fixtures + "trace-failed.jsonl",
      turns: [
        {
          ordinal: 0,
          seq: 1,
          id: 1,
          tool: "edit_file",
          args: { path: "tests/test_app.py", old: "assert result == 3", new: "assert result == 0" },
          result: { content: [{ type: "text", text: "edited tests/test_app.py" }] },
          isError: false,
          t_in: "2026-08-24T10:00:00.000000+00:00",
          truncated: false,
          stateHandle: { status: "present", handle: "9f2c1a…" },
          annotations: null,
          correlated: "answered",
        },
      ],
      frames: 2,
      skipped: { unparseableLines: 0, unknownKinds: [], gaps: [] },
      windows: { open: true, close: true },
    };
    const fetchMock = mockFetch({
      "/api/trace": { view },
      "/api/verify": { ok: true, doc: failedDoc },
    });

    const wrapper = mount(TraceView, { props: { tracePath: "trace-failed.jsonl" } });
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith("/api/trace?path=trace-failed.jsonl", { cache: "no-store" });
    const rows = wrapper.findAll('[data-testid="turn-row"]');
    expect(rows).toHaveLength(1);
    expect(wrapper.find(".verdict-fail").exists()).toBe(true);

    const diff = wrapper.find('[data-testid="diff-view"]');
    expect(diff.exists()).toBe(true);
    expect(diff.text()).toContain("-assert result == 3");
    expect(diff.text()).toContain("+assert result == 0");

    // the aggregate strip carries the engine's counts
    const strip = wrapper.find('[data-testid="aggregate-strip"]');
    expect(strip.exists()).toBe(true);
    expect(strip.text()).toContain("FAIL");
    expect(strip.text()).toContain("1 turns verified");

    // coverage line is present on the surface
    expect(wrapper.find('[data-testid="coverage-line"]').text()).toContain("effect:network");
  });

  it("renders the no-engine state distinctly from PASS and UNVERIFIED", async () => {
    mockFetch({
      "/api/trace": {
        view: {
          path: "x",
          turns: [
            {
              ordinal: 0, seq: 1, id: 1, tool: "write_note", args: {}, result: null, isError: false,
              t_in: "2026-08-24T10:00:00.000000+00:00", truncated: false, stateHandle: { status: "absent" },
              annotations: null, correlated: "answered",
            },
          ],
          frames: 1,
          skipped: { unparseableLines: 0, unknownKinds: [], gaps: [] },
          windows: { open: true, close: true },
        },
      },
      "/api/verify": { ok: false, error: { cause: "engine-not-found", detail: "belay" } },
    });

    const wrapper = mount(TraceView, { props: { tracePath: "trace-x.jsonl" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="engine-unavailable"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="engine-unavailable"]').text()).toContain("engine unavailable");
    expect(wrapper.find(".verdict-no-engine").exists()).toBe(true);
    expect(wrapper.find(".verdict-pass").exists()).toBe(false);
    expect(wrapper.find(".verdict-unverified").exists()).toBe(false);
  });

  it("renders the engine's instance-level trajectory block when the doc carries one", async () => {
    const view = {
      path: "x",
      turns: [] as unknown[],
      frames: 0,
      skipped: { unparseableLines: 0, unknownKinds: [], gaps: [] },
      windows: { open: true, close: true },
    };
    mockFetch({
      "/api/trace": { view },
      "/api/verify": {
        ok: true,
        doc: {
          ...failedDoc,
          trajectory: {
            status: "UNVERIFIED",
            cause: "NO_CLAIM_RECORDED",
            message: "no claim record in this trace — nothing was claimed, nothing judged",
          },
        },
      },
    });
    const wrapper = mount(TraceView, { props: { tracePath: "trace-x.jsonl" } });
    await flushPromises();
    const line = wrapper.find('[data-testid="trajectory-line"]');
    expect(line.exists()).toBe(true);
    expect(line.text()).toContain("NO_CLAIM_RECORDED");
    expect(line.text()).toContain("nothing was claimed, nothing judged");
  });

  it("renders a trajectory PASS with its evidence count (the demo capture's shape)", async () => {
    const view = {
      path: "x",
      turns: [] as unknown[],
      frames: 0,
      skipped: { unparseableLines: 0, unknownKinds: [], gaps: [] },
      windows: { open: true, close: true },
    };
    mockFetch({
      "/api/trace": { view },
      "/api/verify": {
        ok: true,
        doc: {
          ...failedDoc,
          trajectory: {
            status: "PASS",
            cause: null,
            message: "PASS — the claim is supported by 2 replayed command turn(s)",
          },
        },
      },
    });
    const wrapper = mount(TraceView, { props: { tracePath: "trace-x.jsonl" } });
    await flushPromises();
    const line = wrapper.find('[data-testid="trajectory-line"]');
    expect(line.exists()).toBe(true);
    expect(line.text()).toContain("supported by 2 replayed command turn(s)");
    expect(line.find(".verdict-pass").exists()).toBe(true);
  });

  it("renders no trajectory line when the doc carries none (null)", async () => {
    const view = {
      path: "x",
      turns: [] as unknown[],
      frames: 0,
      skipped: { unparseableLines: 0, unknownKinds: [], gaps: [] },
      windows: { open: true, close: true },
    };
    mockFetch({
      "/api/trace": { view },
      "/api/verify": { ok: true, doc: { ...failedDoc, trajectory: null } },
    });
    const wrapper = mount(TraceView, { props: { tracePath: "trace-x.jsonl" } });
    await flushPromises();
    expect(wrapper.find('[data-testid="trajectory-line"]').exists()).toBe(false);
  });

  it("emits back", async () => {
    mockFetch({
      "/api/trace": {
        view: {
          path: "x", turns: [], frames: 0,
          skipped: { unparseableLines: 0, unknownKinds: [], gaps: [] },
          windows: { open: true, close: true },
        },
      },
      "/api/verify": { ok: true, doc: failedDoc },
    });
    const wrapper = mount(TraceView, { props: { tracePath: "trace-x.jsonl" } });
    await flushPromises();
    await wrapper.find(".back-btn").trigger("click");
    expect(wrapper.emitted("back")).toBeTruthy();
  });
});