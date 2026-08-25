// Trace derivation on the SYNTHETIC fixture traces (console/fixtures) plus
// hand-built edge shapes: inverted request/response order, unknown kinds, and
// unparseable raw. Verdicts never appear in any of this — the trace carries
// facts, the engine carries verdicts.

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { deriveTurns } from "./trace";

const fixtures = new URL("../../fixtures/", import.meta.url).pathname;
const clean = path.join(fixtures, "trace-clean.jsonl");
const failed = path.join(fixtures, "trace-failed.jsonl");
const unverified = path.join(fixtures, "trace-unverified.jsonl");

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "belay-trace-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("deriveTurns on the synthetic fixtures", () => {
  it("derives the clean 2-turn run with correlation and annotations", () => {
    const view = deriveTurns(clean);
    expect(view.turns).toHaveLength(2);
    expect(view.windows).toEqual({ open: true, close: true });
    expect(view.skipped.unparseableLines).toBe(0);
    expect(view.skipped.unknownKinds).toEqual([]);

    const [turn0, turn1] = view.turns;
    expect(turn0.ordinal).toBe(0);
    expect(turn0.tool).toBe("write_note");
    expect(turn0.args).toEqual({ file: "note.txt", content: "hello console" });
    expect(turn0.correlated).toBe("answered");
    expect(turn0.result).toMatchObject({ content: [{ type: "text", text: "wrote 1 note" }] });
    expect(turn0.isError).toBe(false);
    expect(turn0.stateHandle).toEqual({ status: "absent" });
    expect(turn0.annotations?.annotations.openWorldHint).toEqual({ state: "declared-false" });
    expect(turn0.annotations?.annotations.readOnlyHint).toEqual({ state: "declared-false" });

    expect(turn1.tool).toBe("list_files");
    expect(turn1.ordinal).toBe(1);
    expect(turn1.annotations?.annotations.readOnlyHint).toEqual({ state: "declared-true" });
  });

  it("derives the FAILed turn with its captured pre-state handle", () => {
    const view = deriveTurns(failed);
    expect(view.turns).toHaveLength(1);
    const [turn] = view.turns;
    expect(turn.tool).toBe("edit_file");
    expect(turn.args).toEqual({ path: "tests/test_app.py", old: "assert result == 3", new: "assert result == 0" });
    expect(turn.correlated).toBe("answered");
    expect(turn.stateHandle.status).toBe("present");
    // no tools/list snapshot predates this call — annotations are honestly null
    expect(turn.annotations).toBeNull();
  });

  it("derives the UNVERIFIED turn with its unrestorable-pre-state cause", () => {
    const view = deriveTurns(unverified);
    expect(view.turns).toHaveLength(1);
    const [turn] = view.turns;
    expect(turn.stateHandle).toMatchObject({
      status: "unrestorable",
      cause: "UNRESTORABLE_CONCURRENT_TURN",
      source: "turn-gate",
    });
  });
});

describe("deriveTurns edge shapes", () => {
  it("correlates an inverted pair (response recorded before its request)", () => {
    const file = path.join(dir, "inverted.jsonl");
    // The documented ordering race: the RESPONSE lands before the REQUEST.
    writeFileSync(
      file,
      [
        '{"v":1,"kind":"frame","seq":1,"dir":"s2c","raw":"' +
          Buffer.from(JSON.stringify({ jsonrpc: "2.0", id: 7, result: { ok: true } })).toString("base64") +
          '","hash_raw":"x","hash_canonical":null,"canonical_form":null,"t_in":"t","observation_point":"proxy","truncated":false,"state_handle":{"status":"absent"}}',
        '{"v":1,"kind":"frame","seq":2,"dir":"c2s","raw":"' +
          Buffer.from(
            JSON.stringify({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name: "ping", arguments: {} } }),
          ).toString("base64") +
          '","hash_raw":"x","hash_canonical":null,"canonical_form":null,"t_in":"t","observation_point":"proxy","truncated":false,"state_handle":{"status":"absent"}}',
        "",
      ].join("\n"),
    );
    const view = deriveTurns(file);
    expect(view.turns).toHaveLength(1);
    expect(view.turns[0].correlated).toBe("answered");
    expect(view.turns[0].result).toEqual({ ok: true });
  });

  it("records unanswered calls honestly", () => {
    const file = path.join(dir, "unanswered.jsonl");
    writeFileSync(
      file,
      '{"v":1,"kind":"frame","seq":1,"dir":"c2s","raw":"' +
        Buffer.from(JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "ping", arguments: {} } })).toString("base64") +
        '","hash_raw":"x","hash_canonical":null,"canonical_form":null,"t_in":"t","observation_point":"proxy","truncated":false,"state_handle":{"status":"absent"}}\n',
    );
    const view = deriveTurns(file);
    expect(view.turns).toHaveLength(1);
    expect(view.turns[0].correlated).toBe("unanswered");
    expect(view.turns[0].result).toBeNull();
  });

  it("skips unknown kinds and names them (the unknown-kind rule)", () => {
    const file = path.join(dir, "future.jsonl");
    writeFileSync(
      file,
      [
        '{"v":2,"kind":"quantum_verdict","seq":0,"t_in":"t","observation_point":"proxy"}',
        '{"v":1,"kind":"frame","seq":1,"dir":"c2s","raw":"' +
          Buffer.from(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "ping", arguments: {} } })).toString("base64") +
          '","hash_raw":"x","hash_canonical":null,"canonical_form":null,"t_in":"t","observation_point":"proxy","truncated":false,"state_handle":{"status":"absent"}}',
        "",
      ].join("\n"),
    );
    const view = deriveTurns(file);
    expect(view.turns).toHaveLength(1);
    expect(view.skipped.unknownKinds).toEqual(["quantum_verdict"]);
  });

  it("counts an unparseable final line as skipped, never a turn", () => {
    const file = path.join(dir, "partial.jsonl");
    writeFileSync(file, '{"v":1,"kind":"frame","seq":1,"dir":"c2s","raw":"not-base64","hash_raw":"x","hash_canonical":null,"canonical_form":null,"t_in":"t","observation_point":"proxy","truncated":false,"state_handle":{"status":"absent"}}\n');
    const view = deriveTurns(file);
    expect(view.turns).toHaveLength(0);
    expect(view.skipped.gaps).toEqual([{ seq: 1, cause: "unparseable raw" }]);
  });
});