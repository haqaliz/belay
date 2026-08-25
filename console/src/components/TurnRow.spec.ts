// @vitest-environment jsdom
// TurnRow — every surface renders status + coverage line (a PASS without its
// coverage line FAILS a test); a FAILed turn shows its diff; no-engine renders
// distinct from PASS and UNVERIFIED; NOT_COVERED renders as a boundary.

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { DerivedTurn, VerdictTurn } from "../server/types";
import TurnRow from "./TurnRow.vue";
import type { CoverageEntry } from "./CoverageLine.vue";

const coverage: CoverageEntry[] = [
  {
    dimension: "effect:network",
    block: { not_observed_turns: 1, of_turns: 1, message: "network egress is not observed" },
  },
];

function turn(overrides: Partial<DerivedTurn> = {}): DerivedTurn {
  return {
    ordinal: 0,
    seq: 4,
    id: 2,
    tool: "write_note",
    args: { file: "note.txt", content: "hello" },
    result: { content: [{ type: "text", text: "wrote 1 note" }] },
    isError: false,
    t_in: "2026-08-24T10:00:00.000000+00:00",
    truncated: false,
    stateHandle: { status: "absent" },
    annotations: null,
    correlated: "answered",
    ...overrides,
  };
}

function mountRow(t: DerivedTurn, verdict: VerdictTurn | null, engineError = null) {
  return mount(TurnRow, {
    props: { turn: t, verdict, engineError, coverage },
  });
}

const passVerdict: VerdictTurn = {
  ordinal: 0,
  tool: "write_note",
  status: "PASS",
  cause: null,
  sub_verdicts: [
    { axis: "A2", kind: "replay", status: "PASS", message: "reply reproduced" },
    { axis: "A2", kind: "effect:network", status: "NOT_COVERED", message: "openWorldHint: false declared — egress not observed, never verified" },
  ],
};

const failVerdict: VerdictTurn = {
  ordinal: 0,
  tool: "edit_file",
  status: "FAIL",
  cause: null,
  sub_verdicts: [
    { axis: "A1", kind: "invariant", status: "FAIL", message: "tests/test_app.py: assertion weakened (-1/+1): -assert result == 3 | +assert result == 0" },
  ],
};

describe("TurnRow", () => {
  it("renders a PASS with its coverage line — removing the line fails this test", () => {
    const wrapper = mountRow(turn(), passVerdict);
    expect(wrapper.find(".verdict-pass").exists()).toBe(true);
    expect(wrapper.find('[data-testid="coverage-line"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="coverage-line"]').text()).toContain("effect:network");
  });

  it("renders 'coverage unavailable' when coverage data is absent — never a bare PASS", () => {
    const wrapper = mount(TurnRow, {
      props: { turn: turn(), verdict: passVerdict, engineError: null, coverage: null },
    });
    expect(wrapper.find('[data-testid="coverage-line"]').text()).toContain("coverage unavailable");
  });

  it("shows the diff on a FAILed turn (from the sub-verdict message)", () => {
    const wrapper = mountRow(turn({ tool: "edit_file" }), failVerdict);
    const diff = wrapper.find('[data-testid="diff-view"]');
    expect(diff.exists()).toBe(true);
    expect(diff.text()).toContain("-assert result == 3");
    expect(diff.text()).toContain("+assert result == 0");
  });

  it("renders a FAIL badge that is not a PASS badge", () => {
    const wrapper = mountRow(turn({ tool: "edit_file" }), failVerdict);
    expect(wrapper.find(".verdict-fail").exists()).toBe(true);
    expect(wrapper.find(".verdict-pass").exists()).toBe(false);
  });

  it("renders NOT_COVERED sub-verdicts as a boundary, never as PASS", () => {
    const wrapper = mountRow(turn(), passVerdict);
    const nc = wrapper.find(".verdict-not-covered");
    expect(nc.exists()).toBe(true);
    expect(nc.text()).toBe("NOT_COVERED");
    expect(wrapper.find(".sub-verdict[data-kind='effect:network']").text()).toContain("never verified");
  });

  it("renders the no-engine state distinct from PASS and from UNVERIFIED", () => {
    const wrapper = mountRow(turn(), null, { cause: "engine-not-found" });
    const badge = wrapper.find(".verdict-no-engine");
    expect(badge.exists()).toBe(true);
    expect(badge.text()).toBe("NO ENGINE");
    expect(wrapper.find(".verdict-pass").exists()).toBe(false);
    expect(wrapper.find(".verdict-unverified").exists()).toBe(false);
  });

  it("renders an UNVERIFIED turn with its named cause", () => {
    const unverifiedVerdict: VerdictTurn = {
      ordinal: 0,
      tool: "write_note",
      status: "UNVERIFIED",
      cause: "UNRESTORABLE_CONCURRENT_TURN",
      sub_verdicts: [],
    };
    const wrapper = mountRow(turn(), unverifiedVerdict);
    expect(wrapper.find(".verdict-unverified").exists()).toBe(true);
    expect(wrapper.text()).toContain("UNRESTORABLE_CONCURRENT_TURN");
    expect(wrapper.find(".verdict-pass").exists()).toBe(false);
  });

  it("emits replay with the turn", async () => {
    const wrapper = mountRow(turn(), passVerdict);
    await wrapper.find(".replay-btn").trigger("click");
    expect(wrapper.emitted("replay")).toBeTruthy();
    expect(wrapper.emitted("replay")![0][0]).toMatchObject({ ordinal: 0, tool: "write_note" });
  });
});