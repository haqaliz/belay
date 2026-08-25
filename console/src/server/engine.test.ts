// The engine subprocess contract, proven against the STUB engine binary
// (console/fixtures/stub-engine.mjs) — never against the real `belay`, which
// aspect verify-json owns. The stub emits the pinned A1 `verify --json`
// documents; the console's integration with the real engine is proven by A1's
// own tests.

import { chmodSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveBelayBinary, runVerifyJson, verifyArgv } from "./engine";

const stub = new URL("../../fixtures/stub-engine.mjs", import.meta.url).pathname;
const clean = path.join(path.dirname(stub), "trace-clean.jsonl");
const failed = path.join(path.dirname(stub), "trace-failed.jsonl");
const unverified = path.join(path.dirname(stub), "trace-unverified.jsonl");

chmodSync(stub, 0o755);

function env(extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  return { ...process.env, BELAY_CONSOLE_ENGINE: stub, ...extra };
}

describe("resolveBelayBinary", () => {
  it("defaults to `belay` on PATH", () => {
    expect(resolveBelayBinary({})).toBe("belay");
  });

  it("honours the BELAY_CONSOLE_ENGINE override (the repo venv case)", () => {
    expect(resolveBelayBinary({ BELAY_CONSOLE_ENGINE: "/venvs/belay" })).toBe("/venvs/belay");
  });
});

describe("verifyArgv", () => {
  it("builds the verify argv with the trace last", () => {
    expect(verifyArgv({ trace: "/t/trace-a.jsonl" })).toEqual(["verify", "--json", "/t/trace-a.jsonl"]);
  });

  it("adds --turn N before the trace (the replay path)", () => {
    expect(verifyArgv({ trace: "/t/trace-a.jsonl", turn: 3 })).toEqual([
      "verify",
      "--json",
      "--turn",
      "3",
      "/t/trace-a.jsonl",
    ]);
  });
});

describe("runVerifyJson against the stub engine", () => {
  it("parses the clean document and reports exit 0", async () => {
    const result = await runVerifyJson({ trace: clean, env: env() });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.exitCode).toBe(0);
    expect(result.doc.schema).toBe(1);
    expect(result.doc.turns).toHaveLength(2);
    expect(result.doc.turns[0].status).toBe("PASS");
    // the honesty contract on the machine surface: a PASS carries its coverage
    expect(result.doc.coverage["effect:network"].not_observed_turns).toBe(2);
    expect(result.doc.error).toBeNull();
  });

  it("renders verdicts from a parseable FAIL document — exit code is NOT the error signal", async () => {
    const result = await runVerifyJson({ trace: failed, env: env() });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.exitCode).toBe(1);
    expect(result.doc.turns[0].status).toBe("FAIL");
    expect(result.doc.turns[0].sub_verdicts.some((s) => s.kind === "invariant" && s.status === "FAIL")).toBe(true);
  });

  it("renders an UNVERIFIED turn with its named cause", async () => {
    const result = await runVerifyJson({ trace: unverified, env: env() });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.doc.turns[0].status).toBe("UNVERIFIED");
    expect(result.doc.turns[0].cause).toBe("UNRESTORABLE_CONCURRENT_TURN");
  });

  it("passes --turn N through (the replay seam) and gets the single-turn shape", async () => {
    const result = await runVerifyJson({ trace: clean, turn: 1, env: env() });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.doc.turns).toHaveLength(1);
    expect(result.doc.turns[0].ordinal).toBe(1);
    expect(result.doc.trajectory).toBeNull();
  });

  it("surfaces an internal-failure document ({error} + non-zero) as parsed data", async () => {
    const result = await runVerifyJson({ trace: clean, env: env({ STUB_ENGINE_MODE: "error" }) });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.exitCode).toBe(1);
    expect(result.doc.error?.cause).toContain("trace-claim");
  });

  it("returns a named error on unparseable output, never a guess", async () => {
    const result = await runVerifyJson({ trace: clean, env: env({ STUB_ENGINE_MODE: "bad-json" }) });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.cause).toBe("unparseable-json");
  });

  it("returns a named error on empty stdout", async () => {
    const result = await runVerifyJson({ trace: clean, env: env({ STUB_ENGINE_MODE: "empty" }) });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.cause).toBe("empty-output");
  });

  it("returns engine-not-found when the binary does not exist", async () => {
    const result = await runVerifyJson({
      trace: clean,
      env: env({ BELAY_CONSOLE_ENGINE: "/nonexistent/belay" }),
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.cause).toBe("engine-not-found");
  });

  it("does not depend on the repo venv: the override is used verbatim", async () => {
    const result = await runVerifyJson({ trace: clean, env: env() });
    expect(result.ok).toBe(true);
  });
});