// @vitest-environment jsdom
// ReplayDialog — valid context invokes the engine (POST /api/replay); missing
// context renders a named-cause UNVERIFIED and NEVER invokes; engine errors
// render as "engine unavailable", distinct from PASS and UNVERIFIED.

import { flushPromises, mount } from "@vue/test-utils";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DerivedTurn, VerifyJsonDoc } from "../server/types";
import ReplayDialog from "./ReplayDialog.vue";

const turn: DerivedTurn = {
  ordinal: 0, seq: 4, id: 2, tool: "write_note", args: { file: "note.txt" }, result: null,
  isError: false, t_in: "2026-08-24T10:00:00.000000+00:00", truncated: false,
  stateHandle: { status: "absent" }, annotations: null, correlated: "answered",
};

const cleanDoc = JSON.parse(
  readFileSync(path.join(process.cwd(), "fixtures", "verify-turn.json"), "utf8"),
) as VerifyJsonDoc;

function mockFetch(route: (url: string, init?: RequestInit) => unknown): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = route(String(input), init);
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ReplayDialog", () => {
  it("missing context renders a named-cause UNVERIFIED and never invokes the engine", async () => {
    const fetchMock = mockFetch(() => {
      throw new Error("must not be called");
    });
    const wrapper = mount(ReplayDialog, { props: { trace: "trace-clean.jsonl", turn } });
    await wrapper.get('[data-testid="run-btn"]').trigger("click");
    await flushPromises();

    expect(fetchMock).not.toHaveBeenCalled();
    const cause = wrapper.find('[data-testid="unverified-cause"]');
    expect(cause.exists()).toBe(true);
    expect(cause.text()).toContain("UNVERIFIED");
    expect(cause.text()).toContain("missing-context");
    expect(cause.text()).toContain("server command and manifest dir");
  });

  it("valid context invokes the engine once and renders the verdict + coverage", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/events") return { ok: true }; // the click log
      expect(url).toBe("/api/replay");
      const body = JSON.parse(String((init as RequestInit).body));
      expect(body).toEqual({
        trace: "trace-clean.jsonl",
        turn: 0,
        server: "python server.py",
        manifest: "/tmp/manifest",
      });
      return { ok: true, doc: cleanDoc };
    });

    const wrapper = mount(ReplayDialog, { props: { trace: "trace-clean.jsonl", turn } });
    await wrapper.get('[data-testid="server-input"]').setValue("python server.py");
    await wrapper.get('[data-testid="manifest-input"]').setValue("/tmp/manifest");
    await wrapper.get('[data-testid="run-btn"]').trigger("click");
    await flushPromises();

    const replayCalls = fetchMock.mock.calls.filter(([url]) => String(url) === "/api/replay");
    expect(replayCalls).toHaveLength(1);
    const result = wrapper.find('[data-testid="replay-result"]');
    expect(result.exists()).toBe(true);
    expect(result.find(".verdict-pass").exists()).toBe(true);
    expect(result.find('[data-testid="coverage-line"]').text()).toContain("effect:network");
  });

  it("an engine error renders 'engine unavailable', distinct from PASS and UNVERIFIED", async () => {
    mockFetch(() => ({ ok: false, error: { cause: "engine-not-found", detail: "belay" } }));
    const wrapper = mount(ReplayDialog, { props: { trace: "trace-clean.jsonl", turn } });
    await wrapper.get('[data-testid="server-input"]').setValue("python server.py");
    await wrapper.get('[data-testid="manifest-input"]').setValue("/tmp/manifest");
    await wrapper.get('[data-testid="run-btn"]').trigger("click");
    await flushPromises();

    const error = wrapper.find('[data-testid="replay-error"]');
    expect(error.exists()).toBe(true);
    expect(error.text()).toContain("engine unavailable");
    expect(error.text()).toContain("engine-not-found");
    expect(wrapper.find(".verdict-pass").exists()).toBe(false);
    expect(wrapper.find(".verdict-unverified").exists()).toBe(false);
  });

  it("emits close", async () => {
    const wrapper = mount(ReplayDialog, { props: { trace: "trace-clean.jsonl", turn } });
    await wrapper.find(".close-btn").trigger("click");
    expect(wrapper.emitted("close")).toBeTruthy();
  });
});