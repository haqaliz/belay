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
import type { EngineResult, VerifyJsonDoc } from "./types";

export interface VerifyOptions {
  /** Trace path, passed positionally as the last argument. */
  trace: string;
  /** `--turn N` — the console's replay path (N1: replay uses verify --turn N). */
  turn?: number;
  /** Extra positional flags (e.g. `--server`, `--manifest-dir` for replay). */
  extraArgs?: string[];
  env?: NodeJS.ProcessEnv;
  binary?: string;
  timeoutMs?: number;
  maxBuffer?: number;
}

export function resolveBelayBinary(env: NodeJS.ProcessEnv = process.env): string {
  const override = env.BELAY_CONSOLE_ENGINE;
  return typeof override === "string" && override.length > 0 ? override : "belay";
}

export function verifyArgv(opts: VerifyOptions): string[] {
  // The trace positional MUST precede the extra args: `verify`'s `--server`
  // is nargs=REMAINDER, so everything after it is swallowed as the server
  // command — a trace placed last would vanish (argparse: "required: trace").
  const argv = ["verify", "--json"];
  if (opts.turn !== undefined) argv.push("--turn", String(opts.turn));
  argv.push(opts.trace);
  if (opts.extraArgs !== undefined) argv.push(...opts.extraArgs);
  return argv;
}

export function runVerifyJson(opts: VerifyOptions): Promise<EngineResult> {
  const binary = opts.binary ?? resolveBelayBinary(opts.env);
  const argv = verifyArgv(opts);
  const env = { ...process.env, ...(opts.env ?? {}) };

  return new Promise((resolve) => {
    execFile(
      binary,
      argv,
      {
        env,
        timeout: opts.timeoutMs ?? 60_000,
        maxBuffer: opts.maxBuffer ?? 4 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        if (error !== null) {
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