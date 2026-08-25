// @vitest-environment jsdom
// CoverageLine — the coverage block must travel with every status. An ABSENT
// block renders "coverage unavailable" — never fabricated, never dropped.

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import CoverageLine from "./CoverageLine.vue";
import type { CoverageEntry } from "./CoverageLine.vue";

const entries: CoverageEntry[] = [
  {
    dimension: "effect:network",
    block: {
      not_observed_turns: 2,
      of_turns: 2,
      message: "network egress is not observed; a declared-false openWorldHint is recorded as NOT_COVERED, never verified",
    },
  },
];

describe("CoverageLine", () => {
  it("renders the engine's coverage block with dimension, count and message", () => {
    const wrapper = mount(CoverageLine, { props: { coverage: entries } });
    expect(wrapper.find('[data-testid="coverage-line"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("effect:network");
    expect(wrapper.text()).toContain("2/2 turns");
    expect(wrapper.text()).toContain("NOT_COVERED");
  });

  it("renders 'coverage unavailable' when the block is ABSENT — never fabricates", () => {
    const wrapper = mount(CoverageLine, { props: { coverage: null } });
    expect(wrapper.text()).toContain("coverage unavailable");
  });

  it("renders the engine's empty-but-present block honestly, without inventing exclusions", () => {
    const wrapper = mount(CoverageLine, { props: { coverage: [] } });
    expect(wrapper.text()).toContain("no dimensions outside the checked set");
    expect(wrapper.text()).not.toContain("coverage unavailable");
  });
});