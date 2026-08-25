// @vitest-environment jsdom
// VerdictBadge — THE honesty surface. The C7 correctness test: UNVERIFIED
// renders distinctly from PASS (different class, different label, never
// grouped), NOT_COVERED renders as a boundary, no-engine renders distinctly.

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import VerdictBadge from "./VerdictBadge.vue";

function badge(status: string, cause: string | null = null) {
  return mount(VerdictBadge, { props: { status, cause } });
}

describe("VerdictBadge — the honesty surface", () => {
  it("UNVERIFIED renders distinctly from PASS — different class and label (C7)", () => {
    const pass = badge("PASS");
    const unverified = badge("UNVERIFIED", "NO_CLAIM_RECORDED");

    expect(pass.classes()).toContain("verdict-pass");
    expect(unverified.classes()).toContain("verdict-unverified");
    expect(unverified.classes()).not.toContain("verdict-pass");
    expect(pass.classes()).not.toContain("verdict-unverified");

    expect(pass.text()).toBe("PASS");
    expect(unverified.text()).toContain("UNVERIFIED");
    expect(unverified.text()).not.toContain("PASS");

    // the named cause travels with the badge — never a bare abstention
    expect(unverified.text()).toContain("NO_CLAIM_RECORDED");
  });

  it("FAIL renders distinctly from PASS", () => {
    const fail = badge("FAIL");
    expect(fail.classes()).toContain("verdict-fail");
    expect(fail.classes()).not.toContain("verdict-pass");
    expect(fail.text()).toBe("FAIL");
  });

  it("NOT_COVERED renders as a boundary, never as PASS", () => {
    const nc = badge("NOT_COVERED");
    expect(nc.classes()).toContain("verdict-not-covered");
    expect(nc.classes()).not.toContain("verdict-pass");
    expect(nc.text()).toBe("NOT_COVERED");
  });

  it("no-engine renders distinctly from PASS and from UNVERIFIED", () => {
    const noEngine = badge("no-engine");
    expect(noEngine.classes()).toContain("verdict-no-engine");
    expect(noEngine.classes()).not.toContain("verdict-pass");
    expect(noEngine.classes()).not.toContain("verdict-unverified");
    expect(noEngine.text()).toBe("NO ENGINE");
  });

  it("carries the data-status attribute for DOM-level assertions", () => {
    expect(badge("UNVERIFIED").attributes("data-status")).toBe("UNVERIFIED");
    expect(badge("PASS").attributes("data-status")).toBe("PASS");
  });
});