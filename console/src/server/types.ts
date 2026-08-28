// Shared server types: the trace-derived turn, the verdict doc (the pinned A1
// `verify --json` machine contract), and the engine/error envelopes.
//
// The console NEVER computes a verdict of its own: verdicts travel only in the
// engine's JSON document (aspect verify-json, pinned at
// console/fixtures/verify-*.json) and are rendered verbatim. This file is the
// single source of the shapes both sides of the wire speak.

export type VerdictStatus = "PASS" | "WARN" | "FAIL" | "UNVERIFIED" | "NOT_COVERED";

export interface StateHandle {
  status: "absent" | "present" | "unrestorable";
  handle?: string;
  cause?: string;
  source?: string;
}

export interface ToolAnnotations {
  name: string;
  annotations_object: "present" | "absent";
  annotations: Record<string, { state: string; declared_value?: unknown }>;
  incoherence: unknown[];
}

/** A turn derived from the trace (TRACE_FORMAT.md — frames, never verdicts). */
export interface DerivedTurn {
  ordinal: number;
  seq: number;
  id: number;
  tool: string;
  args: unknown;
  result: unknown;
  isError: boolean;
  t_in: string;
  truncated: boolean;
  stateHandle: StateHandle;
  annotations: ToolAnnotations | null;
  correlated: "answered" | "unanswered";
}

export interface TraceGap {
  seq: number;
  cause: string;
}

export interface TraceView {
  path: string;
  turns: DerivedTurn[];
  frames: number;
  /** records the reader skipped, with why (the unknown-kind rule). */
  skipped: { unparseableLines: number; unknownKinds: string[]; gaps: TraceGap[] };
  windows: { open: boolean; close: boolean };
}

// --- the A1 `verify --json` document ---------------------------------------

export interface SubVerdict {
  axis: string;
  kind: string;
  status: VerdictStatus;
  message: string;
  rule?: string;
  scope?: string;
  files_compared?: number;
  cause?: string | null;
}

export interface VerdictTurn {
  ordinal: number;
  tool: string;
  status: VerdictStatus;
  cause: string | null;
  sub_verdicts: SubVerdict[];
}

export interface VerifyAggregate {
  turns_verified: number;
  PASS: number;
  WARN: number;
  FAIL: number;
  UNVERIFIED: number;
}

export interface CoverageBlock {
  not_observed_turns: number;
  of_turns: number;
  message: string;
}

export interface VerifyJsonDoc {
  schema: number;
  trace: string | null;
  turns: VerdictTurn[];
  aggregate: VerifyAggregate;
  coverage: Record<string, CoverageBlock>;
  exposure: { recorded: boolean; judged_turns: number; comparisons: number };
  trajectory: { status: VerdictStatus; cause: string | null; message: string } | null;
  error: { cause: string } | null;
}

// --- engine wrapper envelope ------------------------------------------------

export type EngineErrorCause =
  | "engine-not-found"
  | "spawn-failed"
  | "unparseable-json"
  | "empty-output"
  // The console's own wall killed the subprocess. Kept distinct from
  // `empty-output`: a killed engine leaves empty stdout too, and conflating the
  // two blames the engine for the caller's SIGTERM.
  | "console-wall-timeout"
  | "missing-context";

export interface EngineError {
  cause: EngineErrorCause;
  detail?: string;
}

export type EngineResult =
  | { ok: true; doc: VerifyJsonDoc; exitCode: number }
  | { ok: false; error: EngineError; exitCode: number | null };

/** The no-engine / no-context state the SPA renders distinctly from PASS. */
export const NO_ENGINE_STATUS = "no-engine" as const;
export type RenderStatus = VerdictStatus | typeof NO_ENGINE_STATUS;