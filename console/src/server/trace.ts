// Trace → per-turn derivation (TRACE_FORMAT.md). The console reads frames and
// derived records and NEVER renders a verdict of its own: `tools/call`
// correlation mirrors `belay.index.tool_calls` (a filter over the correlation
// entries), args/results are decoded from the base64 `raw`, annotations come
// from `annotation_snapshot` records whose `source_seq` predates the call, and
// every fact the trace cannot supply is a named gap — never a guess.
//
// The ordering race the format documents (a RESPONSE recorded before its own
// REQUEST) is handled by correlating at the end, by id, so an inverted pair
// still pairs. Records the reader cannot parse are counted, and unknown kinds
// are skipped and named (the unknown-kind rule).

import { readFileSync } from "node:fs";
import type {
  DerivedTurn,
  StateHandle,
  ToolAnnotations,
  TraceGap,
  TraceView,
} from "./types.js";

interface SnapshotRecord {
  seq: number;
  source_seq: number;
  tools: ToolAnnotations[];
}

interface ResponseRecord {
  id: number;
  result: unknown;
  error: unknown;
  truncated: boolean;
}

function decodeFrameRaw(raw: string): unknown {
  const bytes = Buffer.from(raw, "base64");
  return JSON.parse(bytes.toString("utf8"));
}

export function deriveTurns(path: string): TraceView {
  const turns: DerivedTurn[] = [];
  const skippedUnknownKinds = new Set<string>();
  const gaps: TraceGap[] = [];
  let frames = 0;
  let unparseableLines = 0;
  let windowsOpen = false;
  let windowsClose = false;
  const snapshots: SnapshotRecord[] = [];
  const responses = new Map<number, ResponseRecord>();

  const file = readFileSync(path, "utf8");
  for (const line of file.split("\n")) {
    if (line.length === 0) continue;
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(line);
    } catch {
      unparseableLines += 1; // includes a partial final line of a live trace
      continue;
    }

    const kind = record.kind;
    if (kind === "connection_window") {
      if (record.phase === "open") windowsOpen = true;
      if (record.phase === "close") windowsClose = true;
      continue;
    }
    if (kind === "annotation_snapshot") {
      const seq = typeof record.seq === "number" ? record.seq : -1;
      const sourceSeq = typeof record.source_seq === "number" ? record.source_seq : -1;
      const tools = Array.isArray(record.tools) ? (record.tools as ToolAnnotations[]) : [];
      snapshots.push({ seq, source_seq: sourceSeq, tools });
      continue;
    }
    if (kind !== "frame") {
      skippedUnknownKinds.add(typeof kind === "string" ? kind : String(kind));
      continue;
    }

    frames += 1;
    const seq = typeof record.seq === "number" ? record.seq : -1;
    const dir = record.dir;
    if (typeof record.raw !== "string") {
      gaps.push({ seq, cause: "frame with no base64 raw" });
      continue;
    }
    let message: Record<string, unknown>;
    try {
      message = decodeFrameRaw(record.raw) as Record<string, unknown>;
    } catch {
      gaps.push({ seq, cause: "unparseable raw" });
      continue;
    }
    if (typeof message !== "object" || message === null || Array.isArray(message)) {
      gaps.push({ seq, cause: "raw is not a JSON object" });
      continue;
    }

    const isRequest = typeof message.method === "string";
    const isResponse = message.result !== undefined || message.error !== undefined;
    if (!isRequest && !isResponse) {
      gaps.push({ seq, cause: "unclassifiable message (no method, no result/error)" });
      continue;
    }

    const id = typeof message.id === "number" ? message.id : null;
    const stateHandle = (record.state_handle ?? { status: "absent" }) as StateHandle;
    const truncated = record.truncated === true;

    if (isRequest && dir === "c2s" && message.method === "tools/call") {
      const params = (message.params ?? {}) as Record<string, unknown>;
      const tool = typeof params.name === "string" ? params.name : String(params.name);
      turns.push({
        ordinal: turns.length,
        seq,
        id: id as number,
        tool,
        args: params.arguments ?? null,
        result: null,
        isError: false,
        t_in: typeof record.t_in === "string" ? record.t_in : "",
        truncated,
        stateHandle,
        annotations: toolAnnotationsFor(snapshots, seq, tool),
        correlated: "unanswered",
      });
    } else if (isResponse && dir === "s2c" && id !== null) {
      responses.set(id, {
        id,
        result: message.result ?? null,
        error: message.error ?? null,
        truncated,
      });
    }
  }

  for (const turn of turns) {
    const response = responses.get(turn.id);
    if (response === undefined) continue;
    turn.correlated = "answered";
    turn.result = response.result;
    turn.isError = response.error !== null;
  }

  return {
    path,
    turns,
    frames,
    skipped: {
      unparseableLines,
      unknownKinds: [...skippedUnknownKinds].sort(),
      gaps,
    },
    windows: { open: windowsOpen, close: windowsClose },
  };
}

/**
 * The tool's annotations from the LATEST snapshot whose `source_seq` predates
 * the call — a snapshot after the call is not an offering. `null` when no
 * snapshot predates it (never an invented `not-declared`).
 */
function toolAnnotationsFor(
  snapshots: SnapshotRecord[],
  frameSeq: number,
  tool: string,
): ToolAnnotations | null {
  let chosen: SnapshotRecord | null = null;
  for (const snapshot of snapshots) {
    if (snapshot.source_seq <= frameSeq) chosen = snapshot;
    else break; // snapshots are appended in capture order
  }
  if (chosen === null) return null;
  return chosen.tools.find((t) => t.name === tool) ?? null;
}