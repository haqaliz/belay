// Engine subprocess wrapper: `belay verify --json` and `belay verify --turn N
// --json`. The binary resolves PATH-first with a `BELAY_CONSOLE_ENGINE`
// override (the repo venv case); stdout is captured with the exit code, and
// parseable JSON is REQUIRED — anything else is a named error, never a guess.
//
// The exit code is deliberately NOT the error signal: FAIL/UNVERIFIED traces
// exit non-zero exactly as without `--json` (pinned by aspect verify-json), and
// the console renders the verdicts the document carries. The only error signals
// are a missing binary, an unparseable document, or an empty stdout.

import { execFile } from "node:child_process";
import type { EngineResult, VerifyJsonDoc } from "./types.js";

export interface VerifyOptions {
  /** Trace path, passed positionally as the last argument. */
  trace: string;
  /** `--turn N` — the console's replay path (N1: replay uses verify --turn N). */
  turn?: number;
  /**
   * `--timeout <seconds>` — the per-replay timeout passthrough. The engine's
   * default (10s) cannot replay the demo capture's ~44s `run_process` turns,
   * so the demo surfaces set this; absent means nothing is passed and the
   * engine default applies.
   */
  replayTimeoutSeconds?: number;
  /** Extra positional flags (e.g. `--server`, `--manifest-dir` for replay). */
  extraArgs?: string[];
  /**
   * How many turns this invocation will replay — 1 for `--turn N`, the trace's turn
   * count for a whole-trace verify. Used only to size the subprocess wall; an absent
   * value is treated as 1, which can only make the wall smaller, never a false PASS.
   */
  turnsInScope?: number;
  env?: NodeJS.ProcessEnv;
  binary?: string;
  timeoutMs?: number;
  maxBuffer?: number;
}

export function resolveBelayBinary(env: NodeJS.ProcessEnv = process.env): string {
  const override = env.BELAY_CONSOLE_ENGINE;
  return typeof override === "string" && override.length > 0 ? override : "belay";
}

/**
 * The bundled engine's version, probed the way the container's static server
 * probed it: `python -c "import belay; print(belay.__version__)"`. `null` on
 * ANY failure — the probe is a liveness fact, and an unreportable engine must
 * answer as `null`, never a guessed version (the /health 503 contract).
 */
export function probeEngineVersion(timeoutMs = 10_000): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      "python",
      ["-c", "import belay; print(belay.__version__)"],
      { timeout: timeoutMs, maxBuffer: 64 * 1024 },
      (error, stdout) => {
        if (error !== null) {
          resolve(null);
          return;
        }
        const version = String(stdout).trim();
        resolve(version.length > 0 ? version : null);
      },
    );
  });
}

/** The floor (and the default) for the subprocess wall — unchanged behaviour when no
 * per-replay budget was authorised. */
export const DEFAULT_WALL_MS = 60_000;

/**
 * The wall around the WHOLE `belay verify` subprocess, in ms.
 *
 * The engine's `--timeout` is per replay; this is the caller's budget for all of them.
 * When the wall is the smaller of the two it silently overrides what the operator
 * authorised: the engine is SIGTERMed mid-replay and leaves empty stdout, which reads
 * as an engine failure rather than as the caller's kill. So the wall is derived from
 * the same number — the per-replay budget times the turns in scope, plus slack for
 * process start-up and the engine's own work — and never falls below the old default.
 */
export function subprocessWallMs(perReplaySeconds: number | undefined, turnsInScope: number): number {
  if (perReplaySeconds === undefined) return DEFAULT_WALL_MS;
  const turns = Math.max(1, turnsInScope);
  return Math.max(DEFAULT_WALL_MS, perReplaySeconds * 1000 * turns + 30_000);
}

export function verifyArgv(opts: VerifyOptions): string[] {
  // The trace positional MUST precede the extra args: `verify`'s `--server`
  // is nargs=REMAINDER, so everything after it is swallowed as the server
  // command — a trace placed last would vanish (argparse: "required: trace").
  const argv = ["verify", "--json"];
  if (opts.replayTimeoutSeconds !== undefined) argv.push("--timeout", String(opts.replayTimeoutSeconds));
  if (opts.turn !== undefined) argv.push("--turn", String(opts.turn));
  argv.push(opts.trace);
  if (opts.extraArgs !== undefined) argv.push(...opts.extraArgs);
  return argv;
}

export function runVerifyJson(opts: VerifyOptions): Promise<EngineResult> {
  const binary = opts.binary ?? resolveBelayBinary(opts.env);
  const argv = verifyArgv(opts);
  const env = { ...process.env, ...(opts.env ?? {}) };

  const wallMs = opts.timeoutMs ?? subprocessWallMs(opts.replayTimeoutSeconds, opts.turnsInScope ?? 1);

  return new Promise((resolve) => {
    execFile(
      binary,
      argv,
      {
        env,
        timeout: wallMs,
        maxBuffer: opts.maxBuffer ?? 4 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        if (error !== null) {
          // execFile's own timeout: the child was SIGTERMed by US. Its stdout is
          // empty because we killed it, so `empty-output` here would blame the
          // engine for the caller's wall — a named, distinguishable cause instead.
          if ((error as { killed?: boolean }).killed === true) {
            resolve({
              ok: false,
              error: { cause: "console-wall-timeout", detail: `killed after ${wallMs}ms` },
              exitCode: null,
            });
            return;
          }
          const errno = (error as NodeJS.ErrnoException).code;
          if (typeof errno === "string") {
            if (errno === "ENOENT") {
              resolve({ ok: false, error: { cause: "engine-not-found", detail: binary }, exitCode: null });
              return;
            }
            resolve({ ok: false, error: { cause: "spawn-failed", detail: errno }, exitCode: null });
            return;
          }
        }

        const exitCode = error === null ? 0 : typeof error.code === "number" ? error.code : 1;
        const out = typeof stdout === "string" ? stdout : String(stdout);
        if (out.trim().length === 0) {
          resolve({
            ok: false,
            error: { cause: "empty-output", detail: (stderr ?? "").slice(0, 400) || undefined },
            exitCode,
          });
          return;
        }
        try {
          const doc = JSON.parse(out) as VerifyJsonDoc;
          resolve({ ok: true, doc, exitCode });
        } catch {
          resolve({
            ok: false,
            error: {
              cause: "unparseable-json",
              detail: out.slice(0, 200).trim() || (stderr ?? "").slice(0, 400),
            },
            exitCode,
          });
        }
      },
    );
  });
}