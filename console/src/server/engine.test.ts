// The engine subprocess contract, proven against the STUB engine binary
// (console/fixtures/stub-engine.mjs) — never against the real `belay`, which
// aspect verify-json owns. The stub emits the pinned A1 `verify --json`
// documents; the console's integration with the real engine is proven by A1's
// own tests.

import { chmodSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveBelayBinary, runVerifyJson, subprocessWallMs, verifyArgv } from "./engine";

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
  it("builds the verify argv with the trace before extra args", () => {
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

  it("adds --timeout <seconds> before the trace when replayTimeoutSeconds is set", () => {
    expect(verifyArgv({ trace: "/t/trace-a.jsonl", replayTimeoutSeconds: 300 })).toEqual([
      "verify",
      "--json",
      "--timeout",
      "300",
      "/t/trace-a.jsonl",
    ]);
  });

  it("keeps --timeout ahead of --turn and the trace (both regular options)", () => {
    expect(verifyArgv({ trace: "/t/trace-a.jsonl", turn: 3, replayTimeoutSeconds: 300 })).toEqual([
      "verify",
      "--json",
      "--timeout",
      "300",
      "--turn",
      "3",
      "/t/trace-a.jsonl",
    ]);
  });

  it("omits --timeout when replayTimeoutSeconds is not set (current behavior)", () => {
    const argv = verifyArgv({ trace: "/t/trace-a.jsonl" });
    expect(argv).not.toContain("--timeout");
    expect(argv).toEqual(["verify", "--json", "/t/trace-a.jsonl"]);
  });

  it("keeps the trace ahead of REMAINDER-style extra args (--server swallows the tail)", () => {
    // `belay verify`'s `--server` is nargs=REMAINDER: a trace placed after it
    // would be eaten and argparse would die with "required: trace".
    expect(
      verifyArgv({
        trace: "/t/trace-a.jsonl",
        turn: 0,
        extraArgs: ["--manifest-dir", "/m", "--server", "python", "server.py"],
      }),
    ).toEqual([
      "verify",
      "--json",
      "--turn",
      "0",
      "/t/trace-a.jsonl",
      "--manifest-dir",
      "/m",
      "--server",
      "python",
      "server.py",
    ]);
  });
});

describe("the console's OWN subprocess wall", () => {
  // The engine's `--timeout` is PER REPLAY; this is the wall around the whole
  // subprocess. When the wall is the smaller of the two it silently overrides the
  // budget the operator authorised, and the engine — SIGTERMed mid-run — leaves
  // empty stdout. Reporting that as `empty-output` blames the engine for the
  // caller's kill, so the two are different named causes.
  it("names ITSELF as the cause when it kills the engine, never empty-output", async () => {
    const result = await runVerifyJson({
      trace: clean,
      env: env({ STUB_ENGINE_MODE: "hang" }),
      timeoutMs: 200,
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.cause).toBe("console-wall-timeout");
    expect(result.error.detail).toContain("200");
  });

  it("scales the wall to the per-replay budget and the turns in scope", () => {
    // A whole-trace verify at 300s/replay over 7 turns really can take ~2 minutes;
    // a wall below that is a guaranteed false error. The floor is the old default,
    // so an unset timeout behaves exactly as before.
    expect(subprocessWallMs(undefined, 7)).toBe(60_000);
    expect(subprocessWallMs(300, 1)).toBeGreaterThanOrEqual(300_000);
    expect(subprocessWallMs(300, 7)).toBeGreaterThanOrEqual(7 * 300_000);
    // Never below the floor, even for a tiny authorised budget.
    expect(subprocessWallMs(1, 1)).toBe(60_000);
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