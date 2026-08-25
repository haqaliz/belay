// Append-only file tail: size/offset polling, portable (no inotify), and
// tolerant of a partial final line — the unterminated tail of a live JSONL
// trace is PENDING, never a verdict. Offsets are bytes, and the offset only
// ever advances to the end of the last COMPLETE line, so a pending line is
// re-read on the next poll until its newline arrives.
//
// A file that shrank (rotation / truncation) resets the offset to 0 — the new
// file is a new trace and is read from its start.

import { readFileSync, statSync } from "node:fs";

export interface TailState {
  /** Byte offset of the next unread byte. */
  offset: number;
}

export interface TailDelta {
  /** Complete JSONL lines newly read (no trailing newline). */
  lines: string[];
  /** The unterminated final line, if the file currently ends mid-line. */
  pending: string | null;
  /** Byte offset to pass back on the next poll. */
  offset: number;
}

export function createTailState(offset = 0): TailState {
  return { offset };
}

export function readTail(path: string, state: TailState): TailDelta {
  let size: number;
  try {
    size = statSync(path).size;
  } catch {
    // Missing file: nothing to read. The offset is kept; if the file later
    // appears smaller than it, the shrink rule below restarts from 0.
    return { lines: [], pending: null, offset: state.offset };
  }

  if (size < state.offset) {
    // The file shrank: it was rotated or truncated. Read the new file whole.
    state.offset = 0;
  }
  if (size === state.offset) {
    return { lines: [], pending: null, offset: state.offset };
  }

  const slice = readFileSync(path).subarray(state.offset, size);
  const lastNl = slice.lastIndexOf(0x0a); // byte-level: no UTF-8 boundary drift
  if (lastNl === -1) {
    // No complete line in this slice: everything is pending.
    return { lines: [], pending: slice.toString("utf8"), offset: state.offset };
  }

  const completeBytes = slice.subarray(0, lastNl);
  const lines = completeBytes.length === 0 ? [] : completeBytes.toString("utf8").split("\n");
  const pendingBytes = slice.subarray(lastNl + 1);
  const offset = state.offset + lastNl + 1;
  state.offset = offset;

  return {
    lines,
    pending: pendingBytes.length === 0 ? null : pendingBytes.toString("utf8"),
    offset,
  };
}