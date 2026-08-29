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

  it("renders the boundary abstention's named cause distinctly from PASS (AC-7)", () => {
    // Aspect `cause-and-surfaces`: a turn the replay boundary never offered the tool for
    // is UNVERIFIED with a cause of its own — "replayed but the boundary does not offer
    // the tool" — kept apart from the generic replayed-but-unverified cause so a mint can
    // count it. The console is one of the surfaces that must carry the NAME beside the
    // status; a badge that showed only "UNVERIFIED" would hide the one number the Phase-0
    // gate needed. The engine owns the string (belay.replay.report), so this asserts the
    // badge carries whatever cause it is handed, verbatim and never as a PASS.
    const notOffered = badge(
      "UNVERIFIED",
      "replayed but the boundary does not offer the tool",
    );
    const generic = badge("UNVERIFIED", "replayed but result unverified");

    expect(notOffered.classes()).toContain("verdict-unverified");
    expect(notOffered.classes()).not.toContain("verdict-pass");
    expect(notOffered.text()).toContain("UNVERIFIED");
    expect(notOffered.text()).toContain("does not offer the tool");
    expect(notOffered.text()).not.toContain("PASS");
    // …and it is not rendered as the generic abstention it used to bucket under.
    expect(notOffered.text()).not.toBe(generic.text());
    expect(notOffered.attributes("title")).toBe(
      "replayed but the boundary does not offer the tool",
    );
  });

  it("carries the data-status attribute for DOM-level assertions", () => {
    expect(badge("UNVERIFIED").attributes("data-status")).toBe("UNVERIFIED");
    expect(badge("PASS").attributes("data-status")).toBe("PASS");
  });
});