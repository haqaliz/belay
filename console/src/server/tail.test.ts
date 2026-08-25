// The append-only tail: size/offset polling with a partial final line pending.
// All appends happen inside the tests on real files in a tmp dir — offline.

import { appendFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createTailState, readTail } from "./tail";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "belay-tail-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function trace(name: string): string {
  return path.join(dir, name);
}

describe("readTail", () => {
  it("reads nothing from a missing file and keeps the offset", () => {
    const state = createTailState(0);
    const delta = readTail(trace("none.jsonl"), state);
    expect(delta).toEqual({ lines: [], pending: null, offset: 0 });
  });

  it("emits complete lines and advances the offset to the last newline", () => {
    const file = trace("a.jsonl");
    writeFileSync(file, '{"seq":0}\n{"seq":1}\n'); // 9 bytes per line + 1 newline each = 20
    const state = createTailState(0);
    const delta = readTail(file, state);
    expect(delta.lines).toEqual(['{"seq":0}', '{"seq":1}']);
    expect(delta.pending).toBeNull();
    expect(delta.offset).toBe(20);
  });

  it("returns nothing on a second poll with no appends", () => {
    const file = trace("a.jsonl");
    writeFileSync(file, '{"seq":0}\n'); // 10 bytes
    const state = createTailState(0);
    readTail(file, state);
    const delta = readTail(file, state);
    expect(delta.lines).toEqual([]);
    expect(delta.pending).toBeNull();
    expect(delta.offset).toBe(10);
  });

  it("holds a partial final line as PENDING, never a complete line", () => {
    const file = trace("live.jsonl");
    writeFileSync(file, '{"seq":0}\n{"seq":1'); // 19 bytes total
    const state = createTailState(0);
    const delta = readTail(file, state);
    expect(delta.lines).toEqual(['{"seq":0}']);
    expect(delta.pending).toBe('{"seq":1');
    // The offset sits at the end of the COMPLETE line: the pending bytes are
    // re-read on the next poll, so the completion is not split across polls.
    expect(delta.offset).toBe(10);
  });

  it("completes a pending line once its newline arrives", () => {
    const file = trace("live.jsonl");
    writeFileSync(file, '{"seq":0}\n{"seq":1');
    const state = createTailState(0);
    const first = readTail(file, state);
    expect(first.pending).toBe('{"seq":1');

    appendFileSync(file, '}\n');
    const second = readTail(file, state);
    expect(second.lines).toEqual(['{"seq":1}']);
    expect(second.pending).toBeNull();
    expect(second.offset).toBe(20);
  });

  it("re-reads from an existing cursor (a caller resuming mid-file)", () => {
    const file = trace("a.jsonl");
    writeFileSync(file, '{"seq":0}\n{"seq":1}\n');
    const state = createTailState(10); // cursor after the first line
    const delta = readTail(file, state);
    expect(delta.lines).toEqual(['{"seq":1}']);
    expect(delta.offset).toBe(20);
  });

  it("resets to 0 when the file shrank (rotation/truncation)", () => {
    const file = trace("a.jsonl");
    writeFileSync(file, '{"seq":0}\n{"seq":1}\n{"seq":2}\n');
    const state = createTailState(20);
    writeFileSync(file, '{"seq":0}\n'); // truncated — a NEW trace
    const delta = readTail(file, state);
    expect(delta.lines).toEqual(['{"seq":0}']);
    expect(delta.offset).toBe(10);
  });

  it("handles a multi-byte UTF-8 pending tail without byte drift", () => {
    const file = trace("utf8.jsonl");
    writeFileSync(file, '{"seq":0}\n{"text":"héllo');
    const state = createTailState(0);
    const delta = readTail(file, state);
    expect(delta.lines).toEqual(['{"seq":0}']);
    expect(delta.pending).toBe('{"text":"héllo');
    appendFileSync(file, '"}\n');
    const next = readTail(file, state);
    expect(next.lines).toEqual(['{"text":"héllo"}']);
    expect(next.pending).toBeNull();
  });
});